"""Human review queue: anything the system is unsure about goes to a person before it counts.

`kind` names what is being reviewed. Each kind is a small handler registered in `app.state.review_kinds`
(patient mode), so another module (for example lab values) can add a kind without touching the routes:

    class ReviewKind(Protocol):
        def items(self) -> list[dict]: ...                      # queue rows, shape of `item()` below
        def apply(self, item_id, action, value) -> dict: ...    # raises LookupError (404) / ValueError (422);
                                                                # returns {"before", "after", "entry_id"?, "source_excerpt"?}

Every decision is also written to the vault as a `correction_log` record (before/after), kept for later fine-tuning.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Callable, Protocol

from .knowledge import Ontology
from .models import Entity, Entry

ACTIONS = ("confirm", "correct", "reject")
EXCERPT_WIDTH = 90


def route_review(confidence: float | None, threshold: float) -> str:
    """Below the threshold -> needs_review. No confidence measured -> auto."""
    return "needs_review" if confidence is not None and confidence < threshold else "auto"


def excerpt(text: str, quote: str, width: int = EXCERPT_WIDTH) -> str:
    """The part of the entry around the quote, with the quote kept whole."""
    i = text.lower().find(quote.lower())
    if i < 0:
        return text[:2 * width].strip() + ("..." if len(text) > 2 * width else "")
    a, b = max(0, i - width), min(len(text), i + len(quote) + width)
    return ("..." if a else "") + text[a:b].strip() + ("..." if b < len(text) else "")


def entity_item(entry: Entry, ent: Entity) -> dict:
    return {"kind": "entity", "id": ent.id, "entry_id": entry.id,
            "display": ("No " if ent.negated else "") + ent.canonical,
            "value": ent.hpo_id, "confidence": ent.confidence,
            "source_excerpt": excerpt(entry.text, ent.quote),
            "quote": ent.quote, "hpo_label": ent.hpo_label, "occurred_on": entry.occurred_on,
            "negated": ent.negated, "family_history": ent.family_history}


def apply_entity_action(ent: Entity, action: str, value: str | None, onto: Ontology) -> Entity:
    if action not in ACTIONS:
        raise ValueError("action must be confirm, correct or reject")
    if action == "confirm":
        return ent.model_copy(update={"review": "confirmed"})
    if action == "reject":
        return ent.model_copy(update={"review": "rejected"})
    hid = (value or "").strip().upper()
    if not re.fullmatch(r"HP:\d{7}", hid) or not onto.exists(hid):
        raise ValueError("correct needs the id of a term from the term list")
    label = onto.label(hid)
    flags = [f for f in ent.flags if not f.startswith(("hpo_", "no_hpo"))] + ["fixed_by_patient"]
    return ent.model_copy(update={"hpo_id": hid, "hpo_label": label, "canonical": label or ent.canonical,
                                  "flags": flags, "review": "corrected"})


class ReviewKind(Protocol):
    def items(self) -> list[dict]: ...
    def apply(self, item_id: str, action: str, value: str | None) -> dict: ...


class EntityReview:
    """Entities extracted from diary entries."""

    def __init__(self, all_entries: Callable[[], list[Entry]], save: Callable[[Entry], Entry], onto: Ontology):
        self._all, self._save, self._onto = all_entries, save, onto

    def items(self) -> list[dict]:
        rows = [(e, x) for e in self._all() for x in e.entities if x.review == "needs_review"]
        rows.sort(key=lambda r: (r[1].confidence if r[1].confidence is not None else 1.0, r[0].occurred_on))
        return [entity_item(e, x) for e, x in rows]

    def apply(self, item_id: str, action: str, value: str | None) -> dict:
        for e in self._all():
            for i, x in enumerate(e.entities):
                if x.id != item_id:
                    continue
                new = apply_entity_action(x, action, value, self._onto)
                e.entities[i] = new
                self._save(e)
                return {"entry_id": e.id, "source_excerpt": excerpt(e.text, x.quote),
                        "before": _snap(x), "after": _snap(new)}
        raise LookupError("item not found")


def _snap(x: Entity) -> dict:
    return {"canonical": x.canonical, "hpo_id": x.hpo_id, "quote": x.quote, "negated": x.negated,
            "family_history": x.family_history, "confidence": x.confidence, "review": x.review}


def correction_record(kind: str, item_id: str, action: str, detail: dict) -> tuple[str, dict]:
    rid = f"cl_{uuid.uuid4().hex[:10]}"
    return rid, {"id": rid, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind,
                 "item_id": item_id, "action": action, **detail}
