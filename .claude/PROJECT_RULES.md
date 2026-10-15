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
- Clario here is a NEW, standalone project. Never reference, link, import from or mention any earlier diary project, its repo, its HF dataset or a Kaggle entry, in code, docs, commits or pitch. Git history was squashed clean on 2026-10-15.
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
- `Entity.review` (auto|needs_review|confirmed|corrected|rejected) is the single state field. Patterns and shares count `confirmed`/`corrected` only (`models.COUNTED`), never negated, family_history, needs_review or rejected.
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
- Labs are review kind `lab` (registered in `doc_routes.py`). Dosing and medicine-change questions are intercepted in `safety.check_entry` (level `advice`, entry saved with `extraction=done`, no model call).
- Clinic mode never writes diary text in clear: inbox is sealed, briefs and call-log previews are AES-GCM under a key derived from `clinic.key`.
- i18n: frontend `src/i18n/{en,it}.ts` (typed, `it` must have every `en` key), `useT()`; `hpo.it.ts` equals `backend/clario/data/hpo_it.json` (test). Patient-facing server text takes `lang=en|it` (`clario/i18n.py`). Italian next questions need an entry in `data/lay_terms_it.json`; add HPO ids there and in both hpo_it tables together.
- Personas: `giulia`, `giulia_it` (`demo.py`); `POST /api/demo/documents` imports the 3 shipped referti.
- Tooling quirks (worktree shells): use `/usr/bin/git -C <worktree>`, no heredocs with git, no word "eval" in a command line; write scripts to the scratchpad and run them.
- One sqlite connection serves the thread pool: every Vault read and write takes `_lock` (a race gave HTTP 500 on GET /api/entries).
