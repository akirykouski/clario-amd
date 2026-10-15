"""The negation and family cue words live twice: backend/clario/extract.py (app) and train/synth.py (training data).

train/ must stay standalone, so the lists are copies. This test keeps them from drifting: every cue word the app
detects must also be detected by the generator's regexes, except the documented differences below.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "train"))

from clario import extract  # noqa: E402
import synth  # noqa: E402

NEG_WORDS = ["no", "not", "without", "never", "denies", "nessuno", "nessuna", "non", "senza", "niente"]
IT_REL = ["madre", "mamma", "padre", "papa", "papà", "sorella", "fratello", "nonna", "nonno", "zia", "zio", "cugino",
          "genitori", "famiglia"]
EN_REL = ["mother", "mom", "mum", "father", "dad", "sister", "brother", "grandmother", "grandfather", "grandma",
          "grandpa", "aunt", "uncle", "cousin", "parents", "family"]
# Intended differences: the app also reads these words, the generator never writes them
# (it writes "in my family" / "in famiglia" instead of a bare "family" relation).
NEG_APP_ONLY = {"denies"}
REL_APP_ONLY = {"parents", "family", "genitori", "famiglia"}


def _pre_neg(w: str) -> str:
    return f"{w} any very bad "


def _pre_rel(w: str) -> str:
    return f"{'mia' if w in IT_REL else 'my'} {w} has "


def test_negation_cues_match_between_app_and_generator():
    for w in NEG_WORDS:
        assert extract._NEG.search(_pre_neg(w)), f"app regex lost {w}"
    gaps = {w for w in NEG_WORDS if not synth.NEG.search(_pre_neg(w))}
    assert gaps == NEG_APP_ONLY


def test_family_cues_match_between_app_and_generator():
    for w in EN_REL + IT_REL:
        assert extract._FAMILY_IN_QUOTE.search(_pre_rel(w)), f"app regex lost {w}"
    gaps = {w for w in EN_REL + IT_REL if not synth.FAM.search(_pre_rel(w))}
    assert gaps == REL_APP_ONLY
