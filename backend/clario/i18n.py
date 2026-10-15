"""Server-side wording for patient-facing text in English or Italian.

Clinical vocabulary (HPO labels) is English. For the patient in Italian we show a plain Italian name where the
shipped table `data/hpo_it.json` has one; every other term keeps its English label (the clinician side always
keeps the English clinical term and the HPO id).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"


def norm_lang(lang: str | None) -> str:
    return "it" if (lang or "").strip().lower().startswith("it") else "en"


@lru_cache(maxsize=1)
def hpo_it() -> dict[str, str]:
    f = DATA / "hpo_it.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


@lru_cache(maxsize=1)
def lay_it() -> dict[str, str]:
    """HPO id -> everyday Italian phrase that completes 'Ti capita di avere ...?' (curated, short)."""
    f = DATA / "lay_terms_it.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def term_label(hpo_id: str | None, label: str, lang: str) -> str:
    return hpo_it().get(hpo_id or "", label) if lang == "it" else label


# Condition names the patient may open under "what this pattern resembles". Others keep the published English name.
DISEASE_IT = {"Systemic lupus erythematosus": "Lupus eritematoso sistemico"}


def disease_name(name: str, lang: str) -> str:
    return DISEASE_IT.get(name, name) if lang == "it" else name


PATTERNS_NOTE = {
    "en": ("Patterns worth discussing with your clinician. Not a diagnosis.",
           "Confirm at least 3 terms in your entries to look for patterns.",
           "No pattern stands out from your confirmed terms yet. Keep writing and confirming."),
    "it": ("Schemi da discutere con il medico. Non è una diagnosi.",
           "Conferma almeno 3 termini nelle tue note per cercare degli schemi.",
           "Per ora nessuno schema emerge dai termini confermati. Continua a scrivere e a confermare."),
}

ANSWER_ENTRY = {"en": ("Answer to a question:", "Yes", "No"), "it": ("Risposta a una domanda:", "Sì", "No")}
