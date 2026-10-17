"""Offline checks for the fine-tune tooling: LoRA target selection, resolver metrics, batched eval, checkpoint pick.
No torch, no model."""
import json
import os

import eval as ev
import select_ckpt as sc
from train_rocm import lm_targets


class Linear: pass
class Linear4bit: pass
class Conv: pass


def test_lm_targets_skip_vision_audio_experts_and_non_linear():
    mods = [
        ("model.language_model.layers.0.self_attn.q_proj", Linear()),
        ("model.language_model.layers.0.mlp.down_proj", Linear4bit()),
        ("model.vision_tower.encoder.layers.0.self_attn.q_proj", Linear()),
        ("model.audio_tower.layers.0.self_attn.k_proj", Linear()),
        ("model.embed_vision.embedding_projection", Linear()),
        ("model.language_model.layers.1.mlp.experts.7.gate_proj", Linear()),
        ("model.language_model.layers.1.per_layer_input_gate", Linear()),
        ("model.language_model.layers.1.self_attn.v_proj", Conv()),
    ]
    assert lm_targets(mods) == ["model.language_model.layers.0.self_attn.q_proj",
                                "model.language_model.layers.0.mlp.down_proj"]
    assert "model.language_model.layers.1.mlp.experts.7.gate_proj" in lm_targets(mods, experts=True)


def E(q, h, canon="X"):
    return {"quote": q, "canonical": canon, "hpo_id": h, "type": "symptom", "negated": False, "family_history": False,
            "onset_hint": None, "severity": None, "confidence": None}


def test_resolved_metrics_rescore_after_resolver_and_leave_records_untouched():
    gold = [E("red cheeks", "HP:0000469")]
    recs = [{"id": "1", "diary": "red cheeks", "gold": gold, "pred": [E("red cheeks", "HP:9999999", "Malar rash")]},
            {"id": "2", "diary": "nothing", "gold": [], "pred": None}]
    assert ev.score(recs)["entity_f1"] == 0.0
    m = ev.resolved_metrics(recs, lambda e: "HP:0000469" if e["canonical"] == "Malar rash" else None)
    assert m["resolved_entity_f1"] == 1.0 and m["resolved_tp"] == 1
    assert recs[0]["pred"][0]["hpo_id"] == "HP:9999999"  # the raw predictions are not rewritten


def test_real_resolver_keeps_a_correct_id_and_fixes_a_wrong_one():
    resolve = ev.make_resolver()
    if resolve is None:  # backend not importable in this environment
        return
    assert resolve(E("red cheeks", "HP:0025300", "Malar rash")) == "HP:0025300"  # right id kept
    assert resolve(E("red cheeks", "HP:0001945", "Malar rash")) == "HP:0025300"  # Fever: words disagree, fixed
    assert resolve(E("red cheeks", "HP:0000469", "Malar rash")) == "HP:0025300"  # id not in the ontology, fixed


def test_run_records_uses_batches_for_in_process_models():
    calls = []

    def complete(diary):
        raise AssertionError("single calls must not be used when batching")

    def batch(diaries):
        calls.append(len(diaries))
        return [(json.dumps({"entities": []}), 0.1, 3) for _ in diaries]
    complete.batch = batch
    gold = [{"id": str(i), "diary": f"d{i}", "gold": []} for i in range(5)]
    recs, _ = ev.run_records(gold, complete, batch_size=2)
    assert calls == [2, 2, 1] and [r["id"] for r in recs] == ["0", "1", "2", "3", "4"]
    assert all(r["pred"] == [] and r["strict"] for r in recs)


def test_run_records_falls_back_to_single_calls_when_a_batch_fails():
    def complete(diary):
        return json.dumps({"entities": []}), 0.1, 3

    def batch(diaries):
        raise RuntimeError("CUDA out of memory")
    complete.batch = batch
    recs, _ = ev.run_records([{"id": "1", "diary": "d", "gold": []}], complete, batch_size=4)
    assert recs[0]["pred"] == [] and recs[0]["err"] is None


def test_checkpoints_in_training_order_and_pick_prefers_earlier_on_ties(tmp_path):
    for d in ("checkpoint-300", "checkpoint-75", "checkpoint-150", "adapter", "checkpoint-9-noadapter"):
        os.makedirs(tmp_path / d)
        if "noadapter" not in d:
            (tmp_path / d / "adapter_config.json").write_text("{}")
    assert [os.path.basename(c) for c in sc.checkpoints(str(tmp_path))] == \
        ["checkpoint-75", "checkpoint-150", "checkpoint-300", "adapter"]
    best = sc.pick([("checkpoint-75", 0.61, {}), ("checkpoint-150", 0.70, {}), ("checkpoint-300", 0.70, {}), ("adapter", None, {})])
    assert best[0] == "checkpoint-150"


def test_value_falls_back_to_plain_f1_without_resolver():
    assert sc.value({"entity_f1": 0.5}) == 0.5
    assert sc.value({"entity_f1": 0.5, "resolved_entity_f1": 0.7}) == 0.7


def test_summary_picks_the_best_run_and_writes_the_winner(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "RESULTS", str(tmp_path / "results"))
    for run, v in (("e4b-r16-lr1e-4", 0.62), ("e4b-r32-lr1e-4", 0.71)):
        os.makedirs(tmp_path / run)
        (tmp_path / run / "best.json").write_text(json.dumps({"run": run, "metric": sc.METRIC, "best": "checkpoint-150", "value": v}))
    os.makedirs(tmp_path / "sweep-e4b")
    sc.main(["--summary", "--tag", "e4b", "--out", str(tmp_path)])
    body = json.load(open(tmp_path / "results" / "sweep_e4b.json"))
    assert body["winner"] == "e4b-r32-lr1e-4" and body["split"] == "val"
    assert (tmp_path / "sweep-e4b" / "WINNER").read_text().strip().endswith("e4b-r32-lr1e-4/best_adapter")
