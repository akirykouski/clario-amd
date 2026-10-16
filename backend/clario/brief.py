"""Clinic side: draft a one-page clinician brief from a shared package.

Facts the patient recorded become `origin=patient` items straight from data (no model).
The model drafts `origin=ai` items (summary, timeline, questions to ask, pattern notes).
Code checks every AI item: citations must point at entries in the package, pattern and
summary text must pass the hedge validator. Every AI item starts `pending` and needs a clinician.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter

from pydantic import BaseModel, Field

from .i18n import hpo_it
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
LAB_PENDING = {"en": "from documents, pending check", "it": "dai referti, da verificare"}
SECTIONS = {"summary", "timeline", "symptoms", "labs", "medications", "patterns", "questions"}


def model_input(pkg: SharePackage, lang: str = "en") -> str:
    entries = [{"id": e.id, "date": e.occurred_on, "text": e.text} for e in pkg.entries]
    terms = Counter((x.canonical, x.hpo_id) for x in pkg.entities if not x.negated and not x.family_history)
    pats = [{"name": p.disease_name, "signal": p.signal, "overlap": [m.label for m in p.matched]} for p in pkg.patterns]
    return json.dumps({"language": "Italian" if lang == "it" else "English", "period": pkg.period,
                       "patient_note": pkg.note, "entries": entries,
                       "confirmed_terms": [{"term": t, "hpo": h, "times": n} for (t, h), n in terms.most_common()],
                       "pattern_overlaps": pats}, ensure_ascii=False)


_MONTHS = {"en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
           "it": "gen feb mar apr mag giu lug ago set ott nov dic".split()}


def elide_it(s: str) -> str:
    """Italian elision before the day numbers 8 and 11: "dal 8" -> "dall'8"."""
    base = {"dal": "dall'", "al": "all'", "del": "dell'", "il": "l'"}
    return re.sub(r"\b(dal|al|del|il) (8|11)(?!\d)", lambda m: base[m.group(1).lower()] + m.group(2), s, flags=re.I)


def fdate(iso: str, lang: str, year: bool = False) -> str:
    """"22 Aug" / "22 ago" for an ISO date, the way the UI writes it. Anything that is not an ISO date is returned as is."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso
    out = f"{int(m.group(3))} {_MONTHS['it' if lang == 'it' else 'en'][int(m.group(2)) - 1]}"
    return f"{out} {m.group(1)}" if year else out


def _span(ds: list[str], lang: str, year: bool = False) -> str:
    if not ds:
        return ""
    a, b = fdate(ds[0], lang, year), fdate(ds[-1], lang, year)
    if a == b:
        return a
    return elide_it(f"dal {a} al {b}") if lang == "it" else f"{a} to {b}"


def _times(n: int, lang: str) -> str:
    if lang == "it":
        return "1 volta" if n == 1 else f"{n} volte"
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


_LAB_FLAG = {"en": {"low": "low", "high": "high", "normal": "in range"}, "it": {"low": "basso", "high": "alto", "normal": "nella norma"}}


def _num(n: float) -> str:
    return f"{n:g}"


def _range_text(lo: float | None, hi: float | None, lang: str) -> str:
    """Printed reference range: both ends, only an upper end, or only a lower end."""
    it = lang == "it"
    if lo is not None and hi is not None:
        return f"valori di riferimento da {_num(lo)} a {_num(hi)}" if it else f"printed range {_num(lo)} to {_num(hi)}"
    if hi is not None:
        return f"valori di riferimento fino a {_num(hi)}" if it else f"printed range up to {_num(hi)}"
    if lo is not None:
        return f"valori di riferimento da {_num(lo)}" if it else f"printed range from {_num(lo)}"
    return ""


def _lab_value(r) -> str:
    return r.value_text or (_num(r.value_numeric) if r.value_numeric is not None else "?")


def lab_items(pkg: SharePackage, lang: str = "en") -> list[BriefItem]:
    """Lab lines straight from the shared rows (no model). Only tests that are out of range, positive or changed over
    time get a line; the rest are one count. A line is `pending` while any of its rows is unchecked, then `accepted`."""
    it = lang == "it"
    year = pkg.period[0][:4] != pkg.period[1][:4]
    groups: dict[str, list] = {}
    for l in pkg.labs:
        groups.setdefault(l.test_key or l.test_name, []).append(l)
    items: list[BriefItem] = []
    calm, calm_pending = 0, False
    for key, rows in sorted(groups.items(), key=lambda kv: min(r.date for r in kv[1])):
        rows = sorted(rows, key=lambda r: (r.date, r.page))
        pending = any(not r.reviewed for r in rows)
        changed = len({_lab_value(r) for r in rows}) > 1
        if not (changed or any(r.abnormal or r.flag in ("low", "high") for r in rows)):
            calm += 1
            calm_pending = calm_pending or pending
            continue
        name = rows[0].name_en if lang == "en" and rows[0].name_en else rows[0].test_name
        parts = []
        for r in rows:
            flag = f", {_LAB_FLAG[lang][r.flag]}" if r.flag else ""
            parts.append(f"{(_lab_value(r) + ' ' + r.unit).strip()}{flag} ({fdate(r.date, lang, year)}, {'pagina' if it else 'page'} {r.page})")
        rng = next((r for r in rows if r.ref_low is not None or r.ref_high is not None), None)
        rtxt = f"; {_range_text(rng.ref_low, rng.ref_high, lang)}" if rng else ""
        mark = f" ({LAB_PENDING[lang]})" if pending else ""
        items.append(BriefItem(id=f"bi_lab_{key}"[:60], section="labs", text=f"{name}: {'; '.join(parts)}{rtxt}{mark}",
                               pages=sorted({r.page for r in rows}), origin="document",
                               review="pending" if pending else "accepted"))
    if calm:
        text = (f"{calm} esami nella norma" if calm != 1 else "1 esame nella norma") if it else f"{calm} test{'s' if calm != 1 else ''} in range"
        items.append(BriefItem(id="bi_lab_in_range", section="labs", text=text, origin="document",
                               review="pending" if calm_pending else "accepted"))
    return items


def with_labs(brief: Brief, pkg: SharePackage, lang: str) -> Brief:
    """The brief with its lab lines rebuilt from the package as the clinic has decided it (rejected rows dropped)."""
    keep = [i for i in brief.items if not (i.section == "labs" and i.origin in ("patient", "document"))]
    return brief.model_copy(update={"items": keep + lab_items(pkg, lang)})


_NOTE_LEAD = re.compile(r"^\s*(domanda\s+(per|alla|della)\s+(la\s+|questa\s+)?visita|question\s+for\s+(the|this)\s+visit)\s*:\s*", re.I)


def _note_text(note: str) -> str:
    """The patient's own question without a label they typed themselves; the UI and the markdown add one."""
    return _NOTE_LEAD.sub("", note.strip(), count=1).strip() or note.strip()


def _label(x, lang: str) -> str:
    if lang == "it" and x.hpo_id and hpo_it().get(x.hpo_id):
        return hpo_it()[x.hpo_id]
    return x.canonical


def patient_items(pkg: SharePackage, lang: str = "en") -> list[BriefItem]:
    """Clinician view of what the patient recorded, straight from data: clinical terms and HPO ids."""
    it = lang == "it"
    year = pkg.period[0][:4] != pkg.period[1][:4]
    items = []
    if pkg.note:
        items.append(BriefItem(id="bi_note", section="summary", text=_note_text(pkg.note), origin="patient", review="accepted",
                               kind="patient_note"))
    groups: dict[tuple[str, str], list] = {}
    for x in pkg.entities:
        if x.negated:
            continue
        sec = {"lab": "labs", "medication": "medications"}.get(x.type, "symptoms")
        fam = ("Storia familiare: " if it else "Family history: ") if x.family_history else ""
        label = fam + _label(x, lang) + (f" ({x.hpo_id})" if x.hpo_id else "")
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
        rec = f"registrato {_times(len(cites), lang)}" if it else f"recorded {_times(len(cites), lang)}"
        items.append(BriefItem(id=_id(), section=sec, text=f"{label}: {rec}, {_span(ds, lang, year)}{extra}{mark}",
                               cites=sorted(set(cites)), origin="patient", review="accepted",
                               from_question=all(x.from_question for x in xs)))
    return items + lab_items(pkg, lang)


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
                        "labs": "Esami", "medications": "Farmaci", "patterns": "Da discutere con il medico (non è una diagnosi)",
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
    from .patterns import PATIENT_CARDS, neutral_label, patient_label

    it = lang == "it"
    items: list[BriefItem] = []
    if pkg.note:
        items.append(BriefItem(id="bi_p_note", section="summary", origin="patient", review="accepted", kind="patient_note",
                               text=_note_text(pkg.note)))
    year = pkg.period[0][:4] != pkg.period[1][:4]
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
        own = [y for y in xs if not y.from_question]
        asked = not own  # every mention is an answer to a question the app asked: there are no words of the patient to quote
        x = (own or xs)[-1]
        cites = sorted({y.entry_id for y in xs})
        ds = sorted(dates[c] for c in cites if c in dates)
        name = patient_label(onto, x.hpo_id, lang).capitalize() if x.hpo_id else x.canonical
        quote = x.quote if not names_condition(x.quote, onto) else ""
        times = f"{_times(len(xs), lang)}, {_span(ds, lang, year)}"
        if asked:
            lead = "hai risposto sì alla domanda" if it else "you answered yes when asked"
            fallback = "hai risposto sì a una domanda dell'app" if it else "you answered yes to a question from the app"
            text = f'{name}: {lead}: "{quote}" ({times})' if quote else f"{name}: {fallback} ({times})"
        else:
            words = f'"{quote}"' if quote else ""
            text = f"{name}: {'hai scritto' if it else 'you wrote'} {words + ' ' if words else ''}({times})"
        items.append(BriefItem(id=f"bi_p{n}", section="symptoms", text=text, cites=cites, origin="patient", review="accepted",
                               from_question=asked))
        n += 1
    items += lab_items(pkg, lang)
    if family:
        items.append(BriefItem(id="bi_p_family", section="summary", origin="patient", review="accepted",
                               text="Hai scritto di una condizione che ha un tuo parente." if it
                               else "You wrote about a condition that a relative has."))
    for i, p in enumerate(pkg.patterns[:PATIENT_CARDS]):
        title = neutral_label([patient_label(onto, m.hpo_id, lang) for m in p.matched])  # everyday words, never a condition name
        items.append(BriefItem(id=f"bi_p_pat{i}", section="patterns", origin="patient", review="accepted", cites=[],
                               text=(f"Cose che hai annotato e che spesso compaiono insieme: {title}. Non è una diagnosi."
                                     if it else f"Things you recorded that often show up together: {title}. Not a diagnosis.")))
    return items


def render_brief(pkg: SharePackage, brief: Brief, audience: str, lang: str, onto) -> Brief:
    """The brief as `audience` reads it, in `lang`. Clinician in the drafted language is the stored brief untouched.

    The patient copy keeps only AI items a clinician accepted or edited, drafted in the same language, that name no
    condition. Patient-origin items are rebuilt from the package in the requested wording."""
    if audience == "clinician" and lang == brief.lang:
        return with_labs(brief, pkg, lang).model_copy(update={"audience": "clinician"})
    ai = [i for i in brief.items if i.origin == "ai"]
    if audience == "clinician":
        items = patient_items(pkg, lang) + ai
    else:
        keep = [i for i in ai if i.review in ("accepted", "edited") and i.section in ("summary", "timeline")
                and brief.lang == lang and not i.flag and not names_condition(i.text, onto)]
        items = patient_view_items(pkg, lang, onto) + keep
    return brief.model_copy(update={"items": items, "audience": audience, "lang": lang})


def _term_names(pkg: SharePackage) -> dict[str, set[str]]:
    """Every way the package names one of the patient's terms (clinical name, Italian name) -> the term keys it can mean."""
    names: dict[str, set[str]] = {}
    for x in pkg.entities:
        if x.negated or x.family_history or x.type == "lab":
            continue
        key = x.hpo_id or x.canonical.lower()
        for n in (x.canonical, hpo_it().get(x.hpo_id or "", "")):
            if len(n.strip()) >= 4:
                names.setdefault(n.strip().lower(), set()).add(key)
    return names


def citation_problem(pkg: SharePackage, text: str, cites: list[str]) -> tuple[str, list[str]] | None:
    """The term the text names that none of the cited entries confirms, with the entries that do record it."""
    low = text.lower()
    supported = {x.hpo_id or x.canonical.lower() for x in pkg.entities
                 if x.entry_id in cites and not x.negated and not x.family_history}
    for name, keys in _term_names(pkg).items():
        if re.search(rf"\b{re.escape(name)}\b", low) and not (keys & supported):
            where = sorted({x.entry_id for x in pkg.entities
                            if (x.hpo_id or x.canonical.lower()) in keys and not x.negated and not x.family_history})
            return name, where
    return None


def citation_mismatch(pkg: SharePackage, text: str, cites: list[str]) -> bool:
    """True when the text names a term of the patient that none of the cited entries confirms."""
    return citation_problem(pkg, text, cites) is not None


def localize_dates(text: str, lang: str, year: bool = False) -> str:
    """ISO dates in model text become "22 Aug" / "22 ago", the way the UI writes them."""
    return elide_it(re.sub(r"\b\d{4}-\d{2}-\d{2}\b", lambda m: fdate(m.group(0), lang, year), text)) if lang == "it" \
        else re.sub(r"\b\d{4}-\d{2}-\d{2}\b", lambda m: fdate(m.group(0), lang, year), text)


def check_ai_items(pkg: SharePackage, draft: DraftOut, lang: str = "en") -> list[BriefItem]:
    valid = {e.id for e in pkg.entries}
    out = []
    for d in draft.items:
        text = localize_dates(d.text.strip(), lang, pkg.period[0][:4] != pkg.period[1][:4])
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
        bad = citation_problem(pkg, text, cites) if cites else None  # flagged items are never accepted without a clinician
        out.append(BriefItem(id=_id(), section=sec, text=text, cites=cites, origin="ai", review="pending",
                             flag="citation_mismatch" if bad else None, flag_term=bad[0] if bad else None,
                             flag_entries=bad[1] if bad else []))
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
    year = pkg.period[0][:4] != pkg.period[1][:4]
    lines = [head, f"Periodo {_span(list(pkg.period), 'it', True)}" if it else f"Period {_span(list(pkg.period), 'en', True)}", ""]
    for sec, title in titles.items():
        items = [i for i in brief.items if i.section == sec and i.review in ("accepted", "edited")]
        if not items:
            continue
        lines.append(f"## {title}")
        for i in items:
            cite = ", ".join(fdate(dates.get(c, c), lang, year) for c in i.cites)
            tag = "" if i.origin != "ai" or audience == "patient" else (" (bozza IA, rivista)" if it else " (AI-drafted, reviewed)")
            lead = ""
            if i.kind == "patient_note":
                lead = ("La tua domanda per questa visita: " if it else "Your question for this visit: ") if audience == "patient" \
                    else ("Domanda del paziente per questa visita: " if it else "Patient's question for this visit: ")
            lines.append(f"- {lead}{i.text}{f' [{cite}]' if cite else ''}{tag}")
        lines.append("")
    lines.append(FOOTER[(audience, lang)])
    return "\n".join(lines) + "\n"
