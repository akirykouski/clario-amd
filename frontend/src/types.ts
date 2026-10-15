// Mirror of backend/clario/models.py and docs/API.md
export type EntityType = "symptom" | "finding" | "lab" | "medication" | "trigger" | "body_site";
export type Signal = "weak" | "moderate" | "strong";
export type EntityReview = "auto" | "needs_review" | "confirmed" | "corrected" | "rejected";
export type Extraction = "pending" | "done" | "failed";

export interface Term { hpo_id: string; label: string }

export interface Entity {
  id: string; entry_id: string; type: EntityType; quote: string; canonical: string;
  hpo_id: string | null; hpo_label: string | null; negated: boolean; severity: number | null;
  family_history: boolean; onset_hint: string | null; confidence: number | null; review: EntityReview;
  flags: string[]; model: string | null;
}

export interface ReviewItem {
  kind: "entity" | "lab"; id: string; entry_id: string | null; display: string; value: string | null;
  confidence: number | null; source_excerpt: string;
  quote?: string; hpo_label?: string | null; occurred_on?: string; negated?: boolean; family_history?: boolean;
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
  neutral_label: string;
}

export interface ShareRequest {
  clinic_url: string; since: string; until: string; include_patterns: boolean;
  note?: string | null; expires_hours: number;
}

export interface SharedEntity {
  entry_id: string; occurred_on: string; type: EntityType; quote: string; canonical: string;
  hpo_id: string | null; negated: boolean; family_history: boolean; severity: number | null; reviewed: boolean;
}

export interface SharePackage {
  package_id: string; patient_alias: string; created_at: string; expires_at: string;
  period: [string, string]; note: string | null; entries: Entry[]; entities: SharedEntity[]; patterns: Pattern[];
}

export type BriefSection = "summary" | "timeline" | "symptoms" | "labs" | "medications" | "patterns" | "questions";
export type BriefReview = "pending" | "accepted" | "rejected" | "edited";

export interface BriefItem {
  id: string; section: BriefSection; text: string; cites: string[];
  origin: "patient" | "ai"; review: BriefReview;
}

export interface Brief {
  package_id: string; items: BriefItem[]; model: string | null; backend: string | null;
  finalized: boolean; stats: { latency_ms?: number; tokens_per_s?: number; tokens?: number } & Record<string, unknown>;
}

export interface Health {
  ok: boolean; mode: "patient" | "clinic";
  llm: { backend?: string; model?: string; base_url_host?: string; is_amd?: boolean; pseudonymize?: boolean };
  locked?: boolean | null; ontology?: { terms?: number; diseases?: number };
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
export interface Timeline { days: TimelineDay[]; terms: Evidence[] }
export interface PatternsResponse { patterns: Pattern[]; confirmed_terms: number; note: string }
export interface ShareResult {
  package_id: string; clinic_url: string; expires_at: string; qr_payload: string; entities: number; entries: number;
}
export interface ClinicKey { public_key: string; fingerprint: string; clinic_name: string }
export interface InboxRow {
  package_id: string; patient_alias: string; period: [string, string]; received_at: string;
  expires_at: string; entities: number; brief_state: string;
}

export interface RunEvent {
  stage: string; message?: string; progress?: number; backend?: string; model?: string;
  tokens_per_s?: number; latency_ms?: number; payload?: unknown;
}

export type LabReview = "auto" | "needs_review" | "confirmed" | "corrected" | "rejected";
export type LabFlag = "low" | "high" | "normal";
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
}
export interface LabResult {
  id: string; batch_id: string; test_name: string; test_key: string; value_numeric: number | null;
  value_text: string | null; unit: string; ref_low: number | null; ref_high: number | null; flag: LabFlag | null;
  date: string; page: number; confidence: number | null; review: LabReview; model: string | null;
}
export interface NextQuestion {
  feature_id: string; question: string; why: string; ig: number; splits: string[]; question_source: "model" | "template";
}
export interface RankedPattern { disease_id: string; label: string; score: number; rank: number }
export interface AnswerResult { before: RankedPattern[]; after: RankedPattern[]; entry_id: string | null }
export type Answer = "yes" | "no" | "unsure";
