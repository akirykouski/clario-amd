import json
import random

import pytest

import prep
from prompt import SYSTEM_PROMPT, strict_valid


def row(i, disease, lang, ents=None):
    return {"diary": f"diary number {i} for {disease} with enough words to be unique", "lang": lang, "source_disease": disease,
            "target": {"entities": ents if ents is not None else [
                {"quote": "x", "canonical": "X", "hpo_id": "HP:0000155", "type": "symptom", "negated": False}]}}


def corpus(n_dis=60, per=10, seed=3):
    rng = random.Random(seed)
    rows = []
    for d in range(n_dis):
        for k in range(per):
            rows.append(row(len(rows), f"ORPHA:{d}", "it" if rng.random() < 0.4 else "en",
                            ents=[] if k == 0 else None))
    return [prep.normalise_row(r) for r in rows]


def test_three_way_split_is_disease_disjoint_and_language_stratified():
    rows = corpus()
    tr, va, te = prep.split(rows, 0.1, 0.1, seed=5)
    dis = lambda rs: {r["source_disease"] for r in rs}
    assert not (dis(tr) & dis(va)) and not (dis(tr) & dis(te)) and not (dis(va) & dis(te))
    assert len(tr) + len(va) + len(te) == len(rows)
    assert 0.07 * len(rows) <= len(va) <= 0.14 * len(rows) and 0.07 * len(rows) <= len(te) <= 0.14 * len(rows)
    share = lambda rs: sum(r["lang"] == "it" for r in rs) / len(rs)
    for part in (tr, va, te):
        assert abs(share(part) - share(rows)) < 0.12


def test_split_is_deterministic():
    rows = corpus()
    a = prep.split(rows, 0.1, 0.1, seed=5)
    b = prep.split(list(rows), 0.1, 0.1, seed=5)
    assert [[r["id"] for r in x] for x in a] == [[r["id"] for r in x] for x in b]


def test_normalise_row_upgrades_old_entities_to_v3():
    r = prep.normalise_row({"diary": "d d d", "target": {"entities": [
        {"name_colloquial": "q", "name_canonical": "c", "hpo_id": "", "type": "trigger", "negated": False}]}})
    e = r["target"]["entities"][0]
    assert e["quote"] == "q" and e["hpo_id"] is None and e["family_history"] is False and e["confidence"] is None
    assert r["kind"] == "clinical" and r["lang"] == "en" and len(r["id"]) == 12
    assert prep.normalise_row({"diary": "d", "target": {"entities": []}})["kind"] == "hard_negative"


def test_end_to_end_files(tmp_path, monkeypatch):
    rows = corpus(n_dis=40)
    src = tmp_path / "in" / "s.jsonl"
    src.parent.mkdir()
    src.write_text("".join(json.dumps(r) + "\n" for r in rows + rows[:5]))  # 5 exact duplicates must be dropped
    out = tmp_path / "v3"
    monkeypatch.setattr("sys.argv", ["prep.py", "--inputs", str(src), "--data-dir", str(out)])
    prep.main()
    counts = {}
    for name in ("train", "val", "test"):
        data = [json.loads(l) for l in open(out / f"{name}.jsonl")]
        sft = [json.loads(l) for l in open(out / f"{name}_sft.jsonl")]
        assert len(data) == len(sft) > 0
        counts[name] = len(data)
        for d, s in zip(data, sft):
            assert s["id"] == d["id"] and [m["role"] for m in s["messages"]] == ["system", "user", "assistant"]
            assert s["messages"][0]["content"] == SYSTEM_PROMPT and strict_valid(s["messages"][2]["content"])
            assert json.loads(s["messages"][2]["content"])["entities"] == d["target"]["entities"]
        assert prep.check_sft(str(out / f"{name}_sft.jsonl"))["rows"] == len(data)
    assert sum(counts.values()) == len(rows)
    md = (out / "SPLIT.md").read_text()
    assert "overlap train/val/test: 0" in md and "5 duplicate" in md and "hard negatives" in md


def test_check_sft_refuses_old_format(tmp_path):
    p = tmp_path / "old.jsonl"
    old = {"messages": [{"role": "system", "content": "old prompt"}, {"role": "user", "content": "u"},
                        {"role": "assistant", "content": '{"entities":[]}'}]}
    p.write_text(json.dumps(old) + "\n")
    with pytest.raises(ValueError, match="not a v3 chat row"):
        prep.check_sft(str(p))
    old["messages"][0]["content"] = SYSTEM_PROMPT
    old["messages"][2]["content"] = '{"entities":[{"quote":"a","canonical":"b","hpo_id":"","type":"symptom","negated":false}]}'
    p.write_text(json.dumps(old) + "\n")
    with pytest.raises(ValueError, match="strict extraction_v3"):
        prep.check_sft(str(p))
