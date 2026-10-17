// Mirror of backend/clario/models.py and docs/API.md
export type EntityType = "symptom" | "finding" | "lab" | "medication" | "trigger" | "body_site";
export type Signal = "weak" | "moderate" | "strong";
export type EntityReview = "auto" | "needs_review" | "confirmed" | "corrected" | "rejected";
export type Extraction = "pending" | "done" | "failed";

export interface Term { hpo_id: string; label: string }

/** Past history read from the note's words ("5 years ago", "as a child"): not a current finding. */
export interface PastRef {
  kind: "ago" | "year" | "childhood" | "past"; n: number | null; unit: "year" | "month" | null;
  approx_date: string | null; cue: string;
}

export interface Entity {
  id: string; entry_id: string; type: EntityType; quote: string; canonical: string;
  hpo_id: string | null; hpo_label: string | null; negated: boolean; severity: number | null;
  family_history: boolean; onset_hint: string | null; confidence: number | null; review: EntityReview;
  flags: string[]; model: string | null; past?: PastRef | null;
}

export interface ReviewItem {
  kind: "entity" | "lab"; id: string; entry_id: string | null; display: string; value: string | null;
  confidence: number | null; source_excerpt: string;
  quote?: string | null; hpo_label?: string | null; occurred_on?: string; negated?: boolean; family_history?: boolean;
  canonical?: string;
  // lab rows only
  flag?: LabFlag | null; page?: number; batch_id?: string; unit?: string; ref_low?: number | null; ref_high?: number | null;
}
export interface ReviewQueue { items: ReviewItem[]; count: number }
export type ReviewAction = "confirm" | "correct" | "reject";

export interface Entry {
  id: string; created_at: string; occurred_on: string; text: string; mood: number | null;
  extraction: Extraction; entities: Entity[];
}

export interface Evidence {
  hpo_id: string; label: string; entry_ids: string[]; first_seen: string; last_seen: string; count: number;
}

export interface Pattern {
  disease_id: string; disease_name: string; signal: Signal; score: number;
  matched: Evidence[]; missing: Term[]; rationale: string; rationale_source: "model" | "template";
  neutral_label: string; card_id?: string;
}

/** A term as the patient reads it: everyday words first, the clinical (HPO) name as subtext. */
export interface PatientTerm { hpo_id: string; label: string; clinical: string | null }
export interface PatientEvidence extends PatientTerm { entry_ids: string[]; first_seen: string; last_seen: string; count: number }
/** A card for the patient. Never names a condition; card_id is opaque. */
export interface PatientPattern {
  card_id: string; signal: Signal; matched: PatientEvidence[]; missing: PatientTerm[]; neutral_label: string; rationale: string;
}

export interface ShareRequest {
  clinic_url: string; since: string; until: string; include_patterns: boolean;
  note?: string | null; expires_hours: number; include_profile?: boolean;
  /** Send for a second opinion: the previous doctor's conclusions are shown to the new doctor only after they sign. */
  second_opinion?: boolean;
}
export interface Profile { age?: number | null; sex?: "female" | "male" | "other" | null }

export interface SharedEntity {
  id?: string | null; confidence?: number | null; needs_review?: boolean;
  entry_id: string; occurred_on: string; type: EntityType; quote: string; canonical: string;
  hpo_id: string | null; negated: boolean; family_history: boolean; severity: number | null; onset_hint?: string | null; reviewed: boolean; from_question?: boolean;
  past?: PastRef | null;
}

export interface SharedLab {
  test_name: string; value_numeric: number | null; value_text: string | null; unit: string; ref_low: number | null;
  ref_high: number | null; flag: LabFlag | null; date: string; page: number; entry_id: string | null; reviewed: boolean;
  confidence?: number | null; needs_review?: boolean; id: string | null; test_key: string; name_en: string | null; abnormal: boolean;
  decision: "confirmed" | "rejected" | "corrected" | null;
  /** Code checks the reading failed on the device (why it waits for the clinician). */
  checks?: string[];
  /** The printed row cut from the report page, a JPEG data URL; null for photos and scans. */
  crop?: string | null;
  /** What was read, when the clinician corrected the reading. */
  corrected_from?: LabReading | null;
}

export interface LabReading { value_numeric: number | null; value_text: string | null; unit: string }
export interface LabFix { from: LabReading; to: LabReading; at: string }
/** A corrected reading: `value` as printed ("11,0", "Positivo 1:160"), optionally the unit. */
export interface LabCorrection { value: string; unit?: string }

export interface SharePackage {
  package_id: string; patient_alias: string; created_at: string; expires_at: string;
  period: [string, string]; note: string | null; profile?: Profile | null; entries: Entry[]; entities: SharedEntity[]; labs: SharedLab[]; patterns: Pattern[];
  /** Second opinion: facts (`tried`, `tested`) are shown; `previous` (conclusions) is always null here until `/compare`. */
  second_opinion?: boolean; tried?: TriedTreatment[]; tested?: PriorTest[]; previous?: PriorOpinion | null;
}

// ---- second opinion: facts (shared) vs conclusions (held back until the new doctor signs)
export type TreatmentEffect = "none" | "partial" | "good" | "worse" | "unknown";
export interface TriedTreatment { treatment: string; started?: string | null; duration?: string | null; effect: TreatmentEffect; note?: string | null }
export interface PriorTest { test: string; date?: string | null; result: string; abnormal?: boolean | null }
export interface PriorCondition { name: string; disease_id?: string | null }
export interface PriorOpinion {
  clinician: string; date?: string | null; diagnosis: PriorCondition[]; conditions: PriorCondition[];
  accepted: string[]; rejected: string[]; notes?: string | null;
}
/** Patient side: facts, and only who gave the previous opinion and when (its conclusions name conditions). */
export interface Care { tried: TriedTreatment[]; tested: PriorTest[]; previous: { clinician: string; date?: string | null } | null }
export interface CompareRow { name: string; disease_id: string | null; previous: "diagnosis" | "considered" | null; current_rank: number | null; agree: boolean }
export interface Comparison {
  previous: PriorOpinion | null;
  current: { conditions: { disease_id: string; name: string; rank: number; signal: string | null }[]; accepted: string[]; rejected: string[]; finalized_at: string | null } | null;
  rows: CompareRow[]; disagreements: number; since_previous: string[];
}

export type BriefSection = "summary" | "timeline" | "symptoms" | "labs" | "medications" | "patterns" | "questions";
export type BriefReview = "pending" | "accepted" | "rejected" | "edited";

export interface BriefItem {
  id: string; section: BriefSection; text: string; cites: string[];
  origin: "patient" | "ai" | "document" | "clinician"; review: BriefReview; flag?: "citation_mismatch" | null;
  flag_term?: string | null; flag_entries?: string[]; kind?: "patient_note" | null; pages?: number[]; from_question?: boolean;
  /** Clinician copy: specialties the line belongs to, set in code by the server; empty = general practice only */
  specialties?: Specialty[];
}

export type Specialty = "rheumatology" | "nephrology";

export type Persona = "giulia" | "giulia_it";
export type BriefView = { audience?: "clinician" | "patient"; lang?: "en" | "it" };

export interface Brief {
  package_id: string; items: BriefItem[]; model: string | null; backend: string | null;
  lang?: "en" | "it"; audience?: "clinician" | "patient";
  review_seconds?: number | null; finalized_at?: string | null;
  /** Signing: the name the clinician typed, the signed text, the specialty it was prepared for */
  signed_by?: string | null; text?: string | null; specialty?: Specialty | null;
  /** Model input was pseudonymised before the call; the model ran off the clinic server */
  pseudonymized?: boolean | null; model_remote?: boolean | null;
  /** Demo persona: date the stored draft was generated live; `stats` are that run's. */
  precomputed?: string | null;
  finalized: boolean; stats: { latency_ms?: number; tokens_per_s?: number; tokens?: number } & Record<string, unknown>;
}

export interface BriefWarning {
  kind: "citation" | "hedge" | "diagnosis" | "unknown_section" | "unknown_date" | "labs_pending";
  section?: string | null; line?: string | null; message: string;
  /** Card editor: index of the line (in the items sent or returned) the warning is about. */
  item?: number | null;
}
/** One reading of a lab line, for the editor's read-only table. */
export interface BriefLabRow { test: string; value: string; flag: LabFlag | null; abnormal: boolean; date: string; page: number; range: string | null; corrected: boolean }
/** A drafted line as the card editor gets it; `rows` on lab lines. */
export interface BriefEditorItem {
  id: string; section: BriefSection; text: string; cites: string[]; origin: BriefItem["origin"]; kind?: "patient_note" | null;
  pages?: number[]; specialties?: string[]; rows?: BriefLabRow[];
}
/** A line the card editor sends: `id` of the drafted line it comes from, absent for a new one. */
export interface BriefLine { id?: string; section: BriefSection; text: string; cites: string[] }
export interface BriefText {
  text: string; warnings: BriefWarning[]; lang: "en" | "it"; signed: boolean;
  items?: BriefEditorItem[]; sections?: { key: BriefSection; title: string }[];
}

export interface Health {
  ok: boolean; mode: "patient" | "clinic";
  llm: { backend?: string; model?: string; base_url_host?: string; is_amd?: boolean; pseudonymize?: boolean };
  demo_instance?: boolean; clinic_url?: string | null; locked?: boolean | null; ontology?: { terms?: number; diseases?: number };
}

export type PrivacyKind = "email" | "phone" | "codice_fiscale" | "iban" | "date" | "address" | "name";
export interface PrivacyReplacement { type: PrivacyKind; start: number; end: number; out_start: number; out_end: number }
export interface PrivacyPreview { original: string; redacted: string; replacements: PrivacyReplacement[]; applied: boolean; backend: string }
export interface AiCall {
  id: string; seq: number; ts: string; backend: string; model: string;
  purpose: "extract" | "rationale" | "brief" | "next_question" | "document" | "other";
  redacted_preview: string; payload_sha256: string; prev_hash: string; hash: string;
  redacted: boolean; replacements: number; images: number;
}
export interface PrivacyVerify { ok: boolean; broken_at: string | null; count: number }

export interface SafetyNotice { level: "emergency" | "advice"; message: string; matched: string }
export interface VaultState { initialized: boolean; locked: boolean }
export interface TimelineDay { date: string; entries: Entry[]; terms: Term[] }
export interface Timeline { days: TimelineDay[]; terms: (Evidence & { clinical?: string })[]; systems?: Record<string, string> }
export interface PatternsResponse { patterns: PatientPattern[]; confirmed_terms: number; note: string }
export interface ShareResult {
  package_id: string; clinic_url: string; expires_at: string; qr_payload: string; entities: number; entries: number;
  mentions?: number; terms?: number; labs?: number;  // entities = mentions: patient terms only, no negated, no family history
  second_opinion?: boolean; tried?: number; tested?: number;
}
export interface ClinicKey { public_key: string; fingerprint: string; clinic_name: string }
export interface InboxRow {
  package_id: string; patient_alias: string; period: [string, string]; received_at: string;
  expires_at: string; entities: number; terms?: number; mentions?: number; labs?: number; brief_state: string; second_opinion?: boolean;
}

export interface RunEvent {
  stage: string; message?: string; progress?: number; backend?: string; model?: string;
  tokens_per_s?: number; latency_ms?: number; payload?: unknown; precomputed?: string;
}

export type LabReview = "auto" | "needs_review" | "confirmed" | "corrected" | "rejected";
export type LabFlag = "low" | "high" | "normal" | "positive"; // positive: a qualitative result such as ANA "Positivo 1:80"
export interface LabValue {
  id: string; date: string; value_numeric: number | null; value_text: string | null; flag: LabFlag | null;
  review: LabReview; confidence: number | null; page: number; batch_id: string;
}
export interface LabTest {
  test_key: string; test_name: string; unit: string; ref_low: number | null; ref_high: number | null;
  latest: LabValue; out_of_range: boolean; values: LabValue[];
}
export interface LabsResponse { tests: LabTest[]; n_results: number; needs_review: number; out_of_range: number }
export interface LabPatch {
  action: "confirm" | "correct" | "reject";
  value_numeric?: number | null; value_text?: string | null; unit?: string | null;
  ref_low?: number | null; ref_high?: number | null;
}
export interface BatchStarted { batch_id: string; pages: number; entry_id: string }
export interface BatchEvent {
  batch_id: string; pages_done: number; pages_total: number; pages_per_sec: number;
  gpu: Record<string, unknown> | null; errors: number; labs: number; needs_review: number; done: boolean;
  /** Seconds since the batch started; backend and model(s) that read the pages ("MinerU2.5-Pro + Gemma-4-31B-IT"). */
  elapsed_s?: number; backend?: string; model?: string | null;
  /** The demo referti: rows stored from the reviewed sample results, no page was read now (no speed, no reader). */
  precomputed?: boolean;
}
export interface LabResult {
  id: string; batch_id: string; test_name: string; test_key: string; value_numeric: number | null;
  value_text: string | null; unit: string; ref_low: number | null; ref_high: number | null; flag: LabFlag | null;
  date: string; page: number; confidence: number | null; review: LabReview; model: string | null;
}
export interface NextQuestion {
  feature_id: string; question: string; why: string; ig: number; splits: string[]; question_source: "model" | "template";
}
export interface RankedPattern { card_id: string; label: string; score: number; rank: number }
export interface AnswerResult { before: RankedPattern[]; after: RankedPattern[]; entry_id: string | null }
export type Answer = "yes" | "no" | "unsure";

export interface DecisionCounts { accepted: number; edited: number; rejected: number }
export interface BriefDecisions extends DecisionCounts { package_id: string; finalized_at: string; review_seconds: number | null }
export interface ClinicMetrics {
  briefs: BriefDecisions[]; totals: DecisionCounts; finalized: number; timed: number; mean_review_seconds: number | null;
}

// Clinic differential (clinician only)
/** `count`: notes that record the feature; `labs`: lab dates with an out-of-range result that maps to it (0 or absent: notes only). */
export interface ConditionFeature { hpo_id: string; label: string; count: number; labs?: number; freq: number | null }
export interface Condition {
  disease_id: string; name: string; full_name: string; signal: Signal | null; score: number; rank: number; url: string | null;
  matched: ConditionFeature[]; missing: ConditionFeature[];
}
export interface ClinicQuestion { feature_id: string; label: string; question: string; ig: number; freq_by: { name: string; freq: number | null }[] }
export interface ClinicAnswer { feature_id: string; label: string; answer: Answer; at: string }
export interface Differential { conditions: Condition[]; question: ClinicQuestion | null; answers: ClinicAnswer[]; n_terms: number; note: string }
export type TermDecision = "confirmed" | "rejected" | "corrected" | "pending";
/** A term the clinician replaced: the id and label it had (`from`, null when it had no id) and the one picked (`to`). */
export interface TermCorrection { from: string | null; from_label: string; to: string; label: string; at: string }
export interface Decisions { terms: Record<string, TermDecision>; corrections?: Record<string, TermCorrection>; labs?: Record<string, TermDecision>; lab_fixes?: Record<string, LabFix>; answers: ClinicAnswer[] }

export interface OverviewTerm { label: string; count: number; recent_count: number; first: string; last: string; max_severity: number | null }
export interface Overview {
  profile: Profile | null; notes: number; weeks: number; frequent: OverviewTerm[]; recent: OverviewTerm[]; new: string[];
  first: OverviewTerm | null; severe: OverviewTerm[]; labs_off: OverviewLab[];
  past?: OverviewPast[]; family: string[]; denied: string[]; mood: { avg: number; trend: "down" | "up" | "flat" } | null;
  asks: { text: string; entry_id: string; date: string }[];
}
/** Past history line of the glance; `when` is worded by the server ("about 5 years ago (around 2021)"). */
export interface OverviewPast { label: string; past: PastRef; when: string; entry_id: string; date: string; quote: string }
/** One test with an out-of-range result: its latest out-of-range reading; `latest_in_range` when a later one is back in range. */
export interface OverviewLab {
  name: string; test_key: string; value: string; unit: string; flag: "low" | "high" | "positive"; date: string; latest_in_range: boolean;
}
