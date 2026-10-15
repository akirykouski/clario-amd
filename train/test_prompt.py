import json
from pathlib import Path

from prompt import (FIELDS, SYSTEM_PROMPT, SYSTEM_PROMPT_CONF, build_messages, from_dataset_entities, normalise, parse,
                    strict_valid, target_json)

V3 = {"quote": "red cheeks", "canonical": "Malar rash", "hpo_id": "HP:0000469", "type": "symptom", "negated": False,
      "family_history": True, "onset_hint": "since Tuesday", "severity": 6, "confidence": 0.8}


def test_v3_roundtrip_keeps_every_field():
    out = parse(json.dumps({"entities": [V3]}))
    assert out == [V3] and list(out[0]) == list(FIELDS)


def test_target_json_has_all_fields_and_null_confidence_for_training():
    t = json.loads(target_json(from_dataset_entities([V3])))
    assert set(t["entities"][0]) == set(FIELDS) and t["entities"][0]["confidence"] is None
    assert strict_valid(target_json(from_dataset_entities([V3])))


def test_older_outputs_still_parse():
    old = '{"entities":[{"quote":"a b","canonical":"C","hpo_id":"","type":"bodypart","negated":true}]}'
    e = parse(old)[0]
    assert e["hpo_id"] is None and e["type"] == "body_site" and e["negated"] is True
    assert e["family_history"] is False and e["onset_hint"] is None and e["severity"] is None and e["confidence"] is None
    legacy = parse('{"entities":[{"span":"x y","name":"Fever","type":"med"}]}')[0]
    assert legacy["quote"] == "x y" and legacy["canonical"] == "Fever" and legacy["type"] == "medication"
    assert not strict_valid(old)  # old shape is parseable but not strict v3


def test_dataset_rows_and_bad_values_are_normalised():
    e = normalise({"name_colloquial": "q", "name_canonical": "c", "hpo_id": "hp:0000001", "severity": 11, "confidence": 1.5,
                   "onset_hint": "null"})
    assert e["quote"] == "q" and e["hpo_id"] == "HP:0000001" and e["severity"] is None and e["confidence"] is None
    assert e["onset_hint"] is None
    assert normalise({"severity": "7", "confidence": "0.25"})["severity"] == 7
    assert normalise({"confidence": True})["confidence"] is None


def test_parse_handles_fences_prose_and_failures():
    assert parse('```json\n{"entities":[]}\n```') == []
    assert parse('Sure: {"entities":[]} done') == []
    assert parse("nope") is None and parse('{"x":1}') is None and parse("") is None


def test_strict_valid_rejects_bad_shapes():
    ok = target_json([V3])
    assert strict_valid(ok)
    bad = json.loads(ok)
    bad["entities"][0]["severity"] = 11
    assert not strict_valid(json.dumps(bad))
    bad["entities"][0]["severity"] = 3
    bad["entities"][0]["extra"] = 1
    assert not strict_valid(json.dumps(bad))
    assert not strict_valid('{"entities":[],"x":1}') and strict_valid('{"entities":[]}')


def test_prompt_variants_and_contract_words():
    assert build_messages(" hi ")[0]["content"] == SYSTEM_PROMPT and build_messages("hi")[1]["content"] == "hi"
    assert build_messages("hi", confidence=True)[0]["content"] == SYSTEM_PROMPT_CONF != SYSTEM_PROMPT
    for w in ("family_history", "onset_hint", "severity", "confidence", "niente febbre", "mia madre"):
        assert w in SYSTEM_PROMPT
    assert "\u2014" not in SYSTEM_PROMPT and "!" not in SYSTEM_PROMPT
    schema = json.loads((Path(__file__).resolve().parent.parent / "backend/clario/schemas/extraction_v3.json").read_text())
    assert list(schema["properties"]["entities"]["items"]["required"]) == list(FIELDS)
