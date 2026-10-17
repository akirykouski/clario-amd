"""Past history: a term the patient mentions as something that happened long before the note.

Patients write about the past in today's note ("I had knee surgery 5 years ago", "as a child I had asthma",
"ho avuto un'operazione al ginocchio cinque anni fa", "da bambina avevo l'asma"). Without this, such a term is
dated to the note: it lights up this week in the heat map, reads as a new current finding in the glance, and
scores in the differential as a current phenotype.

The extraction prompt is frozen (it is the LoRA's training prompt) and the extraction_v3 schema has no field for
it, so the reference is read in code after parsing, in `extract.ground`, from the clause around the quote:

  * cue in the quote's own clause, or in a clause next to it that holds only the cue ("As a child, I had asthma")
  * cues: "N years/months ago", "a year ago", "years back", "last year", "in 2019" (a year before the note year),
    "in the past", "as a child", "when I was little"; Italian "N anni/mesi fa", "l'anno scorso", "nel 2019",
    "in passato", "da bambino/a", "da piccolo/a", "quando ero piccola"
  * not past: an onset of something ongoing ("since two years", "for the past 3 weeks", "started 2 years ago",
    "da due anni", "dall'anno scorso", "dal 2019"), a clause that says it is still there ("still", "again",
    "ancora", "di nuovo"), and days or weeks ago (the current episode, dated close enough to the note)

`PastRef.approx_date` is the note date minus the stated amount (the first of that month or year). "As a child" or
"in the past" carries no date.

Downstream: a past term is not one of the patient's current terms (`share.patient_mentions`,
`patterns.counts_as_evidence`), so it stays out of the heat map, the recent picture and the differential, and shows
under "Past history" in the clinic glance, the details and the brief. The differential leaves it out on purpose: a
past procedure or a childhood condition is history the clinician reads, not a phenotype seen now.
"""

from __future__ import annotations

import re
from datetime import date

from .knowledge import fold
from .models import PastRef

_NUM_EN = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30}
_NUM_IT = {"un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7, "otto": 8,
           "nove": 9, "dieci": 10, "undici": 11, "dodici": 12, "quindici": 15, "venti": 20, "trenta": 30}
_VAGUE_EN = r"a\s+few|a\s+couple\s+of|a\s+couple|several|many|some"
_VAGUE_IT = r"qualche|alcuni|alcune|tanti|tante|molti|molte|parecchi|un\s+paio\s+di"
_N_EN = rf"(?P<n>\d{{1,2}}|{'|'.join(_NUM_EN)}|{_VAGUE_EN})"
_N_IT = rf"(?P<n>\d{{1,2}}|{'|'.join(_NUM_IT)}|{_VAGUE_IT})"

# Each cue: (regex on the folded text, kind). Named groups: n (amount), unit (year/month words), year.
_CUES: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"\b(?:{_N_EN}\s+)?(?P<unit>years?|months?)\s+(?:ago|back|before)\b"), "ago"),
    (re.compile(rf"\b(?:{_N_IT}\s+)?(?P<unit>anni|anno|mesi|mese)\s+fa\b"), "ago"),
    (re.compile(r"(?<!the\s)\blast\s+year\b"), "last_year"),  # "in the last year" is a recent period, not history
    (re.compile(r"\b(?:l'|lo\s+)?(?:anno\s+scorso|scorso\s+anno|anno\s+passato)\b"), "last_year"),
    (re.compile(r"\b(?:in|back\s+in|during|nel|durante\s+il|a\s+fine|a\s+inizio)\s+(?P<year>(?:19|20)\d{2})\b"), "year"),
    (re.compile(r"\b(?:as\s+an?\s+(?:child|kid|toddler|baby|little\s+(?:girl|boy))|when\s+i\s+was\s+(?:an?\s+)?"
                r"(?:child|kid|little|small|young|baby|toddler)|in\s+(?:my\s+)?(?:early\s+)?childhood|growing\s+up)\b"),
     "childhood"),
    (re.compile(r"\b(?:da\s+(?:bambin[oa]|piccol[oa]|neonat[oa])|quando\s+ero\s+(?:bambin[oa]|piccol[oa]|neonat[oa])|"
                r"nell'infanzia|durante\s+l'infanzia|in\s+eta\s+infantile)\b"), "childhood"),
    (re.compile(r"\bin\s+the\s+past\b(?!\s+(?:few|couple|\d|one|two|three|four|five|six|several|many|days?|weeks?|"
                r"months?|years?|while))"), "past"),
    (re.compile(r"\b(?:in\s+passato|tempo\s+fa|molto\s+tempo\s+fa|a\s+long\s+time\s+ago|long\s+ago)\b"), "past"),
]
# Words right before a cue that make it an onset of something still there ("since last year", "dall'anno scorso").
_ONSET_LEFT = re.compile(r"(?:\b(?:since|for|from|ever\s+since|over|da|dal|dalla|dallo|dai|dalle|dagli|a\s+partire\s+da\w*)"
                         r"|\bdall')\s*(?:the\s+)?$")
# A clause that says when something started, or that it is still there now.
_ONSET_VERB = re.compile(r"\b(?:start\w*|began|begin\w*|begun|onset|iniziat\w*|inizia|cominciat\w*|comincia|"
                         r"e\s+iniziat\w*|partit[oa])\b")
_PRESENT = re.compile(r"\b(?:still|again|currently|anymore|lately|these\s+days|ancora|di\s+nuovo|attualmente|"
                      r"ultimamente|tuttora|in\s+questi\s+giorni)\b")
# The next clause says the same thing is still there ("... and still have it", "... e ce l'ho ancora").
_STILL_IT = re.compile(r"\b(?:it|them)\b|\bce\s+l'|\bl'ho\b|\bne\s+soffro\b")
# Clause boundaries inside a sentence. A boundary word starts the next clause, so "now my knees ache" is its own clause.
_CLAUSE = re.compile(r",|\s(?=(?:and|but|however|though|although|while|whereas|now|today|e|ma|pero|mentre|"
                     r"anche\s+se|ora|adesso|oggi)\b)")
_SENT_END = re.compile(r"[.;!?\n]")
_FILLER = {"i", "had", "have", "was", "were", "it", "my", "and", "e", "ho", "avevo", "ero", "avuto", "then", "allora",
           "back", "about", "around", "circa", "almost", "quasi", "maybe", "forse", "already", "gia"}


def _clauses(sentence: str) -> list[tuple[int, int]]:
    bounds, start = [], 0
    for m in _CLAUSE.finditer(sentence):
        bounds.append((start, m.start()))
        start = m.end() if m.group(0) == "," else m.start() + 1
    bounds.append((start, len(sentence)))
    return [(a, b) for a, b in bounds if b > a]


def _cue_in(clause: str) -> tuple[re.Match, str] | None:
    """The first past cue in a clause that is not an onset ("since last year")."""
    for rx, kind in _CUES:
        for m in rx.finditer(clause):
            if _ONSET_LEFT.search(clause[:m.start()]):
                continue
            return m, kind
    return None


def _only_cue(clause: str, m: re.Match) -> bool:
    """The clause holds the cue and nothing that could be another statement ("As a child,", "Cinque anni fa,")."""
    rest = re.findall(r"[a-z0-9']+", clause[:m.start()] + " " + clause[m.end():])
    return all(w in _FILLER for w in rest)


def _amount(m: re.Match, kind: str) -> tuple[int | None, str | None]:
    if kind == "last_year":
        return 1, "year"
    if kind != "ago":
        return None, None
    unit = "month" if m.group("unit").startswith(("month", "mes")) else "year"
    raw = (m.group("n") or "").strip()
    if raw.isdigit():
        return int(raw), unit
    n = _NUM_EN.get(raw) or _NUM_IT.get(raw)
    if not raw and m.group("unit") in ("year", "month", "anno", "mese"):
        n = 1  # "a year ago" is caught with n; "anno fa" alone reads as one
    return n, unit


def approx_date(ref: PastRef, note_date: str | None) -> str | None:
    """The note date minus the stated amount: first of the month for months, first of the year for years."""
    if not note_date:
        return None
    try:
        d = date.fromisoformat(note_date[:10])
    except ValueError:
        return None
    if ref.kind == "year" and ref.n:
        return f"{ref.n:04d}-01-01"
    if ref.kind != "ago" or not ref.n:
        return None
    if ref.unit == "month":
        months = d.year * 12 + d.month - 1 - ref.n
        return f"{months // 12:04d}-{months % 12 + 1:02d}-01"
    return f"{d.year - ref.n:04d}-01-01"


def past_reference(text: str, span: tuple[int, int], note_date: str | None = None) -> PastRef | None:
    """A past-history reference for the quote at `span`, read from its clause, or None (current, or an onset)."""
    folded = fold(text)  # same length as text for Latin text: positions carry over
    if len(folded) != len(text):
        folded = text.lower()
    s = max((m.end() for m in _SENT_END.finditer(folded, 0, span[0])), default=0)
    e_m = _SENT_END.search(folded, span[1])
    e = e_m.start() if e_m else len(folded)
    sentence = folded[s:e]
    clauses = _clauses(sentence)
    a, b = span[0] - s, span[1] - s
    own = [i for i, (cs, ce) in enumerate(clauses) if cs < b and ce > a] or [0]
    first, last = own[0], own[-1]
    off = clauses[first][0]
    body = sentence[off:clauses[last][1]]
    if _PRESENT.search(body) or _ONSET_VERB.search(body):
        return None
    if last + 1 < len(clauses):
        tail = sentence[clauses[last + 1][0]:clauses[last + 1][1]]
        if _PRESENT.search(tail) and _STILL_IT.search(tail):
            return None
    hit = _cue_in(body)
    if hit is None:
        for j in (first - 1, last + 1):  # a clause next to it that holds only the cue
            if 0 <= j < len(clauses):
                side = sentence[clauses[j][0]:clauses[j][1]]
                h = _cue_in(side)
                if h and _only_cue(side, h[0]):
                    hit, off = h, clauses[j][0]
                    break
    if hit is None:
        return None
    m, kind = hit
    cue = text[s + off + m.start():s + off + m.end()]  # as the patient wrote it
    if kind == "year":
        year = int(m.group("year"))
        note_year = int(note_date[:4]) if note_date and note_date[:4].isdigit() else date.today().year
        if year >= note_year:
            return None  # this year is not history
        ref = PastRef(kind="year", n=year, cue=cue)
    else:
        n, unit = _amount(m, kind)
        ref = PastRef(kind="ago" if kind == "last_year" else kind, n=n, unit=unit, cue=cue)  # type: ignore[arg-type]
    ref.approx_date = approx_date(ref, note_date)
    return ref


_MONTHS = {"en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
           "it": "gen feb mar apr mag giu lug ago set ott nov dic".split()}


def when_text(ref: PastRef, lang: str = "en", around: bool = False) -> str:
    """"about 5 years ago", "in childhood", "circa 5 anni fa", "nell'infanzia". `around` adds the approximate date
    for the clinician: "about 5 years ago (around 2021)"."""
    it = lang == "it"
    if ref.kind == "childhood":
        return "nell'infanzia" if it else "in childhood"
    if ref.kind == "past":
        return "in passato" if it else "in the past"
    if ref.kind == "year":
        return f"nel {ref.n}" if it else f"in {ref.n}"
    month = ref.unit == "month"
    if ref.n is None:
        out = ("qualche mese fa" if month else "qualche anno fa") if it else ("some months ago" if month else "some years ago")
    elif ref.n == 1:
        out = ("circa un mese fa" if month else "circa un anno fa") if it else ("about a month ago" if month else "about a year ago")
    else:
        out = f"circa {ref.n} {'mesi' if month else 'anni'} fa" if it else f"about {ref.n} {'months' if month else 'years'} ago"
    if around and ref.approx_date:
        y, m = ref.approx_date[:4], int(ref.approx_date[5:7])
        shown = f"{_MONTHS['it' if it else 'en'][m - 1]} {y}" if month else y
        out += f" (intorno a {shown})" if it and month else f" ({'intorno al' if it else 'around'} {shown})"
    return out


def sort_key(ref: PastRef) -> tuple[int, str]:
    """Oldest first: childhood, then dated references, then undated ones."""
    if ref.kind == "childhood":
        return 0, ""
    return (1, ref.approx_date) if ref.approx_date else (2, "")
