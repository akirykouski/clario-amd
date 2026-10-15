import json
import os
import py_compile
from pathlib import Path

import pytest

import export
import train_grpo as g
from prompt import SYSTEM_PROMPT

HERE = Path(__file__).resolve().parent
DIARY = "red cheeks since Tuesday, no fever. My mother has a joint pain."
GOLD = [
    {"quote": "red cheeks", "canonical": "Malar rash", "hpo_id": "HP:0000469", "type": "symptom", "negated": False,
     "family_history": False, "onset_hint": "since Tuesday", "severity": None, "confidence": None},
    {"quote": "fever", "canonical": "Fever", "hpo_id": "HP:0001945", "type": "symptom", "negated": True,
     "family_history": False, "onset_hint": None, "severity": None, "confidence": None},
    {"quote": "joint pain", "canonical": "Arthralgia", "hpo_id": "HP:0002829", "type": "symptom", "negated": False,
     "family_history": True, "onset_hint": None, "severity": None, "confidence": None},
]


def out(entities):
    return json.dumps({"entities": entities})


def ents(conf=0.9, **over):
    es = [dict(e, confidence=conf) for e in GOLD]
    for i, patch in over.items():
        es[int(i)].update(patch)
    return es


def r(text, gold=GOLD, diary=DIARY):
    return g.reward_total(diary, gold, text)


def test_perfect_confident_beats_everything_else():
    perfect = r(out(ents(1.0)))
    assert abs(perfect - (1.0 + 0.25 + 0.25)) < 1e-9
    assert perfect > r(out(ents(0.9)))  # same answer, less sure of itself: Brier is above zero
    assert r(out(ents(1.0, **{"0": {"hpo_id": "HP:0000001"}}))) < perfect
    assert r("not json") == -1.0 and r("") == -1.0


def test_calibration_term_prefers_honest_uncertainty():
    wrong_confident = r(out(ents(1.0, **{"0": {"hpo_id": "HP:0000001"}})))
    wrong_unsure = r(out(ents(1.0, **{"0": {"hpo_id": "HP:0000001", "confidence": 0.1}})))
    assert wrong_unsure > wrong_confident
    right_unsure = r(out(ents(1.0, **{"0": {"confidence": 0.1}})))
    assert right_unsure < r(out(ents(1.0)))  # being unsure about a right answer costs too
    comp = g.components(DIARY, GOLD, out(ents(1.0, **{"0": {"hpo_id": "HP:0000001"}})))
    assert abs(comp["brier"] - 1 / 3) < 1e-9  # one of three confident entities is wrong


def test_missing_confidence_is_punished():
    no_conf = [dict(e, confidence=None) for e in GOLD]
    assert g.components(DIARY, GOLD, out(no_conf))["brier"] == 1.0
    assert r(out(no_conf)) < r(out(ents(0.9)))


def test_hallucinated_quote_and_flags():
    fake = ents(1.0, **{"0": {"quote": "purple elephants"}})
    comp = g.components(DIARY, GOLD, out(fake))
    assert abs(comp["halluc"] - 1 / 3) < 1e-9 and abs(comp["grounding"] - 2 / 3) < 1e-9
    flipped = ents(1.0, **{"1": {"negated": False}, "2": {"family_history": False}})
    assert abs(g.components(DIARY, GOLD, out(flipped))["flags"] - 1 / 3) < 1e-9
    assert r(out(flipped)) < r(out(ents(1.0)))


def test_empty_gold_rewards_empty_output_only():
    assert r(out([]), gold=[], diary="quiet day") == 1.5
    assert r(out(ents(1.0)[:1]), gold=[], diary="red cheeks quiet day") < 0.5
    assert r(out([]), gold=GOLD) < 0.6  # silence on a clinical entry earns the grounding and nothing else


def test_trl_reward_functions_match_total_and_accept_chat_completions():
    comps = [[{"role": "assistant", "content": out(ents(0.8))}], out(ents(1.0, **{"1": {"negated": False}})), "garbage"]
    kw = dict(prompts=["p"] * 3, completions=comps, diary=[DIARY] * 3, gold=[json.dumps(GOLD)] * 3)
    cols = [fn(**kw) for fn in g.REWARD_FUNCS]
    assert [fn.__name__ for fn in g.REWARD_FUNCS] == ["reward_f1", "reward_grounding", "reward_flags", "reward_halluc",
                                                     "reward_brier", "reward_format"]
    assert len(g.REWARD_WEIGHTS) == len(g.REWARD_FUNCS)
    for i, c in enumerate(comps):
        weighted = sum(w * col[i] for w, col in zip(g.REWARD_WEIGHTS, cols))
        assert abs(weighted - r(g.completion_text(c))) < 1e-9
    assert cols[3][0] <= 0 and cols[4][0] <= 0 and cols[5] == [0.0, 0.0, -1.0]


def test_calibration_diagnostic():
    ece = g.reward_calibration([DIARY], [GOLD], [out(ents(1.0))])
    assert ece == 0.0
    assert g.reward_calibration([DIARY], [GOLD], [out([dict(e, confidence=None) for e in GOLD])]) is None


def test_load_rows_builds_confidence_prompt_and_gold(tmp_path):
    p = tmp_path / "train.jsonl"
    p.write_text(json.dumps({"diary": "red cheeks", "target": {"entities": GOLD[:1]}}) + "\n")
    rows = g.load_rows(str(p))
    assert rows[0]["prompt"][0]["content"] != SYSTEM_PROMPT and "probability" in rows[0]["prompt"][0]["content"]
    assert json.loads(rows[0]["gold"])[0]["confidence"] is None and rows[0]["diary"] == "red cheeks"


def test_dry_run_needs_no_torch(capsys):
    g.dry_run(str(HERE / "data" / "does-not-exist.jsonl"))
    out_ = capsys.readouterr().out
    assert "correct, confident" in out_ and "-1.000" in out_


def test_export_modelfile_and_merged_check(tmp_path):
    text = export.modelfile_text("clario-q4.gguf")
    assert text.startswith("FROM clario-q4.gguf") and "PARAMETER temperature 0.0" in text and "family_history" in text
    assert text.count('"""') == 2 and "\u2014" not in text
    assert set(export.merged_ok(str(tmp_path))) == {"config.json", "tokenizer_config.json", "*.safetensors"}
    for n in ("config.json", "tokenizer_config.json", "model-00001-of-00002.safetensors"):
        (tmp_path / n).write_text("x")
    assert export.merged_ok(str(tmp_path)) == []


@pytest.mark.parametrize("name", ["train_rocm.py", "train_grpo.py", "export.py", "gold_draft.py", "psytar_hpo.py",
                                  "synth.py", "prep.py", "eval.py", "prompt.py"])
def test_scripts_compile(name, tmp_path):
    py_compile.compile(str(HERE / name), cfile=str(tmp_path / (name + "c")), doraise=True)


def test_train_rocm_uses_v3_defaults_and_data_check():
    src = (HERE / "train_rocm.py").read_text()
    assert "data/v3/train_sft.jsonl" in src and "check_sft" in src and "remove_columns=ds.column_names" in src
