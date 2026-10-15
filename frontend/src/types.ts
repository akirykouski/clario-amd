// Mirror of backend/clario/models.py and docs/API.md
export type EntityType = "symptom" | "finding" | "lab" | "medication" | "trigger" | "body_site";
export type Signal = "weak" | "moderate" | "strong";
export type EntityStatus = "suggested" | "confirmed" | "rejected";
export type Extraction = "pending" | "done" | "failed";

export interface Term { hpo_id: string; label: string }

export interface Entity {
  id: string; entry_id: string; type: EntityType; quote: string; canonical: string;
  hpo_id: string | null; hpo_label: string | null; negated: boolean; severity: number | null;
  status: EntityStatus; flags: string[]; model: string | null;
}

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
}

export interface ShareRequest {
  clinic_url: string; since: string; until: string; include_patterns: boolean;
  note?: string | null; expires_hours: number;
}

export interface SharedEntity {
  entry_id: string; occurred_on: string; type: EntityType; quote: string; canonical: string;
  hpo_id: string | null; negated: boolean; severity: number | null;
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
  llm: { backend?: string; model?: string; base_url_host?: string; is_amd?: boolean };
  locked?: boolean | null; ontology?: { terms?: number; diseases?: number };
}

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
