import type {
  AiCall, Answer, AnswerResult, BatchStarted, PrivacyPreview, PrivacyVerify, Brief, BriefLine, BriefText, BriefWarning, ClinicMetrics, BriefView, Persona, ClinicKey, Entity, Entry, Health, InboxRow, LabPatch, LabResult, LabsResponse, NextQuestion, PatternsResponse, ReviewAction, ReviewQueue, SafetyNotice,
  ShareRequest, ShareResult, SharePackage, Term, Timeline, VaultState, Differential, Decisions, TermDecision, Condition, Overview, Profile, LabCorrection, Specialty,
  Care, Comparison, VerifyStarted, VerifyStatus, VerifyLookup, VerifyClaim, VerifyDoctorStatus, VerifyConclusions, VerifyRegister,
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

async function request<T>(method: string, path: string, opts: { params?: Record<string, string | undefined>; body?: unknown; form?: FormData; text?: boolean; headers?: Record<string, string>; keepalive?: boolean } = {}): Promise<T> {
  const res = await fetch(buildUrl(path, opts.params), {
    method,
    headers: opts.body !== undefined || opts.headers ? { ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}), ...opts.headers } : undefined,
    keepalive: opts.keepalive,
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
  /** Decide many readings that need a check in one call: no filter is every one, `test_key` one test, `page` + `entry_id` one report page. */
  decideLabs: (pkg: string, b: { decision: TermDecision; test_key?: string; page?: number; entry_id?: string | null }) =>
    request<SharePackage>("POST", `/inbox/${encodeURIComponent(pkg)}/labs/decide`, { body: b }),
  /** Draft the brief; the demo persona's unchanged package gets its stored draft at once unless `live` ("Regenerate live"). */
  startBrief: (id: string, lang?: string, live?: boolean) =>
    request<{ run_id: string; precomputed?: boolean }>("POST", `/inbox/${encodeURIComponent(id)}/brief`, { params: { lang, live: live ? "true" : undefined } }),
  brief: (id: string, v?: BriefView) => request<Brief>("GET", `/inbox/${encodeURIComponent(id)}/brief`, { params: v }),
  briefText: (id: string, specialty?: Specialty) =>
    request<BriefText>("GET", `/inbox/${encodeURIComponent(id)}/brief/text`, { params: { specialty } }),
  /** Code checks on the card editor's lines; each warning's `item` indexes `items`. */
  checkBrief: (id: string, items: BriefLine[], specialty?: Specialty) =>
    request<{ warnings: BriefWarning[] }>("POST", `/inbox/${encodeURIComponent(id)}/brief/check`, { body: { items, specialty } }),
  signBrief: (id: string, b: { items: BriefLine[]; clinician: string; specialty?: Specialty; seconds?: number }) =>
    request<Brief>("POST", `/inbox/${encodeURIComponent(id)}/brief/sign`, { body: b }),
  /** The edited lines as the PDF they would sign (still watermarked as a draft), as a blob URL to open. */
  previewBrief: async (id: string, items: BriefLine[], specialty?: Specialty): Promise<string> => {
    const res = await fetch(buildUrl(`/inbox/${encodeURIComponent(id)}/brief/preview.pdf`), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items, specialty }),
    });
    if (!res.ok) throw new ApiError(res.status, res.statusText || `HTTP ${res.status}`);
    return URL.createObjectURL(await res.blob());
  },
  /** One-page PDF: the AI draft (watermarked, for `specialty`) until signed, then the signed brief. `v` busts the cache. */
  briefPdfUrl: (id: string, v?: { specialty?: Specialty; v?: string }) => buildUrl(`/inbox/${encodeURIComponent(id)}/brief.pdf`, v),
  clinicMetrics: () => request<ClinicMetrics>("GET", "/clinic/metrics"),
  /** The signed clinician brief as Markdown. */
  briefMdUrl: (id: string) => buildUrl(`/inbox/${encodeURIComponent(id)}/brief.md`),
  /** The patient copy of the signed brief: a one-page PDF rendered by the clinic server, in `lang`. */
  briefPatientPdfUrl: (id: string, lang: "en" | "it") => buildUrl(`/inbox/${encodeURIComponent(id)}/brief/patient.pdf`, { lang }),
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
  overview: (id: string, lang?: string) => request<Overview>("GET", `/inbox/${encodeURIComponent(id)}/overview`, { params: { lang } }),
  profile: () => request<Profile>("GET", "/profile"),
  care: () => request<Care>("GET", "/care"),
  /** Second opinion, after the brief is final: the previous doctor's conclusions next to this one's (409 before). */
  compare: (id: string, lang?: string) => request<Comparison>("GET", `/inbox/${encodeURIComponent(id)}/compare`, { params: { lang } }),
  /** Doctor verify (demo). Patient side: start, status, confirm, reject, end. Doctor side (no vault): lookup, claim, doctor status, conclusions, end. */
  verifyStart: () => request<VerifyStarted>("POST", "/verify/start"),
  verifyStatus: (code: string) => request<VerifyStatus>("GET", `/verify/${encodeURIComponent(code)}/status`),
  verifyConfirm: (code: string) => request<VerifyStatus>("POST", `/verify/${encodeURIComponent(code)}/confirm`),
  verifyReject: (code: string) => request<VerifyStatus>("POST", `/verify/${encodeURIComponent(code)}/reject`),
  verifyEnd: (code: string, token?: string) =>
    request<{ ok: boolean; state: string }>("POST", `/verify/${encodeURIComponent(code)}/end`, { headers: token ? { "X-Doctor-Token": token } : undefined, keepalive: true }),
  verifyRegister: () => request<VerifyRegister>("GET", "/verify/register"),
  verifyLookup: (code: string, b: { name: string; surname: string; province: string }) =>
    request<VerifyLookup>("POST", `/verify/${encodeURIComponent(code)}/lookup`, { body: b }),
  verifyClaim: (code: string, hitId: string) => request<VerifyClaim>("POST", `/verify/${encodeURIComponent(code)}/claim`, { body: { hit_id: hitId } }),
  verifyDoctorStatus: (code: string, token: string) =>
    request<VerifyDoctorStatus>("GET", `/verify/${encodeURIComponent(code)}/doctor-status`, { headers: { "X-Doctor-Token": token } }),
  verifyConclusions: (code: string, token: string) =>
    request<VerifyConclusions>("GET", `/verify/${encodeURIComponent(code)}/conclusions`, { headers: { "X-Doctor-Token": token } }),
  saveProfile: (p: Profile) => request<Profile>("PUT", "/profile", { body: p }),
  privacyCounts: () => request<Record<string, number>>("GET", "/privacy/counts"),
  termSystems: (ids: string[]) => request<Record<string, string>>("GET", "/terms/systems", { params: { ids: ids.join(",") } }),
  ddx: (id: string, lang?: string) => request<Differential>("GET", `/inbox/${encodeURIComponent(id)}/ddx`, { params: { lang } }),
  ddxAnswer: (id: string, b: { feature_id: string; answer: Answer; lang?: string }) =>
    request<{ before: Condition[]; differential: Differential }>("POST", `/inbox/${encodeURIComponent(id)}/ddx/answer`, { body: b }),
  ddxReset: (id: string, lang?: string) => request<Differential>("DELETE", `/inbox/${encodeURIComponent(id)}/ddx/answers`, { params: { lang } }),
  decisions: (id: string) => request<Decisions>("GET", `/inbox/${encodeURIComponent(id)}/decisions`),
  decideLab: (id: string, labId: string, decision: TermDecision) =>
    request<Decisions>("PATCH", `/inbox/${encodeURIComponent(id)}/labs/${encodeURIComponent(labId)}`, { body: { decision } }),
  /** The clinician's reading of the printed row replaces the OCR reading; ranking then uses it (computed in code). */
  correctLab: (id: string, labId: string, c: LabCorrection) =>
    request<Decisions>("PATCH", `/inbox/${encodeURIComponent(id)}/labs/${encodeURIComponent(labId)}`, { body: { decision: "corrected", ...c } }),
  decideTerm: (id: string, entId: string, decision: TermDecision) =>
    request<Decisions>("PATCH", `/inbox/${encodeURIComponent(id)}/terms/${encodeURIComponent(entId)}`, { body: { decision } }),
  replaceTerm: (id: string, entId: string, hpoId: string) =>
    request<Decisions>("PATCH", `/inbox/${encodeURIComponent(id)}/terms/${encodeURIComponent(entId)}`, { body: { decision: "corrected", hpo_id: hpoId } }),
  termCandidates: (id: string, entId: string, lang?: string) =>
    request<Term[]>("GET", `/inbox/${encodeURIComponent(id)}/terms/${encodeURIComponent(entId)}/candidates`, { params: { lang } }),
};
