# Clario HTTP API (contract)

Shapes: `backend/clario/models.py`. One codebase, two modes: `CLARIO_MODE=patient` (port 8765, runs on the patient's device) and `CLARIO_MODE=clinic` (port 8800, runs on the clinic's AMD server). JSON unless noted.

## Both modes
| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `Health` (`mode`, `llm: {backend, model, base_url_host, is_amd}`, `ontology: {terms, diseases}`) |

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

## Privacy (both modes)
Text is pseudonymized (`backend/clario/privacy.py`) before a model call when `CLARIO_PSEUDONYMIZE=1`, or by default in patient mode when `LLM_BASE_URL` is not localhost. Email, phone, codice fiscale, IBAN, absolute dates, street addresses and first names become `[EMAIL]` `[PHONE]` `[CODICE_FISCALE]` `[IBAN]` `[DATE]` `[ADDRESS]` `[NAME]`. Medical terms, doses, lab values and scores are untouched. Quotes returned by the model are mapped back to the original text (the map lives in memory for the call). Every call is logged on every backend, redacted or not: patient mode in the vault (kind `ai_call`), clinic mode in `ai_calls.jsonl` in the clinic data dir.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/privacy/calls` | `?limit=50` (max 500). `AiCall[]` newest first |
| GET | `/api/privacy/verify` | `PrivacyVerify` = `{ok, broken_at: id \| null, count}`. Recomputes the chain; any edited, removed or reordered record gives `ok=false` and the first bad id |
| GET | `/api/privacy/preview` | patient only. `?entry_id=` returns `PrivacyPreview` = `{original, redacted, replacements: [{type, start, end, out_start, out_end}], applied, backend}` |

`/api/health` `llm.pseudonymize` reports whether redaction is active. The log stores a 200 char redacted preview and the sha256 of the exact payload sent, never the raw text. Deleting the newest records (tail truncation) is not detectable by the chain alone.
