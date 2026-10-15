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
clinician may want to ask the patient. Write the items in the requested language (the clinical terms stay as given)."""


class DraftItem(BaseModel):
    section: str = "summary"
    text: str = ""
    cites: list[str] = Field(default_factory=list)


class DraftOut(BaseModel):
    items: list[DraftItem] = Field(default_factory=list)


NOT_REVIEWED = "not reviewed by a person"
SECTIONS = {"summary", "timeline", "symptoms", "labs", "medications", "patterns", "questions"}


def model_input(pkg: SharePackage, lang: str = "en") -> str:
    entries = [{"id": e.id, "date": e.occurred_on, "text": e.text} for e in pkg.entries]
    terms = Counter((x.canonical, x.hpo_id) for x in pkg.entities if not x.negated and not x.family_history)
    pats = [{"name": p.disease_name, "signal": p.signal, "overlap": [m.label for m in p.matched]} for p in pkg.patterns]
    return json.dumps({"language": "Italian" if lang == "it" else "English", "period": pkg.period,
                       "patient_note": pkg.note, "entries": entries,
                       "confirmed_terms": [{"term": t, "hpo": h, "times": n} for (t, h), n in terms.most_common()],
                       "pattern_overlaps": pats}, ensure_ascii=False)


def _span(ds: list[str], lang: str) -> str:
    if not ds:
        return ""
    if ds[0] == ds[-1]:
        return ds[0]
    return f"dal {ds[0]} al {ds[-1]}" if lang == "it" else f"{ds[0]} to {ds[-1]}"


def patient_items(pkg: SharePackage, lang: str = "en") -> list[BriefItem]:
    """Clinician view of what the patient recorded, straight from data: clinical terms and HPO ids."""
    it = lang == "it"
    items = []
    if pkg.note:
        lead = "Domanda per questa visita" if it else "Patient's question for this visit"
        items.append(BriefItem(id=_id(), section="summary", text=f"{lead}: {pkg.note}", origin="patient", review="accepted"))
    groups: dict[tuple[str, str], list] = {}
    for x in pkg.entities:
        if x.negated:
            continue
        sec = {"lab": "labs", "medication": "medications"}.get(x.type, "symptoms")
        fam = ("Storia familiare: " if it else "Family history: ") if x.family_history else ""
        label = fam + x.canonical + (f" ({x.hpo_id})" if x.hpo_id else "")
        groups.setdefault((sec, label), []).append(x)
    dates = {e.id: e.occurred_on for e in pkg.entries}
    for (sec, label), xs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        cites = [x.entry_id for x in xs]
        ds = sorted(dates[c] for c in cites if c in dates)
        extra = ""
        sev = [x.severity for x in xs if x.severity is not None]
        if sev:
            extra += f"; {'gravità fino a' if it else 'severity up to'} {max(sev)}/10"
        onset = next((x.onset_hint for x in xs if x.onset_hint), None)
        if onset:
            extra += f"; {'esordio' if it else 'onset'}: {onset}"
        mark = ""
        if any(not x.reviewed for x in xs):
            mark = f" ({'non verificato da una persona' if it else NOT_REVIEWED})"
        rec = f"registrato {len(cites)} {'volta' if len(cites) == 1 else 'volte'}" if it else f"recorded {len(cites)}x"
        items.append(BriefItem(id=_id(), section=sec, text=f"{label}: {rec}, {_span(ds, lang)}{extra}{mark}",
                               cites=sorted(set(cites)), origin="patient", review="accepted"))
    return items


# ---------------------------------------------------------------- audience and language views
TITLES = {
    ("clinician", "en"): {"summary": "Summary", "timeline": "Timeline", "symptoms": "Recorded symptoms", "labs": "Labs",
                          "medications": "Medications", "patterns": "Patterns software noticed (not a diagnosis)",
                          "questions": "Questions to ask"},
    ("clinician", "it"): {"summary": "Riepilogo", "timeline": "Cronologia", "symptoms": "Sintomi registrati", "labs": "Esami",
                          "medications": "Farmaci", "patterns": "Schemi notati dal software (non è una diagnosi)",
                          "questions": "Domande da fare"},
    ("patient", "en"): {"summary": "Summary", "timeline": "What happened when", "symptoms": "What you wrote about",
                        "labs": "Lab results", "medications": "Medicines", "patterns": "Worth discussing (not a diagnosis)",
                        "questions": "Questions"},
    ("patient", "it"): {"summary": "Riepilogo", "timeline": "Cosa è successo e quando", "symptoms": "Di cosa hai scritto",
                        "labs": "Esami", "medications": "Farmaci", "patterns": "Da discutere col medico (non è una diagnosi)",
                        "questions": "Domande"},
}
FOOTER = {
    ("clinician", "en"): "Prepared with Clario. AI-drafted items were reviewed by the clinician before this brief was final.",
    ("clinician", "it"): "Preparato con Clario. Le voci scritte dall'IA sono state riviste dal medico prima di rendere definitivo questo riepilogo.",
    ("patient", "en"): "Prepared with Clario. This is a plain-words copy of the brief your clinician reviewed. It is not a diagnosis.",
    ("patient", "it"): "Preparato con Clario. È una copia in parole semplici del riepilogo rivisto dal tuo medico. Non è una diagnosi.",
}


def names_condition(text: str, onto) -> bool:
    from .knowledge import _norm
    from .next_question import _all_names

    padded = f" {_norm(text)} "
    return any(f" {n} " in padded for n in _all_names(onto))


def patient_view_items(pkg: SharePackage, lang: str, onto) -> list[BriefItem]:
    """What the patient may keep: their own words, plain names, no condition names, nothing the clinician did not review."""
    from .i18n import term_label
    from .patterns import localize

    it = lang == "it"
    items: list[BriefItem] = []
    if pkg.note:
        items.append(BriefItem(id="bi_p_note", section="summary", origin="patient", review="accepted",
                               text=f"{'La tua domanda per questa visita' if it else 'Your question for this visit'}: {pkg.note}"))
    dates = {e.id: e.occurred_on for e in pkg.entries}
    groups: dict[str, list] = {}
    family = False
    for x in pkg.entities:
        if x.negated or x.type in ("lab", "medication", "trigger"):
            continue
        if x.family_history:
            family = True
            continue
        groups.setdefault(x.hpo_id or x.canonical, []).append(x)
    n = 0
    for xs in sorted(groups.values(), key=lambda v: -len(v)):
        x = xs[-1]
        cites = sorted({y.entry_id for y in xs})
        ds = sorted(dates[c] for c in cites if c in dates)
        name = term_label(x.hpo_id, x.canonical, lang)
        words = f'"{x.quote}"' if not names_condition(x.quote, onto) else ""
        times = f"{len(xs)} {'volta' if len(xs) == 1 else 'volte'}" if it else f"{len(xs)}x"
        said = "hai scritto" if it else "you wrote"
        text = f"{name}: {said} {words + ' ' if words else ''}({times}, {_span(ds, lang)})"
        items.append(BriefItem(id=f"bi_p{n}", section="symptoms", text=text, cites=cites, origin="patient", review="accepted"))
        n += 1
    if family:
        items.append(BriefItem(id="bi_p_family", section="summary", origin="patient", review="accepted",
                               text="Hai scritto di una condizione che ha un tuo parente." if it
                               else "You wrote about a condition that a relative has."))
    for i, p in enumerate(pkg.patterns):
        p = localize(p, lang)
        items.append(BriefItem(id=f"bi_p_pat{i}", section="patterns", origin="patient", review="accepted", cites=[],
                               text=(f"Cose che hai annotato e che spesso compaiono insieme: {p.neutral_label}. Non è una diagnosi."
                                     if it else f"Things you recorded that often show up together: {p.neutral_label}. Not a diagnosis.")))
    return items


def render_brief(pkg: SharePackage, brief: Brief, audience: str, lang: str, onto) -> Brief:
    """The brief as `audience` reads it, in `lang`. Clinician in the drafted language is the stored brief untouched.

    The patient copy keeps only AI items a clinician accepted or edited, drafted in the same language, that name no
    condition. Patient-origin items are rebuilt from the package in the requested wording."""
    if audience == "clinician" and lang == brief.lang:
        return brief.model_copy(update={"audience": "clinician"})
    ai = [i for i in brief.items if i.origin == "ai"]
    if audience == "clinician":
        items = patient_items(pkg, lang) + ai
    else:
        keep = [i for i in ai if i.review in ("accepted", "edited") and i.section in ("summary", "timeline")
                and brief.lang == lang and not names_condition(i.text, onto)]
        items = patient_view_items(pkg, lang, onto) + keep
    return brief.model_copy(update={"items": items, "audience": audience, "lang": lang})


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


def to_markdown(pkg: SharePackage, brief: Brief, audience: str = "clinician", lang: str | None = None, onto=None) -> str:
    lang = lang or brief.lang
    if onto is not None:
        brief = render_brief(pkg, brief, audience, lang, onto)
    it = lang == "it"
    dates = {e.id: e.occurred_on for e in pkg.entries}
    titles = TITLES[(audience, lang)]
    if audience == "clinician":
        head = f"# Riepilogo clinico: {pkg.patient_alias}" if it else f"# Clinician brief: {pkg.patient_alias}"
    else:
        head = f"# Il tuo riepilogo: {pkg.patient_alias}" if it else f"# Your summary: {pkg.patient_alias}"
    lines = [head, (f"Periodo dal {pkg.period[0]} al {pkg.period[1]}" if it else f"Period {pkg.period[0]} to {pkg.period[1]}"), ""]
    for sec, title in titles.items():
        items = [i for i in brief.items if i.section == sec and i.review in ("accepted", "edited")]
        if not items:
            continue
        lines.append(f"## {title}")
        for i in items:
            cite = ", ".join(dates.get(c, c) for c in i.cites)
            tag = "" if i.origin == "patient" or audience == "patient" else (" (bozza IA, rivista)" if it else " (AI-drafted, reviewed)")
            lines.append(f"- {i.text}{f' [{cite}]' if cite else ''}{tag}")
        lines.append("")
    lines.append(FOOTER[(audience, lang)])
    return "\n".join(lines) + "\n"
