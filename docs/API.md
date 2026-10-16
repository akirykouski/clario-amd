# Clario HTTP API (contract)

Shapes: `backend/clario/models.py`. One codebase, two modes: `CLARIO_MODE=patient` (port 8765, runs on the patient's device) and `CLARIO_MODE=clinic` (port 8800, runs on the clinic's AMD server). JSON unless noted.

## Both modes
| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `Health` (`mode`, `llm: {backend, model, base_url_host, is_amd}`, `ontology: {terms, diseases}`, `demo_instance: bool`) |
| GET | `/api/system/gpu` | `{gpu_name, util_pct, vram_used_gb, vram_total_gb}` or `null` (proxies `CLARIO_GPU_METRICS_URL`, else local `amd-smi`, else null) |
| GET | `/api/terms/systems` | `?ids=HP:..,HP:..` -> `{hpo_id: system}`: organ-system key per term (`skin`, `joints`, `kidney`, `blood`, `immune`, `nervous`, `heart`, `lungs`, `digestive`, `eye`, `endocrine`, `metabolism`, `head`, `general`, `other`) for grouping heat map rows. Ontology only |

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
| GET | `/api/timeline` | `?lang=en\|it` | `{days: [{date, entries: [{id, text, mood, occurred_on}], terms: [{hpo_id,label}]}], terms: (Evidence & {clinical})[], systems: {hpo_id: system}}`. `terms[].label` is the everyday name, `clinical` the HPO label |
| GET | `/api/privacy/counts` | | `{entry_id: n}`: personal details the pseudonymizer would replace, only entries with at least one |
| GET | `/api/patterns` | `?lang=en\|it` | `{patterns: PatientPattern[] (at most 2), confirmed_terms: int, note: string}`. Condition names are clinician-only: a card carries an opaque `card_id`, the features the patient recorded in everyday words (`label`, with the clinical HPO name as `clinical` subtext) and a template `rationale` that names no condition. A card needs at least 3 matched specific terms (fever, headache and fatigue never count alone); the score counts close matches only; `count` is the number of notes. `missing` lists only features the condition shows in more than half of cases, with real frequency data, that a person can notice (no red-flag, lab, structural or frightening terms). Computed from every entity except rejected ones (the patient does not have to confirm anything); negated and family-history entities never count. `confirmed_terms` is the number of counted terms (name kept for compatibility) |
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

`Entity.review` is the single state field: `auto` (extracted, not looked at), `needs_review` (self-consistency confidence below the threshold: flagged for the clinician, optional for the patient), `confirmed`, `corrected`, `rejected` (decided by a person). Extraction v3 also fills `family_history`, `onset_hint` and `confidence` (null when not measured). Every entity except `rejected` counts toward patterns and leaves the device in a share (`models.COUNTED`); `models.REVIEWED` = `confirmed`, `corrected`.

`ReviewItem = {kind: "entity" \| "lab", id, entry_id, canonical, display, value, confidence, source_excerpt, quote, hpo_label, occurred_on, negated, family_history}`. Lab items add `{flag, page, batch_id, unit, ref_low, ref_high}` (`entry_id` null, `value` = printed value with unit) and use the same `POST /api/review/lab/{id}`: `correct` takes `value` as free text (`5,5` or `Positivo 1:160`), the flag is recomputed in code. Other modules add a kind by registering a handler in `app.state.review_kinds` (see `review.py`); the lab handler is registered by `doc_routes.py`.

`SafetyNotice = {level: "emergency" \| "advice", message, matched}`: returned when the text matches a red-flag rule. Emergency text still saves, but the UI must show the notice first.

Extraction env (patient mode): `CLARIO_SC_N` (self-consistency samples, default 5, 1 disables), `CLARIO_TRUST_MODEL_CONFIDENCE=1` (use the model's own `confidence`), `CLARIO_HPO_PICK` (default 1: second call picks the HPO id from ontology candidates only), `CLARIO_REVIEW_THRESHOLD` (default 0.7).

`SharedEntity` carries `id` (the entity id, which the clinic keys its decisions on), `family_history`, `onset_hint`, `reviewed`, `confidence` and `needs_review`; the clinician brief marks items with `needs_review=true` as "low-confidence reading, please check", and the clinic screen lists them for a confirm or reject. A relative's condition leaves the device only as family history: `family_history=true` and no `hpo_id`, so it is never a patient term and never counted. Negated entities keep `negated=true` and are not counted either.

`SharePackage.labs: SharedLab[]` holds every lab row dated inside the shared period except rejected ones. Rows nobody looked at carry `reviewed=false`; low-confidence rows carry `needs_review=true` (the brief and the clinic screen say "low-confidence reading"). `SharedLab = {id, test_name, value_numeric, value_text, unit, ref_low, ref_high, flag, date, page, entry_id, reviewed, confidence, needs_review}`; `entry_id` is the diary entry of the import, which the brief's labs items cite. `POST /api/demo/documents` moves the newest synthetic report to 28 days ago so the demo labs fall inside a normal share period.

## Clinic mode
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/clinic/key` | | `{public_key (base64), fingerprint, clinic_name}` |
| POST | `/api/inbox` | `{package_id, sealed (base64)}` | `{ok, package_id}` (sealed box to clinic key; rejects expired) |
| GET | `/api/inbox` | | `[{package_id, patient_alias, period, received_at, expires_at, entities, mentions, terms, labs, entries, brief_state}]` |
| GET | `/api/inbox/{id}` | | `SharePackage` |
| POST | `/api/inbox/{id}/brief` | `?lang=en\|it` | `{run_id}`: drafts the brief with the clinic model; SSE events on `/api/runs/{run_id}/events` |
| GET | `/api/runs/{run_id}/events` | | SSE `{stage, message, progress, backend, model, tokens_per_s, latency_ms, payload}`; final `done` payload = `Brief` |
| GET | `/api/inbox/{id}/brief` | `?audience=clinician\|patient&lang=it\|en` | `Brief` (carries `lang`, `audience`). Default: the stored clinician brief. `clinician`: clinical terms, HPO ids, severity and onset, family history marked. `patient`: plain words (the patient's own quotes and Italian names where shipped), no condition names, only AI items a clinician accepted or edited that were drafted in the same `lang`; 409 until the brief is finalized |
| PATCH | `/api/brief-items/{package_id}/{item_id}` | `{review, text?}` | `BriefItem` (`flag: "citation_mismatch" \| null`, set in code when the text names a term that none of its cited entries confirms; flagged items stay `pending` and never reach the patient copy) |
| POST | `/api/inbox/{id}/brief/finalize` | | `Brief` (409 while any item is `pending`) |
| GET | `/api/inbox/{id}/brief.md` | `?audience&lang` as above | text/markdown of accepted and edited items only, with citations |
| GET | `/api/inbox/{id}/ddx` | `?lang=en\|it` | `Differential {conditions: Condition[], question: ClinicQuestion \| null, answers: ClinicAnswer[], n_terms, note}`. Clinician only, computed in code from HPO annotations with the clinician's decisions applied. `Condition {disease_id, name, full_name, signal (null = weaker match on score only), score, rank, url (Orphanet or OMIM), matched: [{hpo_id, label, count}], missing: [{hpo_id, label, freq}]}`: signalled conditions first, then the best others above 0.2, at most 4. `ClinicQuestion {feature_id, label, question, ig, freq_by: [{name, freq}]}`: the finding with the highest expected information gain over the top 3; `freq` null when the annotation lists the feature without a frequency, 0 when not listed |
| POST | `/api/inbox/{id}/ddx/answer` | `{feature_id, answer: yes\|no\|unsure, lang?}` | `{before: Condition[], differential: Differential}`; yes/no are applied as present/absent terms, unsure is recorded and not asked again |
| DELETE | `/api/inbox/{id}/ddx/answers` | `?lang` | `Differential` with the answers cleared |
| GET | `/api/inbox/{id}/decisions` | | `{terms: {entity_id: confirmed\|rejected}, answers: ClinicAnswer[]}` (encrypted at rest with the clinic data key) |
| PATCH | `/api/inbox/{id}/labs/{lab_id}` | `{decision: confirmed\|rejected\|pending}` | decisions (`labs: {lab_id: decision}`); low-confidence lab values are checked by the clinician, never by the patient. A rejected value leaves the clinic lab tables |
| PATCH | `/api/inbox/{id}/terms/{entity_id}` | `{decision: confirmed\|rejected\|pending}` | decisions; rejected terms leave the differential, pending clears the decision |
| GET | `/api/bench` | | latest `bench/results/*.json` |

## Privacy (both modes)
Text is pseudonymized (`backend/clario/privacy.py`) before a model call when `CLARIO_PSEUDONYMIZE=1`, or by default in patient mode when `LLM_BASE_URL` is not localhost. Email, phone, codice fiscale, IBAN, absolute dates, street addresses and first names become `[EMAIL]` `[PHONE]` `[CODICE_FISCALE]` `[IBAN]` `[DATE]` `[ADDRESS]` `[NAME]`. Medical terms, doses, lab values and scores are untouched. Quotes returned by the model are mapped back to the original text (the map lives in memory for the call). Every call is logged on every backend, redacted or not: patient mode in the vault (kind `ai_call`), clinic mode in `ai_calls.jsonl` in the clinic data dir.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/privacy/calls` | `?limit=50` (max 500). `AiCall[]` newest first |
| GET | `/api/privacy/verify` | `PrivacyVerify` = `{ok, broken_at: id \| null, count}`. Recomputes the chain; any edited, removed or reordered record gives `ok=false` and the first bad id |
| GET | `/api/privacy/preview` | patient only. `?entry_id=` returns `PrivacyPreview` = `{original, redacted, replacements: [{type, start, end, out_start, out_end}], applied, backend}` |

`/api/health` `llm.pseudonymize` reports whether redaction is active. The log stores a 200 char redacted preview and the sha256 of the exact payload sent, never the raw text. Deleting the newest records (tail truncation) is not detectable by the chain alone.

## Safety interceptor, wording and storage
- Red-flag text and dosing or medicine-change questions (EN and IT: "can I take more ibuprofen", "should I stop my pills", "posso aumentare la dose", "smetto di prendere ...?", and any such question about medicines in pregnancy or breastfeeding) are matched in `safety.check_entry` before any model call. Emergencies return `level=emergency`. Dosing questions return `level=advice`, point to the clinician or pharmacist, and the entry skips extraction. A note that merely mentions a medicine is not blocked.
- Patient-facing server text honours `lang=it`: safety notices, `/api/patterns` (labels, note), `/api/patterns/next-question`, the saved answer entry (`Risposta a una domanda: ... Sì|No`). HPO names in Italian come from `clario/data/hpo_it.json` and `lay_terms_it.json`; a term without an entry keeps its English label. Italian next questions are only asked for terms that have an Italian phrase.
- Clinic mode stores the opened packages sealed to the clinic key (as received) and writes briefs and the call-log previews encrypted with AES-256-GCM under a key derived (HKDF) from the clinic key file. No diary text is written to disk in clear.
- One extraction prompt: `backend/clario/prompt.py` is a verbatim copy of `train/prompt.py` (a test fails if they differ); the app sends the same system prompt and a single user turn as training. No few-shot.
