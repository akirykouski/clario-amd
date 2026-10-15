"""Shared data contract for the patient app, the clinic server, and the frontend."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

EntityType = Literal["symptom", "finding", "lab", "medication", "trigger", "body_site"]
Signal = Literal["weak", "moderate", "strong"]
Review = Literal["auto", "needs_review", "confirmed", "corrected", "rejected"]
COUNTED = ("confirmed", "corrected")  # decided by a person and kept: counts toward patterns and sharing


class Term(BaseModel):
    """An HPO ontology term."""

    hpo_id: str
    label: str


class Entity(BaseModel):
    """One thing extracted from a diary entry, grounded in a verbatim quote."""

    id: str
    entry_id: str
    type: EntityType
    quote: str = Field(description="Verbatim span copied from the entry text")
    canonical: str = Field(description="Clinical name, e.g. 'Malar rash'")
    hpo_id: str | None = Field(None, description="Validated against the shipped ontology, else null")
    hpo_label: str | None = None
    negated: bool = Field(False, description="'no fever today' -> negated")
    severity: int | None = Field(None, ge=0, le=10)
    family_history: bool = Field(False, description="'my mother has lupus' -> about a relative, not the patient")
    onset_hint: str | None = Field(None, description="ISO date or relative phrase from the text ('since Tuesday')")
    confidence: float | None = Field(None, ge=0, le=1, description="Self-consistency share, or the model's own; null if not measured")
    review: Review = Field("auto", description="auto: not looked at; needs_review: confidence below threshold; "
                                               "confirmed, corrected, rejected: decided by the patient")
    flags: list[str] = Field(default_factory=list, description="e.g. hpo_dropped, quote_not_found")
    model: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _legacy_status(cls, d):
        """Records saved before `review` existed carried status suggested|confirmed|rejected."""
        if isinstance(d, dict) and "status" in d:
            d = dict(d)
            st = d.pop("status")
            d.setdefault("review", st if st in ("confirmed", "rejected") else "auto")
        return d


class Entry(BaseModel):
    id: str
    created_at: str
    occurred_on: str = Field(description="ISO date the patient says this happened")
    text: str
    mood: int | None = Field(None, ge=0, le=10)
    extraction: Literal["pending", "done", "failed"] = "pending"
    entities: list[Entity] = Field(default_factory=list)


class Evidence(BaseModel):
    hpo_id: str
    label: str
    entry_ids: list[str]
    first_seen: str
    last_seen: str
    count: int


class Pattern(BaseModel):
    """A hedged pattern signal. Never a diagnosis."""

    disease_id: str = Field(description="ORPHA:xxx or OMIM:xxx")
    disease_name: str
    signal: Signal
    score: float = Field(description="Internal IC-overlap score, not shown as a probability")
    matched: list[Evidence]
    missing: list[Term] = Field(default_factory=list, description="Typical features not recorded, top 5 by IC")
    rationale: str = Field(description="Hedged text, passed the hedge validator")
    rationale_source: Literal["model", "template"] = "template"


class ShareRequest(BaseModel):
    clinic_url: str
    since: str = Field(description="ISO date, inclusive")
    until: str
    include_patterns: bool = True
    note: str | None = Field(None, description="What the patient wants to ask at the visit")
    expires_hours: int = Field(72, ge=1, le=720)


class SharedEntity(BaseModel):
    entry_id: str
    occurred_on: str
    type: EntityType
    quote: str
    canonical: str
    hpo_id: str | None = None
    negated: bool = False
    family_history: bool = False
    severity: int | None = None
    reviewed: bool = Field(True, description="False: no person has checked it; the brief says so")


class SharePackage(BaseModel):
    """Decrypted payload a clinic receives. Only confirmed entities and the selected entries."""

    package_id: str
    patient_alias: str
    created_at: str
    expires_at: str
    period: tuple[str, str]
    note: str | None = None
    entries: list[Entry]
    entities: list[SharedEntity]
    patterns: list[Pattern] = Field(default_factory=list)


class BriefItem(BaseModel):
    """One AI-drafted line of the clinician brief. Must be reviewed before it is final."""

    id: str
    section: Literal["summary", "timeline", "symptoms", "labs", "medications", "patterns", "questions"]
    text: str
    cites: list[str] = Field(default_factory=list, description="entry ids")
    origin: Literal["patient", "ai"] = "ai"
    review: Literal["pending", "accepted", "rejected", "edited"] = "pending"


class Brief(BaseModel):
    package_id: str
    items: list[BriefItem]
    model: str | None = None
    backend: str | None = None
    finalized: bool = False
    stats: dict = Field(default_factory=dict, description="latency_ms, tokens_per_s, tokens")


class Health(BaseModel):
    ok: bool
    mode: Literal["patient", "clinic"]
    llm: dict
    locked: bool | None = None
    ontology: dict = Field(default_factory=dict)
