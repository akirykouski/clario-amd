"""Detectors added for the pseudonymisation leak work, the eponym regression, and the leak corpus itself."""
import importlib.util
from pathlib import Path

import pytest

from clario.privacy import pseudonymize

PII_LEAK = Path(__file__).resolve().parents[2] / "eval" / "pii_leak.py"


def _red(text: str) -> str:
    return pseudonymize(text)[0]


# ---------------------------------------------------------------- new identifier detectors
@pytest.mark.parametrize("text,value", [
    ("Tessera sanitaria 80380123456789012345 al banco", "80380123456789012345"),
    ("TS 80380 1234 5678 9012 345 requested", "80380 1234 5678 9012 345"),
    ("health card no. 80380-0123-4567-8901-234", "80380-0123-4567-8901-234"),
    ("MRN 58290700: follow-up", "58290700"),
    ("Cartella clinica n. 2021/835665, reparto reumatologia", "2021/835665"),
    ("Patient ID AB-123456 on the letter", "AB-123456"),
    ("Numero ricovero 1234567", "1234567"),
    ("NHS number 943 476 5919", "943 476 5919"),
    ("Ref. 3347631 in the corner", "3347631"),
    ("the code at the top is 48062081", "48062081"),
    ("CF RSS MRC 85M01 H501Z", "RSS MRC 85M01 H501Z"),
    ("CF RSSMRC85M01H501Z", "RSSMRC85M01H501Z"),
    ("CF RSSMRC85M01H5O1Z (retyped)", "RSSMRC85M01H5O1Z"),
    ("write to tommaso.moretti [at] gmail.com", "tommaso.moretti [at] gmail.com"),
    ("Via XX Settembre 3 is the pharmacy", "Via XX Settembre 3"),
    ("Via dei Mille 7/B", "Via dei Mille 7/B"),
    ("Lungarno Vespucci 9", "Lungarno Vespucci 9"),
    ("abito in via garibaldi 42", "via garibaldi 42"),
    ("Flat 4, 22 Elm Close", "Flat 4, 22 Elm Close"),
    ("Condominio Le Rose, scala B, int. 4", "Condominio Le Rose, scala B, int. 4"),
    ("Born March 12th, 1985", "March 12th, 1985"),
    ("nata il 12 marzo '85", "12 marzo '85"),
    ("DOB 12-mar-1985", "12-mar-1985"),
    ("call 06/1234567 now", "06/1234567"),
    ("call 02 97 62 13 31 now", "02 97 62 13 31"),
    ("call (555) 123-4567 now", "(555) 123-4567"),
    ("call 333 12 34 567 now", "333 12 34 567"),
    ("call 02 00027264 now", "02 00027264"),
])
def test_identifier_is_fully_redacted(text, value):
    out = _red(text)
    for chunk in value.replace(",", " ").replace("[", " ").replace("]", " ").split():
        if len(chunk) > 3 and chunk.lower() not in {"born", "scala", "flat"}:
            assert chunk not in out, (text, out)


@pytest.mark.parametrize("text,gone", [
    ("Paziente: Moretti Tommaso. Motivo: stanchezza", ["Moretti", "Tommaso"]),
    ("PAZIENTE MORETTI TOMMASO esame", ["MORETTI", "TOMMASO"]),
    ("Cognome: Santoro   Nome: Ignazio", ["Santoro", "Ignazio"]),
    ("Dottoressa Barbieri ha detto di riposare", ["Barbieri"]),
    ("Prof. Pellegrini ha suggerito un esame", ["Pellegrini"]),
    ("il referto e firmato Gallo", ["Gallo"]),
    ("Referral signed by Dr Tommaso Moretti, rheumatology", ["Tommaso", "Moretti"]),
    ("my friend Priya noticed the rash", ["Priya"]),
    ("mia cugina Ilaria ha notato le dita bianche", ["Ilaria"]),
    ("Spoke to Fabrizio Gallo at reception", ["Fabrizio", "Gallo"]),
    ("Esposito said everything looks normal", ["Esposito"]),
    ("Visit with Moretti Marco today", ["Moretti", "Marco"]),
])
def test_names_by_label_title_and_cue(text, gone):
    out = _red(text)
    for g in gone:
        assert g not in out, (text, out)
    assert "[NAME]" in out


def test_tessera_and_record_numbers_report_an_existing_kind():
    _, reps = pseudonymize("TS 80380123456789012345 and MRN 5829070")
    assert {r["type"] for r in reps} == {"codice_fiscale"}
    out, _ = pseudonymize("TS 80380123456789012345 and MRN 5829070")
    assert "[HEALTH_ID]" in out and "[RECORD_NO]" in out


# ---------------------------------------------------------------- eponym regression (must NOT be redacted)
EPONYMS = ["Raynaud", "Sjogren", "Sjögren", "Hashimoto", "Crohn", "Parkinson", "Graves", "Behcet", "Addison", "Cushing",
           "Hodgkin", "Meniere", "Marfan", "Kawasaki", "Wilson", "Alzheimer", "Asperger", "Huntington", "Gilbert", "Paget"]


@pytest.mark.parametrize("epo", EPONYMS)
@pytest.mark.parametrize("tpl", [
    "Diagnosed with {e} disease two years ago.",
    "Il Dott. Rossi sospetta la sindrome di {e}.",
    "Anamnesi familiare: morbo di {e}.",
    "{e}'s syndrome runs in the family.",
    "The rheumatologist called it {e} syndrome.",
    "She told me it was {e} disease, not lupus.",
    "Called {e} syndrome by the second doctor.",
    "Mi hanno detto che potrebbe essere la malattia di {e}.",
    "Marco asked whether {e} could explain the pain.",
    "Dr. Bianchi mentioned {e} phenomenon again.",
    "Sara told me about {e} thyroiditis.",
])
def test_eponyms_are_never_redacted(epo, tpl):
    text = tpl.format(e=epo)
    out = _red(text)
    assert epo in out, (text, out)


@pytest.mark.parametrize("text", [
    "Sent the symptom sheet via email 2 times.",
    "Sent it via WhatsApp 5 times.",
    "Rheumatologist said the joints look fine.",
    "Neurologist asked about the tingling.",
    "Pharmacist told me to take it with food.",
    "Mom said she would drive me.",
    "Corso di fisioterapia 10 sedute.",
    "CRP 12 mg/L, ferritin 85 ng/mL, ANA 1:320, BP 120/80, HbA1c 53 mmol/mol.",
    "Methotrexate 15 mg weekly, Plaquenil 200 mg, prednisone 5 mg.",
    "Infusion at Ospedale San Raffaele in Milano, then St Thomas' Hospital in London.",
    "Walked 4000 steps, slept 6 hours, VAS 6/10, pulse 72/min at 14:30.",
])
def test_medical_content_and_places_survive(text):
    assert _red(text) == text


# ---------------------------------------------------------------- the leak corpus
def _corpus_module():
    spec = importlib.util.spec_from_file_location("clario_pii_leak", PII_LEAK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_corpus_is_deterministic_big_and_split_is_disjoint():
    m = _corpus_module()
    dev, test = m.build_corpus("dev"), m.build_corpus("test")
    assert len(dev) + len(test) >= 500 and len(test) >= 500
    assert m.build_corpus("test") == test
    assert m._vocab_disjoint()
    assert {ln["lang"] for ln in test} == {"en", "it"}
    for ln in dev + test:  # every gold span points at its text
        for s, e, _cat in ln["gold"] + ln["neg"]:
            assert 0 <= s < e <= len(ln["text"])
    assert not set(m.VOCAB["dev"]["first"]) & set(m.VOCAB["test"]["first"])


def test_leak_rates_stay_low_and_eponyms_stay_safe():
    m = _corpus_module()
    res = m.score(m.build_corpus("test"), pseudonymize)
    assert res["overall_identifiers"]["leak_rate"] <= 0.10
    for cat in ("email", "codice_fiscale", "tessera_sanitaria", "record_number", "phone", "date_of_birth"):
        assert res["per_category"][cat]["leak_rate"] <= 0.05, cat
    assert res["false_redaction"]["eponym"]["rate"] == 0
    assert res["false_redaction"]["lab_value"]["rate"] == 0
    assert res["false_redaction"]["drug"]["rate"] == 0
