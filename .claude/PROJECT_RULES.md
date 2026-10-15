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

## ML lane (train/, eval/) must-knows
- Claude/Haiku output never becomes a training target. `synth.py` refuses anthropic.com; Haiku only drafts gold for human review (`train/gold_draft.py`) and acts as an eval comparator.
- Targets are extraction_v3 (`confidence` null in training data). `prompt.py` is the single prompt source; `prep.check_sft` refuses old-format chat files.
- `eval/results/extraction_*.json` must carry n, dataset, model, backend, date. Dry-run and offline files are labelled (`dry_run: true`) and rendered apart by `eval/make_results_md.py`.
- PsyTAR is only available through a store page that returns 403 to scripts: download in a browser, then run `train/psytar_hpo.py`.
- Run train tests from `train/` with `../backend/.venv/bin/python -m pytest -q`.
