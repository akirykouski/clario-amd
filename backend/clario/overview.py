"""Clinician overview of a shared package, in plain words: who, what the patient keeps writing about, what is new,
how it started, labs out of range, past history, family history, mood, and the questions the patient wrote down.

Computed in code from the package (no model call), so it is there the moment a package is opened and never invents
anything. Terms use everyday names (no HPO codes); the clinical names stay in the details block.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .knowledge import Ontology
from .brief import _num
from .documents import is_off, lab_flag
from .models import SharedLab, SharePackage
from .patterns import patient_label
from .past import sort_key, when_text
from .share import LAB_NAMES_EN, past_mentions, patient_mentions

RECENT_DAYS = 14
ANSWER_LEADS = ("Answer to a question:", "Risposta a una domanda:")
_ASK = re.compile(r"\b(ask|question|questions|want to know|wonder|chiedere|chiedo|domand\w*|vorrei sapere)\b|\?", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")


def _label(onto: Ontology, hpo_id: str | None, canonical: str, lang: str) -> str:
    return patient_label(onto, hpo_id, lang) if hpo_id else canonical.lower()


def asks_from_notes(pkg: SharePackage, limit: int = 3) -> list[dict]:
    """Sentences where the patient says what they want to ask, newest first, in their own words, no repeats."""
    out, seen = [], set()
    for e in sorted(pkg.entries, key=lambda e: e.occurred_on, reverse=True):
        if e.text.startswith(ANSWER_LEADS):
            continue
        sents = [s.strip() for s in _SENT.split(e.text) if s.strip()]
        hits = [i for i, s in enumerate(sents) if _ASK.search(s)]
        if not hits:
            continue
        if len(hits) > 1:
            picked = [sents[i] for i in hits[1:]]  # "Writing down questions... I want to ask about X": keep the question
        elif not sents[hits[0]].endswith("?") and hits[0] + 1 < len(sents):
            picked = sents[hits[0]:hits[0] + 2]  # a lead-in alone says little: add the sentence that follows
        else:
            picked = [sents[hits[0]]]
        text = " ".join(picked)
        if text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append({"text": text, "entry_id": e.id, "date": e.occurred_on})
        if len(out) == limit:
            break
    return out


def lab_name(l: SharedLab, lang: str) -> str:
    """English clinic UI: the English name of a known test; Italian: the name as printed."""
    return (l.name_en or LAB_NAMES_EN.get(l.test_key) or l.test_name) if lang == "en" else l.test_name


def labs_out_of_range(labs: list[SharedLab], lang: str = "en") -> list[dict]:
    """Every test with an out-of-range result in the package (the same set the lab table's out-of-range block and the
    header count show), one line per test: its latest out-of-range reading, and whether a later reading is back in
    range. Still out of range first, then newest first."""
    groups: dict[str, list[SharedLab]] = {}
    for l in labs:
        if l.decision != "rejected":
            groups.setdefault(l.test_key or l.test_name.lower(), []).append(l)
    out = []
    for key, rows in groups.items():
        rows.sort(key=lambda l: (l.date, l.page))
        off = [l for l in rows if is_off(lab_flag(l))]
        if not off:
            continue
        last_off, last = off[-1], rows[-1]
        value = last_off.value_text or (_num(last_off.value_numeric, lang) if last_off.value_numeric is not None else "")
        out.append({"name": lab_name(last_off, lang), "test_key": key, "value": value, "unit": last_off.unit,
                    "flag": lab_flag(last_off), "date": last_off.date,
                    "latest_in_range": last is not last_off and lab_flag(last) == "normal"})
    out.sort(key=lambda r: r["name"].lower())
    out.sort(key=lambda r: r["date"], reverse=True)
    out.sort(key=lambda r: r["latest_in_range"])
    return out


def past_history(pkg: SharePackage, onto: Ontology, lang: str = "en") -> list[dict]:
    """The patient's past history (clario/past.py), one line per term, oldest first: "knee surgery, about 5 years ago
    (around 2021)". Not counted in the frequent, recent or new lists: it did not happen in the shared period."""
    out: dict[str, dict] = {}
    for x in past_mentions(pkg.entities):
        if x.type in ("lab", "trigger"):
            continue
        k = x.hpo_id or x.canonical.lower()
        if k in out and sort_key(out[k]["past"]) <= sort_key(x.past):  # type: ignore[arg-type]
            continue
        out[k] = {"label": _label(onto, x.hpo_id, x.canonical, lang), "past": x.past, "when": when_text(x.past, lang, around=True),  # type: ignore[arg-type]
                  "entry_id": x.entry_id, "date": x.occurred_on, "quote": x.quote}
    rows = sorted(out.values(), key=lambda r: sort_key(r["past"]))
    return [r | {"past": r["past"].model_dump()} for r in rows]


def overview(pkg: SharePackage, onto: Ontology, lang: str = "en") -> dict:
    entries = sorted(pkg.entries, key=lambda e: e.occurred_on)
    end = date.fromisoformat(entries[-1].occurred_on) if entries else date.today()
    recent_from = (end - timedelta(days=RECENT_DAYS)).isoformat()
    terms: dict[str, dict] = {}
    for x in patient_mentions(pkg.entities):
        if x.type in ("lab", "medication", "trigger"):
            continue
        k = x.hpo_id or x.canonical.lower()
        t = terms.setdefault(k, {"label": _label(onto, x.hpo_id, x.canonical, lang), "notes": set(), "recent": set(),
                                 "first": x.occurred_on, "last": x.occurred_on, "max_severity": None})
        t["notes"].add(x.entry_id)
        if x.occurred_on >= recent_from:
            t["recent"].add(x.entry_id)
        t["first"] = min(t["first"], x.occurred_on)
        t["last"] = max(t["last"], x.occurred_on)
        if x.severity is not None:
            t["max_severity"] = max(t["max_severity"] or 0, x.severity)
    rows = [{"label": t["label"], "count": len(t["notes"]), "recent_count": len(t["recent"]), "first": t["first"],
             "last": t["last"], "max_severity": t["max_severity"]} for t in terms.values()]
    frequent = sorted(rows, key=lambda r: (-r["count"], r["first"]))[:5]
    recent = sorted((r for r in rows if r["recent_count"]), key=lambda r: (-r["recent_count"], r["last"]), reverse=False)[:5]
    new = [r["label"] for r in sorted(rows, key=lambda r: r["first"]) if r["first"] >= recent_from][:3]
    first = min(rows, key=lambda r: r["first"]) if rows else None
    severe = sorted((r for r in rows if (r["max_severity"] or 0) >= 6), key=lambda r: -(r["max_severity"] or 0))[:3]

    labs_off = labs_out_of_range(pkg.labs, lang)

    family = sorted({x.canonical for x in pkg.entities if x.family_history and not x.negated})
    denied = sorted({_label(onto, x.hpo_id, x.canonical, lang) for x in pkg.entities
                     if x.negated and not x.family_history and (x.hpo_id or x.canonical.lower()) not in terms})

    moods = [e.mood for e in entries if e.mood is not None]
    mood = None
    if moods:
        half = len(moods) // 2 or 1
        a, b = sum(moods[:half]) / half, sum(moods[half:]) / max(1, len(moods) - half)
        mood = {"avg": round(sum(moods) / len(moods), 1), "trend": "down" if b < a - 0.7 else "up" if b > a + 0.7 else "flat"}

    span_weeks = max(1, round((end - date.fromisoformat(entries[0].occurred_on)).days / 7) + 1) if entries else 0
    return {"profile": pkg.profile, "notes": len(entries), "weeks": span_weeks, "frequent": frequent, "recent": recent,
            "new": new, "first": first, "severe": severe, "labs_off": labs_off, "past": past_history(pkg, onto, lang), "family": family, "denied": denied,
            "mood": mood, "asks": asks_from_notes(pkg)}
