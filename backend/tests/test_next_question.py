import asyncio
import json

import numpy as np

from conftest import confirm_all, wait_extracted
from clario.knowledge import Ontology
from clario.llm import LLM, Stats
from clario.models import Entity, Entry
from clario.safety import is_red_flag_term
from clario.next_question import default_lay_terms, choose, expected_gain, next_question, question_problems, rank_diseases, template_question

T = {1: "Alpha sign", 2: "Beta sign", 3: "Shared sign", 4: "Only in first", 5: "Only in second", 6: "Only in third",
     7: "Chest pain", 100: "Root"}
LAY = {f"HP:{n:07d}": [w] for n, w in {1: "alpha thing", 2: "beta thing", 3: "shared thing", 4: "first thing",
                                         5: "second thing", 6: "third thing", 7: "chest ache"}.items()}


def hid(n):
    return f"HP:{n:07d}"


def toy() -> Ontology:
    """Three conditions share signs 1, 2, 3 and chest pain; each has one private sign."""
    terms = [[n, label, [], [] if n == 100 else [100], 0.0 if n == 100 else 2.5] for n, label in T.items()]
    base = [[1, 0.9], [2, 0.9], [3, 0.9], [7, 0.9]]
    diseases = [["ORPHA:1", "Zeta syndrome", base + [[4, 0.9]]],
                ["ORPHA:2", "Eta disease", base + [[5, 0.9]]],
                ["ORPHA:3", "Theta disorder", base + [[6, 0.9]]]]
    return Ontology({"terms": terms, "diseases": diseases})


def entry(*items: tuple[int, bool], eid="e1") -> Entry:
    ents = [Entity(id=f"x{n}{neg}{eid}", entry_id=eid, type="symptom", quote=T[n], canonical=T[n], hpo_id=hid(n),
                   negated=neg, status="confirmed") for n, neg in items]
    return Entry(id=eid, created_at="2026-01-01T00:00:00Z", occurred_on="2026-01-01", text="x", entities=ents)


def test_discriminating_feature_beats_shared_and_red_flag_is_never_asked():
    onto = toy()
    es = [entry((1, False), (2, False))]
    cs = choose(onto, es, LAY, min_terms=2)
    ids = [c.feature_id for c in cs]
    assert ids and ids[0] in {hid(4), hid(5), hid(6)}
    assert hid(3) not in ids  # shared by all three: zero gain
    assert hid(7) not in ids  # red-flag term, even though every condition has it
    assert all(c.ig > 0 for c in cs)
    assert cs[0].splits and set(cs[0].splits) <= {"ORPHA:1", "ORPHA:2", "ORPHA:3"}


def test_expected_gain_math():
    prior = np.array([1 / 3] * 3)
    lik = np.array([[0.9, 0.9, 0.02], [0.9, 0.02, 0.9], [0.9, 0.02, 0.02]])
    ig, pf = expected_gain(prior, lik)
    assert ig[0] < 0.1 < ig[1] and 0 < pf[1] < 1


def test_yes_raises_and_no_lowers_the_condition_with_the_feature():
    onto = toy()
    base = [entry((1, False), (2, False))]

    def score(es, did):  # share of the total, as the prior in the information-gain step sees it
        rs = rank_diseases(onto, es)
        return next(r.score for r in rs if r.disease.id == did) / sum(r.score for r in rs)

    s0 = score(base, "ORPHA:1")
    yes = base + [entry((4, False), eid="e2")]
    no = base + [entry((4, True), eid="e2")]
    assert score(yes, "ORPHA:1") > s0
    assert score(no, "ORPHA:1") < s0
    assert rank_diseases(onto, yes)[0].disease.id == "ORPHA:1"
    assert rank_diseases(onto, no)[0].disease.id != "ORPHA:1"
    assert not any(c.feature_id == hid(4) for c in choose(onto, no, LAY, min_terms=2))  # answered, not asked again


class FakeLLM(LLM):
    def __init__(self, text):
        super().__init__()
        self.text = text

    async def _complete(self, task, messages, json_mode, max_tokens, payload):
        return json.dumps({"question": self.text}), Stats("fake", "fake")


def test_questions_never_name_a_disease_or_a_drug():
    onto = toy()
    for bad in ["Do you have Zeta syndrome?", "Do you take ibuprofen for it?", "Did hydroxychloroquine help?",
                "Do you take a 200 mg dose?", "Is it a first thing. Or not?", "Tell me about it"]:
        assert question_problems(bad, onto), bad
    assert not question_problems("Do you sometimes have: first thing?", onto)
    es = [entry((1, False), (2, False))]
    q = asyncio.run(next_question(FakeLLM("Do you have Zeta syndrome?"), onto, es, "en", lay=LAY, min_terms=2))
    assert q and q.question_source == "template" and "zeta" not in q.question.lower()
    assert q.question == template_question(LAY[q.feature_id][0], "en")
    q = asyncio.run(next_question(FakeLLM("Did you take paracetamol?"), onto, es, "it", lay=LAY, min_terms=2))
    assert q and q.question.startswith("Le capita di avere")
    ok = asyncio.run(next_question(FakeLLM("Is there a second thing going on?"), onto, es, "en", lay=LAY, min_terms=2))
    assert ok and ok.question_source == "model"
    assert "may" in ok.why and "syndrome" not in ok.why.lower()


def test_real_ontology_never_asks_red_flags_or_names():
    onto = Ontology.load()
    es = [Entry(id="e", created_at="2026-01-01T00:00:00Z", occurred_on="2026-01-01", text="x", entities=[
        Entity(id=f"x{h}", entry_id="e", type="symptom", quote="q", canonical=onto.label(h), hpo_id=h, status="confirmed")
        for h in ["HP:0012378", "HP:0002829", "HP:0025300", "HP:0000155", "HP:0030880"]])]
    cs = choose(onto, es)
    assert cs
    lay = default_lay_terms()
    for c in cs:
        assert not is_red_flag_term(onto.label(c.feature_id), *lay[c.feature_id])


def test_api_question_and_answer_reorders_and_is_traceable(unlocked):
    unlocked.post("/api/demo", json={"persona": "giulia"})
    wait_extracted(unlocked)
    assert unlocked.get("/api/patterns/next-question").json() is None  # nothing confirmed yet
    confirm_all(unlocked)
    q = unlocked.get("/api/patterns/next-question", params={"lang": "en"}).json()
    assert q and q["question"].endswith("?") and q["ig"] > 0
    n_before = len(unlocked.get("/api/entries").json())
    r = unlocked.post("/api/patterns/answer", json={"feature_id": q["feature_id"], "answer": "yes"}).json()
    assert len(r["before"]) == 5 and len(r["after"]) == 5 and r["entry_id"]
    assert all("label" in x and "disease_name" not in x for x in r["after"])
    entries = unlocked.get("/api/entries").json()
    assert len(entries) == n_before + 1
    e = next(x for x in entries if x["id"] == r["entry_id"])
    assert e["text"].startswith("Answer to a question: ") and e["text"].endswith("Yes")
    ent = e["entities"][0]
    assert ent["hpo_id"] == q["feature_id"] and ent["status"] == "confirmed" and not ent["negated"]
    q2 = unlocked.get("/api/patterns/next-question").json()
    assert q2["feature_id"] != q["feature_id"]  # not asked again
    r2 = unlocked.post("/api/patterns/answer", json={"feature_id": q2["feature_id"], "answer": "no"}).json()
    e2 = next(x for x in unlocked.get("/api/entries").json() if x["id"] == r2["entry_id"])
    assert e2["entities"][0]["negated"] is True
    q3 = unlocked.get("/api/patterns/next-question").json()
    r3 = unlocked.post("/api/patterns/answer", json={"feature_id": q3["feature_id"], "answer": "unsure"}).json()
    assert r3["entry_id"] is None and r3["before"] == r3["after"]
    assert unlocked.get("/api/patterns/next-question").json()["feature_id"] != q3["feature_id"]
    assert unlocked.post("/api/patterns/answer", json={"feature_id": "HP:9999999", "answer": "yes"}).status_code == 422
    assert unlocked.get("/api/patterns").json()["patterns"]
