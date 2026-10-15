"""Risk-coverage curve: how much goes to a human at 1 / 2 / 5 % tolerated error.

Input: eval/results/extraction_<label>.json written with --confidence (needs `per_item`, the per-entity
confidence and correctness). Auto-accept every entity (or item) at or above a confidence threshold, send the
rest to review. For each tolerated error rate the output gives the smallest review share whose
auto-accepted part stays within the tolerance.

  entity level: error = share of auto-accepted entities that are wrong (false positives under the HPO-id match).
  item level:   an item is auto-accepted when its LOWEST entity confidence passes; error = share of
                auto-accepted items that contain a wrong entity. Items with no predicted entity are skipped.
CONFIDENCE SOURCE. The confidence in a `--confidence` run is what the model SAYS about itself (a probability it was
asked to write), not a measured self-consistency. Treat the curve as valid only as far as that number is calibrated:
the output carries `confidence_source` and the run's `ece` so a reader can judge. The app itself routes by
self-consistency across samples (backend/clario/extract.py); `eval/extraction_eval.py` measures that path.
The figure is the share ROUTED TO REVIEW, not coverage and not accuracy.
Misses (gold entities the model never output) carry no confidence and cannot be routed; they are reported as
`unrouted_misses` so the curve is not read as a recall guarantee.

    python eval/review_curve.py                          # every extraction_*.json that has per_item
    python eval/review_curve.py eval/results/extraction_ft.json
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


def entity_points(items):
    return [(e["confidence"], e["correct"]) for it in items for e in it["entities"]]


def item_points(items):
    return [(min(e["confidence"] for e in it["entities"]), int(all(e["correct"] for e in it["entities"])))
            for it in items if it["entities"]]


def build(res):
    items = res["per_item"]
    ep, ip = entity_points(items), item_points(items)
    out = {k: res[k] for k in ("label", "dataset", "model", "backend") if k in res}
    out.update({"date": datetime.date.today().isoformat(), "source_result": f"extraction_{res['label']}.json",
                "n": res["n"], "n_entities_with_confidence": len(ep), "n_items_scored": len(ip),
                "unrouted_misses": res.get("fn"),
                "confidence_source": "model self-reported (prompt asked for a probability); not self-consistency",
                "ece": res.get("ece"), "metric": "share of entities routed to review (not coverage, not accuracy)",
                "tolerances": {}})
    for tol in TOLERANCES:
        out["tolerances"][f"{int(tol * 100)}pct"] = {"entity": review_share(ep, tol), "item": review_share(ip, tol)}
    out["entity_curve"] = [{"threshold": t, "coverage": c, "error": e} for t, c, e in risk_coverage(ep)]
    return out


def main(paths):
    paths = paths or sorted(glob.glob(os.path.join(HERE, "results", "extraction_*.json")))
    done = 0
    for p in paths:
        res = json.load(open(p))
        if not res.get("per_item"):
            print(f"skip {os.path.basename(p)}: no per-item confidence (run the eval with --confidence)")
            continue
        out = build(res)
        dest = os.path.join(os.path.dirname(os.path.abspath(p)), f"review_curve_{res['label']}.json")
        json.dump(out, open(dest, "w"), indent=2)
        for k, v in out["tolerances"].items():
            print(f"{res['label']} @ {k}: entity review share {v['entity']['review_share']:.3f}, item {v['item']['review_share']:.3f}")
        done += 1
    if not done:
        print("no review curve written")


if __name__ == "__main__":
    main(sys.argv[1:])
