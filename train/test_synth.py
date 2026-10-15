import synth
from synth import Ontology, validate

ONTO = Ontology.load()
PLAN = {"disease": "X", "lang": "en", "present": ["HP:0000155"], "absent": ["HP:0001945"],
        "trigger": None, "days": 1}


def reply(diary, mentions):
    return {"diary": diary, "mentions": [{"id": i, "quote": q} for i, q in mentions]}


def test_accepts_grounded_row_with_ontology_labels():
    row, why = validate(ONTO, PLAN, reply("Woke up with a sore in my mouth again. Thankfully no fever today.",
                                          [("HP:0000155", "sore in my mouth"), ("HP:0001945", "fever")]))
    assert why == "ok"
    ents = {e["hpo_id"]: e for e in row["target"]["entities"]}
    assert ents["HP:0000155"]["name_canonical"] == ONTO.label("HP:0000155")
    assert ents["HP:0001945"]["negated"] is True and ents["HP:0000155"]["negated"] is False


def test_rejects_paraphrased_quote():
    _, why = validate(ONTO, PLAN, reply("Woke up with a sore in my mouth again. No fever today.",
                                        [("HP:0000155", "mouth ulcer"), ("HP:0001945", "fever")]))
    assert why == "quote_not_verbatim"


def test_rejects_absent_symptom_written_as_present():
    _, why = validate(ONTO, PLAN, reply("Woke up with a sore in my mouth again and a fever all day long.",
                                        [("HP:0000155", "sore in my mouth"), ("HP:0001945", "fever")]))
    assert why == "negation_mismatch"


def test_rejects_missing_mention():
    _, why = validate(ONTO, PLAN, reply("Woke up with a sore in my mouth again. No fever today.",
                                        [("HP:0000155", "sore in my mouth")]))
    assert why == "missing_mention"


def test_sampler_only_uses_lay_terms():
    import random
    rng = random.Random(1)
    ds = [d for d in ONTO.diseases() if len(d.phenotypes) >= 3]
    plans = [p for p in (synth.plan(ONTO, ds, rng) for _ in range(200)) if p]
    assert len(plans) > 50
    assert all(t in synth.LAY for p in plans for t in p["present"])
