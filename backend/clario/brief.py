"""Clinic side: draft a one-page clinician brief from a shared package.

Facts the patient recorded become `origin=patient` items straight from data (no model).
The model drafts `origin=ai` items (summary, timeline, questions to ask, pattern notes).
Code checks every AI item: citations must point at entries in the package, pattern and
summary text must pass the hedge validator. Every AI item starts `pending` and needs a clinician.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter

from pydantic import BaseModel, Field

from .models import Brief, BriefItem, SharePackage
from .safety import hedge_problems

SYSTEM = """You draft a one-page brief for a clinician who has 15 minutes with this patient. You get the \
patient's own diary entries (with ids), the clinical terms the patient confirmed, and pattern overlaps computed by \
software. Write short, factual items. Every item must cite the entry ids it is based on. Do not diagnose, do not \
recommend treatment or doses, do not use percentages. Pattern items must use hedged words ("resembles", "may be \
worth considering"). Return JSON only:
{"items": [{"section": "summary|timeline|symptoms|labs|medications|patterns|questions", "text": "...", "cites": ["entry id", ...]}]}
Aim for: 1-2 summary items, 3-6 timeline items (dated, what changed), up to 3 pattern items, 2-4 questions the \
clinician may want to ask the patient."""


class DraftItem(BaseModel):
    section: str = "summary"
    text: str = ""
    cites: list[str] = Field(default_factory=list)


class DraftOut(BaseModel):
    items: list[DraftItem] = Field(default_factory=list)


SECTIONS = {"summary", "timeline", "symptoms", "labs", "medications", "patterns", "questions"}


def model_input(pkg: SharePackage) -> str:
    entries = [{"id": e.id, "date": e.occurred_on, "text": e.text} for e in pkg.entries]
    terms = Counter((x.canonical, x.hpo_id) for x in pkg.entities if not x.negated)
    pats = [{"name": p.disease_name, "signal": p.signal, "overlap": [m.label for m in p.matched]} for p in pkg.patterns]
    return json.dumps({"period": pkg.period, "patient_note": pkg.note, "entries": entries,
                       "confirmed_terms": [{"term": t, "hpo": h, "times": n} for (t, h), n in terms.most_common()],
                       "pattern_overlaps": pats}, ensure_ascii=False)


def patient_items(pkg: SharePackage) -> list[BriefItem]:
    items = []
    if pkg.note:
        items.append(BriefItem(id=_id(), section="summary", text=f"Patient's question for this visit: {pkg.note}",
                               origin="patient", review="accepted"))
    by_term: dict[tuple[str, str | None], list[str]] = {}
    for x in pkg.entities:
        if x.negated:
            continue
        sec = {"lab": "labs", "medication": "medications"}.get(x.type, "symptoms")
        by_term.setdefault((sec, x.canonical + (f" ({x.hpo_id})" if x.hpo_id else "")), []).append(x.entry_id)
    dates = {e.id: e.occurred_on for e in pkg.entries}
    for (sec, label), cites in sorted(by_term.items(), key=lambda kv: -len(kv[1])):
        ds = sorted(dates[c] for c in cites if c in dates)
        span = f"{ds[0]} to {ds[-1]}" if ds and ds[0] != ds[-1] else (ds[0] if ds else "")
        items.append(BriefItem(id=_id(), section=sec, text=f"{label}: recorded {len(cites)}x, {span}",
                               cites=sorted(set(cites)), origin="patient", review="accepted"))
    return items


def check_ai_items(pkg: SharePackage, draft: DraftOut) -> list[BriefItem]:
    valid = {e.id for e in pkg.entries}
    out = []
    for d in draft.items:
        text = d.text.strip()
        sec = d.section if d.section in SECTIONS else "summary"
        cites = [c for c in d.cites if c in valid]
        if not text or len(text) > 500:
            continue
        if sec != "questions" and not cites:
            continue  # uncited claims never reach the clinician
        problems = hedge_problems(text)
        if sec == "patterns" and problems:
            continue  # pattern notes must be hedged
        if any(p != "no hedging language" for p in problems):
            continue  # diagnostic or prescriptive language
        out.append(BriefItem(id=_id(), section=sec, text=text, cites=cites, origin="ai", review="pending"))
    return out


def _id() -> str:
    return f"bi_{uuid.uuid4().hex[:8]}"


def to_markdown(pkg: SharePackage, brief: Brief) -> str:
    dates = {e.id: e.occurred_on for e in pkg.entries}
    titles = {"summary": "Summary", "timeline": "Timeline", "symptoms": "Recorded symptoms", "labs": "Labs",
              "medications": "Medications", "patterns": "Patterns software noticed (not a diagnosis)",
              "questions": "Questions to ask"}
    lines = [f"# Clinician brief: {pkg.patient_alias}", f"Period {pkg.period[0]} to {pkg.period[1]}", ""]
    for sec, title in titles.items():
        items = [i for i in brief.items if i.section == sec and i.review in ("accepted", "edited")]
        if not items:
            continue
        lines.append(f"## {title}")
        for i in items:
            cite = ", ".join(dates.get(c, c) for c in i.cites)
            tag = "" if i.origin == "patient" else " (AI-drafted, reviewed)"
            lines.append(f"- {i.text}{f' [{cite}]' if cite else ''}{tag}")
        lines.append("")
    lines.append("Prepared with Clario. AI-drafted items were reviewed by the clinician before this brief was final.")
    return "\n".join(lines) + "\n"
