# Clario HTTP API (contract)

Shapes: `backend/clario/models.py`. One codebase, two modes: `CLARIO_MODE=patient` (port 8765, runs on the patient's device) and `CLARIO_MODE=clinic` (port 8800, runs on the clinic's AMD server). JSON unless noted.

## Both modes
| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `Health` (`mode`, `llm: {backend, model, base_url_host, is_amd}`, `ontology: {terms, diseases}`, `demo_instance: bool`) |
| GET | `/api/system/gpu` | `{gpu_name, util_pct, vram_used_gb, vram_total_gb}` or `null` (proxies `CLARIO_GPU_METRICS_URL`, else local `amd-smi`, else null) |

## Patient mode
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/vault` | | `{initialized: bool, locked: bool}` |
| POST | `/api/vault/setup` | `{passphrase}` (min 12 chars) | `{ok}`; vault unlocked |
| POST | `/api/vault/unlock` | `{passphrase}` | `{ok}` or 401 |
| POST | `/api/vault/lock` | | `{ok}` |
| GET | `/api/entries` | `?since&until` | `Entry[]` newest first (423 if locked) |
| POST | `/api/entries` | `{text, occurred_on?, mood?}` | `{entry: Entry, safety: SafetyNotice \| null}`; extraction runs in background |
| GET | `/api/entries/{id}` | | `Entry` |
| DELETE | `/api/entries/{id}` | | `{ok}` |
| POST | `/api/entries/{id}/extract` | | `Entry` (re-run extraction synchronously) |
| PATCH | `/api/entities/{id}` | `{status?, canonical?, hpo_id?, severity?, negated?}` | `Entity` |
| GET | `/api/terms/search` | `?q=` | `Term[]` (ontology lookup for manual fixes) |
| GET | `/api/timeline` | | `{days: [{date, entries, terms: [{hpo_id,label}]}], terms: Evidence[]}` |
| GET | `/api/patterns` | | `{patterns: Pattern[], confirmed_terms: int, note: string}` (computed from confirmed entities only) |
| POST | `/api/demo` | `{persona: "giulia"}` | loads synthetic entries (marked as demo) |
| POST | `/api/share` | `ShareRequest` | `{package_id, clinic_url, expires_at, qr_payload, entities: n, entries: n}` |
| GET | `/api/clinic/key` | `?url=` | proxy fetch of the clinic's public key (shown to the patient as a fingerprint) |

`SafetyNotice = {level: "emergency" \| "advice", message, matched}`: returned when the text matches a red-flag rule. Emergency text still saves, but the UI must show the notice first.

## Clinic mode
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/clinic/key` | | `{public_key (base64), fingerprint, clinic_name}` |
| POST | `/api/inbox` | `{package_id, sealed (base64)}` | `{ok, package_id}` (sealed box to clinic key; rejects expired) |
| GET | `/api/inbox` | | `[{package_id, patient_alias, period, received_at, expires_at, entities, brief_state}]` |
| GET | `/api/inbox/{id}` | | `SharePackage` |
| POST | `/api/inbox/{id}/brief` | | `{run_id}`: drafts the brief with the clinic model; SSE events on `/api/runs/{run_id}/events` |
| GET | `/api/runs/{run_id}/events` | | SSE `{stage, message, progress, backend, model, tokens_per_s, latency_ms, payload}`; final `done` payload = `Brief` |
| GET | `/api/inbox/{id}/brief` | | `Brief` |
| PATCH | `/api/brief-items/{package_id}/{item_id}` | `{review, text?}` | `BriefItem` |
| POST | `/api/inbox/{id}/brief/finalize` | | `Brief` (409 while any item is `pending`) |
| GET | `/api/inbox/{id}/brief.md` | | text/markdown of accepted and edited items only, with citations |
| GET | `/api/bench` | | latest `bench/results/*.json` |
