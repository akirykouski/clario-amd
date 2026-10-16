import type {
  AiCall, Answer, AnswerResult, BatchStarted, PrivacyPreview, PrivacyVerify, Brief, BriefItem, BriefView, Persona, ClinicKey, Entity, Entry, Health, InboxRow, LabPatch, LabResult, LabsResponse, NextQuestion, PatternsResponse, ReviewAction, ReviewQueue, SafetyNotice,
  ShareRequest, ShareResult, SharePackage, Term, Timeline, VaultState, Differential, Decisions, TermDecision, Condition,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = "ApiError"; }
}

let lockedHandler: () => void = () => {
  if (typeof window !== "undefined" && window.location.pathname !== "/unlock") window.location.assign("/unlock");
};
export function onLocked(fn: () => void) { lockedHandler = fn; }

export function buildUrl(path: string, params?: Record<string, string | undefined>): string {
  const q = Object.entries(params ?? {})
    .filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v as string)}`)
    .join("&");
  return `/api${path}${q ? `?${q}` : ""}`;
}

async function request<T>(method: string, path: string, opts: { params?: Record<string, string | undefined>; body?: unknown; form?: FormData; text?: boolean } = {}): Promise<T> {
  const res = await fetch(buildUrl(path, opts.params), {
    method,
    headers: opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
  });
  if (res.status === 423) {
    lockedHandler();
    throw new ApiError(423, "Diary is locked");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch { /* keep statusText */ }
    throw new ApiError(res.status, res.status === 401 ? "Wrong passphrase or not authorised" : detail || `HTTP ${res.status}`);
  }
  return (opts.text ? res.text() : res.json()) as Promise<T>;
}

export const api = {
  health: () => request<Health>("GET", "/health"),
  vault: () => request<VaultState>("GET", "/vault"),
  setup: (passphrase: string) => request<{ ok: boolean }>("POST", "/vault/setup", { body: { passphrase } }),
  unlock: (passphrase: string) => request<{ ok: boolean }>("POST", "/vault/unlock", { body: { passphrase } }),
  lock: () => request<{ ok: boolean }>("POST", "/vault/lock"),
  entries: (since?: string, until?: string) => request<Entry[]>("GET", "/entries", { params: { since, until } }),
  addEntry: (b: { text: string; occurred_on?: string; mood?: number | null; lang?: string }) =>
    request<{ entry: Entry; safety: SafetyNotice | null }>("POST", "/entries", { body: b }),
  entry: (id: string) => request<Entry>("GET", `/entries/${encodeURIComponent(id)}`),
  deleteEntry: (id: string) => request<{ ok: boolean }>("DELETE", `/entries/${encodeURIComponent(id)}`),
  extract: (id: string) => request<Entry>("POST", `/entries/${encodeURIComponent(id)}/extract`),
  patchEntity: (id: string, b: Partial<Pick<Entity, "review" | "canonical" | "hpo_id" | "severity" | "negated">>) =>
    request<Entity>("PATCH", `/entities/${encodeURIComponent(id)}`, { body: b }),
  review: () => request<ReviewQueue>("GET", "/review"),
  reviewAct: (kind: string, id: string, action: ReviewAction, value?: string) =>
    request<{ ok: boolean; count: number }>("POST", `/review/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, { body: { action, value } }),
  searchTerms: (q: string, lang?: string) => request<Term[]>("GET", "/terms/search", { params: { q, lang } }),
  timeline: (lang?: string) => request<Timeline>("GET", "/timeline", { params: { lang } }),
  gpu: () => request<Record<string, unknown> | null>("GET", "/system/gpu"),
  patterns: (lang?: string) => request<PatternsResponse>("GET", "/patterns", { params: { lang } }),
  nextQuestion: (lang: string) => request<NextQuestion | null>("GET", "/patterns/next-question", { params: { lang } }),
  answerQuestion: (b: { feature_id: string; answer: Answer; question?: string; lang?: string }) =>
    request<AnswerResult>("POST", "/patterns/answer", { body: b }),
  demo: (persona: Persona = "giulia") => request<{ ok: boolean; entries: number; persona: Persona; lang: string }>("POST", "/demo", { body: { persona } }),
  demoDocuments: () => request<BatchStarted>("POST", "/demo/documents"),
  share: (b: ShareRequest) => request<ShareResult>("POST", "/share", { body: b }),
  clinicKey: (url?: string) => request<ClinicKey>("GET", "/clinic/key", { params: { url } }),
  inbox: () => request<InboxRow[]>("GET", "/inbox"),
  package: (id: string) => request<SharePackage>("GET", `/inbox/${encodeURIComponent(id)}`),
  startBrief: (id: string, lang?: string) => request<{ run_id: string }>("POST", `/inbox/${encodeURIComponent(id)}/brief${lang ? `?lang=${encodeURIComponent(lang)}` : ""}`),
  brief: (id: string, v?: BriefView) => request<Brief>("GET", `/inbox/${encodeURIComponent(id)}/brief`, { params: v }),
  reviewItem: (pkg: string, item: string, b: { review: BriefItem["review"]; text?: string }) =>
    request<BriefItem>("PATCH", `/brief-items/${encodeURIComponent(pkg)}/${encodeURIComponent(item)}`, { body: b }),
  finalize: (id: string) => request<Brief>("POST", `/inbox/${encodeURIComponent(id)}/brief/finalize`),
  briefMdUrl: (id: string, v?: BriefView) => buildUrl(`/inbox/${encodeURIComponent(id)}/brief.md`, v),
  privacyPreview: (entryId: string) => request<PrivacyPreview>("GET", "/privacy/preview", { params: { entry_id: entryId } }),
  privacyCalls: (limit = 50) => request<AiCall[]>("GET", "/privacy/calls", { params: { limit: String(limit) } }),
  privacyVerify: () => request<PrivacyVerify>("GET", "/privacy/verify"),
  labs: () => request<LabsResponse>("GET", "/labs"),
  patchLab: (id: string, b: LabPatch) => request<LabResult>("PATCH", `/labs/${encodeURIComponent(id)}`, { body: b }),
  uploadBatch: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<BatchStarted>("POST", "/documents/batch", { form: fd });
  },
  batchEventsUrl: (id: string) => buildUrl(`/documents/batch/${encodeURIComponent(id)}/events`),
  runEventsUrl: (runId: string) => buildUrl(`/runs/${encodeURIComponent(runId)}/events`),
  privacyCounts: () => request<Record<string, number>>("GET", "/privacy/counts"),
  termSystems: (ids: string[]) => request<Record<string, string>>("GET", "/terms/systems", { params: { ids: ids.join(",") } }),
  ddx: (id: string, lang?: string) => request<Differential>("GET", `/inbox/${encodeURIComponent(id)}/ddx`, { params: { lang } }),
  ddxAnswer: (id: string, b: { feature_id: string; answer: Answer; lang?: string }) =>
    request<{ before: Condition[]; differential: Differential }>("POST", `/inbox/${encodeURIComponent(id)}/ddx/answer`, { body: b }),
  ddxReset: (id: string, lang?: string) => request<Differential>("DELETE", `/inbox/${encodeURIComponent(id)}/ddx/answers`, { params: { lang } }),
  decisions: (id: string) => request<Decisions>("GET", `/inbox/${encodeURIComponent(id)}/decisions`),
  decideLab: (id: string, labId: string, decision: TermDecision) =>
    request<Decisions>("PATCH", `/inbox/${encodeURIComponent(id)}/labs/${encodeURIComponent(labId)}`, { body: { decision } }),
  decideTerm: (id: string, entId: string, decision: TermDecision) =>
    request<Decisions>("PATCH", `/inbox/${encodeURIComponent(id)}/terms/${encodeURIComponent(entId)}`, { body: { decision } }),
};
