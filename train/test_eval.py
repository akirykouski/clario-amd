from eval import score, match_counts, fuzzy_counts, grounded
from prompt import parse, from_dataset_entities, build_messages, target_json


def E(q, c, h):
    return {"quote": q, "canonical": c, "hpo_id": h, "type": "symptom", "negated": False}


G = [E("pins and needles", "Paresthesia", "HP:0003401"), E("blurry vision", "Blurred vision", "HP:0000622")]


def rec(pred, diary="I have pins and needles and blurry vision"):
    return {"diary": diary, "gold": G, "pred": pred}


def test_perfect():
    m = score([rec(list(G))])
    assert m["entity_f1"] == 1.0 and m["hpo_id_accuracy"] == 1.0 and m["json_validity_rate"] == 1.0
    assert m["quote_grounding_rate"] == 1.0 and m["fuzzy_f1"] == 1.0


def test_empty_pred_valid_json():
    m = score([rec([])])
    assert m["entity_f1"] == 0.0 and m["entity_recall"] == 0.0 and m["json_validity_rate"] == 1.0


def test_invalid_json():
    m = score([rec(None)])
    assert m["json_validity_rate"] == 0.0 and m["entity_f1"] == 0.0


def test_both_empty():
    m = score([{"diary": "fine day", "gold": [], "pred": []}])
    assert m["entity_f1"] == 1.0


def test_partial():
    m = score([rec([G[0], E("headache", "Headache", "HP:0002315")])])
    assert (m["tp"], m["fp"], m["fn"]) == (1, 1, 1)
    assert abs(m["entity_precision"] - 0.5) < 1e-9 and abs(m["entity_recall"] - 0.5) < 1e-9
    assert abs(m["hpo_id_accuracy"] - 0.5) < 1e-9
    assert m["quote_grounding_rate"] == 0.5  # "headache" not in diary


def test_duplicate_not_double_counted():
    assert match_counts(G, [G[0], G[0]], lambda e: e["hpo_id"]) == (1, 1, 1)


def test_fuzzy_name_variant():
    p = [E("x", "Paraesthesia", "HP:9999999")]
    assert fuzzy_counts([G[0]], p)[0] == 1
    assert score([rec(p)])["entity_f1"] == 0.0


def test_grounding_case_insensitive():
    assert grounded("I have Pins And Needles", "pins and needles") and not grounded("abc", "")


def test_parse_variants():
    raw = '```json\n{"entities":[{"quote":"a","canonical":"b","hpo_id":"hp:0000001","type":"bodypart"}]}\n```'
    p = parse(raw)
    assert p[0]["hpo_id"] == "HP:0000001" and p[0]["type"] == "body_site"
    assert parse("nope") is None and parse('{"x":1}') is None
    assert parse('Sure: {"entities":[]} done') == []


def test_dataset_mapping_roundtrip():
    ents = from_dataset_entities([{"name_colloquial": "q", "name_canonical": "c", "hpo_id": "HP:0000001", "type": "bodypart"}])
    assert ents[0]["type"] == "body_site" and parse(target_json(ents)) == ents
    assert build_messages("hi")[1]["content"] == "hi"
