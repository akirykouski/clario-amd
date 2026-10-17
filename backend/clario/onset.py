"""Keep `onset_hint` to phrases that say when something started.

The extraction prompt asks for "the time phrase from the diary for when it started", but a model sometimes fills
the field with a time of day ("in the morning", "la sera") or a trigger ("after the sun", "dopo una corsa"). The
patient UI shows the field as "Since: ..." and the clinic brief as "onset: ...", so those would read wrong.

The prompt is frozen (it is the LoRA's training prompt), so this runs in code after parsing, in `extract.ground`.
The extraction_v3 schema has no timing or trigger field on an entity (a trigger is its own entity of type
`trigger`), so a phrase that is not an onset is dropped from the field and the entity gets the flag
`onset_dropped`. The diary text itself still holds the words.

Rules, in order, on the accent-folded lower-case phrase:
  1. starts with an onset cue ("since", "for", "da", "dal", ...) or names a date, a weekday or "ago"/"fa": keep
  2. starts with a trigger cue ("after", "when", "dopo", "quando", ...): drop
  3. only time-of-day or frequency words ("in the morning", "every evening", "stamattina", "la sera"): drop
  4. anything else: keep (a phrase we do not recognise is left as the model wrote it)
"""

from __future__ import annotations

import re

from .knowledge import fold

_ONSET_START = re.compile(
    r"^(?:ever\s+since|since|for|from|starting|started|began|beginning|"
    r"da|dal|dall|dallo|dalla|dai|dagli|dalle|a\s+partire|iniziat[oaie]|cominciat[oaie]|e\s+iniziat[oa])\b")
_ONSET_ANYWHERE = re.compile(
    r"\b(?:ago|fa|yesterday|ieri|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"lunedi|martedi|mercoledi|giovedi|venerdi|sabato|domenica|last\s+(?:week|month|year)|"
    r"(?:settimana|mese|anno)\s+scors[oa])\b")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\b\d{1,2}[/.]\d{1,2}\b")
_TRIGGER_START = re.compile(
    r"^(?:after|afterwards|when|whenever|every\s+time|each\s+time|any\s+time|once|while|during|if|because|"
    r"dopo|quando|ogni\s+volta|appena|mentre|durante|se|perche)\b")
_TIME_WORDS = {
    # en
    "morning", "mornings", "evening", "evenings", "night", "nights", "afternoon", "afternoons", "nighttime",
    "daytime", "bedtime", "day", "days", "weekend", "weekends", "daily", "nightly", "often", "sometimes",
    "always", "usually", "waking", "wake", "midday", "noon", "midnight", "lunchtime",
    # it
    "mattina", "mattine", "mattino", "mattinata", "sera", "sere", "serata", "notte", "notti", "nottata",
    "pomeriggio", "pomeriggi", "giorno", "giorni", "giornata", "stamattina", "stamani", "stamane", "stasera",
    "stanotte", "risveglio", "spesso", "volte", "sempre", "mezzogiorno", "mezzanotte",
}
_FILLERS = {
    # en
    "in", "at", "the", "every", "each", "most", "some", "this", "on", "of", "all", "a", "early", "late", "up",
    "upon", "around", "through", "overnight",
    # it
    "la", "il", "le", "i", "l", "di", "al", "alla", "alle", "nel", "nella", "nelle", "ogni", "tutti", "tutte",
    "tutto", "tutta", "verso", "sul", "presto", "tardi", "in", "a", "per",
}


def _words(phrase: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(phrase))


def onset_kind(phrase: str | None) -> str | None:
    """'onset', 'trigger', 'time_of_day', or None for an empty phrase."""
    if not phrase or not phrase.strip():
        return None
    words = _words(phrase)
    if not words:
        return None
    folded = " ".join(words)
    if _ONSET_START.search(folded) or _ONSET_ANYWHERE.search(folded) or _DATE.search(phrase):
        return "onset"
    if _TRIGGER_START.search(folded):
        return "trigger"
    if any(w in _TIME_WORDS for w in words) and all(w in _TIME_WORDS or w in _FILLERS for w in words):
        return "time_of_day"
    return "onset"


def normalise_onset(phrase: str | None) -> str | None:
    """The phrase when it reads as an onset, else None."""
    return phrase if onset_kind(phrase) == "onset" else None
