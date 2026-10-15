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
| POST | `/api/entries` | `{text, occurred_on?, mood?, lang?: en\|it}` | `{entry: Entry, safety: SafetyNotice \| null}`; extraction runs in background, except for a dosing or medicine-change question (`safety.level = advice`): the entry is saved with `extraction=done`, no entities, and never reaches a model. `lang` words the notice |
| GET | `/api/entries/{id}` | | `Entry` |
| DELETE | `/api/entries/{id}` | | `{ok}` |
| POST | `/api/entries/{id}/extract` | | `Entry` (re-run extraction synchronously) |
| PATCH | `/api/entities/{id}` | `{review?, canonical?, hpo_id?, severity?, negated?}` (`review`: `auto\|confirmed\|rejected`; setting `hpo_id` alone marks it `corrected`) | `Entity` |
| GET | `/api/review` | | `{items: ReviewItem[], count}`: entities and lab rows in `needs_review` (confidence below `CLARIO_REVIEW_THRESHOLD`). `count` feeds the nav badge |
| POST | `/api/review/{kind}/{id}` | `{action: confirm\|correct\|reject, value?}` | `{ok, count}`; `correct` needs `value` = an HPO id from the term list. Writes a `correction_log` record to the vault (kind, item_id, action, before, after, source_excerpt, ts) |
| GET | `/api/terms/search` | `?q=&lang=en\|it` | `Term[]` (ontology lookup for manual fixes; with `lang=it` the shipped plain Italian names are searched first and labels come back in Italian) |
| GET | `/api/timeline` | | `{days: [{date, entries, terms: [{hpo_id,label}]}], terms: Evidence[]}` |
| GET | `/api/patterns` | `?lang=en\|it` | `{patterns: PatientPattern[] (at most 2), confirmed_terms: int, note: string}`. Condition names are clinician-only: a card carries an opaque `card_id`, the features the patient recorded in everyday words (`label`, with the clinical HPO name as `clinical` subtext) and a template `rationale` that names no condition. A card needs at least 3 matched specific terms (fever, headache and fatigue never count alone); the score counts close matches only; `count` is the number of notes. `missing` lists only features the condition shows in more than half of cases, with real frequency data, that a person can notice (no red-flag, lab, structural or frightening terms). Computed from confirmed or corrected entities only; negated, family-history, `needs_review` and rejected entities never count |
| GET | `/api/patterns/next-question` | `?lang=en\|it` | `NextQuestion \| null`: the one yes/no question with the highest expected information gain, asked only about features of a card on screen at moderate or stronger signal (null when only weak cards are shown, fewer than 3 confirmed terms, or nothing askable). `splits` holds `card_id`s of the shown cards only. Wording: "Do you ever notice <everyday phrase>?". Never names a condition or medicine; red-flag, medicine, lab-only, structural and frightening terms are never asked |
| POST | `/api/patterns/answer` | `{feature_id, answer: "yes"\|"no"\|"unsure", question?, lang?}` | `AnswerResult {before: RankedPattern[], after: RankedPattern[], entry_id}` (the cards on screen, at most 2, keyed by `card_id`). yes/no saves a diary entry "Answer to a question: <question> Yes\|No" with one confirmed entity (negated for no); unsure only records that it was skipped (`entry_id` null) |
| POST | `/api/demo` | `{persona: "giulia" \| "giulia_it"}` | loads synthetic entries (marked as demo): the English persona or "Giulia (IT)", the same clinical picture in colloquial Italian (negation, a relative's condition, onset hints, a 0-10 rating). Returns `{ok, entries, persona, lang}` |
| POST | `/api/demo/documents` | | reads the 3 synthetic Italian referti shipped with the app, same path as an upload. Returns `{batch_id, pages, entry_id}` |
| POST | `/api/share` | `ShareRequest` | `{package_id, clinic_url, expires_at, qr_payload, entries, entities, mentions, terms, labs, patterns}`. `entities` = `mentions` = the patient's own mentions (negated and family-history entities are not counted), `terms` = distinct terms, `labs` = shared lab rows; the clinic inbox row carries the same numbers ("N mentions of M terms") |
| GET | `/api/clinic/key` | `?url=` | proxy fetch of the clinic's public key (shown to the patient as a fingerprint) |
| POST | `/api/documents/batch` | multipart `files` (PDF, JPEG, PNG; max 400 pages) | `{batch_id, pages, entry_id}`; pages stored encrypted, entry "Imported documents (N pages)", extraction runs in the background |
| GET | `/api/documents/batch/{id}/events` | | SSE once per second `{batch_id, pages_done, pages_total, pages_per_sec, gpu, errors, labs, needs_review, done}`; `gpu` = result of `GET /api/system/gpu` if that route exists, else null |
| GET | `/api/labs` | `?include_rejected` | `{tests: LabTest[], n_results, needs_review, out_of_range}`; `LabTest = {test_key, test_name, unit, ref_low, ref_high, latest, out_of_range, values: LabValue[] (oldest first)}` |
| PATCH | `/api/labs/{id}` | `{action: confirm \| correct \| reject, value_numeric?, value_text?, unit?, ref_low?, ref_high?}` | `LabResult` (`review` becomes confirmed, corrected or rejected; flag recomputed in code) |

Lab rows carry `confidence` (self-consistency across samples when the client has `samples`, else the model's own) and `review`: `auto` or `needs_review` (confidence below `CLARIO_REVIEW_THRESHOLD`, default 0.7). Env: `CLARIO_DOC_CONCURRENCY` (default 4, 32 for remote backends), `CLARIO_DOC_SAMPLES` (3), `LLM_VISION_MODEL` (else `LLM_MODEL`).

`Entity.review` is the single state field: `auto` (extracted, not looked at), `needs_review` (self-consistency confidence below the threshold, shown in the review queue), `confirmed`, `corrected`, `rejected` (decided by the patient). Extraction v3 also fills `family_history`, `onset_hint` and `confidence` (null when not measured). Only `confirmed` and `corrected` entities count toward patterns and leave the device in a share.

`ReviewItem = {kind: "entity" \| "lab", id, entry_id, canonical, display, value, confidence, source_excerpt, quote, hpo_label, occurred_on, negated, family_history}`. Lab items add `{flag, page, batch_id, unit, ref_low, ref_high}` (`entry_id` null, `value` = printed value with unit) and use the same `POST /api/review/lab/{id}`: `correct` takes `value` as free text (`5,5` or `Positivo 1:160`), the flag is recomputed in code. Other modules add a kind by registering a handler in `app.state.review_kinds` (see `review.py`); the lab handler is registered by `doc_routes.py`.

`SafetyNotice = {level: "emergency" \| "advice", message, matched}`: returned when the text matches a red-flag rule. Emergency text still saves, but the UI must show the notice first.

Extraction env (patient mode): `CLARIO_SC_N` (self-consistency samples, default 5, 1 disables), `CLARIO_TRUST_MODEL_CONFIDENCE=1` (use the model's own `confidence`), `CLARIO_HPO_PICK` (default 1: second call picks the HPO id from ontology candidates only), `CLARIO_REVIEW_THRESHOLD` (default 0.7).

`SharedEntity` carries `family_history`, `onset_hint` and `reviewed`; the clinician brief marks any item with `reviewed=false` as "not reviewed by a person". A relative's condition leaves the device only as family history: `family_history=true` and no `hpo_id`, so it is never a patient term and never counted. Negated entities keep `negated=true` and are not counted either.

`SharePackage.labs: SharedLab[]` is lab history, not just the period: every result (up to the end date) of each test that appears in the shared period, plus any out-of-range result (flag low or high, or a positive text result) from the 12 months before the end date, so an earlier positive ANA or high anti-dsDNA stays visible next to a later negative. Rows a person confirmed or corrected, plus confident rows nobody has checked (`reviewed=false`, shown as "From documents, pending check"). `needs_review` and rejected rows never leave. `SharedLab = {id, test_name, test_key, name_en, value_numeric, value_text, unit, ref_low, ref_high, flag, abnormal, date, page, entry_id, reviewed, decision}`; `test_name` is as printed, `name_en` is the English name of a known test (the English clinic UI shows it), `test_key` groups one test across documents, `entry_id` is the diary entry of the import, which the brief's labs items cite. `flag` is null when no reference range is printed (never "normal"). `decision` (`accepted`, `rejected` or null) is filled by the clinic server for unchecked rows. `POST /api/demo/documents` moves the newest synthetic report to 28 days ago so the demo labs fall inside a normal share period.

## Clinic mode
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/clinic/key` | | `{public_key (base64), fingerprint, clinic_name}` |
| POST | `/api/inbox` | `{package_id, sealed (base64)}` | `{ok, package_id}` (sealed box to clinic key; rejects expired) |
| PUT | `/api/inbox/{id}/labs/{lab_id}` | `{decision: accepted \| rejected \| pending}` | `SharePackage` with decisions applied. Only rows with `reviewed=false`; 404 unknown row, 409 for a row the patient checked or after the brief is final. Decisions are stored encrypted on the clinic server. Finalize returns 409 while any unchecked lab row has no decision; rejected rows are left out of the brief and both copies |
| GET | `/api/inbox` | | `[{package_id, patient_alias, period, received_at, expires_at, entities, mentions, terms, labs, entries, brief_state}]` |
| GET | `/api/inbox/{id}` | | `SharePackage` |
| POST | `/api/inbox/{id}/brief` | `?lang=en\|it` | `{run_id}`: drafts the brief with the clinic model; SSE events on `/api/runs/{run_id}/events` |
| GET | `/api/runs/{run_id}/events` | | SSE `{stage, message, progress, backend, model, tokens_per_s, latency_ms, payload}`; final `done` payload = `Brief` |
| GET | `/api/inbox/{id}/brief` | `?audience=clinician\|patient&lang=it\|en` | `Brief` (carries `lang`, `audience`). Default: the stored clinician brief. `clinician`: clinical terms, HPO ids, severity and onset, family history marked. `patient`: plain words (the patient's own quotes and Italian names where shipped), no condition names, only AI items a clinician accepted or edited that were drafted in the same `lang`; 409 until the brief is finalized |
| PATCH | `/api/brief-items/{package_id}/{item_id}` | `{review, text?}` | `BriefItem` (`flag: "citation_mismatch" \| null`, set in code when the text names a term that none of its cited entries confirms; flagged items stay `pending` and never reach the patient copy) |
| POST | `/api/inbox/{id}/brief/finalize` | optional `{seconds?}`: time from opening the package to finalize, measured by the clinic UI | `Brief` with `finalized_at` and `review_seconds` (null when the UI sent none or an implausible value). 409 while any item is `pending`. Appends one row to `decisions.jsonl` in the clinic data dir |
| GET | `/api/clinic/metrics` | | `ClinicMetrics` = `{briefs: [{package_id, finalized_at, accepted, edited, rejected, review_seconds}], totals: {accepted, edited, rejected}, finalized, timed, mean_review_seconds}`. Pilot metric: decisions on AI-drafted lines of finalized briefs (patient-origin lines are not counted), newest first, one row per package. Counts and timing only, no diary text, and rows outlive package expiry. `mean_review_seconds` is over the `timed` briefs and null when there are none |
| GET | `/api/inbox/{id}/brief.md` | `?audience&lang` as above | text/markdown of accepted and edited items only, with citations |
| GET | `/api/bench` | | latest `bench/results/*.json` |

## Privacy (both modes)
Text is pseudonymized (`backend/clario/privacy.py`) before a model call when `CLARIO_PSEUDONYMIZE=1`, or by default in patient mode when `LLM_BASE_URL` is not localhost. Email, phone, codice fiscale, IBAN, absolute dates, street addresses, full dates of birth and personal names (recognised by title, label, relation, first-name list or "X said" pattern) become `[EMAIL]` `[PHONE]` `[CODICE_FISCALE]` `[IBAN]` `[DATE]` `[ADDRESS]` `[NAME]` `[HEALTH_ID]` (tessera sanitaria) `[RECORD_NO]` (hospital record number). Rules and a first-name lexicon do this with no model involved. `PrivacyReplacement.type` keeps its seven kinds: `[HEALTH_ID]` and `[RECORD_NO]` report as `codice_fiscale`. The measured miss rate is in `eval/results/pii_leak.json` (5.8% of identifiers on a synthetic test half, n = 712). Scanned images and photos are sent unredacted. Medical terms, doses, lab values and scores are untouched. Quotes returned by the model are mapped back to the original text (the map lives in memory for the call). Every call is logged on every backend, redacted or not: patient mode in the vault (kind `ai_call`), clinic mode in `ai_calls.jsonl` in the clinic data dir.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/privacy/calls` | `?limit=50` (max 500). `AiCall[]` newest first |
| GET | `/api/privacy/verify` | `PrivacyVerify` = `{ok, broken_at: id \| null, count}`. Recomputes the chain; any edited, removed or reordered record gives `ok=false` and the first bad id |
| GET | `/api/privacy/preview` | patient only. `?entry_id=` returns `PrivacyPreview` = `{original, redacted, replacements: [{type, start, end, out_start, out_end}], applied, backend}` |

`/api/health` `llm.pseudonymize` reports whether redaction is active. The log stores a 200 char redacted preview and the sha256 of the exact payload sent; the raw text is not stored. Deleting the newest records (tail truncation) is not detectable by the chain alone.

## Safety interceptor, wording and storage
- Red-flag text and dosing or medicine-change questions (EN and IT: "can I take more ibuprofen", "should I stop my pills", "posso aumentare la dose", "smetto di prendere ...?", and any such question about medicines in pregnancy or breastfeeding) are matched in `safety.check_entry` before any model call. Emergencies return `level=emergency`. Dosing questions return `level=advice`, point to the clinician or pharmacist, and the entry skips extraction. A note that merely mentions a medicine is not blocked.
- Patient-facing server text honours `lang=it`: safety notices, `/api/patterns` (labels, note), `/api/patterns/next-question`, the saved answer entry (`Risposta a una domanda: ... Sì|No`). HPO names in Italian come from `clario/data/hpo_it.json` and `lay_terms_it.json`; a term without an entry keeps its English label. Italian next questions are only asked for terms that have an Italian phrase.
- Clinic mode stores the opened packages sealed to the clinic key (as received) and writes briefs and the call-log previews encrypted with AES-256-GCM under a key derived (HKDF) from the clinic key file. No diary text is written to disk in clear.
- One extraction prompt: `backend/clario/prompt.py` is a verbatim copy of `train/prompt.py` (a test fails if they differ); the app sends the same system prompt and a single user turn as training. No few-shot.
