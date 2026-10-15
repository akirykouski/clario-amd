"""Everyday wording for HPO terms and the filter for what a patient may be asked about or shown as "not recorded yet".

One place for both the next question and the "not recorded yet" lists: a term is patient-noticeable when it has plain
words (data/lay_terms.json), is not an emergency symptom, a lab or imaging finding, a structural or congenital
feature, a measurement a person cannot feel, or a term that mostly frightens.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .i18n import lay_it
from .knowledge import Ontology
from .safety import is_red_flag_term, is_unnoticeable_term

LAY_PATH = Path(__file__).parent / "data" / "lay_terms.json"

# Structural or congenital wording: a person cannot confirm it from how they feel day to day.
STRUCTURAL = re.compile(r"abnormal|anomal|malform|hypoplas|aplasia|dysplas|agenesis|atresia|congenital|aberrant|morpholog|"
                        r"defect|dysmorph|deformit|underdevelop|overgrowth|undergrowth|asymmetr|shape|position|"
                        r"bossing|micro(?:cephal|gnath|phthalm|tia)|macro(?:cephal|gnath)|hypertelor|hypotelor|"
                        r"syndactyl|polydactyl|brachydactyl|clinodactyl|contracture|scolio|kyphos|lordos", re.I)
# Words that mostly frighten without helping a person answer.
ANXIOUS = re.compile(r"cancer|tumou?r|carcinoma|neoplas|malignan|lymphoma|leuk(a)?emia|sarcoma|metasta|death|dying|"
                     r"fatal|blind|dementia|infarct|amputat|terminal|life[- ]threatening|disabilit|kidney failure|renal failure|"
                     r"chronic kidney|end[- ]?stage|organ failure|heart failure|pericard|around (the )?heart|myocard|cardiomyopath", re.I)
# Words that mark a clinical term even when it is listed as a synonym.
_CLINICAL = re.compile(r"\w+(?:itis|osis|emia|aemia|pathy|plasia|trophy|uria|rrhea|rrhoea|rrhagia|penia|megaly|oma|"
                       r"cytosis|lysis|stasis|sclerosis|ectasia)\b", re.I)

# Branches of the ontology a person cannot notice: structure present from birth, and blood or metabolic values.
STRUCTURAL_BRANCHES = ("HP:0011842",  # Abnormal skeletal morphology
                       "HP:0000271",  # Abnormality of the face
                       "HP:0000929",  # Abnormal skull morphology
                       "HP:0002652",  # Skeletal dysplasia
                       "HP:0000925",  # Abnormality of the vertebral column
                       "HP:0001197")  # Abnormality of prenatal development or birth
LAB_BRANCHES = ("HP:0001871",  # Abnormality of blood and blood-forming tissues
                "HP:0001939")  # Abnormality of metabolism/homeostasis
# Symptoms inside those branches a person can notice (they stay askable).
NOTICEABLE_EXCEPTIONS = frozenset({
    "HP:0001945",  # Fever
    "HP:0000952",  # Jaundice
    "HP:0000978",  # Bruising susceptibility
})
NOT_FELT = frozenset({
    "HP:0000822",  # Hypertension
    "HP:0001297",  # Stroke
    "HP:0000093",  # Proteinuria
    "HP:0000790",  # Hematuria
})

# Everyday English for terms where the shortest synonym is a clinical word.
LAY_EN = {
    "HP:0000952": "yellow skin or eyes",
    "HP:0000989": "itchy skin",
    "HP:0002014": "loose stools",
    "HP:0002019": "hard stools",
    "HP:0001824": "weight loss without trying",
    "HP:0002829": "joint pain",
    "HP:0001386": "swollen joints",
    "HP:0005197": "stiff joints in the morning",
    "HP:0025300": "a red rash across the cheeks and nose",
    "HP:0000155": "mouth sores",
    "HP:0001596": "hair loss",
    "HP:0030880": "fingers that turn white or blue in the cold",
    "HP:0033771": "chest pain when breathing in",
    "HP:0010741": "swollen ankles or feet",
    "HP:0001945": "fever",
    "HP:0002315": "headaches",
    "HP:0012378": "unusual tiredness",
    "HP:0000217": "a dry mouth",
    "HP:0000992": "skin that reacts to sunlight",
    "HP:0001882": "low white blood cells",
    "HP:0000093": "protein in the urine",
    "HP:0002027": "belly pain",
    "HP:0001369": "swollen, painful joints",
    "HP:0001025": "hives",
}


@lru_cache(maxsize=1)
def default_lay_terms() -> dict[str, list[str]]:
    return json.loads(LAY_PATH.read_text(encoding="utf-8")) if LAY_PATH.exists() else {}


def lay_phrase(syns: list[str]) -> str | None:
    """A synonym a layperson could recognise: short, no 'abnormality of ...', structural or clinical-looking wording."""
    ok = [s for s in syns if 3 <= len(s) <= 60 and not re.match(r"(decreased|increased|reduced|elevated)", s, re.I)
          and len(s.split()) <= 5 and not STRUCTURAL.search(s) and not re.search(r"\d|\bof the\b.*\bof the\b", s)]
    plain = [s for s in ok if not _CLINICAL.search(s)]
    pick = plain or ok
    return min(pick, key=len).lower() if pick else None


def en_phrase(hid: str, syns: list[str] | None) -> str | None:
    """Everyday English for a term: the curated phrase, else the best plain synonym."""
    return LAY_EN.get(hid) or lay_phrase(syns or [])


def en_label(onto: Ontology, hid: str, lay: dict[str, list[str]] | None = None) -> str:
    """Name of a term for an English-speaking patient: everyday words when we have them, else the ontology label."""
    lay = default_lay_terms() if lay is None else lay
    return en_phrase(hid, lay.get(hid)) or (onto.label(hid) or hid).lower()


def in_branch(onto: Ontology, hid: str, branches: tuple[str, ...]) -> bool:
    anc = onto.ancestors(hid) | {hid}
    return any(b in anc for b in branches)


def patient_noticeable(onto: Ontology, hid: str, lay: dict[str, list[str]]) -> str | None:
    """The plain-words phrase for a term, or None when it must not be asked about or listed for a patient."""
    syns = lay.get(hid)
    label = onto.label(hid)
    if not syns or not label or hid in NOT_FELT:
        return None
    if is_red_flag_term(label, *syns) or is_unnoticeable_term(label, *syns) or STRUCTURAL.search(label):
        return None
    if ANXIOUS.search(label) or any(ANXIOUS.search(s) for s in syns):
        return None
    curated = hid in NOTICEABLE_EXCEPTIONS or hid in lay_it()  # a person wrote plain words for it: askable
    if not curated and in_branch(onto, hid, STRUCTURAL_BRANCHES + LAB_BRANCHES):
        return None
    return en_phrase(hid, syns)
