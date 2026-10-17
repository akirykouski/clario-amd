# Project rules — Clario (AMD Developer Hackathon ACT III, Track 2)

## What this is
Private symptom diary (patient mode) + clinic review server (clinic mode) from one codebase. See docs/PLAN.md, docs/API.md.

## Must-know / gotchas
- NEVER run models locally (no ollama serve/pull, no local inference, no model downloads) unless the user explicitly says so. Live model runs happen on the AMD Developer Cloud (MI300X, vLLM). Without an endpoint: test offline (CLARIO_OFFLINE=1) and report the live path as unverified.
- Contract = backend/clario/models.py + docs/API.md. Change both together.
- Track 2 rules: no diagnosis or treatment language (hedge validator in clario/safety.py), human review before anything AI-written is final.
- Endpoints that spawn background tasks must be `async def` (sync endpoints run in a thread with no event loop).
- Ollama rejects JSON mode for Gemma 4 with HTTP 501; clario/llm.py drops response_format on 400/422/501.
- Vetrina (previous entry) lives on branch `vetrina`.
- Clario is a standalone project: keep code, docs, commits and pitch self-contained, with no links to other projects.
- Work spec: BUILD.md (tasks T1-T11, M1-M5, Russian, user's Downloads). It was written for another codebase: port each task to this one's modules; its file paths do not apply.
- Extraction contract: backend/clario/schemas/extraction_v3.json (frozen 2026-10-15). App prompt, guided JSON, synth.py targets and eval.py all use it.
- Every number in UI, README or slides comes from eval/results/*.json (fields n, dataset, model, backend, date). No result file, no number.
- No real medical data anywhere; synthetic patients and documents only.

## How to run / test / build
- Backend: `cd backend && uv run pytest -q`; `CLARIO_MODE=patient|clinic CLARIO_OFFLINE=1 uv run python -m clario.app`
- Frontend: `cd frontend && npm run build && npx vitest run`
- Training/eval: train/README.md (runs on the AMD droplet)

## Conventions
- Copy: no em dashes, no exclamation marks, plain words.

## Safety rails
- No push without explicit yes. Secrets only via env.

## Extraction v3 and review queue (T4/T5)
- `Entity.review` (auto|needs_review|confirmed|corrected|rejected) is the single state field. Every extracted term counts unless a person rejects it (`models.COUNTED` = all but `rejected`; `models.REVIEWED` = confirmed, corrected): the patient confirms nothing. Negated and family_history entities never count. `needs_review` terms and labs travel marked to the clinic, where the clinician confirms or rejects them (`PATCH /api/inbox/{id}/terms/{id}`, `PATCH|PUT /api/inbox/{id}/labs/{id}`, decisions in `decisions/<pid>.json`); finalize returns 409 while a `needs_review` lab has no decision.
- Clinician term replace (issue #15): `PATCH /api/inbox/{id}/terms/{id}` `{decision: corrected, hpo_id}` stores `corrections[ent_id] = {from, from_label, to, label, at}` in `decisions/<pid>.json`; `clinic_ddx.with_corrections` applies it in `decided()`, the overview and the differential; a draft brief's patient lines are rebuilt. Candidates: `GET /api/inbox/{id}/terms/{id}/candidates` (ontology lookup, no model). Every term decision appends to `term_decisions.jsonl` (ids only).
- `onset_hint` is cleaned in code after parsing (`clario/onset.py`, called in `extract.ground`): time-of-day/frequency and trigger phrases are dropped (flag `onset_dropped`), the prompt stays frozen. train/eval scores raw model output and does not apply it. Patient screens show only plain flag notes (`lib.flagNote`); technical reasons go to the clinic check list (`lib.clinicFlagNote`).
- LLM calls that need n samples or a JSON schema go through `LLM.samples(...)`; OpenAICompat steps json_schema -> guided_json -> plain parsing on 400/422/501.
- Review kinds are handlers added with `review.register_review_kind(app, name, handler)`; the lab kind registers in `doc_routes.py`. Every decision writes a `correction_log` vault record.
- Env: CLARIO_SC_N (5), CLARIO_TRUST_MODEL_CONFIDENCE, CLARIO_HPO_PICK (1), CLARIO_REVIEW_THRESHOLD (0.7). OfflineLLM: a phrase in a "maybe/forse" sentence appears in every other sample, so confidence is 0.6 and it lands in the queue.
- Never `pkill -f clario.app`: other sessions run servers from the same module. Kill by PID.
- Deploy: `deploy/amd/bootstrap.sh` (one command on the MI300X droplet) + `deploy/amd/docker-compose.yml`; runbook in deploy/amd/README.md. Root `Dockerfile` builds the app (`docker build -t clario-app .`). `.env.example` lists every variable. Validate compose: `PUBLIC_HOST=x.sslip.io VLLM_API_KEY=x HF_TOKEN=x docker compose -f deploy/amd/docker-compose.yml config -q`.
- GPU telemetry: `GET /api/system/gpu` (backend/clario/gpu.py, stdlib only, also the sidecar server). amd-smi JSON shape is from AMD docs, unverified on hardware.
- `CLARIO_DEMO_INSTANCE=1` shows the synthetic-data banner in both apps (health.demo_instance).
- Tooling quirk: worktree-isolated shells refuse compound commands containing git/globs/heredocs; use plain commands and the Write/Edit tools.
## ML lane (train/, eval/) must-knows
- Claude/Haiku output never becomes a training target. `synth.py` refuses anthropic.com; Haiku only drafts gold for human review (`train/gold_draft.py`) and acts as an eval comparator.
- Targets are extraction_v3 (`confidence` null in training data). `prompt.py` is the single prompt source; `prep.check_sft` refuses old-format chat files.
- `eval/results/extraction_*.json` must carry n, dataset, model, backend, date. Dry-run and offline files are labelled (`dry_run: true`) and rendered apart by `eval/make_results_md.py`.
- PsyTAR is only available through a store page that returns 403 to scripts: download in a browser, then run `train/psytar_hpo.py`.
- Run train tests from `train/` with `../backend/.venv/bin/python -m pytest -q`.
## Integration and i18n (T9/INT)
- ONE extraction prompt: `backend/clario/prompt.py` is a verbatim copy of `train/prompt.py`; edit train/prompt.py, then `cp train/prompt.py backend/clario/prompt.py` (a backend test compares the bytes and the messages). The app sends system + the diary as the only user turn (no few-shot, as in training). The HPO pick call (`PICK_SYSTEM`) is app-only and not part of the LoRA training.
- Lab flags: one rule, `documents.compute_flag` (`lab_flag` recomputes stored/shared rows on read). Qualitative positive/presente/reattivo -> `positive` (out of range, `abnormal`), negativo/assente -> `normal`. Clinic glance `overview.labs_off` = every test with an out-of-range result (same set as the header count and the lab table), English names via `share.LAB_NAMES_EN` in EN.
- Labs are review kind `lab` (registered in `doc_routes.py`). Dosing and medicine-change questions are intercepted in `safety.check_entry` (level `advice`, entry saved with `extraction=done`, no model call).
- Clinic mode never writes diary text in clear: inbox is sealed, briefs and call-log previews are AES-GCM under a key derived from `clinic.key`.
- i18n: frontend `src/i18n/{en,it}.ts` (typed, `it` must have every `en` key), `useT()`; `hpo.it.ts` equals `backend/clario/data/hpo_it.json` (test). Patient-facing server text takes `lang=en|it` (`clario/i18n.py`). Italian next questions need an entry in `data/lay_terms_it.json`; add HPO ids there and in both hpo_it tables together.
- Personas: `giulia`, `giulia_it` (`demo.py`); `POST /api/demo/documents` imports the 3 shipped referti.
- Tooling quirks (worktree shells): use `/usr/bin/git -C <worktree>`, no heredocs with git, no word "eval" in a command line; write scripts to the scratchpad and run them.
- Review threshold = `eval/results/conformal_threshold.json` (from `eval/conformal.py`, Learn-then-Test on a `--sc-n` eval run) when present and not `dry_run`; else CLARIO_REVIEW_THRESHOLD. `Settings.review_source/alpha/delta` and `GET /api/health` `review` say which. Eval confidence = the app's self-consistency (`train/eval.py --sc-n`); `--confidence` is the verbalized comparison. `train/eval.py` self_consistency mirrors `extract.py` (parity test in backend/tests/test_review_calibration.py).
- One sqlite connection serves the thread pool: every Vault read and write takes `_lock` (a race gave HTTP 500 on GET /api/entries).
## AMD run (one command)
- `deploy/amd/bootstrap.sh --all` runs preflight, serve, health, smoke, synth, prep, train, eval, bench and results; stamps in `deploy/amd/logs/stamps/`, `--step NAME` reruns one, `FORCE=1` redoes all. `--fallback` runs against any OpenAI-compatible BASE_URL/API_KEY/MODEL (anthropic.com refused).
- Real results in eval/results need a `hardware` field; `eval/make_results_md.py --check` enforces it.
- Pseudonymisation eval: `cd backend && uv run python ../eval/pii_leak.py` writes eval/results/pii_leak.json (dev half tuned on, test half reported; disjoint vocab). `privacy.py` stays rule/regex/lexicon only; medical eponyms must never be redacted (`_EPONYMS`, tests in `tests/test_pii_detectors.py`). Tessera sanitaria and record numbers report the existing `codice_fiscale` kind (placeholders `[HEALTH_ID]`, `[RECORD_NO]`); add real kinds in models.py + frontend types + i18n together if wanted.
## Clinic differential: labs and condition families
- Abnormal labs feed the clinic differential through `clinic_ddx.LAB_RULES` (lab name keys = `documents.test_key`, IT and EN; ids and labels pinned in `tests/test_clinic_ddx_labs.py`). The reading is parsed from the value (titre or positive word, number vs range), never from the flag alone. Lab rows count like terms: all but clinician-rejected. Lab features ride in synthetic `clinic_labs_<date>` entries; `ConditionFeature.count` = notes, `.labs` = lab dates.
- `scored_diseases(..., general=True)` (clinic only) groups by `patterns.base_name` and shows the family's general entry (Orphanet, else OMIM, scored on its own annotations). The patient path and calibration keep `display_name` dedupe: do not switch them without rerunning eval/pattern_calibration.py.
## Demo and judge loop (round 3, 2026-10-16)
- Stage walk = DEMO_SCRIPT.md literally, no API shortcuts: scratchpad walk script pattern `walk-r3e.cjs <out> <patientPort> <clinicPort> en|it`, fresh data dirs per run (a reused vault breaks setup). Run EN and IT sequentially against one clinic.
- Patient card tier and clinic card tier must match: share scores the whole diary, the shared window only trims evidence (shared `card_id`). PATIENT_CARDS = 1.
- Patient screens never show a condition name, an HPO code or (in IT) an English clinical label; a relative's condition shows as the patient's own words.
- Numbers in IT use the decimal comma everywhere, server text included (`brief._num(n, lang)`, frontend `fmtNumText`).
- PII headline is the strictly held-out 10.8%; 5.8% only with its caveat.
## AMD Token Factory (T2)
- Backend `amd-token-factory`: detected when LLM_BASE_URL host is developer.amd.com.cn, or forced with LLM_BACKEND=token-factory. Default model `Gemma-4-31B-IT` (case-sensitive) in both modes; is_amd true; UI label "Gemma 4 31B · AMD Token Factory" (`frontend/src/components/compute.ts`); `/api/system/gpu` is null unless CLARIO_GPU_METRICS_URL is set.
- The gateway rejects `n > 1` with 400 ("does not support the n parameter"): `LLM.samples` sends n separate requests (and learns this from the 400 on any server, without dropping the JSON schema mode). `json_schema` works; `guided_json` is ignored; `thinking`/`reasoning.enabled` are rejected, never send them.
- Lab import (T4): `LLM_OCR_MODEL` (default `MinerU2.5-Pro` on Token Factory) -> `POST /v1/ocr` with the page JPEG as a data URL -> markdown. `CLARIO_DOC_STRUCTURE=table` (default): a recognised result table is read in code (`documents.parse_table`), 1 request per page; else, or `=model`, `Gemma-4-31B-IT` (text, pseudonymised) structures it, 2 requests per page and slow (80 to 220 s per page measured on 17 Oct). `LLM.ocr()` (+ `PrivacyLLM.ocr` logs it, `OfflineLLM.ocr` renders the truth sidecar). CLARIO_DOC_SAMPLES defaults to 1 on Token Factory. Rows not found in the OCR text go to `needs_review`; collection date read from the OCR text in code (the pseudonymiser hides it). OCR failure falls back to the image path (`LLM_VISION_MODEL`). A PDF data URL also works on /ocr (`document_url`), unused because pages are read in parallel.
- Shared team key: 20 RPM, 8 in flight, $1/day per user (`x-ratelimit-*` headers). LLM_CONCURRENCY defaults to 4 (cap 8) and every HTTP request takes a slot; 429 retried after Retry-After (wait > 60 s fails fast). One patient entry costs about 6 to 9 requests at CLARIO_SC_N=5.
## Dictation (issue #13)
- Mic on Today (`frontend/src/patient/dictation/`): Whisper `onnx-community/whisper-base` (q8 encoder + q8 merged decoder, about 77 MB, browser cache) via `@huggingface/transformers` 4.3.0 in a module Web Worker; language = UI language. Audio stays in the worker; network is only huggingface.co (model) and cdn.jsdelivr.net (onnxruntime wasm). The 27 MB ort wasm in dist/ is emitted by Vite but unused (runtime loads it from jsDelivr).
- `core.ts` is shared by the worker and the opt-in headless test: `DICTATION_WAV_EN=x.wav DICTATION_WAV_IT=y.wav npx vitest run src/test/dictation.headless.test.ts` (downloads the model; skipped otherwise). Component tests mock `engine.ts`.
## Onboarding tour (issue #14, v2)
- "?" in both headers opens `components/Tour.tsx` (never on load). driver.js 1.8.0 (pinned) runs steps, keys (arrows, Esc), scrolling and the popover; `tour.css` restyles it. Blur = our own fixed layer (`.clario-tour-blur`, backdrop-filter) whose `clip-path: path(evenodd, ...)` hole and the glow ring follow driver's `__activeStagePosition` every frame.
- Steps drive the app: each has `route` + `target` (`data-tour` value) + optional `ready` selector; Back re-navigates; closing returns to the start route. Missing target = centred card, still blurred. The card is docked (bottom right, 24px margin; bottom sheet under 640px), no arrow, one height (tallest step, measured), contents crossfade; `tour.css` overrides driver's inline placement with !important. Each target is scrolled into the area not covered by the card; targets taller than that get a hidden proxy box over their top part (`is-clamped` fade). Sticky bars are marked `data-tour-inset="top|bottom"`.
- Clinic tour is built at open from `api.inbox()` (`clinicTour(id)`): first package, brief via `/p/:id?pane=brief`; empty inbox = one step (`tour.c0.*`). Copy: `tour.*`; patients never see condition names.
## App identity (issue #18)
- `App.tsx` sets `<html data-app="patient|clinic">` from health (`components/AppIdentity.tsx`, `useAppIdentity`): favicon `/favicon-<role>.svg` (frontend/public), tab title "Clario Patient|Clinic" (IT Paziente|Clinica), theme-color. Patient = teal on warm paper (`:root` defaults), clinic = indigo on cool paper (`:root[data-app="clinic"]`, light and dark) in `index.css`; derived `--app-tint`, `--app-edge`, `--app-badge`. All accents pass AA on panel, paper, tint and badge. The tour reads `--accent`, so it follows the app.
- Headers use `.app-header` + `<AppMark role>` ("Clario · Patient" badge); on phones the dot and badge icon hide so the patient header fits 390px.
## Token Factory numbers (T6)
- Eval on the gateway: `eval/extraction_eval.py ... --sc-n 5 --json-schema --rpm 18 --max-inflight 6 --cache-dir eval/.cache/<run> --shuffle-seed S --limit N`. `n > 1` falls back to n separate requests (as the app); 429 waits for Retry-After (12 tries); raw answers per row are cached in the git-ignored `eval/.cache/`, so a rerun resumes and a rescore is free. `--shuffle-seed` + `--limit` = random subsample, recorded as `subsample` in the result; `usage` holds requests and tokens per note.
- Correctness for the review threshold: `eval/conformal.py --correct resolved` / `eval/review_curve.py --correct resolved` score `correct_resolved` (HPO id after the app's resolver, what the app stores minus the pick); `raw` (default) is the model's own id, which Gemma 31B almost never gets exactly right.
- Bench: `bench/bench.py --workload tf` (extract, brief, extract_sc, plus `app` = the real `clario.extract.extract` at --sc-n and 1, counting requests per note; run with backend/.venv/bin/python). Hosted results carry `CLARIO_HARDWARE` = "AMD Token Factory (hosted API; GPU not disclosed, not our own GPU)"; never present them as our GPU.
- Gateway behaviour seen 2026-10-17: about 18 s even for a 5-token reply (queueing), and 429 `token_concurrency_rate_limit_exceeded` (no Retry-After) at 6 in flight. Plan about 8 to 10 requests per minute in practice, not 20.
