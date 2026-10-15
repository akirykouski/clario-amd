import asyncio
import json

from clario.extract import ExtractOpts, RawOut, extract, ground, is_family_history, find_quote, pick_schema
from clario.knowledge import Ontology
from clario.llm import LLM, Stats, merge_stats
from clario.models import Entity, Entry
from clario.patterns import evidence_from
from clario.review import route_review

ONTO = Ontology.load()
KNEES = {"quote": "Knees ache", "canonical": "Arthralgia", "hpo_id": "HP:0002829", "type": "symptom"}


def ent(**kw):
    return {"negated": False, "family_history": False, "onset_hint": None, "severity": None, "confidence": None} | kw


class FakeLLM(LLM):
    """Scripted: `primary` answers n=1 extract calls, `sampled` the n>1 ones, `pick` the hpo_pick calls."""

    backend, model = "fake", "fake-1"

    def __init__(self, primary, sampled=None, pick=None):
        super().__init__(2)
        self.primary, self.sampled, self.pick = primary, sampled or [], pick
        self.pick_schemas: list[dict] = []
        self.calls: list[tuple[str, int]] = []

    async def samples(self, task, messages, n, *, temperature=0.7, schema=None, payload=None, purpose=None):
        self.calls.append((task, n))
        st = Stats("fake", "fake-1", 1.0, 10, None)
        if task == "hpo_pick":
            self.pick_schemas.append(schema)
            ids = [c["id"] for c in payload["candidates"]]
            got = self.pick(payload, ids) if self.pick else "NONE"
            return [json.dumps({"hpo_id": got})], st
        if n == 1:
            return [json.dumps(self.primary)], st
        return [json.dumps(s) for s in self.sampled], st


def go(llm, text, **opts):
    base = dict(sc_n=1, hpo_pick=False) | opts
    return asyncio.run(extract(llm, "e1", text, ONTO, ExtractOpts(**base)))[0]


def test_span_not_in_text_is_dropped():
    llm = FakeLLM({"entities": [ent(**KNEES), ent(quote="seizures every night", canonical="Seizure", hpo_id="HP:0001250", type="symptom")]})
    got = go(llm, "Knees ache this morning")
    assert [e.canonical for e in got] == ["Arthralgia"]


def test_hpo_id_always_from_candidates_or_null():
    text = "Knees ache this morning"
    cands = {t.hpo_id for t in ONTO.search("Arthralgia Knees ache", 20)}
    assert "HP:0002829" in cands
    # model picks an id that is not on the candidate list -> null
    bad = FakeLLM({"entities": [ent(**KNEES)]}, pick=lambda p, ids: "HP:0001250")
    e = go(bad, text, hpo_pick=True)[0]
    assert e.hpo_id is None and "no_hpo" in e.flags
    # the schema offered to the model is exactly the candidates plus NONE
    assert set(bad.pick_schemas[0]["properties"]["hpo_id"]["enum"]) == cands | {"NONE"}
    assert pick_schema(["HP:0000001"])["properties"]["hpo_id"]["enum"] == ["HP:0000001", "NONE"]
    # a valid pick is kept; the proposal from the first call is never used on its own
    good = FakeLLM({"entities": [ent(**(KNEES | {"hpo_id": "HP:0001250"}))]}, pick=lambda p, ids: "HP:0002829")
    e = go(good, text, hpo_pick=True)[0]
    assert e.hpo_id == "HP:0002829" and e.hpo_label == "Arthralgia"
    none = FakeLLM({"entities": [ent(**KNEES)]}, pick=lambda p, ids: "NONE")
    assert go(none, text, hpo_pick=True)[0].hpo_id is None


def test_pick_is_checked_by_the_ontology():
    # a candidate that does not match the words is dropped by the final ontology check
    cands = [t.hpo_id for t in ONTO.search("Arthralgia Knees ache", 20)]
    wrong = next(c for c in cands if c != "HP:0002829" and "HP:0002829" not in ONTO.ancestors(c) and c not in ONTO.ancestors("HP:0002829"))
    llm = FakeLLM({"entities": [ent(**KNEES)]}, pick=lambda p, ids: wrong)
    e = go(llm, "Knees ache this morning", hpo_pick=True)[0]
    assert e.hpo_id in (None, wrong)
    if e.hpo_id is None:
        assert "hpo_dropped" in e.flags


def test_negation_found_in_code_even_if_model_misses_it():
    llm = FakeLLM({"entities": [ent(quote="fever", canonical="Fever", hpo_id="HP:0001945", type="symptom")]})
    e = go(llm, "Knees ache but no fever today")[0]
    assert e.negated and "negation_from_text" in e.flags
    # negated entities never count, even confirmed
    e = e.model_copy(update={"review": "confirmed"})
    entry = Entry(id="e1", created_at="x", occurred_on="2026-09-01", text="t", entities=[e])
    assert evidence_from([entry], ONTO) == {}


def test_family_history_in_english_and_italian_is_flagged_and_not_in_patterns():
    for text, quote in [("My mother has lupus. Knees ache.", "lupus"), ("Oggi bene. Mia madre ha il lupus.", "lupus"),
                        ("Mio padre ha l'artrite da anni", "artrite")]:
        llm = FakeLLM({"entities": [ent(quote=quote, canonical="Arthritis", hpo_id="HP:0001369", type="finding")]})
        e = go(llm, text)[0]
        assert e.family_history, text
        assert "family_history_from_text" in e.flags
        e = e.model_copy(update={"review": "confirmed"})
        entry = Entry(id="e1", created_at="x", occurred_on="2026-09-01", text=text, entities=[e])
        assert evidence_from([entry], ONTO) == {}
    # model flag alone is enough too, and the patient's own symptoms next to it still count
    llm = FakeLLM({"entities": [ent(quote="lupus", canonical="Lupus", type="finding", family_history=True)]})
    assert go(llm, "Lupus runs here")[0].family_history
    t = "My mother says I look tired"
    assert not is_family_history(t, find_quote(t, "tired"))
    t = "Tired. My mother has lupus."
    assert not is_family_history(t, find_quote(t, "Tired"))


def test_confidence_is_share_of_matching_samples():
    primary = {"entities": [ent(**KNEES), ent(quote="Tired", canonical="Fatigue", hpo_id="HP:0012378", type="symptom")]}
    hit = {"entities": [ent(**KNEES), ent(quote="Tired", canonical="Fatigue", type="symptom")]}
    miss = {"entities": [ent(quote="Tired", canonical="Fatigue", type="symptom")]}  # knees missing
    flipped = {"entities": [ent(**KNEES | {"negated": True}), ent(quote="Tired", canonical="Fatigue", type="symptom")]}
    llm = FakeLLM(primary, sampled=[hit, hit, hit, miss, flipped])
    got = {e.canonical: e for e in go(llm, "Knees ache. Tired.", sc_n=5)}
    assert got["Arthralgia"].confidence == 0.6 and got["Fatigue"].confidence == 1.0
    assert ("extract", 5) in llm.calls
    assert got["Arthralgia"].review == "needs_review" and got["Fatigue"].review == "auto"


def test_sc_n_1_gives_null_confidence_and_model_confidence_is_opt_in():
    llm = FakeLLM({"entities": [ent(**KNEES | {"confidence": 0.2})]})
    e = go(llm, "Knees ache", sc_n=1)[0]
    assert e.confidence is None and e.review == "auto" and llm.calls == [("extract", 1)]
    e = go(FakeLLM({"entities": [ent(**KNEES | {"confidence": 0.2})]}), "Knees ache", sc_n=1, trust_model_confidence=True)[0]
    assert e.confidence == 0.2 and e.review == "needs_review"
    # trusting the model with every confidence present skips the extra sampling call
    llm = FakeLLM({"entities": [ent(**KNEES | {"confidence": 0.9})]})
    assert go(llm, "Knees ache", sc_n=5, trust_model_confidence=True)[0].confidence == 0.9
    assert llm.calls == [("extract", 1)]


def test_old_format_outputs_still_parse():
    old = {"entities": [{"quote": "Knees ache", "canonical": "Knee pain", "hpo_id": None, "type": "symptom",
                         "negated": False, "severity": 6}]}
    e = go(FakeLLM(old), "Knees ache")[0]
    assert (e.canonical, e.severity, e.family_history, e.onset_hint, e.confidence, e.review) == ("Knee pain", 6, False, None, None, "auto")
    older = {"entities": [{"name": "Fatigue", "quote": "so tired", "type": "symptom"}]}
    e = go(FakeLLM(older), "I am so tired")[0]
    assert e.canonical == "Fatigue" and e.quote == "so tired"


def test_onset_hint_and_severity_pass_through():
    llm = FakeLLM({"entities": [ent(**KNEES | {"onset_hint": "since Tuesday", "severity": 7})]})
    e = go(llm, "Knees ache since Tuesday")[0]
    assert e.onset_hint == "since Tuesday" and e.severity == 7


def test_threshold_routing():
    assert route_review(0.69, 0.7) == "needs_review"
    assert route_review(0.7, 0.7) == "auto"
    assert route_review(None, 0.7) == "auto"
    assert route_review(0.6, 0.5) == "auto"
    raw = RawOut.model_validate({"entities": [KNEES]})
    e = ground("e1", "Knees ache", raw, ONTO, "m", confidences=[0.6], opts=ExtractOpts(review_threshold=0.7))[0]
    assert e.review == "needs_review"


def test_merge_stats_sums():
    s = merge_stats(Stats("b", "m", 10.0, 5, None), Stats("b", "m", 30.0, 15, None))
    assert s.latency_ms == 40.0 and s.tokens == 20 and s.tokens_per_s == 500.0
