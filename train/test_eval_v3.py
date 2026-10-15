import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import eval as ev
from eval import calibration, score
from prompt import target_json

ROOT = Path(__file__).resolve().parent.parent


def E(q, h, canon="X", neg=False, fam=False, onset=None, sev=None, conf=None, typ="symptom"):
    return {"quote": q, "canonical": canon, "hpo_id": h, "type": typ, "negated": neg, "family_history": fam,
            "onset_hint": onset, "severity": sev, "confidence": conf}


GOLD = [E("red cheeks", "HP:0000469", neg=False, onset="since Tuesday", sev=6),
        E("fever", "HP:0001945", neg=True),
        E("rash on her cheeks", "HP:0000469", fam=True)]
DIARY = "red cheeks since Tuesday 6/10, no fever. My mother has rash on her cheeks."


def rec(pred, gold=GOLD, **kw):
    return {"id": "r1", "diary": DIARY, "gold": gold, "pred": pred, **kw}


def test_flag_accuracy_counts_only_matched_entities():
    pred = [E("red cheeks", "HP:0000469", onset="since Tuesday", sev=6), E("fever", "HP:0001945", neg=False),
            E("rash on her cheeks", "HP:0000469", fam=True)]
    m = score([rec(pred)])
    assert abs(m["entity_f1"] - 2 / 3) < 1e-9 and m["n_matched_pairs"] == 3  # the dropped negation costs F1; the flag metric still sees the pair
    assert abs(m["negation_accuracy"] - 2 / 3) < 1e-9 and m["family_history_accuracy"] == 1.0
    assert m["onset_accuracy"] == 1.0 and m["severity_accuracy"] == 1.0
    pred[2]["family_history"] = False
    assert abs(score([rec(pred)])["family_history_accuracy"] - 2 / 3) < 1e-9


def test_no_pairs_gives_none_not_a_fake_one():
    m = score([rec([])])
    assert m["negation_accuracy"] is None and m["ece"] is None and m["entity_recall"] == 0.0


def test_entities_without_hpo_id_match_on_quote():
    g = [E("after a cold swim", None, typ="trigger")]
    m = score([{"diary": "after a cold swim", "gold": g, "pred": [E("After a cold swim", None, typ="trigger")]}])
    assert m["entity_f1"] == 1.0 and m["hpo_id_accuracy"] is None and m["n_gold_with_hpo_id"] == 0  # nothing to score: None, not 1.0


def test_hard_negative_scoring():
    assert score([{"diary": "quiet day", "gold": [], "pred": []}])["entity_f1"] == 1.0
    assert score([{"diary": "quiet day", "gold": [], "pred": [E("quiet", "HP:0001945")]}])["entity_precision"] == 0.0


def test_partial_gold_skips_flag_metrics_and_is_labelled():
    m = score([rec([E("red cheeks", "HP:0000469")], partial=True, gold_complete=False)])
    assert m["negation_accuracy"] is None and m["gold_complete"] is False


def test_ece_and_brier_on_known_points():
    ece, brier = calibration([(0.9, 1)] * 9 + [(0.9, 0)])  # perfectly calibrated at 0.9
    assert abs(ece) < 1e-9 and abs(brier - (9 * 0.01 + 0.81) / 10) < 1e-9
    ece, _ = calibration([(1.0, 0)] * 4)
    assert abs(ece - 1.0) < 1e-9
    assert calibration([]) == (None, None)
    m = score([rec([E("red cheeks", "HP:0000469", conf=1.0), E("cough", "HP:0012735", conf=1.0)])])
    assert m["n_confidence_entities"] == 2 and abs(m["ece"] - 0.5) < 1e-9 and m["confidence_coverage"] == 1.0
    assert m["per_item"][0]["entities"] == [{"confidence": 1.0, "correct": 1}, {"confidence": 1.0, "correct": 0}]


def test_strict_schema_rate_separate_from_json_validity():
    m = score([rec([], strict=True), {"id": "r2", "diary": "d", "gold": [], "pred": [], "strict": False}])
    assert m["json_validity_rate"] == 1.0 and m["schema_valid_rate"] == 0.5


def fake_complete(gold_by_diary, bad=()):
    def complete(diary):
        if diary in bad:
            raise RuntimeError("endpoint down")
        return target_json(gold_by_diary[diary]), 0.01, 5
    return complete


def test_run_records_with_fake_endpoint_and_errors():
    gold = [{"id": "a", "diary": "d1", "gold": [E("x y z", "HP:0000001")]}, {"id": "b", "diary": "d2", "gold": []}]
    recs, wall = ev.run_records(gold, fake_complete({"d1": gold[0]["gold"], "d2": []}, bad=("d2",)), concurrency=2)
    assert recs[0]["strict"] and recs[0]["pred"][0]["hpo_id"] == "HP:0000001" and recs[0]["pred"][0]["confidence"] is None
    assert recs[1]["pred"] is None and "endpoint down" in recs[1]["err"]
    m = score(recs)
    assert m["json_validity_rate"] == 0.5 and m["schema_valid_rate"] == 0.5


def test_result_file_carries_provenance_and_dry_run_is_labelled(tmp_path):
    data = tmp_path / "test.jsonl"
    data.write_text(json.dumps({"id": "a", "diary": "red cheeks", "target": {"entities": [
        {"quote": "red cheeks", "canonical": "Malar rash", "hpo_id": "HP:0000469", "type": "symptom", "negated": False}]}}) + "\n")
    res = ev.main(["--dry-run", "--data", str(data), "--out-dir", str(tmp_path)])
    f = json.load(open(tmp_path / "extraction_dryrun-gold-vs-gold.json"))
    for k in ("n", "dataset", "model", "backend", "date", "label"):
        assert k in f
    assert f["dry_run"] is True and f["backend"] == "offline-dry-run" and f["entity_f1"] == 1.0 and res["n"] == 1
    assert ev.infer_backend("https://api.anthropic.com/v1/") == "anthropic-openai-compat"
    assert ev.infer_backend("http://localhost:11434/v1") == "ollama" and ev.infer_backend("http://h:8000/v1") == "openai-compatible"


def test_main_with_patched_endpoint_writes_non_dry_result(tmp_path, monkeypatch):
    data = tmp_path / "t.jsonl"
    ent = {"quote": "red cheeks", "canonical": "Malar rash", "hpo_id": "HP:0000469", "type": "symptom", "negated": False}
    data.write_text(json.dumps({"id": "a", "diary": "red cheeks", "target": {"entities": [ent]}}) + "\n")
    gold = {"red cheeks": [ev.from_dataset_entities([ent])[0]]}
    monkeypatch.setattr(ev, "make_complete", lambda *a, **k: fake_complete(gold))
    res = ev.main(["--base-url", "http://h:8000/v1", "--model", "m1", "--label", "fake", "--backend", "vllm-rocm-mi300x",
                   "--data", str(data), "--dataset", "unit", "--out-dir", str(tmp_path)])
    f = json.load(open(tmp_path / "extraction_fake.json"))
    assert f["dry_run"] is False and f["model"] == "m1" and f["backend"] == "vllm-rocm-mi300x" and f["dataset"] == "unit"
    assert f["entity_f1"] == 1.0 and "latency_p50_s" in f and res["n"] == 1


def test_eval_wrapper_dry_run_and_old_dataset_shape(tmp_path):
    data = tmp_path / "old.jsonl"  # the older dataset-row shape must still be scorable
    data.write_text(json.dumps({"diary": "no fever", "target": {"entities": [
        {"name_colloquial": "fever", "name_canonical": "Fever", "hpo_id": "HP:0001945", "type": "symptom", "negated": True}]}}) + "\n")
    r = subprocess.run([sys.executable, str(ROOT / "eval" / "extraction_eval.py"), "--dry-run", "--data", str(data),
                        "--out-dir", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "extraction_dryrun-gold-vs-gold.json").exists() and "entity F1" in r.stdout


def test_empty_denominators_are_none_never_a_perfect_score():
    m = score([{"diary": "quiet day", "gold": [E("fever", "HP:0001945")], "pred": []}])
    assert m["quote_grounding_rate"] is None and m["n_predicted_entities"] == 0  # no prediction, nothing was grounded
    assert m["hpo_id_accuracy"] == 0.0 and m["n_gold_with_hpo_id"] == 1
    assert score([{"diary": "quiet day", "gold": [], "pred": []}])["quote_grounding_rate"] is None


def test_negation_is_part_of_the_match_key_and_negated_recall_reports_n():
    gold = [E("fever", "HP:0001945", neg=True), E("red cheeks", "HP:0000469"), E("mother", "HP:0002725", fam=True)]
    dropped = [E("fever", "HP:0001945", neg=False), E("red cheeks", "HP:0000469"), E("mother", "HP:0002725", fam=True)]
    m = score([{"diary": "d", "gold": gold, "pred": dropped}])
    assert m["tp"] == 2 and m["fp"] == 1 and m["fn"] == 1  # the dropped negation is a miss and a false positive
    assert m["negated_recall"] == 0.0 and m["n_negated_gold"] == 1
    assert m["family_history_recall"] == 1.0 and m["n_family_history_gold"] == 1
    ok = score([{"diary": "d", "gold": gold, "pred": gold}])
    assert ok["negated_recall"] == 1.0 and ok["entity_f1"] == 1.0
    assert score([{"diary": "d", "gold": [E("a", "HP:0000469")], "pred": []}])["negated_recall"] is None  # n = 0
