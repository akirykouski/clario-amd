"""Human review queue: anything the system is unsure about goes to a person before it counts.

`kind` names what is being reviewed. Each kind is a small handler (see `ReviewKind`) added with
`register_review_kind(app, name, handler)` (patient mode), so another module (for example lab values) can add a kind
without touching the routes.

Every decision is also written to the vault as a `correction_log` record (before/after), kept for later fine-tuning.
"""

from __future__ import annotations

import re
import uuid
from typing import Callable, Protocol

from fastapi import FastAPI

from . import documents as docs
from .knowledge import Ontology
from .share import now_iso
from .models import Entity, Entry, LabResult, route_review  # noqa: F401 - route_review re-exported

ACTIONS = ("confirm", "correct", "reject")
EXCERPT_WIDTH = 90


def excerpt(text: str, quote: str, width: int = EXCERPT_WIDTH) -> str:
    """The part of the entry around the quote, with the quote kept whole."""
    i = text.lower().find(quote.lower())
    if i < 0:
        return text[:2 * width].strip() + ("..." if len(text) > 2 * width else "")
    a, b = max(0, i - width), min(len(text), i + len(quote) + width)
    return ("..." if a else "") + text[a:b].strip() + ("..." if b < len(text) else "")


def entity_item(entry: Entry, ent: Entity) -> dict:
    return {"kind": "entity", "id": ent.id, "entry_id": entry.id, "canonical": ent.canonical,
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
    def items(self) -> list[dict]:
        """Queue rows, shaped like `entity_item` / `lab_item`."""

    def apply(self, item_id: str, action: str, value: str | None) -> dict:
        """Raises LookupError (404) or ValueError (422); returns {"before", "after", "entry_id"?, "source_excerpt"?}."""


def register_review_kind(app: FastAPI, name: str, handler: ReviewKind) -> None:
    """Add a review kind to the queue behind GET /api/review and POST /api/review/{kind}/{id}."""
    if not hasattr(app.state, "review_kinds"):
        app.state.review_kinds = {}
    app.state.review_kinds[name] = handler


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


def _num(n: float | None) -> str:
    return "" if n is None else f"{n:.6g}"


def lab_item(lab: LabResult) -> dict:
    """A lab row in queue shape. Text here is language neutral (names, numbers, units); the UI words the rest."""
    val = _num(lab.value_numeric) if lab.value_numeric is not None else (lab.value_text or "")
    shown = f"{val} {lab.unit}".strip()
    rng = (f"{_num(lab.ref_low)} - {_num(lab.ref_high)}" if lab.ref_low is not None and lab.ref_high is not None
           else f"<= {_num(lab.ref_high)}" if lab.ref_high is not None else f">= {_num(lab.ref_low)}" if lab.ref_low is not None else "")
    return {"kind": "lab", "id": lab.id, "entry_id": None, "canonical": lab.test_name,
            "display": f"{lab.test_name}: {shown}", "value": shown, "confidence": lab.confidence,
            "source_excerpt": f"{lab.test_name}   {shown}" + (f"   ({rng})" if rng else ""),
            "quote": None, "hpo_label": None, "occurred_on": lab.date, "negated": False, "family_history": False,
            "flag": lab.flag, "page": lab.page, "batch_id": lab.batch_id, "unit": lab.unit,
            "ref_low": lab.ref_low, "ref_high": lab.ref_high}


def _lab_snap(x: LabResult) -> dict:
    return {"test_name": x.test_name, "value_numeric": x.value_numeric, "value_text": x.value_text, "unit": x.unit,
            "ref_low": x.ref_low, "ref_high": x.ref_high, "flag": x.flag, "confidence": x.confidence, "review": x.review,
            "date": x.date, "page": x.page}


class LabReviewKind:
    """Rows read from scanned lab reports. Same confirm / correct / reject as entities, same log, same badge."""

    def __init__(self, all_labs: Callable[[], list[LabResult]], save: Callable[[LabResult], None]):
        self._all, self._save = all_labs, save

    def items(self) -> list[dict]:
        rows = [x for x in self._all() if x.review == "needs_review"]
        rows.sort(key=lambda x: (x.confidence if x.confidence is not None else 1.0, x.date, x.page))
        return [lab_item(x) for x in rows]

    def apply(self, item_id: str, action: str, value: str | None) -> dict:
        for x in self._all():
            if x.id != item_id:
                continue
            if action == "correct" and not (value or "").strip():
                raise ValueError("correct needs the corrected value")
            new = docs.apply_lab_action(x, action, docs.parse_lab_value(value or "") if action == "correct" else None)
            self._save(new)
            return {"entry_id": None, "source_excerpt": lab_item(x)["source_excerpt"],
                    "before": _lab_snap(x), "after": _lab_snap(new)}
        raise LookupError("item not found")


def _snap(x: Entity) -> dict:
    return {"canonical": x.canonical, "hpo_id": x.hpo_id, "quote": x.quote, "negated": x.negated,
            "family_history": x.family_history, "confidence": x.confidence, "review": x.review}


def correction_record(kind: str, item_id: str, action: str, detail: dict) -> tuple[str, dict]:
    rid = f"cl_{uuid.uuid4().hex[:10]}"
    return rid, {"id": rid, "ts": now_iso(), "kind": kind,
                 "item_id": item_id, "action": action, **detail}
