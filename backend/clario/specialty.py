"""Which specialty a brief line belongs to: rheumatology, nephrology, or only general practice.

Deterministic, no model: a term is mapped through its HPO organ system (`clinic_ddx.system_key`) plus a few label
keywords, a lab line through its test name. The clinic console uses the tags to reorder and filter the brief for the
specialty the clinician picks; general practice (the default) shows everything. Nothing here changes what is stored
or what reaches the patient.
"""

from __future__ import annotations

import re

from .clinic_ddx import system_key
from .documents import test_key
from .knowledge import Ontology
from .models import Brief, BriefItem, SharePackage

SPECIALTIES = ("rheumatology", "nephrology")

# Organ-system keys (clinic_ddx.SYSTEM_ORDER) -> specialties. "general" (fatigue, fever) and "blood" matter to both.
SYSTEMS: dict[str, tuple[str, ...]] = {
    "joints": ("rheumatology",), "skin": ("rheumatology",), "immune": ("rheumatology",),
    "blood": ("rheumatology", "nephrology"), "general": ("rheumatology", "nephrology"),
    "kidney": ("nephrology",), "metabolism": ("nephrology",),
}
# Label words for terms HPO files under a branch that does not say the specialty (Raynaud under cardiovascular,
# oral ulcers under head and neck, pleuritic pain under constitutional, oedema and hypertension for the kidney).
LABEL_WORDS: tuple[tuple[str, str], ...] = (
    ("raynaud", "rheumatology"), ("oral ulcer", "rheumatology"), ("pleur", "rheumatology"), ("sicca", "rheumatology"),
    ("dry eye", "rheumatology"), ("dry mouth", "rheumatology"), ("photosensitiv", "rheumatology"),
    ("edema", "nephrology"), ("oedema", "nephrology"), ("hypertension", "nephrology"), ("hematuria", "nephrology"),
    ("haematuria", "nephrology"), ("urin", "nephrology"), ("nephr", "nephrology"), ("renal", "nephrology"),
    ("kidney", "nephrology"),
)

_R, _N = ("rheumatology",), ("nephrology",)
_BOTH = ("rheumatology", "nephrology")
# Lab tests by folded name (documents.test_key), Italian and English. Unknown tests are general practice only.
_LABS: dict[tuple[str, ...], tuple[str, ...]] = {
    ("ANA", "Anticorpi antinucleo", "Antinuclear antibodies", "Anti-dsDNA", "dsDNA", "Anti-ENA", "ENA",
     "Fattore reumatoide", "Rheumatoid factor", "RF", "Anti-CCP", "VES", "ESR", "PCR", "CRP", "Proteina C reattiva",
     "C-reactive protein", "Linfociti", "Lymphocytes", "Neutrofili", "Neutrophils", "Piastrine", "Platelets",
     "Globuli bianchi", "White blood cells", "WBC", "Leucociti", "Leukocytes", "CK", "CPK"): _R,
    ("C3", "C4", "Complemento C3", "Complemento C4", "Complement C3", "Complement C4", "Emoglobina", "Hemoglobin",
     "Haemoglobin", "Hb", "Ematocrito", "Hematocrit", "Globuli rossi", "Red blood cells"): _BOTH,
    ("Creatinina", "Creatinine", "eGFR", "Filtrato glomerulare", "Azotemia", "Urea", "BUN", "Proteine urinarie",
     "Proteinuria", "Urine protein", "Albuminuria", "Microalbuminuria", "Sodio", "Sodium", "Potassio", "Potassium",
     "Calcio", "Calcium", "Fosforo", "Phosphate", "Acido urico", "Uric acid", "Bicarbonato", "Bicarbonate",
     "Emazie urinarie", "Urine red cells", "PTH", "Paratormone"): _N,
}
LAB_SPECIALTIES: dict[str, tuple[str, ...]] = {test_key(n): sp for names, sp in _LABS.items() for n in names}
_HPO = re.compile(r"\((HP:\d{7})\)")


def term_specialties(onto: Ontology, hpo_id: str | None, label: str = "") -> set[str]:
    """Specialties one term belongs to, from its organ system and its label. Empty: general practice only."""
    out = set(SYSTEMS.get(system_key(onto, hpo_id), ()))
    hpo_label = (onto.label(hpo_id) or "") if hpo_id else ""
    words = f"{label} {hpo_label}".lower()
    out |= {sp for w, sp in LABEL_WORDS if w in words}
    return out


def lab_specialties(name: str) -> set[str]:
    return set(LAB_SPECIALTIES.get(test_key(name or ""), ()))


def item_specialties(pkg: SharePackage, it: BriefItem, onto: Ontology) -> list[str]:
    """Specialties a brief line belongs to. Lab lines by test, term lines by their HPO id, AI lines by the terms
    recorded in the entries they cite. Medications, the summary and the questions are left untagged: the console
    shows those sections for every specialty."""
    out: set[str] = set()
    if it.section == "labs":
        key = it.id.removeprefix("bi_lab_")
        rows = [l for l in pkg.labs if (l.test_key or l.test_name)[:60 - len("bi_lab_")] == key]
        for l in rows:
            out |= lab_specialties(l.test_key or l.test_name) | lab_specialties(l.name_en or "") | lab_specialties(l.test_name)
    elif it.origin == "ai":
        for x in pkg.entities:
            if x.entry_id in it.cites and not x.negated and not x.family_history and x.type not in ("lab", "medication"):
                out |= term_specialties(onto, x.hpo_id, x.canonical)
    else:
        m = _HPO.search(it.text)
        if m:
            out |= term_specialties(onto, m.group(1), it.text)
    return [s for s in SPECIALTIES if s in out]


def tag(pkg: SharePackage, items: list[BriefItem], onto: Ontology) -> list[BriefItem]:
    return [i.model_copy(update={"specialties": item_specialties(pkg, i, onto)}) for i in items]


def tag_brief(pkg: SharePackage, brief: Brief, onto: Ontology) -> Brief:
    return brief.model_copy(update={"items": tag(pkg, brief.items, onto)})
