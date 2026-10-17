"""Precomputed brief drafts for the demo persona (how they were made: data/demo/LABELS.md).

The clinic drafts a brief with the clinic model. For the demo persona's package, exactly as "Load the demo patient"
(and "Import the 3 sample referti") make it, the draft was generated once, live, with Gemma 4 31B on AMD Token Factory
from pseudonymised input, and is served from here so the demo opens at once. A package matches when its model input is
the same as the one the draft was made from, up to the things that change with the day it is loaded: entry ids become
positions (E1, E2, ...) and calendar dates become days from the start of the period. Any other change (a note of one's
own, a different period, a corrected term, another question for the doctor) is another input, so it goes to the live
model. "Regenerate live" always calls the model.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from functools import lru_cache

from . import brief as briefing
from .demo import DEMO_DIR
from .models import SharePackage

BRIEFS_FILE = DEMO_DIR / "giulia_briefs.json"
_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_TOKEN = re.compile(r"\bE(\d+)\b")


def _ids(pkg: SharePackage) -> dict[str, str]:
    return briefing.entry_aliases(pkg)  # the aliases pseudonymised input already carries (E1, E2, ...)


def portable(text: str, pkg: SharePackage) -> str:
    """`text` with entry ids as positions and ISO dates as day offsets from the period start ("@d-12")."""
    for eid, tok in _ids(pkg).items():
        text = text.replace(eid, tok)
    start = date.fromisoformat(pkg.period[0])

    def off(m: re.Match) -> str:
        try:
            return f"@d{(date.fromisoformat(m.group(1)) - start).days}"
        except ValueError:
            return m.group(0)

    return _ISO.sub(off, text)


def fingerprint(pkg: SharePackage, lang: str) -> str:
    """Hash of the brief model input for `pkg` (pseudonymised form, day numbers), independent of load day and entry ids."""
    canon = portable(briefing.model_input(pkg, lang, relative_dates=True), pkg)
    return hashlib.sha256(f"{lang}\n{canon}".encode()).hexdigest()


@lru_cache(maxsize=1)
def _records() -> tuple[dict, ...]:
    if not BRIEFS_FILE.exists():
        return ()
    return tuple(json.loads(BRIEFS_FILE.read_text())["drafts"])


def lookup(pkg: SharePackage, lang: str) -> dict | None:
    """The precomputed draft for this package and language, or None (then the brief goes to the live model)."""
    if not _records():
        return None
    fp = fingerprint(pkg, lang)
    return next((r for r in _records() if r["fingerprint"] == fp and r["lang"] == lang), None)


def draft_out(rec: dict, pkg: SharePackage) -> briefing.DraftOut:
    """The stored model output with its cited aliases (positions) mapped to this package's entry ids."""
    raw = briefing.DraftOut.model_validate(rec["output"])
    for it in raw.items:
        it.cites = briefing.restore_cites(it.cites, pkg)
    return raw
