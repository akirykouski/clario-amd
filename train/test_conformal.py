import importlib.util
import json
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cf = load("conformal", "eval/conformal.py")
rc = load("review_curve", "eval/review_curve.py")
ev = load("clario_train_eval_t", "train/eval.py")  # loaded by path; needs train/ on sys.path for `prompt`

LEVELS = [0.2, 0.4, 0.6, 0.8, 1.0]
P_RIGHT = {0.2: 0.4, 0.4: 0.6, 0.6: 0.8, 0.8: 0.93, 1.0: 0.99}


def draw(rng, n):
    out = []
    for _ in range(n):
        c = rng.choice(LEVELS)
        out.append((c, int(rng.random() < P_RIGHT[c])))
    return out


def true_risk(t):
    acc = [c for c in LEVELS if c >= t]  # levels are equally likely
    return 1 - sum(P_RIGHT[c] for c in acc) / len(acc)


def test_binom_cdf_matches_direct_sum():
    from math import comb
    for k, w, p in [(10, 0, 0.1), (10, 3, 0.3), (50, 2, 0.05), (7, 7, 0.4)]:
        direct = sum(comb(k, i) * p ** i * (1 - p) ** (k - i) for i in range(w + 1))
        assert cf.binom_cdf(w, k, p) == pytest.approx(direct, rel=1e-9)
    assert cf.binom_cdf(0, 0, 0.1) == 1.0
    assert cf.binom_cdf(5000, 20000, 0.5) < 1e-300 or cf.binom_cdf(5000, 20000, 0.5) == 0.0  # no overflow at large k


def test_guarantee_holds_over_many_seeds():
    alpha, delta = 0.10, 0.10
    fails = found = 0
    runs = 400
    for seed in range(runs):
        cal = draw(random.Random(seed), 300)
        c = cf.certify(cal, alpha, delta)
        if c["threshold"] is None:
            continue
        found += 1
        fails += true_risk(c["threshold"]) > alpha
    assert fails / runs <= delta  # the promised failure rate (in practice far below it)
    assert found / runs > 0.8     # and the method is not vacuous: it finds a threshold most of the time
    # lower-confidence levels are unsafe at alpha=0.10: never certified
    assert all(true_risk(t) > alpha for t in (0.2, 0.4))


def test_guarantee_holds_when_the_target_is_tight():
    # alpha=0.04: only the top level (true risk 0.01) is safe, 0.8 and up has risk 0.04 (not strictly below alpha)
    alpha, delta, fails, runs = 0.03, 0.10, 0, 400
    for seed in range(runs):
        c = cf.certify(draw(random.Random(1000 + seed), 300), alpha, delta)
        fails += c["threshold"] is not None and true_risk(c["threshold"]) > alpha
    assert fails / runs <= delta


def test_nothing_certified_when_data_cannot_back_alpha():
    bad = [(0.9, 0)] * 30 + [(0.9, 1)] * 30
    c = cf.certify(bad, 0.05, 0.1)
    assert c["threshold"] is None
    assert cf.certify([], 0.05, 0.1)["threshold"] is None
    assert cf.certify([(0.9, 1)] * 3, 0.05, 0.1)["threshold"] is None  # 3 right answers prove nothing at alpha 0.05


def test_threshold_lowest_certified_and_perfect_data():
    pts = [(0.95, 1)] * 200 + [(0.5, 1)] * 100 + [(0.5, 0)] * 100
    c = cf.certify(pts, 0.05, 0.1)
    assert c["threshold"] == 0.95 and c["n_wrong_cal"] == 0
    c2 = cf.certify(pts, 0.40, 0.1)  # 0.5 level: 100 of 400 wrong overall = 0.25 <= 0.40
    assert c2["threshold"] == 0.5


def test_split_is_by_group_and_deterministic():
    rows = [(0.5, 1, f"d{i // 3}") for i in range(60)]
    cal, held = cf.split_by_group(rows, 0.5, 0)
    assert len(cal) + len(held) == 60 and len(cal) == 30
    cal2, _ = cf.split_by_group(rows, 0.5, 0)
    assert cal == cal2
    # whole diaries (3 rows each) go to one side
    rows = [(float(i), 1, f"d{i // 3}") for i in range(60)]
    cal, held = cf.split_by_group(rows, 0.5, 3)
    cal_diaries = {int(c) // 3 for c, _ in cal}
    held_diaries = {int(c) // 3 for c, _ in held}
    assert not cal_diaries & held_diaries and len(cal) == 3 * len(cal_diaries)


def test_build_end_to_end_fields_and_heldout():
    rng = random.Random(5)
    rows = [(c, ok, f"d{i // 3}") for i, (c, ok) in enumerate(draw(rng, 900))]
    res = cf.build(rows, {"dataset": "d", "model": "m", "backend": "b", "dry_run": False, "confidence_source": "x"},
                   [0.10, 0.05], delta=0.1)
    for k in ("n", "dataset", "model", "backend", "date", "alpha", "delta", "threshold", "auto_accept_rate", "heldout_error", "dry_run"):
        assert k in res
    assert res["n"] == 900 and res["alpha"] == 0.10 and res["dry_run"] is False
    assert res["threshold"] is not None and res["heldout_error"] <= 0.2
    assert set(res["by_alpha"]) == {"0.1", "0.05"}
    strict = res["by_alpha"]["0.05"]["threshold"]
    assert strict is None or strict >= res["threshold"]  # a stricter target never accepts more


def test_dry_run_cli_writes_labelled_file(tmp_path):
    out = tmp_path / "conformal_threshold.json"
    cf.main(["--dry-run", "--alpha", "0.05", "--alpha", "0.10", "--out", str(out)])
    d = json.load(open(out))
    assert d["dry_run"] is True and "synthetic" in d["note"]
    assert d["model"] == "none" and d["dataset"].startswith("synthetic")


def test_dry_run_flag_propagates_from_input(tmp_path):
    per_item = [{"id": str(i), "entities": [{"confidence": 1.0, "correct": 1}]} for i in range(300)]
    src = tmp_path / "extraction_x.json"
    src.write_text(json.dumps({"label": "x", "dataset": "d", "model": "m", "backend": "b", "n": 300, "dry_run": True, "per_item": per_item}))
    out = tmp_path / "o.json"
    res = cf.main([str(src), "--out", str(out)])
    assert res["dry_run"] is True
    src.write_text(json.dumps({"label": "x", "dataset": "d", "model": "m", "backend": "b", "n": 300, "dry_run": False, "per_item": per_item}))
    assert cf.main([str(src), "--out", str(out)])["dry_run"] is False


def test_pairs_file_formats(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"pairs": [[0.9, 1]] * 200 + [{"confidence": 0.3, "correct": 0, "group": "g"}]}))
    rows, meta = cf.load_rows(str(p))
    assert len(rows) == 201 and meta["dry_run"] is False


# ---- the eval scores the app's own signal
def ent(canonical, quote, neg=False, hpo=None):
    return {"canonical": canonical, "quote": quote, "negated": neg, "hpo_id": hpo}


def test_self_consistency_agreement_rate():
    diary = "My knees ache and no fever today"
    pred = [ent("knee pain", "knees ache"), ent("fever", "fever", neg=True)]
    s1 = [ent("Knee pain", "knees ache")]                                   # case-insensitive canonical match
    s2 = [ent("arthralgia", "knees ache", hpo="HP:1")]                      # different name, no hpo on pred: miss
    s3 = [ent("fever", "fever", neg=False)]                                 # negation differs: miss
    s4 = [ent("knee pain", "invented words")]                               # quote not in the diary: miss
    got = ev.self_consistency(pred, [[*s1, ent("fever", "fever", True)], s2, s3, s4, None], diary)
    assert got == [0.2, 0.2]
    assert ev.self_consistency(pred, [], diary) == [None, None]
    pred2 = [ent("joint pain", "knees ache", hpo="HP:0002829")]
    assert ev.self_consistency(pred2, [[ent("arthralgia", "Knees  ache", hpo="HP:0002829")]], diary) == [1.0]  # same id matches


def test_run_records_sets_confidence_and_keeps_verbalized():
    gold = [{"id": "a", "diary": "my knees ache", "gold": [], "gold_complete": True}]
    out = json.dumps({"entities": [{"quote": "knees ache", "canonical": "knee pain", "hpo_id": None, "type": "symptom", "negated": False,
                                    "family_history": False, "onset_hint": None, "severity": None, "confidence": 0.99}]})
    other = json.dumps({"entities": []})

    def complete(d):
        return out, 0.1, 5
    complete.samples = lambda d, n, temperature=0.7: [out, out, other, other][:n]
    recs, _ = ev.run_records(gold, complete, 1, sc_n=4)
    e = recs[0]["pred"][0]
    assert e["confidence"] == 0.5 and e["verbalized"] == 0.99
    m = ev.score([{**recs[0], "gold": [{"quote": "knees ache", "canonical": "knee pain", "hpo_id": None, "negated": False, "family_history": False}]}])
    row = m["per_item"][0]["entities"][0]
    assert row["confidence"] == 0.5 and row["confidence_verbalized"] == 0.99 and row["correct"] == 1


def test_review_curve_source_selection():
    items = [{"id": str(i), "n_gold": 1, "n_pred": 1,
              "entities": [{"confidence": 0.9, "confidence_verbalized": 0.5, "correct": 1}]} for i in range(10)]
    res = {"label": "l", "dataset": "d", "model": "m", "backend": "b", "n": 10, "sc_n": 5, "confidence_prompt": True, "per_item": items}
    assert rc.pick_field(res) == ("confidence", "self_consistency")
    assert rc.pick_field(res, "verbalized") == ("confidence_verbalized", "verbalized")
    out = rc.build(res)
    assert out["confidence_kind"] == "self_consistency" and out["sc_n"] == 5
    assert rc.build(res, "verbalized")["confidence_kind"] == "verbalized"
    with pytest.raises(ValueError):
        rc.pick_field({**res, "sc_n": 0, "confidence_prompt": False}, "sc")


def test_correct_resolved_selects_the_resolver_label(tmp_path):
    items = [{"id": f"d{i}", "entities": [{"confidence": 1.0, "correct": 0, "correct_resolved": 1},
                                          {"confidence": 0.2, "correct": 0, "correct_resolved": 0}]} for i in range(400)]
    res = {"label": "x", "dataset": "d", "model": "m", "backend": "b", "n": 400, "sc_n": 5, "per_item": items,
           "hardware": {"gpu_name": "hosted"}}
    p = tmp_path / "extraction_x.json"
    p.write_text(json.dumps(res))
    raw_rows, _ = cf.load_rows(str(p), "sc", "raw")
    rows, meta = cf.load_rows(str(p), "sc", "resolved")
    assert sum(ok for _, ok, _ in raw_rows) == 0 and sum(ok for _, ok, _ in rows) == 400
    assert "resolver" in meta["correctness"] and meta["hardware"] == {"gpu_name": "hosted"} and meta["n_diaries"] == 400
    out = cf.build(rows, meta, [0.05])
    assert out["threshold"] == 1.0 and out["hardware"] and out["n_diaries"] == 400 and out["correctness"]
    curve = rc.build(res, "sc", "resolved")
    assert curve["correctness_kind"] == "resolved" and curve["tolerances"]["1pct"]["entity"]["review_share"] == 0.5
    with pytest.raises(ValueError):
        rc.build({**res, "per_item": [{"id": "a", "entities": [{"confidence": 1.0, "correct": 1}]}]}, "sc", "resolved")


def test_attach_resolved_copies_correctness_in_order():
    m = {"per_item": [{"entities": [{"confidence": 1.0, "correct": 0}, {"confidence": 0.4, "correct": 1}]}]}
    rm = {"resolved_entity_f1": 0.5, "_resolved_per_item": [{"entities": [{"confidence": 1.0, "correct": 1},
                                                                          {"confidence": 0.4, "correct": 1}]}]}
    ev.attach_resolved(m, rm)
    assert [e["correct_resolved"] for e in m["per_item"][0]["entities"]] == [1, 1] and "_resolved_per_item" not in rm
