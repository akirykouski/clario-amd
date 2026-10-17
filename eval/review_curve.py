"""Risk-coverage curve: how much goes to a human at 1 / 2 / 5 % tolerated error.

Input: eval/results/extraction_<label>.json written with --confidence (needs `per_item`, the per-entity
confidence and correctness). Auto-accept every entity (or item) at or above a confidence threshold, send the
rest to review. For each tolerated error rate the output gives the smallest review share whose
auto-accepted part stays within the tolerance.

  entity level: error = share of auto-accepted entities that are wrong (false positives under the HPO-id match).
  item level:   an item is auto-accepted when its LOWEST entity confidence passes; error = share of
                auto-accepted items that contain a wrong entity. Items with no predicted entity are skipped.
CONFIDENCE SOURCE. The app routes on self-consistency: the share of n sampled answers that hold the same
(term, negated) pair (backend/clario/extract.py). Run the eval with `--sc-n N` to score that same signal; the run
then stores it as `confidence` per entity. A run with only `--confidence` carries what the model SAYS about itself
(a probability it was asked to write), which is a comparison, not the app's signal. With both flags the file holds
both numbers (`confidence` = self-consistency, `confidence_verbalized`). `--source sc|verbalized|auto` picks the
column (auto: self-consistency when the run has it); the output names it in `confidence_source`.
The figure is the share ROUTED TO REVIEW, not coverage and not accuracy.
Misses (gold entities the model never output) carry no confidence and cannot be routed; they are reported as
`unrouted_misses` so the curve is not read as a recall guarantee.

    python eval/review_curve.py                          # every extraction_*.json that has per_item
    python eval/review_curve.py eval/results/extraction_ft.json
    python eval/review_curve.py --source verbalized eval/results/extraction_ft.json   # the model's own number
    python eval/review_curve.py --correct resolved eval/results/extraction_ft.json  # correct after the app's HPO resolver
CORRECTNESS. `--correct raw` (default): the model's own HPO id must equal gold. `--correct resolved`: the id after the
app's ontology resolver (per-entity `correct_resolved`, written when the backend is importable), closer to what the
app stores. Output name gets `_resolved`.
Writes eval/results/review_curve_<label>.json (n, dataset, model, backend, date, curves).
"""
import datetime
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOLERANCES = (0.01, 0.02, 0.05)


def risk_coverage(points):
    """points: [(confidence, correct 0/1)] -> list of (threshold, coverage, error) from strict to loose threshold."""
    n = len(points)
    if not n:
        return []
    by = sorted(points, key=lambda p: -p[0])
    curve, accepted, wrong, i = [], 0, 0, 0
    while i < n:
        c = by[i][0]
        while i < n and by[i][0] == c:  # ties are accepted together
            accepted += 1; wrong += 1 - by[i][1]; i += 1
        curve.append((c, accepted / n, wrong / accepted))
    return curve


def review_share(points, tol):
    """Smallest review share with auto-accepted error <= tol. Returns dict (threshold None when nothing qualifies)."""
    best = {"threshold": None, "coverage": 0.0, "review_share": 1.0, "error_at_threshold": None}
    for thr, cov, err in risk_coverage(points):
        if err <= tol and cov > best["coverage"]:
            best = {"threshold": thr, "coverage": cov, "review_share": 1.0 - cov, "error_at_threshold": err}
    return best


def pick_field(res, source="auto"):
    """-> (entity field holding the confidence, confidence_source label). Raises ValueError when the run lacks it."""
    run_sc = (res.get("sc_n") or 0) > 1
    if source == "verbalized":
        if not (res.get("confidence_prompt") or any("confidence_verbalized" in e for it in res["per_item"] for e in it["entities"])):
            raise ValueError("run has no verbalized confidence (run it with --confidence)")
        return ("confidence_verbalized" if run_sc else "confidence"), "verbalized"
    if source == "sc":
        if not run_sc:
            raise ValueError("run has no self-consistency (run it with --sc-n N)")
        return "confidence", "self_consistency"
    return ("confidence", "self_consistency") if run_sc else ("confidence", "verbalized")


CORRECT_FIELD = {"raw": "correct", "resolved": "correct_resolved"}
CORRECT_TEXT = {"raw": "HPO id as the model wrote it, plus negation and family flags (exact match with gold)",
                "resolved": "HPO id after the app's ontology resolver (clario.extract.resolve_hpo, what the app stores "
                            "minus the optional model pick), plus negation and family flags (exact match with gold)"}


def correct_field(res, correct="raw"):
    """-> per-entity correctness key. 'resolved' needs a run scored with the backend resolver (correct_resolved)."""
    f = CORRECT_FIELD[correct]
    if correct == "resolved" and not any(f in e for it in res["per_item"] for e in it["entities"]):
        raise ValueError("run has no correct_resolved (score it with the backend importable, without --no-resolve)")
    return f


def entity_points(items, field="confidence", ok="correct"):
    return [(e[field], e[ok]) for it in items for e in it["entities"] if e.get(field) is not None]


def item_points(items, field="confidence", ok="correct"):
    rows = [[e for e in it["entities"] if e.get(field) is not None] for it in items]
    return [(min(e[field] for e in r), int(all(e[ok] for e in r))) for r in rows if r]


SOURCE_TEXT = {"self_consistency": "self-consistency: agreement rate across n sampled answers (the signal the app routes on)",
               "verbalized": "model self-reported (prompt asked for a probability); not self-consistency"}


def build(res, source="auto", correct="raw"):
    items = res["per_item"]
    field, src = pick_field(res, source)
    ok = correct_field(res, correct)
    ep, ip = entity_points(items, field, ok), item_points(items, field, ok)
    out = {k: res[k] for k in ("label", "dataset", "model", "backend", "hardware") if k in res}
    out.update({"date": datetime.date.today().isoformat(), "source_result": f"extraction_{res['label']}.json",
                "n": res["n"], "n_entities_with_confidence": len(ep), "n_items_scored": len(ip),
                "unrouted_misses": res.get("fn"),
                "confidence_source": SOURCE_TEXT[src], "confidence_kind": src, "sc_n": res.get("sc_n") or None,
                "correctness": CORRECT_TEXT[correct], "correctness_kind": correct,
                "ece": res.get("ece"), "metric": "share of entities routed to review (not coverage, not accuracy)",
                "tolerances": {}})
    for tol in TOLERANCES:
        out["tolerances"][f"{int(tol * 100)}pct"] = {"entity": review_share(ep, tol), "item": review_share(ip, tol)}
    out["entity_curve"] = [{"threshold": t, "coverage": c, "error": e} for t, c, e in risk_coverage(ep)]
    return out


def main(paths, source="auto", correct="raw"):
    paths = paths or sorted(glob.glob(os.path.join(HERE, "results", "extraction_*.json")))
    done = 0
    for p in paths:
        res = json.load(open(p))
        if not res.get("per_item"):
            print(f"skip {os.path.basename(p)}: no per-item confidence (run the eval with --confidence)")
            continue
        try:
            out = build(res, source, correct)
        except ValueError as e:
            print(f"skip {os.path.basename(p)}: {e}")
            continue
        suffix = "" if out["confidence_kind"] == "self_consistency" or source == "auto" else "_" + out["confidence_kind"]
        suffix += "_resolved" if correct == "resolved" else ""
        dest = os.path.join(os.path.dirname(os.path.abspath(p)), f"review_curve_{res['label']}{suffix}.json")
        json.dump(out, open(dest, "w"), indent=2)
        for k, v in out["tolerances"].items():
            print(f"{res['label']} @ {k}: entity review share {v['entity']['review_share']:.3f}, item {v['item']['review_share']:.3f}")
        done += 1
    if not done:
        print("no review curve written")


if __name__ == "__main__":
    args = sys.argv[1:]
    src = "auto"
    if "--source" in args:
        i = args.index("--source")
        src = args[i + 1]
        args = args[:i] + args[i + 2:]
    cor = "raw"
    if "--correct" in args:
        i = args.index("--correct")
        cor = args[i + 1]
        args = args[:i] + args[i + 2:]
    main(args, src, cor)
