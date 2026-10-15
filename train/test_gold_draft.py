import json
import re
from pathlib import Path
from types import SimpleNamespace

import gold_draft as gd
from gold_draft import Ontology

ONTO = Ontology.load()


def fake_client(replies):
    """Hands out one canned reply per call, in order."""
    it = iter(replies)

    class Completions:
        def create(self, **kw):
            assert kw["messages"][0]["content"] == gd.SYSTEM
            r = next(it)
            if isinstance(r, Exception):
                raise r
            msg = SimpleNamespace(content=r if isinstance(r, str) else json.dumps(r))
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))


def test_plans_cover_80_entries_with_hard_negatives():
    plans = gd.make_plans(50, 30)
    assert len(plans) == 80 and sum(p["lang"] == "en" for p in plans) == 50 and sum(p["lang"] == "it" for p in plans) == 30
    assert len({p["id"] for p in plans}) == 80
    hard = [p for p in plans if p["hard_negative"]]
    assert 8 <= len(hard) <= 16 and all(not p["features"] for p in hard)
    assert any("family" in " ".join(p["features"]) for p in plans)
    assert "NO health content" in gd.user_prompt(hard[0]) and "Italian" in gd.user_prompt(plans[-1])


def test_build_row_grounds_hpo_and_flags_disagreements():
    p = gd.make_plans(1, 0)[0]
    diary = "Since Tuesday my head has been pounding, no fever though. My mother has a rash on her cheeks."
    reply = {"diary": diary, "entities": [
        {"quote": "head has been pounding", "canonical": "Headache", "type": "symptom", "negated": False,
         "family_history": False, "onset_hint": "since Tuesday", "severity": None},
        {"quote": "fever", "canonical": "Fever", "type": "symptom", "negated": False, "family_history": False},  # wrong flag
        {"quote": "rash on her cheeks", "canonical": "Malar rash", "type": "symptom", "negated": False, "family_history": True},
        {"quote": "made up words", "canonical": "Cough", "type": "symptom"}]}
    row, why = gd.build_row(ONTO, p, reply, "claude-haiku-5-5")
    assert why == "ok" and row["status"] == "draft" and row["reviewer"] is None and row["dropped_not_verbatim"] == 1
    ents = {e["quote"]: e for e in row["target"]["entities"]}
    assert ents["head has been pounding"]["hpo_id"] == "HP:0002315"  # from the ontology, not from the model
    assert ents["head has been pounding"]["onset_hint"] == "since Tuesday"
    assert any("negation" in f for f in ents["fever"]["review_flags"])
    assert ents["rash on her cheeks"]["family_history"] is True
    assert not any("family" in f for f in ents["rash on her cheeks"]["review_flags"])
    assert all(len(e["hpo_candidates"]) > 0 and e["confidence"] is None for e in ents.values())
    assert all(e["quote"] in diary for e in row["target"]["entities"])


def test_run_with_fake_client_writes_drafts_jsonl(tmp_path):
    plans = gd.make_plans(2, 2)
    good = {"diary": "I woke up with a headache again today and my knees were stiff all morning.",
            "entities": [{"quote": "headache", "canonical": "Headache", "type": "symptom"}]}
    hard = {"diary": "Quiet day, walked the dog and cooked pasta for the whole family tonight.", "entities": []}
    bad_hard = {"diary": "Quiet day, walked the dog and cooked pasta for the whole family tonight.",
                "entities": [{"quote": "dog", "canonical": "Cough"}]}
    replies = [good, good, "not json at all", good]
    out = tmp_path / "gold" / "drafts.jsonl"
    # plan order: en-001, en-002, it-001, it-002; hard negatives are i % 7 == 3, none among the first two of a language
    res = gd.run(fake_client(replies), "fake-haiku", plans, out, concurrency=1)
    rows = [json.loads(l) for l in open(out)]
    assert res["requested"] == 4 and res["drafted"] == 3 and res["reasons"]["JSONDecodeError"] == 1
    assert all(r["status"] == "draft" and r["drafted_by"] == "fake-haiku" for r in rows)
    # hard-negative plan: entities must be empty
    hn = dict(plans[0], hard_negative=True, features=[])
    assert gd.build_row(ONTO, hn, hard, "m")[1] == "ok"
    assert gd.build_row(ONTO, hn, bad_hard, "m")[1] == "entities_in_hard_negative"


def test_review_html_is_self_contained_and_term_list_is_valid():
    html = (Path(__file__).resolve().parent.parent / "eval" / "gold" / "review.html").read_text()
    assert "<script src" not in html and "<link" not in html and "http://" not in html and "https://" not in html
    m = re.search(r"const TERMS = (\[.*?\]);\n", html, re.S)
    terms = json.loads(m.group(1))
    assert len(terms) > 1000 and all(re.fullmatch(r"HP:\d{7}", t[0]) and t[1] for t in terms)
    for needle in ("status:\"reviewed\"", "reviewer:rev", "hpo_candidates", "drafts", "gold.jsonl", "mark"):
        assert needle in html
    assert "\u2014" not in html


def test_build_review_html_roundtrip(tmp_path):
    p = tmp_path / "r.html"
    p.write_text("<script>\nconst TERMS = /*TERMS*/[];\nlet x;\n</script>\n")
    n = gd.build_review_html(p)
    assert n > 1000 and json.loads(re.search(r"const TERMS = (\[.*?\]);\n", p.read_text(), re.S).group(1))[0][0].startswith("HP:")
    assert gd.build_review_html(p) == n  # idempotent
