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
| PATCH | `/api/entities/{id}` | `{review?, canonical?, hpo_id?, severity?, negated?}` (`review`: `auto\|confirmed\|rejected`; legacy `status` is accepted as an alias; setting `hpo_id` alone marks it `corrected`) | `Entity` |
| GET | `/api/review` | | `{items: ReviewItem[], count}`: entities in `needs_review` (confidence below `CLARIO_REVIEW_THRESHOLD`) |
| POST | `/api/review/{kind}/{id}` | `{action: confirm\|correct\|reject, value?}` | `{ok, count}`; `correct` needs `value` = an HPO id from the term list. Writes a `correction_log` record to the vault (kind, item_id, action, before, after, source_excerpt, ts) |
| GET | `/api/terms/search` | `?q=` | `Term[]` (ontology lookup for manual fixes) |
| GET | `/api/timeline` | | `{days: [{date, entries, terms: [{hpo_id,label}]}], terms: Evidence[]}` |
| GET | `/api/patterns` | | `{patterns: Pattern[], confirmed_terms: int, note: string}` (computed from confirmed or corrected entities only; negated, family-history, `needs_review` and rejected entities never count) |
| POST | `/api/demo` | `{persona: "giulia"}` | loads synthetic entries (marked as demo) |
| POST | `/api/share` | `ShareRequest` | `{package_id, clinic_url, expires_at, qr_payload, entities: n, entries: n}` |
| GET | `/api/clinic/key` | `?url=` | proxy fetch of the clinic's public key (shown to the patient as a fingerprint) |

`Entity.review` is the single state field: `auto` (extracted, not looked at), `needs_review` (self-consistency confidence below the threshold, shown in the review queue), `confirmed`, `corrected`, `rejected` (decided by the patient). Extraction v3 also fills `family_history`, `onset_hint` and `confidence` (null when not measured). Only `confirmed` and `corrected` entities count toward patterns and leave the device in a share.

`ReviewItem = {kind: "entity" (later "lab"), id, entry_id, display, value, confidence, source_excerpt, quote, hpo_label, occurred_on, negated, family_history}`. Other modules add a kind by registering a handler in `app.state.review_kinds` (see `review.py`).

`SafetyNotice = {level: "emergency" \| "advice", message, matched}`: returned when the text matches a red-flag rule. Emergency text still saves, but the UI must show the notice first.

Extraction env (patient mode): `CLARIO_SC_N` (self-consistency samples, default 5, 1 disables), `CLARIO_TRUST_MODEL_CONFIDENCE=1` (use the model's own `confidence`), `CLARIO_HPO_PICK` (default 1: second call picks the HPO id from ontology candidates only), `CLARIO_REVIEW_THRESHOLD` (default 0.7).

`SharedEntity` carries `family_history` and `reviewed`; the clinician brief marks any item with `reviewed=false` as "not reviewed by a person".

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
