"""Review-queue threshold with a finite-sample guarantee (split calibration, Learn-then-Test).

The app auto-accepts an entity when its confidence is at or above a threshold and sends the rest to a person.
This script picks that threshold from labelled calibration data so that, for a target error rate `alpha`,

    P( error rate among auto-accepted entities  <=  alpha )  >=  1 - delta

holds for a new batch drawn like the calibration data. No assumption on the model or the confidence being calibrated.

METHOD. Learn-then-Test / conformal risk control (Angelopoulos, Bates, Candes, Jordan, Lei, "Learn then Test:
Calibrating Predictive Algorithms to Achieve Risk Control", 2021, arXiv:2110.01052; see also Angelopoulos, Bates,
Fisch, Lei, Schuster, "Conformal Risk Control", 2022, arXiv:2208.02814).
  1. Split the labelled entities in two halves, by diary (all entities of one diary stay together, because entities
     of one diary are not independent). The calibration half picks the threshold, the held-out half only reports.
  2. Candidate thresholds: up to `grid` quantiles of the calibration confidences. The grid looks at confidences only,
     never at labels, so it does not spend any of the error budget.
  3. For each candidate t, k entities have confidence >= t and w of them are wrong. Null hypothesis "the true error
     rate of the accepted set is above alpha". Exact binomial p-value  p(t) = P(Binomial(k, alpha) <= w). For
     0/1 losses this is the tightest of the Hoeffding-Bentkus family (Hoeffding and Bentkus are bounds on this same
     tail for bounded losses; for Bernoulli losses the exact tail is below both).
  4. A threshold is certified when p(t) <= delta / m (Bonferroni over the m candidates; family-wise error <= delta).
     The reported threshold is the lowest certified one, i.e. the largest auto-accept share the data supports.
     No certified threshold means the data cannot back this alpha: `threshold` is null and everything stays in review.
Caveats stated in the output: the guarantee is about the error of auto-accepted entities (precision), not about
entities the model never output (misses carry no confidence); it holds for data like the calibration set, so a
synthetic calibration set certifies synthetic-like diaries only; the empirical error on the held-out half is one
draw, reported for transparency, not part of the guarantee.

INPUT (one file, one of):
  eval/results/extraction_<label>.json  with per_item (written by eval/extraction_eval.py --sc-n N, so the confidence is
                                        the self-consistency the app uses; --source verbalized picks the model's own number)
  {"pairs": [{"confidence": 0.9, "correct": 1, "group": "diary-12"}, ...]}   (group optional; [conf, correct] also accepted)

    python eval/conformal.py eval/results/extraction_ft-e4b-r16-sc.json --alpha 0.05 --alpha 0.10
    python eval/conformal.py --dry-run                      # labelled synthetic fixture, writes dry_run: true

Writes eval/results/conformal_threshold.json: n, dataset, model, backend, date, alpha, delta, threshold, auto_accept_rate,
heldout_error, plus by_alpha for every requested alpha. The first --alpha is the headline one the app reads.
The app (backend/clario/config.py) ignores a file with dry_run true.
"""
import argparse
import datetime
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_curve  # noqa: E402  (pick_field: which confidence column a run carries)

DEFAULT_OUT = os.path.join(HERE, "results", "conformal_threshold.json")
METHOD = ("split calibration + Learn-then-Test (arXiv:2110.01052): exact binomial p-value on the accepted set, "
          "Bonferroni over the threshold grid")


def binom_cdf(w, k, p):
    """P(Binomial(k, p) <= w), summed in log space (k up to many thousands)."""
    if w >= k:
        return 1.0
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    logs = [math.lgamma(k + 1) - math.lgamma(i + 1) - math.lgamma(k - i + 1) + i * lp + (k - i) * lq for i in range(w + 1)]
    m = max(logs)
    return min(1.0, math.exp(m) * sum(math.exp(x - m) for x in logs))


def grid_of(confs, m):
    """Up to m candidate thresholds: quantiles of the calibration confidences (labels are not looked at)."""
    vals = sorted(set(confs))
    if len(vals) <= m:
        return vals
    return sorted({vals[min(len(vals) - 1, round(i * (len(vals) - 1) / (m - 1)))] for i in range(m)})


def certify(pairs, alpha, delta, grid=20):
    """pairs: [(confidence, correct 0/1)] (calibration half). Returns dict with threshold (None if none certified),
    the number accepted and wrong at it, its p-value, and the grid size m."""
    out = {"threshold": None, "n_cal": len(pairs), "n_accepted_cal": 0, "n_wrong_cal": 0, "p_value": None, "grid": 0}
    if not pairs:
        return out
    cand = grid_of([c for c, _ in pairs], max(2, grid))
    out["grid"] = m = len(cand)
    best = None
    for t in cand:
        acc = [ok for c, ok in pairs if c >= t]
        k, w = len(acc), sum(1 - ok for ok in acc)
        p = binom_cdf(w, k, alpha)
        if p <= delta / m and (best is None or t < best[0]):
            best = (t, k, w, p)
    if best:
        out.update(threshold=best[0], n_accepted_cal=best[1], n_wrong_cal=best[2], p_value=best[3])
    return out


def split_by_group(rows, frac, seed):
    """rows: [(confidence, correct, group)]. Whole groups go to one side. Returns (calibration, heldout) pair lists."""
    groups = sorted({g for _, _, g in rows}, key=str)
    random.Random(seed).shuffle(groups)
    cut = max(1, min(len(groups) - 1, round(len(groups) * frac))) if len(groups) > 1 else len(groups)
    cal_g = set(groups[:cut])
    cal = [(c, ok) for c, ok, g in rows if g in cal_g]
    held = [(c, ok) for c, ok, g in rows if g not in cal_g]
    return cal, held


def evaluate(pairs, threshold):
    """Auto-accept share and error among the accepted for a threshold (None = nothing is accepted)."""
    if threshold is None or not pairs:
        return {"n": len(pairs), "n_accepted": 0, "auto_accept_rate": 0.0, "error": None}
    acc = [ok for c, ok in pairs if c >= threshold]
    return {"n": len(pairs), "n_accepted": len(acc), "auto_accept_rate": len(acc) / len(pairs),
            "error": (sum(1 - ok for ok in acc) / len(acc)) if acc else None}


def load_rows(path, source="auto", correct="raw"):
    """-> (rows [(confidence, correct, group)], meta dict with dataset/model/backend/dry_run/confidence_source)."""
    d = json.load(open(path))
    meta = {k: d.get(k) for k in ("dataset", "model", "backend", "dry_run", "hardware", "label", "n", "subsample")}
    meta["n_diaries"] = meta.pop("n")
    rows = []
    if isinstance(d, dict) and d.get("per_item"):
        field, src = review_curve.pick_field(d, source)
        ok = review_curve.correct_field(d, correct)
        meta["confidence_source"] = review_curve.SOURCE_TEXT[src]
        meta["correctness"] = review_curve.CORRECT_TEXT[correct]
        meta["source_result"] = os.path.basename(path)
        for i, it in enumerate(d["per_item"]):
            for e in it["entities"]:
                if e.get(field) is not None:
                    rows.append((float(e[field]), int(e[ok]), it.get("id") if it.get("id") is not None else f"item{i}"))
    else:
        pairs = d["pairs"] if isinstance(d, dict) else d
        meta["confidence_source"] = (d.get("confidence_source") if isinstance(d, dict) else None) or "as given in the file"
        for i, p in enumerate(pairs):
            if isinstance(p, dict):
                rows.append((float(p["confidence"]), int(p["correct"]), p.get("group", f"row{i}")))
            else:
                rows.append((float(p[0]), int(p[1]), f"row{i}"))
    meta["dry_run"] = bool(meta.get("dry_run"))
    return rows, meta


def synthetic_rows(n_groups=800, per_group=3, seed=7):
    """Dry-run fixture: invented confidences with a plausible link to correctness (not a model result)."""
    rng = random.Random(seed)
    rows = []
    for g in range(n_groups):
        for _ in range(per_group):
            c = rng.choice([0.2, 0.4, 0.6, 0.8, 1.0])
            p_right = 0.35 + 0.64 * c ** 2  # 0.4 at c=0.2 ... 0.99 at c=1.0
            rows.append((c, int(rng.random() < p_right), f"synthetic-{g}"))
    return rows


def build(rows, meta, alphas, delta=0.1, grid=20, cal_frac=0.5, seed=0):
    cal, held = split_by_group(rows, cal_frac, seed)
    by_alpha = {}
    for a in alphas:
        c = certify(cal, a, delta, grid)
        ev = evaluate(held, c["threshold"])
        by_alpha[f"{a:g}"] = {"alpha": a, "threshold": c["threshold"], "status": "certified" if c["threshold"] is not None else "no_valid_threshold",
                              "n_accepted_cal": c["n_accepted_cal"], "n_wrong_cal": c["n_wrong_cal"], "p_value": c["p_value"],
                              "auto_accept_rate": ev["auto_accept_rate"], "heldout_n_accepted": ev["n_accepted"],
                              "heldout_error": ev["error"]}
    head = by_alpha[f"{alphas[0]:g}"]
    return {"n": len(rows), "dataset": meta.get("dataset") or "unknown", "model": meta.get("model") or "unknown",
            "backend": meta.get("backend") or "unknown", "date": datetime.date.today().isoformat(),
            "dry_run": bool(meta.get("dry_run")),
            "alpha": alphas[0], "delta": delta, "threshold": head["threshold"], "status": head["status"],
            "auto_accept_rate": head["auto_accept_rate"], "heldout_error": head["heldout_error"],
            "n_calibration": len(cal), "n_heldout": len(held), "grid": grid, "split_seed": seed, "split_fraction": cal_frac,
            "split_unit": "diary (all entities of one diary on the same side)",
            "confidence_source": meta.get("confidence_source"), "method": METHOD, "by_alpha": by_alpha,
            **{k: meta[k] for k in ("correctness", "hardware", "source_result", "n_diaries", "subsample", "label")
               if meta.get(k) is not None},
            "n_unit": "entities (predicted terms with a confidence)",
            "guarantee": f"with probability >= {1 - delta:g} over the calibration draw, the error rate of auto-accepted entities is <= alpha, "
                         "for data like the calibration set. Precision of accepted entities only: entities the model never output are not covered.",
            **({"note": "synthetic fixture, no model; checks the code path only. The app ignores this file."} if meta.get("dry_run") else {})}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("input", nargs="?", help="extraction_<label>.json with per_item, or a pairs file")
    ap.add_argument("--alpha", type=float, action="append", help="target error rate (repeatable; the first is the headline). default 0.05")
    ap.add_argument("--delta", type=float, default=0.1, help="failure probability of the guarantee (default 0.1 = 90 percent)")
    ap.add_argument("--grid", type=int, default=20, help="number of candidate thresholds (Bonferroni factor)")
    ap.add_argument("--cal-frac", type=float, default=0.5, help="share of diaries used for calibration, the rest is held out")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--source", default="auto", choices=["auto", "sc", "verbalized"])
    ap.add_argument("--correct", default="raw", choices=["raw", "resolved"],
                    help="entity correctness: model's own HPO id (raw) or after the app's ontology resolver (resolved)")
    ap.add_argument("--dry-run", action="store_true", help="use a labelled synthetic fixture and write dry_run: true")
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    alphas = a.alpha or [0.05]
    if not all(0 < x < 1 for x in alphas) or not 0 < a.delta < 1:
        ap.error("alpha and delta must be in (0, 1)")
    if a.dry_run:
        rows = synthetic_rows()
        meta = {"dataset": "synthetic-dry-run-fixture", "model": "none", "backend": "offline-dry-run", "dry_run": True,
                "confidence_source": "invented numbers (no model)"}
    elif a.input:
        rows, meta = load_rows(a.input, a.source, a.correct)
    else:
        ap.error("give an input file or --dry-run")
    if not rows:
        ap.error("no (confidence, correct) pairs in the input")
    res = build(rows, meta, alphas, a.delta, a.grid, a.cal_frac, a.seed)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(res, f, indent=2)
    for k, v in res["by_alpha"].items():
        print(f"alpha {k}: threshold {v['threshold']}, auto-accept {v['auto_accept_rate']:.3f}, held-out error {v['heldout_error']} ({v['status']})")
    return res


if __name__ == "__main__":
    main()
