"""onset_hint keeps phrases that say when something started; a time of day or a trigger is dropped (clario/onset.py)."""

import pytest

from clario.extract import RawOut, ground
from clario.knowledge import Ontology
from clario.onset import normalise_onset, onset_kind

ONTO = Ontology.load()

ONSETS = ["since Tuesday", "since last weekend", "for three days", "for about two weeks", "since Monday morning",
          "ever since the holiday", "three days ago", "yesterday", "2026-10-12", "last week", "started on Friday",
          "da lunedì", "da martedì", "da tre giorni", "da circa due settimane", "dallo scorso fine settimana",
          "da lunedì mattina", "da stamattina", "tre giorni fa", "ieri", "la settimana scorsa", "dal 12/10"]
TIMES = ["in the morning", "in the mornings", "at night", "every evening", "this morning", "in the afternoon",
         "at bedtime", "every day", "most nights", "on waking",
         "stamattina", "la sera", "la mattina", "al mattino", "di notte", "ogni sera", "tutti i giorni",
         "nel pomeriggio", "spesso", "a volte", "al risveglio", "Stasera"]
TRIGGERS = ["after the sun", "after a cold swim", "after a long day in the sun", "when I climb stairs",
            "whenever I eat", "every time I stand up", "during exercise",
            "dopo il sole", "dopo una giornata al sole", "quando salgo le scale", "ogni volta che mangio",
            "mentre cammino", "Dopo un bagno freddo"]


@pytest.mark.parametrize("phrase", ONSETS)
def test_genuine_onsets_are_kept(phrase):
    assert onset_kind(phrase) == "onset" and normalise_onset(phrase) == phrase


@pytest.mark.parametrize("phrase", TIMES)
def test_time_of_day_and_frequency_are_not_an_onset(phrase):
    assert onset_kind(phrase) == "time_of_day" and normalise_onset(phrase) is None


@pytest.mark.parametrize("phrase", TRIGGERS)
def test_triggers_are_not_an_onset(phrase):
    assert onset_kind(phrase) == "trigger" and normalise_onset(phrase) is None


def test_empty_and_unknown_phrases():
    assert normalise_onset(None) is None and normalise_onset("  ") is None and onset_kind("") is None
    assert normalise_onset("recently") == "recently"  # not recognised: left as the model wrote it


def test_synth_onset_phrases_all_survive():
    """Every onset phrase the training generator writes (train/synth.py ONSET) is a genuine onset."""
    for p in ("since Tuesday", "since last weekend", "for three days", "for about two weeks", "since Monday morning",
              "da martedì", "dallo scorso fine settimana", "da tre giorni", "da circa due settimane", "da lunedì mattina"):
        assert normalise_onset(p) == p


def test_live_token_factory_note_is_normalised_in_ground():
    """Gemma-4-31B-IT on Token Factory, 17 Oct: both hints came back filled, neither is an onset."""
    text = "My knees ache in the morning and my cheeks went red after the sun, no fever"
    raw = RawOut.model_validate({"entities": [
        {"quote": "knees ache", "canonical": "Arthralgia", "hpo_id": "HP:0002829", "type": "symptom",
         "onset_hint": "in the morning"},
        {"quote": "cheeks went red", "canonical": "Facial erythema", "hpo_id": "HP:0001041", "type": "symptom",
         "onset_hint": "after the sun"},
        {"quote": "fever", "canonical": "Fever", "hpo_id": "HP:0001945", "type": "symptom", "negated": True,
         "onset_hint": None},
    ]})
    ents = {e.quote: e for e in ground("e1", text, raw, ONTO, "m")}
    assert ents["knees ache"].onset_hint is None and "onset_dropped" in ents["knees ache"].flags
    assert ents["cheeks went red"].onset_hint is None and "onset_dropped" in ents["cheeks went red"].flags
    assert ents["fever"].onset_hint is None and "onset_dropped" not in ents["fever"].flags


def test_genuine_onset_passes_through_ground_without_a_flag():
    raw = RawOut.model_validate({"entities": [
        {"quote": "ginocchia", "canonical": "Arthralgia", "hpo_id": "HP:0002829", "type": "symptom",
         "onset_hint": "da tre giorni"}]})
    e = ground("e1", "Mi fanno male le ginocchia da tre giorni", raw, ONTO, "m")[0]
    assert e.onset_hint == "da tre giorni" and "onset_dropped" not in e.flags
