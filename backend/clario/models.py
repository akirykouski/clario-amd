"""Shared data contract for the patient app, the clinic server, and the frontend."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["symptom", "finding", "lab", "medication", "trigger", "body_site"]
Signal = Literal["weak", "moderate", "strong"]
Review = Literal["auto", "needs_review", "confirmed", "corrected", "rejected"]
LabReview = Literal["auto", "needs_review", "confirmed", "corrected", "rejected"]
LabFlag = Literal["low", "high", "normal"]
COUNTED = ("confirmed", "corrected")  # decided by a person and kept: counts toward patterns and sharing


def route_review(confidence: float | None, threshold: float, *, none_means: str = "auto") -> str:
    """Below the threshold -> needs_review. `none_means` is the state when no confidence was measured:
    entities (nothing to doubt) stay "auto", lab rows (nothing measured) go to "needs_review"."""
    if confidence is None:
        return none_means
    return "needs_review" if confidence < threshold else "auto"


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
    neutral_label: str = Field("", description="Evidence-first title without a disease name: the strongest matched features")
    card_id: str = Field("", description="The id the patient app shows for this card; the signal equals the patient's")


class PatientTerm(BaseModel):
    """A term as the patient reads it: everyday words first, the clinical (HPO) name as subtext."""

    hpo_id: str
    label: str = Field(description="Everyday words (Italian name in Italian)")
    clinical: str | None = Field(None, description="HPO label shown as subtext; null when it equals label")


class PatientEvidence(PatientTerm):
    entry_ids: list[str]
    first_seen: str
    last_seen: str
    count: int = Field(description="Number of notes that mention the term")


class PatientPattern(BaseModel):
    """A pattern card for the patient. Never names a condition: the title is the features the patient recorded."""

    card_id: str = Field(description="Opaque id, stable while the server runs; not a disease id")
    signal: Signal
    matched: list[PatientEvidence]
    missing: list[PatientTerm] = Field(default_factory=list, description="Common, noticeable features not recorded yet")
    neutral_label: str = Field(description="The strongest matched features, in everyday words")
    rationale: str = Field(description="Hedged template text naming no condition")


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
    onset_hint: str | None = Field(None, description="Time phrase the patient wrote ('since Tuesday'); shown to the clinician")
    reviewed: bool = Field(True, description="False: no person has checked it; the brief says so")
    from_question: bool = Field(False, description="The patient answered a question the app asked; `quote` is the app's question, not the patient's words")


class SharedLab(BaseModel):
    """One lab row. Rows a person confirmed or corrected, or that were read with high confidence
    (`reviewed=false`: the clinic must accept or reject them before the brief is final). needs_review and rejected rows never leave the device."""

    test_name: str
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str = ""
    ref_low: float | None = None
    ref_high: float | None = None
    flag: LabFlag | None = None
    date: str
    page: int = Field(description="Page within the imported document batch")
    entry_id: str | None = Field(None, description="The diary entry of the import, when known: what the brief cites")
    reviewed: bool = Field(True, description="False: read from a document and not checked by a person (the clinic labels it 'From documents, pending check')")
    id: str = Field("", description="Stable row id; the clinic's accept or reject decision is keyed by it")
    test_key: str = Field("", description="Folded test name: groups the same test across documents into one history")
    name_en: str | None = Field(None, description="English name of a known test, for an English clinic UI; test_name is as printed")
    abnormal: bool = Field(False, description="Flag is low or high, or a text result reads positive")
    decision: Literal["accepted", "rejected"] | None = Field(None, description="Set by the clinic server for unreviewed rows; absent in the sealed package")


class SharePackage(BaseModel):
    """Decrypted payload a clinic receives. Only confirmed entities, confirmed or confident lab rows, and the selected entries.

    A relative's condition (`family_history`) is shared only as family history: no HPO id, never a patient term."""

    package_id: str
    patient_alias: str
    created_at: str
    expires_at: str
    period: tuple[str, str]
    note: str | None = None
    entries: list[Entry]
    entities: list[SharedEntity]
    labs: list[SharedLab] = Field(default_factory=list)
    patterns: list[Pattern] = Field(default_factory=list)


class BriefItem(BaseModel):
    """One AI-drafted line of the clinician brief. Must be reviewed before it is final."""

    id: str
    section: Literal["summary", "timeline", "symptoms", "labs", "medications", "patterns", "questions"]
    text: str
    cites: list[str] = Field(default_factory=list, description="entry ids")
    origin: Literal["patient", "ai", "document"] = Field(
        "ai", description="patient: straight from the diary; document: a lab line read from an imported report (pending until every row is checked); ai: drafted by the model")
    review: Literal["pending", "accepted", "rejected", "edited"] = "pending"
    flag: Literal["citation_mismatch"] | None = Field(
        None, description="Set by code when the item names a term that none of its cited entries confirms; the clinician sees it")
    flag_term: str | None = Field(None, description="With `flag`: the term the line names that its citations do not record")
    flag_entries: list[str] = Field(default_factory=list, description="With `flag`: entry ids that do record that term")
    kind: Literal["patient_note"] | None = Field(None, description="patient_note: `text` is the patient's own question, the UI adds the label")
    pages: list[int] = Field(default_factory=list, description="Lab lines: report pages the values were read from")
    from_question: bool = Field(False, description="Symptom line the patient confirmed by answering a question the app asked")


class Brief(BaseModel):
    package_id: str
    items: list[BriefItem]
    model: str | None = None
    backend: str | None = None
    finalized: bool = False
    stats: dict = Field(default_factory=dict, description="latency_ms, tokens_per_s, tokens")
    lang: Literal["en", "it"] = Field("en", description="Language of the text: the AI items are drafted in it; patient-origin items are rendered in it")
    audience: Literal["clinician", "patient"] = "clinician"
    review_seconds: float | None = Field(
        None, description="Seconds from opening the package in the clinic UI to finalize, as measured by the UI; set at finalize")
    finalized_at: str | None = None


class DecisionCounts(BaseModel):
    """Clinician decisions on AI-drafted brief lines. Counts only, never text."""

    accepted: int = 0
    edited: int = 0
    rejected: int = 0


class BriefDecisions(DecisionCounts):
    """One finalized brief's row in the decision log (`decisions.jsonl` in the clinic data dir)."""

    package_id: str
    finalized_at: str
    review_seconds: float | None = None


class ClinicMetrics(BaseModel):
    """GET /api/clinic/metrics: pilot metric. Lines are AI-drafted brief items; patient-origin lines are not counted."""

    briefs: list[BriefDecisions] = Field(default_factory=list, description="Finalized briefs, newest first")
    totals: DecisionCounts = Field(default_factory=DecisionCounts)
    finalized: int = 0
    timed: int = Field(0, description="Finalized briefs that carry review_seconds")
    mean_review_seconds: float | None = Field(None, description="Mean over timed briefs; null when none")


class PrivacyReplacement(BaseModel):
    """One redaction. Positions only, never the original value. start/end index the original, out_* the sent text."""

    type: Literal["email", "phone", "codice_fiscale", "iban", "date", "address", "name"]
    start: int
    end: int
    out_start: int
    out_end: int


class PrivacyPreview(BaseModel):
    original: str
    redacted: str
    replacements: list[PrivacyReplacement]
    applied: bool = Field(description="True when redaction runs before calls on this server's backend")
    backend: str


class AiCall(BaseModel):
    """One model call in the tamper-evident log. hash = sha256(prev_hash + payload_sha256 + ts + backend + model + purpose)."""

    id: str
    seq: int
    ts: str
    backend: str
    model: str
    purpose: Literal["extract", "rationale", "brief", "next_question", "document", "other"]
    redacted_preview: str = Field(description="First 200 chars of the redacted text")
    payload_sha256: str
    prev_hash: str
    hash: str
    redacted: bool = Field(False, description="Whether text was pseudonymized before this call")
    replacements: int = 0
    images: int = 0


class PrivacyVerify(BaseModel):
    ok: bool
    broken_at: str | None = None
    count: int = 0


class ReviewPolicy(BaseModel):
    """Which review threshold is in force. source "conformal": certified by eval/conformal.py, so auto-accepted
    entities have error <= alpha with probability >= 1 - delta on data like the calibration set."""

    threshold: float
    source: Literal["conformal", "env", "override"]
    alpha: float | None = None
    delta: float | None = None
    calibration_n: int | None = None
    calibration_status: Literal["used", "missing", "invalid", "dry_run_ignored", "no_valid_threshold"] = "missing"


class Health(BaseModel):
    ok: bool
    mode: Literal["patient", "clinic"]
    llm: dict
    locked: bool | None = None
    ontology: dict = Field(default_factory=dict)
    demo_instance: bool = False
    review: ReviewPolicy | None = None


class LabResult(BaseModel):
    """One row read from a lab report page. Low-confidence rows wait for a person (needs_review)."""

    id: str
    batch_id: str
    test_name: str = Field(description="As printed on the page")
    test_key: str = Field(description="Folded name used to group the same test across documents")
    value_numeric: float | None = None
    value_text: str | None = Field(None, description="Printed result when it is not a plain number, e.g. 'Positivo 1:160'")
    unit: str = ""
    ref_low: float | None = None
    ref_high: float | None = None
    flag: LabFlag | None = Field(None, description="Recomputed in code from value and range when both exist")
    date: str = Field(description="ISO collection date; falls back to the import date")
    page: int = Field(description="Page number within the batch")
    confidence: float | None = Field(None, ge=0, le=1, description="Self-consistency or model confidence")
    review: LabReview = "auto"
    model: str | None = None


class LabValue(BaseModel):
    id: str
    date: str
    value_numeric: float | None
    value_text: str | None
    flag: LabFlag | None
    review: LabReview
    confidence: float | None
    page: int
    batch_id: str


class LabTest(BaseModel):
    test_key: str
    test_name: str
    unit: str
    ref_low: float | None
    ref_high: float | None
    latest: LabValue
    out_of_range: bool = Field(description="Latest value is flagged low or high")
    values: list[LabValue] = Field(description="Oldest first")


class LabsResponse(BaseModel):
    tests: list[LabTest]
    n_results: int
    needs_review: int
    out_of_range: int


class NextQuestion(BaseModel):
    """One yes/no question that would best separate the current patterns. Never names a condition or a medicine."""

    feature_id: str = Field(description="HPO id the question asks about")
    question: str
    why: str = Field(description="Hedged, no condition names")
    ig: float = Field(description="Expected information gain in bits over the current top patterns")
    splits: list[str] = Field(default_factory=list, description="card_ids of the two shown cards the answer separates; only cards on screen")
    question_source: Literal["model", "template"] = "template"


class RankedPattern(BaseModel):
    card_id: str = Field(description="Opaque card id, the same as PatientPattern.card_id")
    label: str = Field(description="neutral_label, never a condition name")
    score: float
    rank: int


class AnswerResult(BaseModel):
    before: list[RankedPattern]
    after: list[RankedPattern]
    entry_id: str | None = None
