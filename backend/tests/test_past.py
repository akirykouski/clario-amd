"""Past history cues (clario/past.py): read in code from the clause around the quote, EN and IT."""

import pytest

from clario.past import past_reference

NOTE = "2026-10-12"


def ref(text: str, quote: str, note: str = NOTE):
    i = text.lower().find(quote.lower())
    assert i >= 0, quote
    return past_reference(text, (i, i + len(quote)), note)


@pytest.mark.parametrize("text,quote,kind,n,unit,approx", [
    ("I remembered I had knee surgery 5 years ago.", "knee surgery", "ago", 5, "year", "2021-01-01"),
    ("Today I remembered I had knee surgery five years ago.", "knee surgery", "ago", 5, "year", "2021-01-01"),
    ("Two years ago my thyroid was removed.", "thyroid was removed", "ago", 2, "year", "2024-01-01"),
    ("As a child I had asthma.", "asthma", "childhood", None, None, None),
    ("As a child, I had asthma.", "asthma", "childhood", None, None, None),
    ("I had asthma when I was little.", "asthma", "childhood", None, None, None),
    ("I broke my wrist a year ago.", "broke my wrist", "ago", 1, "year", "2025-01-01"),
    ("Last year I had pneumonia.", "pneumonia", "ago", 1, "year", "2025-01-01"),
    ("I had a rash three months ago.", "rash", "ago", 3, "month", "2026-07-01"),
    ("I had shingles a few years back.", "shingles", "ago", None, "year", None),
    ("In 2019 I had my appendix out.", "appendix out", "year", 2019, None, "2019-01-01"),
    ("I had migraines in the past.", "migraines", "past", None, None, None),
    ("Ho avuto un'operazione al ginocchio cinque anni fa.", "operazione al ginocchio", "ago", 5, "year", "2021-01-01"),
    ("Da bambina avevo l'asma.", "asma", "childhood", None, None, None),
    ("Da bambina, avevo l'asma.", "asma", "childhood", None, None, None),
    ("Quando ero piccola avevo l'asma.", "asma", "childhood", None, None, None),
    ("L'anno scorso ho avuto la polmonite.", "polmonite", "ago", 1, "year", "2025-01-01"),
    ("Due anni fa mi hanno tolto la tiroide.", "tolto la tiroide", "ago", 2, "year", "2024-01-01"),
    ("Sei mesi fa ho avuto un'eruzione.", "eruzione", "ago", 6, "month", "2026-04-01"),
    ("Nel 2018 ho avuto la mononucleosi.", "mononucleosi", "year", 2018, None, "2018-01-01"),
    ("In passato ho sofferto di emicrania.", "emicrania", "past", None, None, None),
])
def test_past_cues(text, quote, kind, n, unit, approx):
    r = ref(text, quote)
    assert r is not None, text
    assert (r.kind, r.n, r.unit, r.approx_date) == (kind, n, unit, approx)
    assert r.cue and r.cue.lower() in text.lower()


@pytest.mark.parametrize("text,quote", [
    # onsets of something ongoing
    ("I have had headaches since two years.", "headaches"),
    ("I have had headaches for two years.", "headaches"),
    ("My knees started aching two years ago.", "knees started aching"),
    ("The rash began a few months ago.", "rash"),
    ("Headaches since last year.", "Headaches"),
    ("Headaches since 2019.", "Headaches"),
    ("I have had headaches for the past 3 weeks.", "headaches"),
    ("In the past few days my knees ache.", "knees ache"),
    ("In the last year I have been tired.", "tired"),
    ("Mal di testa da due anni.", "Mal di testa"),
    ("Ho mal di testa dall'anno scorso.", "mal di testa"),
    ("Ho l'asma da quando ero bambina.", "asma"),
    ("Mal di testa dal 2019.", "Mal di testa"),
    ("Il dolore è iniziato due anni fa.", "dolore"),
    # still there, or a current clause next to a past one
    ("I had asthma as a child and still have it.", "asthma"),
    ("I had knee surgery 5 years ago and now my knees ache.", "knees ache"),
    ("I had knee surgery 5 years ago, but my knees ache today.", "knees ache"),
    ("Cinque anni fa mi sono operata al ginocchio, ora le ginocchia fanno male.", "ginocchia fanno male"),
    ("Da bambina avevo l'asma, adesso sono stanca.", "stanca"),
    # recent, or this year
    ("Two weeks ago I had a fever.", "fever"),
    ("Three days ago I had a fever.", "fever"),
    ("In 2026 I started a diary.", "diary"),
    ("My knees ache.", "knees ache"),
])
def test_not_past(text, quote):
    assert ref(text, quote) is None, text


def test_cue_is_scoped_to_the_sentence():
    text = "I had knee surgery 5 years ago. My knees ache today."
    assert ref(text, "knee surgery").n == 5
    assert ref(text, "knees ache") is None


def test_approx_months_cross_the_year():
    assert ref("I had a rash eleven months ago.", "rash", "2026-03-15").approx_date == "2025-04-01"
