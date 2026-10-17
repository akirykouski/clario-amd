"""Clinic side: draft a one-page clinician brief from a shared package, then the clinician edits and signs it.

Facts the patient recorded become `origin=patient` items straight from data (no model).
The model drafts `origin=ai` items (summary, timeline, questions to ask, pattern notes).
Code checks every AI item: citations must point at entries in the package, pattern and
summary text must pass the hedge validator. The draft opens as a PDF marked "AI draft, not reviewed".
The clinician edits it as plain text (`brief_text`, one "## Section" per section), sees the same code checks as
warnings (`text_warnings`), and signs (`sign_items`): the signed text is the brief.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import date, timedelta
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from .i18n import hpo_it
from .models import Brief, BriefItem, BriefLine, BriefWarning, SharePackage
from .past import when_text
from .safety import hedge_problems
from .share import lab_needs_check

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


LOW_CONFIDENCE = "low-confidence reading, please check"
_LOW = {"en": LOW_CONFIDENCE, "it": "lettura incerta, da verificare"}
SECTIONS = {"summary", "timeline", "symptoms", "labs", "medications", "patterns", "questions"}


def _day(pkg: SharePackage, iso: str) -> str:
    """"day 12" for an ISO date: days from the first day of the shared period (day 1)."""
    try:
        return f"day {(date.fromisoformat(iso) - date.fromisoformat(pkg.period[0])).days + 1}"
    except ValueError:
        return iso


def entry_aliases(pkg: SharePackage) -> dict[str, str]:
    """Entry id -> short alias ("E1" is the first shared entry). Pseudonymised input carries these instead of the ids:
    the pseudonymiser reads the digits in an id as a record number and would cut it ("e_[RECORD_NO]"), so the model
    could only cite ids that do not exist. An alias has too few digits to look like an identifier."""
    return {e.id: f"E{n + 1}" for n, e in enumerate(pkg.entries)}


def model_input(pkg: SharePackage, lang: str = "en", relative_dates: bool = False) -> str:
    """The user message for the brief model. `relative_dates` (on whenever the input is pseudonymised): calendar
    dates become day numbers in the period ("day 12"), so no date leaves the server; `restore_days` maps them back.
    Entry ids become aliases ("E3", `entry_aliases`) the pseudonymiser leaves alone; `restore_cites` maps them back."""
    when = (lambda d: _day(pkg, d)) if relative_dates else (lambda d: d)
    alias = entry_aliases(pkg) if relative_dates else {}
    entries = [{"id": alias.get(e.id, e.id), "date": when(e.occurred_on), "text": e.text} for e in pkg.entries]
    terms = Counter((x.canonical, x.hpo_id) for x in pkg.entities if not x.negated and not x.family_history and not x.past)
    past = [{"term": x.canonical, "when": when_text(x.past, lang, around=True), "entry": alias.get(x.entry_id, x.entry_id)}
            for x in pkg.entities if x.past and not x.negated and not x.family_history]
    pats = [{"name": p.disease_name, "signal": p.signal, "overlap": [m.label for m in p.matched]} for p in pkg.patterns]
    head = {"language": "Italian" if lang == "it" else "English", "period": [when(d) for d in pkg.period]}
    if relative_dates:
        head["dates"] = 'Dates are day numbers in the period ("day 1" is its first day). Write dates the same way, e.g. "day 12".'
    return json.dumps({**head, "patient_note": pkg.note, "entries": entries,
                       "confirmed_terms": [{"term": t, "hpo": h, "times": n} for (t, h), n in terms.most_common()],
                       # past history the patient mentioned: it happened long before the note, not in the period
                       "past_history": past, "pattern_overlaps": pats,
                       # facts about earlier care (never the previous doctor's conclusions: share.facts_only)
                       "already_tried": [t.model_dump(exclude_none=True) for t in pkg.tried],
                       "already_tested": [t.model_dump(exclude_none=True) for t in pkg.tested]}, ensure_ascii=False)


_MONTHS = {"en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
           "it": "gen feb mar apr mag giu lug ago set ott nov dic".split()}


def elide_it(s: str) -> str:
    """Italian elision before the day numbers 8 and 11: "dal 8" -> "dall'8"."""
    base = {"dal": "dall'", "al": "all'", "del": "dell'", "il": "l'"}
    return re.sub(r"\b(dal|al|del|il) (8|11)(?!\d)", lambda m: base[m.group(1).lower()] + m.group(2), s, flags=re.I)


def fdate(iso: str, lang: str, year: bool = False) -> str:
    """"22 Aug" / "22 ago" for an ISO date, the way the UI writes it, with the year when it is not the current one or when asked. Anything that is not an ISO date is returned as is."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso
    out = f"{int(m.group(3))} {_MONTHS['it' if lang == 'it' else 'en'][int(m.group(2)) - 1]}"
    return f"{out} {m.group(1)}" if year or int(m.group(1)) != date.today().year else out


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


_LAB_FLAG = {"en": {"low": "low", "high": "high", "normal": "in range", "positive": "positive"},
             "it": {"low": "basso", "high": "alto", "normal": "nella norma", "positive": "positivo"}}


def _num(n: float, lang: str = "en") -> str:
    s = f"{n:g}"
    return s.replace(".", ",") if lang == "it" else s


def _range_text(lo: float | None, hi: float | None, lang: str) -> str:
    """Printed reference range: both ends, only an upper end, or only a lower end."""
    it = lang == "it"
    if lo is not None and hi is not None:
        return f"valori di riferimento da {_num(lo, lang)} a {_num(hi, lang)}" if it else f"printed range {_num(lo, lang)} to {_num(hi, lang)}"
    if hi is not None:
        return f"valori di riferimento fino a {_num(hi, lang)}" if it else f"printed range up to {_num(hi, lang)}"
    if lo is not None:
        return f"valori di riferimento da {_num(lo, lang)}" if it else f"printed range from {_num(lo, lang)}"
    return ""


def _lab_value(r, lang: str = "en") -> str:
    return r.value_text or (_num(r.value_numeric, lang) if r.value_numeric is not None else "?")


def _corrected_note(r, lang: str) -> str:
    """", corrected by the clinician (read as 1,1 g/dL)" for a reading the clinician corrected, else ""."""
    f = r.corrected_from
    if not f:
        return ""
    was = f.get("value_text") or (_num(f["value_numeric"], lang) if f.get("value_numeric") is not None else "?")
    was = f"{was} {f.get('unit') or ''}".strip()
    return f", corretto dal medico (letto {was})" if lang == "it" else f", corrected by the clinician (read as {was})"


def lab_items(pkg: SharePackage, lang: str = "en") -> list[BriefItem]:
    """Lab lines straight from the shared rows (no model). Only tests that are out of range, positive or changed over
    time get a line; the rest are one count. A line is `pending` while any of its rows still needs a clinician check, then `accepted`."""
    it = lang == "it"
    year = pkg.period[0][:4] != pkg.period[1][:4]
    groups: dict[str, list] = {}
    for l in pkg.labs:
        groups.setdefault(l.test_key or l.test_name, []).append(l)
    items: list[BriefItem] = []
    calm, calm_pending = 0, False
    for key, rows in sorted(groups.items(), key=lambda kv: min(r.date for r in kv[1])):
        rows = sorted(rows, key=lambda r: (r.date, r.page))
        pending = any(lab_needs_check(r) for r in rows)
        changed = len({_lab_value(r) for r in rows}) > 1
        if not (changed or any(r.abnormal or r.flag in ("low", "high") for r in rows)):
            calm += 1
            calm_pending = calm_pending or pending
            continue
        name = rows[0].name_en if lang == "en" and rows[0].name_en else rows[0].test_name
        parts = []
        for r in rows:
            flag = f", {_LAB_FLAG[lang][r.flag]}" if r.flag and r.value_numeric is not None else ""  # "Positivo 1:80" says it
            parts.append(f"{(_lab_value(r, lang) + ' ' + r.unit).strip()}{flag} ({fdate(r.date, lang, year)}, {'pagina' if it else 'page'} {r.page}"
                         f"{_corrected_note(r, lang)})")
        rng = next((r for r in rows if r.ref_low is not None or r.ref_high is not None), None)
        rtxt = f"; {_range_text(rng.ref_low, rng.ref_high, lang)}" if rng else ""
        mark = f" ({_LOW[lang]})" if pending else ""
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
        if x.past and not x.family_history:  # history, dated by the patient's words, not by the note
            fam = ("Anamnesi remota: " if it else "Past history: ")
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
        past = next((x.past for x in xs if x.past and not x.family_history), None)
        if past:
            extra += f"; {when_text(past, lang, around=True)}"
        mark = ""
        if any(x.needs_review for x in xs):
            mark = f" ({_LOW[lang]})"
        rec = (f"registrato {_times(len(cites), lang)}" if it else f"recorded {_times(len(cites), lang)}") if not past else (
            "menzionato" if it else "mentioned")
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
    past: list = []
    for x in pkg.entities:
        if x.negated or x.type in ("lab", "medication", "trigger"):
            continue
        if x.family_history:
            family = True
            continue
        if x.past:
            past.append(x)
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
    seen: set[str] = set()
    for x in past:  # "Past: knee surgery (about 5 years ago, 12 Oct)"
        key = x.hpo_id or x.canonical.lower()
        if key in seen:
            continue
        seen.add(key)
        # the patient's own words (never an English clinical label in Italian, never a condition name from the software)
        text = f"{'In passato' if it else 'Past'}: {x.quote} ({when_text(x.past, lang)}, {fdate(x.occurred_on, lang, year)})"
        items.append(BriefItem(id=f"bi_p_past{len(seen)}", section="symptoms", origin="patient", review="accepted",
                               cites=[x.entry_id], text=text))
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
    if audience == "clinician" and lang == brief.lang:  # a signed brief is what the clinician signed: never rebuilt
        return (brief if brief.finalized else with_labs(brief, pkg, lang)).model_copy(update={"audience": "clinician"})
    ai = [i for i in brief.items if i.origin in ("ai", "clinician")]
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


_DAY = re.compile(r"\b(?:day|giorno)\s+(\d{1,4})\b", re.I)


def restore_days(text: str, pkg: SharePackage) -> str:
    """"day 12" / "giorno 12" in model text (written from relative-date input) -> the ISO date of that day in the period."""
    start = date.fromisoformat(pkg.period[0])
    span = (date.fromisoformat(pkg.period[1]) - start).days + 1

    def iso(m: re.Match) -> str:
        n = int(m.group(1))
        return (start + timedelta(days=n - 1)).isoformat() if 1 <= n <= span else m.group(0)

    return _DAY.sub(iso, text)


_ALIAS = re.compile(r"\s*E\s*(\d{1,4})\s*", re.I)


def restore_cites(cites: list[str], pkg: SharePackage) -> list[str]:
    """Cited aliases ("E3", written from pseudonymised input) -> this package's entry ids, before the citation check.
    Real ids pass through (a local model sees them); anything else stays as it is and the check drops it."""
    by_alias = {a: i for i, a in entry_aliases(pkg).items()}
    out = []
    for c in cites:
        m = _ALIAS.fullmatch(c)
        out.append(by_alias.get(f"E{int(m.group(1))}", c) if m else c)
    return list(dict.fromkeys(out))


def check_ai_items(pkg: SharePackage, draft: DraftOut, lang: str = "en") -> list[BriefItem]:
    valid = {e.id for e in pkg.entries}
    out = []
    for d in draft.items:
        text = localize_dates(restore_days(d.text.strip(), pkg), lang, pkg.period[0][:4] != pkg.period[1][:4])
        sec = d.section if d.section in SECTIONS else "summary"
        cites = [c for c in restore_cites(d.cites, pkg) if c in valid]
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


# ---------------------------------------------------------------- edit and sign: the brief as plain text
NOTE_LEAD = {"en": "Patient's question for this visit: ", "it": "Domanda del paziente per questa visita: "}


def _year(pkg: SharePackage) -> bool:
    return pkg.period[0][:4] != pkg.period[1][:4]


def item_line(pkg: SharePackage, it: BriefItem, lang: str) -> str:
    """One brief line as the editor and the PDF show it. AI and clinician lines carry their cited entries as dates in
    brackets ("[22 Aug, 3 Sep]"); a line from the patient's data already says when."""
    lead = NOTE_LEAD[lang] if it.kind == "patient_note" else ""
    cite = ""
    if it.origin in ("ai", "clinician") and it.cites:
        dates = {e.id: e.occurred_on for e in pkg.entries}
        ds = list(dict.fromkeys(fdate(dates[c], lang, _year(pkg)) for c in it.cites if c in dates))
        cite = f" [{', '.join(ds)}]" if ds else ""
    return f"{lead}{it.text}{cite}"


def shown_items(pkg: SharePackage, brief: Brief, focus: str | None) -> list[BriefItem]:
    """What goes into the draft text and PDF: AI lines not rejected, patient lines, and only lab lines whose every reading
    is checked (#19), filtered and ordered for the specialty (#21)."""
    from .specialty import focus_items

    keep = [i for i in brief.items if i.review != "rejected" and not (i.origin == "document" and i.review == "pending")]
    return focus_items(keep, focus)


def brief_text(pkg: SharePackage, items: list[BriefItem], lang: str) -> str:
    """The editable text: "## Section" headings in the order the items come, one "- line" per item."""
    titles = TITLES[("clinician", lang)]
    out: list[str] = []
    sec = None
    for it in items:
        if it.section != sec:
            if out:
                out.append("")
            out.append(f"## {titles[it.section]}")
            sec = it.section
        out.append(f"- {item_line(pkg, it, lang)}")
    return "\n".join(out) + "\n"


def _section_of(heading: str) -> str | None:
    h = heading.strip().strip("#").strip().rstrip(":").lower()
    for (aud, _lang), titles in TITLES.items():
        if aud != "clinician":
            continue
        for key, title in titles.items():
            if h in (title.lower(), key):
                return key
    return None


def parse_text(text: str) -> tuple[list[tuple[str, str]], list[BriefWarning]]:
    """(section, line) pairs from the edited text, in order. A heading is a line starting with '#' or a section title on
    its own; lines before any heading belong to the summary. An unknown heading is a warning, its lines stay where they are."""
    out: list[tuple[str, str]] = []
    warns: list[BriefWarning] = []
    sec = "summary"
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        known = _section_of(line)
        if line.startswith("#") or (known and not line.startswith(("-", "*", "•"))):
            if known:
                sec = known
            else:
                warns.append(BriefWarning(kind="unknown_section", section=sec, line=line,
                                          message=f"Unknown section heading; its lines stay under {sec}"))
            continue
        line = re.sub(r"^[-*•]\s*", "", line).strip()
        if line:
            out.append((sec, line))
    return out, warns


_CITE = re.compile(r"\s*\[([^\[\]]+)\]\s*$")


def split_cites(pkg: SharePackage, line: str, lang: str) -> tuple[str, list[str], list[str]]:
    """(text without the trailing date brackets, entry ids on those dates, bracket parts that are no diary date)."""
    m = _CITE.search(line)
    if not m:
        return line, [], []
    by_date: dict[str, list[str]] = {}
    for e in pkg.entries:
        for lg in ("en", "it"):
            for y in (False, True):
                by_date.setdefault(fdate(e.occurred_on, lg, y or _year(pkg)).lower(), []).append(e.id)
                by_date.setdefault(e.occurred_on, []).append(e.id)
    ids: list[str] = []
    bad: list[str] = []
    for part in re.split(r"[,;]", m.group(1)):
        p = part.strip()
        if not p:
            continue
        hit = by_date.get(p.lower())
        if hit:
            ids += [i for i in dict.fromkeys(hit) if i not in ids]
        else:
            bad.append(p)
    if bad and not ids:  # brackets that hold no diary date at all are the clinician's own words
        return line, [], []
    return line[:m.start()].rstrip(), ids, bad


def _warn_texts(lang: str) -> dict[str, str]:
    if lang == "it":
        return {"hedge": "Le righe sugli schemi usano parole prudenti (\"somiglia\", \"potrebbe valere la pena\").",
                "diagnosis": "Suona come una diagnosi o una dose.",
                "citation": "Nomina \"{term}\", che nessuna delle note citate registra.",
                "citation_where": " È registrato il {dates}.",
                "unknown_date": "Tra parentesi c'è una data che non è una nota del diario: {dates}.",
                "unknown_section": "Titolo di sezione sconosciuto: le sue righe restano nella sezione precedente.",
                "labs_pending": "{n} letture di laboratorio da verificare prima di firmare. Le righe degli esami verificati "
                                "entrano nel testo con \"Ripristina la bozza\"."}
    return {"hedge": "Pattern lines use hedged words (\"resembles\", \"may be worth considering\").",
            "diagnosis": "Sounds like a diagnosis or a dose.",
            "citation": "Names \"{term}\", which none of the cited entries records.",
            "citation_where": " It is recorded on {dates}.",
            "unknown_date": "A date in brackets is not a diary entry: {dates}.",
            "unknown_section": "Unknown section heading: its lines stay in the section before it.",
            "labs_pending": "{n} lab reading(s) need your check before signing. Lines for checked labs come into the text "
                            "with \"Reset to draft\"."}


def _line_warnings(pkg: SharePackage, sec: str, line: str, msgs: dict[str, str], lang: str) -> list[BriefWarning]:
    """The code checks on one line the model or the clinician wrote (text as the editor shows it, dates in brackets)."""
    dates = {e.id: e.occurred_on for e in pkg.entries}
    warns: list[BriefWarning] = []
    body, cites, bad = split_cites(pkg, line, lang)
    if bad:
        warns.append(BriefWarning(kind="unknown_date", section=sec, line=line, message=msgs["unknown_date"].format(dates=", ".join(bad))))
    problems = hedge_problems(body)
    if sec == "patterns" and "no hedging language" in problems:
        warns.append(BriefWarning(kind="hedge", section=sec, line=line, message=msgs["hedge"]))
    if any(p != "no hedging language" for p in problems):
        warns.append(BriefWarning(kind="diagnosis", section=sec, line=line, message=msgs["diagnosis"]))
    bad_cite = citation_problem(pkg, body, cites) if cites else None
    if bad_cite:
        where = sorted({dates[c] for c in bad_cite[1] if c in dates})[:3]
        msg = msgs["citation"].format(term=bad_cite[0])
        if where:
            msg += msgs["citation_where"].format(dates=", ".join(fdate(d, lang, _year(pkg)) for d in where))
        warns.append(BriefWarning(kind="citation", section=sec, line=line, message=elide_it(msg) if lang == "it" else msg))
    return warns


def text_warnings(pkg: SharePackage, brief: Brief, text: str, lang: str, pending_labs: int = 0) -> list[BriefWarning]:
    """The code checks that still apply to the edited text, as warnings: the citation check on lines that cite entries,
    the hedge validator on pattern lines, diagnostic or dosing words on any line the model or the clinician wrote.
    Lines straight from the patient's data or a checked lab report are not checked again."""
    msgs = _warn_texts(lang)
    from_data = {item_line(pkg, i, lang) for i in brief.items if i.origin in ("patient", "document")}
    lines, warns = parse_text(text)
    for w in warns:
        w.message = msgs["unknown_section"]
    for sec, line in lines:
        if line not in from_data:
            warns += _line_warnings(pkg, sec, line, msgs, lang)
    if pending_labs:
        warns.append(BriefWarning(kind="labs_pending", message=msgs["labs_pending"].format(n=pending_labs)))
    return warns


# ---------------------------------------------------------------- edit and sign: the brief as cards (structured lines)
def lab_rows(pkg: SharePackage, lang: str) -> dict[str, list[dict]]:
    """Lab item id -> its readings for the editor's read-only table: test, value, flag, date, page (as `lab_items` groups them)."""
    groups: dict[str, list] = {}
    for l in pkg.labs:
        groups.setdefault(l.test_key or l.test_name, []).append(l)
    out: dict[str, list[dict]] = {}
    for key, rows in groups.items():
        rows = sorted(rows, key=lambda r: (r.date, r.page))
        name = rows[0].name_en if lang == "en" and rows[0].name_en else rows[0].test_name
        out[f"bi_lab_{key}"[:60]] = [
            {"test": name, "value": f"{_lab_value(r, lang)} {r.unit}".strip(), "flag": r.flag, "abnormal": r.abnormal,
             "date": r.date, "page": r.page, "range": _range_text(r.ref_low, r.ref_high, lang) if (r.ref_low is not None or r.ref_high is not None) else None,
             "corrected": bool(r.corrected_from)}
            for r in rows]
    return out


def editor_items(pkg: SharePackage, shown: list[BriefItem], lang: str) -> list[dict]:
    """The draft as the card editor shows it: one entry per line, cited entries as ids (the UI shows their dates and
    quotes), lab lines with their readings as rows."""
    rows = lab_rows(pkg, lang)
    out = []
    for i in shown:
        d = {"id": i.id, "section": i.section, "text": i.text, "cites": [c for c in i.cites if any(e.id == c for e in pkg.entries)],
             "origin": i.origin, "kind": i.kind, "pages": i.pages, "specialties": i.specialties}
        if i.origin == "document" and i.id in rows:
            d["rows"] = rows[i.id]
        out.append(d)
    return out


def _clean_cites(pkg: SharePackage, cites: list[str]) -> list[str]:
    known = {e.id for e in pkg.entries}
    return [c for c in dict.fromkeys(cites) if c in known]


def lines_items(pkg: SharePackage, shown: list[BriefItem], lines: list[BriefLine], lang: str) -> list[tuple[int, BriefItem]]:
    """(index in `lines`, item) for each non-empty line, mapped by id: a drafted AI line unchanged is `accepted`, changed
    (text, citations or section) `edited`; a patient or lab line unchanged keeps its origin, changed it becomes the
    clinician's; a line without a known id is the clinician's own (`origin=clinician`). An id used twice counts once."""
    by_id = {i.id: i for i in shown}
    used: set[str] = set()
    out: list[tuple[int, BriefItem]] = []
    for n, ln in enumerate(lines):
        text = " ".join((ln.text or "").split())
        if not text:
            continue
        body, typed, _bad = split_cites(pkg, text, lang)
        cites = _clean_cites(pkg, list(ln.cites) + typed)
        base = by_id.get(ln.id or "") if (ln.id or "") not in used else None
        if base is not None:
            used.add(base.id)
            same = body == base.text and cites == _clean_cites(pkg, base.cites) and ln.section == base.section
            if base.origin == "ai":
                upd = {"review": "accepted"} if same else {"section": ln.section, "text": body, "cites": cites, "review": "edited",
                                                         "flag": None, "flag_term": None, "flag_entries": []}
                out.append((n, base.model_copy(update=upd)))
                continue
            if same:
                out.append((n, base.model_copy()))
                continue
        lead = NOTE_LEAD[lang]
        note = base is None and body.startswith(lead)
        out.append((n, BriefItem(id=_id(), section=ln.section, text=body[len(lead):] if note else body, cites=cites,
                                 origin="clinician", review="accepted", kind="patient_note" if note else None)))
    return out


def lines_warnings(pkg: SharePackage, shown: list[BriefItem], lines: list[BriefLine], lang: str, pending_labs: int = 0) -> list[BriefWarning]:
    """`text_warnings` for the card editor: the same checks, each warning carrying `item`, the index of its line."""
    msgs = _warn_texts(lang)
    warns: list[BriefWarning] = []
    for n, it in lines_items(pkg, shown, lines, lang):
        if it.origin in ("patient", "document"):
            continue
        for w in _line_warnings(pkg, it.section, item_line(pkg, it, lang), msgs, lang):
            w.item = n
            warns.append(w)
    if pending_labs:
        warns.append(BriefWarning(kind="labs_pending", message=msgs["labs_pending"].format(n=pending_labs)))
    return warns


def sign_lines(pkg: SharePackage, shown: list[BriefItem], lines: list[BriefLine], lang: str) -> list[BriefItem]:
    """The brief's items after the clinician signed the cards, in their order; drafted AI lines that are gone are
    `rejected` (kept for the pilot counts, never printed); patient and lab lines that are gone are dropped."""
    kept = [it for _n, it in lines_items(pkg, shown, lines, lang)]
    used = {i.id for i in kept}
    return kept + [i.model_copy(update={"review": "rejected"}) for i in shown if i.origin == "ai" and i.id not in used]


def sign_items(pkg: SharePackage, shown: list[BriefItem], text: str, lang: str) -> list[BriefItem]:
    """The brief's items after the clinician signed `text`, in the order of the text. A line equal to a shown line keeps
    that item (an AI line is then `accepted`); a changed AI line is `edited` (the closest unmatched AI line of the same
    section); any other line is the clinician's own (`origin=clinician`). Shown AI lines that are gone are `rejected`
    (kept for the pilot counts, never printed); patient and lab lines that are gone are dropped."""
    by_line: dict[str, list[BriefItem]] = {}
    for i in shown:
        by_line.setdefault(item_line(pkg, i, lang), []).append(i)
    used: set[str] = set()
    out: list[BriefItem] = []
    pending: list[tuple[str, str]] = []
    lines, _ = parse_text(text)
    for sec, line in lines:
        hit = next((i for i in by_line.get(line, []) if i.id not in used), None)
        if hit:
            used.add(hit.id)
            upd: dict = {"section": sec}
            if hit.origin == "ai":
                upd["review"] = "accepted"
            out.append(hit.model_copy(update=upd))
        else:
            out.append(BriefItem(id="", section=sec, text=line))  # placeholder, resolved below
            pending.append((sec, line))
    free_ai = [i for i in shown if i.origin == "ai" and i.id not in used]
    k = 0
    for n, it in enumerate(out):
        if it.id:
            continue
        sec, line = pending[k]
        k += 1
        body, cites, _bad = split_cites(pkg, line, lang)
        best, score = None, 0.0
        for a in free_ai:
            r = SequenceMatcher(None, a.text.lower(), body.lower()).ratio() + (0.05 if a.section == sec else 0)
            if r > score:
                best, score = a, r
        if best is not None and score >= 0.6:
            free_ai.remove(best)
            used.add(best.id)
            out[n] = best.model_copy(update={"section": sec, "text": body, "cites": cites or best.cites, "review": "edited",
                                             "flag": None, "flag_term": None, "flag_entries": []})
        else:
            lead = NOTE_LEAD[lang]
            note = body.startswith(lead)
            out[n] = BriefItem(id=_id(), section=sec, text=body[len(lead):] if note else body, cites=cites, origin="clinician",
                               review="accepted", kind="patient_note" if note else None)
    rejected = [i.model_copy(update={"review": "rejected"}) for i in shown if i.origin == "ai" and i.id not in used]
    return out + rejected


def to_pdf(pkg: SharePackage, brief: Brief, text: str, lang: str, focus: str | None = None) -> bytes:
    """The brief text as a one-page PDF: the AI draft (watermarked) until the brief is signed, then the signed copy."""
    from . import brief_pdf
    from .specialty import LABELS, norm_focus

    titles = TITLES[("clinician", lang)]
    sections: list[tuple[str, list[str]]] = []
    for sec, line in parse_text(text)[0]:
        if not sections or sections[-1][0] != titles[sec]:
            sections.append((titles[sec], []))
        sections[-1][1].append(line)
    w = brief_pdf.WORDS[lang]
    sub = w["period"].format(a=fdate(pkg.period[0], lang, True), b=fdate(pkg.period[1], lang, True))
    sub = elide_it(sub) if lang == "it" else sub
    focus = norm_focus(focus)
    if focus:
        sub += " · " + w["focus"].format(sp=LABELS[lang][focus])
    signed = None
    if brief.finalized:
        signed = w["signed"].format(name=brief.signed_by or "?", date=fdate((brief.finalized_at or "")[:10], lang, True))
    return brief_pdf.render(brief_pdf.PdfBrief(
        lang=lang, title=w["title"].format(alias=pkg.patient_alias), subtitle=sub, sections=sections, signed=signed,
        provenance=brief_pdf.provenance(brief.backend, brief.model, brief.pseudonymized, brief.model_remote, lang)))
