"""Diary entry -> grounded clinical entities.

The model proposes; code decides:
  * every entity must quote a span that exists in the entry (case-insensitive), else dropped
  * an HPO ID survives only if it exists in the ontology AND the quote or canonical name
    matches that term (label/synonym match score >= threshold); otherwise the ID is removed
    and a better ontology match is tried from the canonical name
  * negations ("no fever", "non ho febbre") are detected in code from the quote's left context
"""

from __future__ import annotations

import re
import unicodedata
import uuid

from pydantic import BaseModel, Field

from .knowledge import Ontology
from .llm import LLM, Stats
from .models import Entity

SYSTEM = """You read one diary entry written by a patient in everyday words (English or Italian) and list the \
clinically relevant things in it. Return JSON only:
{"entities": [{"quote": "<exact words copied from the entry>", "canonical": "<standard clinical English term>", \
"hpo_id": "<HP:0000000 code if you know it, else null>", "type": "symptom|finding|lab|medication|trigger|body_site", \
"negated": <true if the entry says it is absent>, "severity": <0-10 if the patient rates it, else null>}]}
Rules: quote must be copied exactly from the entry. One entity per distinct thing. Do not add anything the entry does \
not say. Do not interpret causes. Moods and weather are triggers only if the patient links them to a symptom."""

FEW_SHOT_USER = "Woke up with that butterfly rash on my cheeks again after gardening. Knees ache, maybe 6/10. No fever."
FEW_SHOT_ASSISTANT = ('{"entities": ['
                      '{"quote": "butterfly rash on my cheeks", "canonical": "Malar rash", "hpo_id": "HP:0025300", '
                      '"type": "symptom", "negated": false, "severity": null},'
                      '{"quote": "after gardening", "canonical": "Sun exposure", "hpo_id": null, "type": "trigger", '
                      '"negated": false, "severity": null},'
                      '{"quote": "Knees ache", "canonical": "Knee pain", "hpo_id": "HP:0030839", "type": "symptom", '
                      '"negated": false, "severity": 6},'
                      '{"quote": "No fever", "canonical": "Fever", "hpo_id": "HP:0001945", "type": "symptom", '
                      '"negated": true, "severity": null}]}')

MATCH_THRESHOLD = 0.6
_TYPES = {"symptom", "finding", "lab", "medication", "trigger", "body_site", "bodypart"}
_NEG = re.compile(r"\b(no|not|without|never|denies|nessun[ao]?|non|senza|niente)\b[^.;,]{0,25}$", re.I)


class RawEntity(BaseModel):
    quote: str = ""
    canonical: str = ""
    hpo_id: str | None = None
    type: str = "symptom"
    negated: bool = False
    severity: int | float | None = None


class RawOut(BaseModel):
    entities: list[RawEntity] = Field(default_factory=list)


def messages_for(text: str) -> list[dict]:
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": FEW_SHOT_USER},
            {"role": "assistant", "content": FEW_SHOT_ASSISTANT},
            {"role": "user", "content": text}]


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def find_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Locate quote in text ignoring case, accents and whitespace runs. Returns (start, end) in text."""
    q = re.sub(r"\s+", " ", _fold(quote).strip(" .,;:\"'"))
    if len(q) < 2:
        return None
    folded = _fold(text)
    pattern = re.escape(q).replace(r"\ ", r"\s+")
    m = re.search(pattern, folded)
    return (m.start(), m.end()) if m else None


def ground(entry_id: str, text: str, raw: RawOut, onto: Ontology, model: str | None) -> list[Entity]:
    out: list[Entity] = []
    seen: set[tuple[str, str]] = set()
    for r in raw.entities:
        span = find_quote(text, r.quote)
        if not span or not r.canonical.strip():
            continue
        quote = text[span[0]:span[1]]
        etype = "body_site" if r.type == "bodypart" else (r.type if r.type in _TYPES else "symptom")
        flags: list[str] = []
        hpo_id, hpo_label = None, None
        if etype in ("symptom", "finding", "lab", "body_site"):
            hpo_id, hpo_label, flags = resolve_hpo(r.hpo_id, quote, r.canonical, onto)
        negated = bool(r.negated) or bool(_NEG.search(text[max(0, span[0] - 30):span[0]]))
        if bool(r.negated) != negated:
            flags.append("negation_from_text")
        sev = r.severity
        sev = int(round(sev)) if isinstance(sev, (int, float)) and 0 <= sev <= 10 else None
        key = (hpo_id or r.canonical.lower(), quote.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(Entity(id=f"ent_{uuid.uuid4().hex[:10]}", entry_id=entry_id, type=etype, quote=quote,
                          canonical=r.canonical.strip()[:120], hpo_id=hpo_id, hpo_label=hpo_label,
                          negated=negated, severity=sev, flags=flags, model=model))
    return out


def resolve_hpo(proposed: str | None, quote: str, canonical: str, onto: Ontology) -> tuple[str | None, str | None, list[str]]:
    """Keep the model's HPO id only if the ontology agrees with the words; else try our own match."""
    flags: list[str] = []
    pid = (proposed or "").strip().upper()
    if pid and re.fullmatch(r"HP:\d{7}", pid) and onto.exists(pid):
        names = [_fold(n) for n in [onto.label(pid) or "", *onto.synonyms(pid)]]
        for phrase in (canonical, quote):
            m = onto.best_match(phrase)
            if m and (m[0].hpo_id == pid or pid in onto.ancestors(m[0].hpo_id) or m[0].hpo_id in onto.ancestors(pid)):
                return pid, onto.label(pid), flags
            if _fold(phrase).strip() in names:
                return pid, onto.label(pid), flags
        flags.append("hpo_dropped")
    elif pid:
        flags.append("hpo_invalid")
    m = onto.best_match(canonical) or onto.best_match(quote)
    if m and m[1] >= MATCH_THRESHOLD:
        flags.append("hpo_from_ontology")
        return m[0].hpo_id, m[0].label, flags
    flags.append("no_hpo")
    return None, None, flags


async def extract(llm: LLM, entry_id: str, text: str, onto: Ontology) -> tuple[list[Entity], Stats]:
    raw, st = await llm.json("extract", messages_for(text), RawOut, max_tokens=900, payload={"text": text})
    return ground(entry_id, text, raw, onto, st.model), st
