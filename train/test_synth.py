import argparse
import asyncio
import json
import random
from types import SimpleNamespace

import pytest

import synth
from prompt import strict_valid, target_json
from synth import Ontology, validate

ONTO = Ontology.load()
ULCER, FEVER, HEADACHE = "HP:0000155", "HP:0001945", "HP:0002315"


def P(**kw):
    p = {"disease": "X", "lang": "en", "kind": "clinical", "present": [ULCER], "absent": [FEVER], "family": [],
         "onset": {}, "severity": {}, "events": [], "trigger": None, "days": 1}
    p.update(kw)
    return p


PLAN = P()


def reply(diary, mentions):
    return {"diary": diary, "mentions": [{"id": i, "quote": q} for i, q in mentions]}


def test_accepts_grounded_row_with_ontology_labels():
    row, why = validate(ONTO, PLAN, reply("Woke up with a sore in my mouth again. Thankfully no fever today.",
                                          [(ULCER, "sore in my mouth"), (FEVER, "fever")]))
    assert why == "ok"
    ents = {e["hpo_id"]: e for e in row["target"]["entities"]}
    assert ents[ULCER]["canonical"] == ONTO.label(ULCER)
    assert ents[FEVER]["negated"] is True and ents[ULCER]["negated"] is False
    assert all(set(e) == set(synth.entity("q", "c", None, "symptom")) for e in ents.values())
    assert strict_valid(target_json(row["target"]["entities"]))


def test_rejects_paraphrased_quote():
    _, why = validate(ONTO, PLAN, reply("Woke up with a sore in my mouth again. No fever today.",
                                        [(ULCER, "mouth ulcer"), (FEVER, "fever")]))
    assert why == "quote_not_verbatim"


def test_rejects_absent_symptom_written_as_present():
    _, why = validate(ONTO, PLAN, reply("Woke up with a sore in my mouth again and a fever all day long.",
                                        [(ULCER, "sore in my mouth"), (FEVER, "fever")]))
    assert why == "negation_mismatch"


def test_rejects_missing_mention():
    _, why = validate(ONTO, PLAN, reply("Woke up with a sore in my mouth again. No fever today.",
                                        [(ULCER, "sore in my mouth")]))
    assert why == "missing_mention"


def test_rejects_copied_clinical_label():
    label = ONTO.label(ULCER).lower()
    assert len(label.split()) > 1
    _, why = validate(ONTO, P(absent=[]), reply(f"Woke up with {label} again and it hurts to eat.", [(ULCER, label)]))
    assert why == "clinical_label_used"


def test_rejects_ambiguous_and_overlapping_quotes():
    _, why = validate(ONTO, P(absent=[]), reply("A sore in my mouth, and again a sore in my mouth today.", [(ULCER, "sore in my mouth")]))
    assert why == "ambiguous_quote"
    p = P(present=[ULCER, HEADACHE], absent=[])
    _, why = validate(ONTO, p, reply("A bad sore in my mouth since yesterday morning.", [(ULCER, "sore in my mouth"), (HEADACHE, "bad sore")]))
    assert why == "overlapping_quotes"


def test_family_history_label_and_cue_check():
    p = P(absent=[], family=[{"id": HEADACHE, "relation": "my mother"}])
    row, why = validate(ONTO, p, reply("A sore in my mouth again today. My mother has terrible head pounding.",
                                       [(ULCER, "sore in my mouth"), (HEADACHE, "terrible head pounding")]))
    assert why == "ok"
    ents = {e["hpo_id"]: e for e in row["target"]["entities"]}
    assert ents[HEADACHE]["family_history"] is True and ents[ULCER]["family_history"] is False
    # relative cue missing for a family item -> reject; relative cue before a patient item -> reject
    _, why = validate(ONTO, p, reply("A sore in my mouth again today. I get terrible head pounding.",
                                     [(ULCER, "sore in my mouth"), (HEADACHE, "terrible head pounding")]))
    assert why == "family_mismatch"
    _, why = validate(ONTO, P(absent=[]), reply("My mother says I have a sore in my mouth again today.", [(ULCER, "sore in my mouth")]))
    assert why == "family_mismatch"


def test_italian_cues():
    p = P(lang="it", absent=[FEVER], family=[{"id": HEADACHE, "relation": "mia madre"}])
    row, why = validate(ONTO, p, reply("Oggi ho una piaga in bocca. Per fortuna niente febbre. Mia madre ha mal di testa forte.",
                                       [(ULCER, "piaga in bocca"), (FEVER, "febbre"), (HEADACHE, "mal di testa forte")]))
    assert why == "ok"
    ents = {e["hpo_id"]: e for e in row["target"]["entities"]}
    assert ents[FEVER]["negated"] and ents[HEADACHE]["family_history"] and not ents[ULCER]["negated"]


def test_onset_and_severity_must_sit_next_to_their_symptom():
    p = P(absent=[], onset={ULCER: "since Tuesday"}, severity={ULCER: 6})
    row, why = validate(ONTO, p, reply("A sore in my mouth since Tuesday, about 6/10 when I eat.", [(ULCER, "sore in my mouth")]))
    assert why == "ok"
    e = row["target"]["entities"][0]
    assert e["onset_hint"] == "since Tuesday" and e["severity"] == 6
    _, why = validate(ONTO, p, reply("A sore in my mouth, about 6/10 when I eat.", [(ULCER, "sore in my mouth")]))
    assert why == "onset_missing"
    _, why = validate(ONTO, p, reply("A sore in my mouth since Tuesday and it is bad when I eat.", [(ULCER, "sore in my mouth")]))
    assert why == "severity_missing"
    far = "A sore in my mouth. " + "Nothing else happened at all today. " * 6 + "Started since Tuesday, 6/10."
    _, why = validate(ONTO, p, reply(far, [(ULCER, "sore in my mouth")]))
    assert why == "onset_missing"
    _, why = validate(ONTO, p, reply("A sore in my mouth since Tuesday 6/10 when I eat.", [(ULCER, "sore in my mouth since Tuesday")]))
    assert why == "quote_overreach"


def test_hard_negative_has_no_entities_and_no_clinical_words():
    hn = P(kind="hard_negative", present=[], absent=[], events=["the bus was late twice"])
    row, why = validate(ONTO, hn, {"diary": "Quiet day, walked the dog and cooked pasta. The bus was late twice.", "mentions": []})
    assert why == "ok" and row["target"]["entities"] == [] and row["kind"] == "hard_negative"
    _, why = validate(ONTO, hn, {"diary": "Quiet day, but a headache since lunch. The bus was late twice.", "mentions": []})
    assert why == "clinical_in_hard_negative"
    _, why = validate(ONTO, hn, {"diary": "Giornata tranquilla, sono stanco ma ho cucinato la pasta oggi.", "mentions": []})
    assert why == "clinical_in_hard_negative"
    _, why = validate(ONTO, hn, {"diary": "Quiet day, walked the dog and cooked pasta.", "mentions": [{"id": ULCER, "quote": "dog"}]})
    assert why == "mentions_in_hard_negative"


def test_sampler_only_uses_lay_terms_and_builds_distractors():
    rng = random.Random(1)
    ds = [d for d in ONTO.diseases() if len(d.phenotypes) >= 3]
    plans = [p for p in (synth.plan(ONTO, ds, rng, 0.4, 0.1) for _ in range(400)) if p]
    assert len(plans) > 200
    clin = [p for p in plans if p["kind"] == "clinical"]
    assert all(t in synth.LAY for p in clin for t in p["present"])
    assert any(p["family"] for p in clin) and any(p["onset"] for p in clin) and any(p["severity"] for p in clin)
    assert any(p["kind"] == "hard_negative" for p in plans)
    assert {p["lang"] for p in plans} == {"en", "it"}
    for p in clin:  # a family item never reuses a term of the patient, onset/severity belong to present terms
        assert all(f["id"] not in p["present"] + p["absent"] for f in p["family"])
        assert set(p["onset"]) <= set(p["present"]) and set(p["severity"]) <= set(p["present"])
        assert len(set(p["onset"].values())) == len(p["onset"]) and len(set(p["severity"].values())) == len(p["severity"])


def _args(tmp_path, n=120, **kw):
    d = dict(n=n, out=str(tmp_path / "s.jsonl"), base_url="http://x/v1", model="m", api_key_env="", concurrency=4,
             max_rounds=3, seed=7, it_frac=0.4, p_hard_neg=0.1, offline=True)
    d.update(kw)
    return argparse.Namespace(**d)


def test_offline_pipeline_writes_valid_v3_rows_and_reports_rejects(tmp_path):
    summary = asyncio.run(synth.run(_args(tmp_path)))
    rows = [json.loads(l) for l in open(tmp_path / "s.jsonl")]
    assert len(rows) >= 100 and summary["rows_in_file"] == len(rows)
    assert {r["lang"] for r in rows} == {"en", "it"}
    ents = [e for r in rows for e in r["target"]["entities"]]
    assert any(e["family_history"] for e in ents) and any(e["negated"] for e in ents)
    assert any(e["onset_hint"] for e in ents) and any(e["severity"] is not None for e in ents)
    assert any(not r["target"]["entities"] for r in rows)
    assert all(strict_valid(target_json(r["target"]["entities"])) for r in rows)
    assert all(e["quote"] in r["diary"] for r in rows for e in r["target"]["entities"])
    stats = json.load(open(str(tmp_path / "s.jsonl") + ".stats.json"))
    assert "reject_reasons" in stats and stats["generator"] == "offline"


def test_model_path_with_fake_client(tmp_path):
    onto = ONTO

    class Fake:
        def __init__(self):
            self.calls = 0
            outer = self

            class Completions:
                async def create(self, **kw):
                    outer.calls += 1
                    user = kw["messages"][1]["content"]
                    assert kw["messages"][0]["content"] == synth.SYSTEM and "Language:" in user
                    ds = [d for d in onto.diseases() if len(d.phenotypes) >= 3]
                    p = synth.plan(onto, ds, random.Random(outer.calls))
                    while p is None:
                        p = synth.plan(onto, ds, random.Random(outer.calls + 99))
                    # answer a different plan's offline text: usually fails validation, which must be counted, not crash
                    txt = json.dumps(synth.offline_reply(onto, p))
                    msg = SimpleNamespace(content="```json\n" + txt + "\n```")
                    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))
            self.chat = SimpleNamespace(completions=Completions())

    fake = Fake()
    summary = asyncio.run(synth.run(_args(tmp_path, n=5, offline=False, max_rounds=2), client=fake))
    assert fake.calls > 0 and summary["tokens_in"] == 10 * fake.calls
    assert sum(summary["reject_reasons"].values()) + summary["accepted_this_run"] == fake.calls


def test_anthropic_endpoint_refused_for_training_data():
    with pytest.raises(SystemExit):
        synth.check_endpoint("https://api.anthropic.com/v1/")
    synth.check_endpoint("http://localhost:8000/v1")
