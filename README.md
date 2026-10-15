# Clario

A private symptom diary for people on a long road to a diagnosis, and a review console for the clinic that receives them.

Clario turns everyday notes ("my knuckles are stiff when I wake up") into clinical terms with a quoted source, asks the patient to confirm each one, and lets the patient send a clinic a sealed, expiring, patient-approved dossier before the visit. The clinic opens it on its own AMD Instinct MI300X server, where Gemma 4 31B on vLLM drafts a one-page brief. A clinician accepts, edits or rejects every AI-written line before the brief is final. Clario organises information. It does not diagnose and it gives no treatment advice.

Built for the lablab.ai AMD Developer Hackathon ACT III, Track 2 (Health and Wellbeing). Team: **Revived**.

> Demo servers hold synthetic patients only. Do not enter real health information.

## The problem

People with rare or hard-to-name conditions wait years for an answer, and the weeks before the first specialist visit are the least documented part of the journey. Patients recall the last few days well and the last few months poorly. Clinics get a 15-minute slot and a pile of paper.

The EURORDIS Rare Barometer survey of 6,507 people living with a rare disease in 41 European countries puts the average time to diagnosis at 4.7 years, of which about 4.3 years pass between first medical contact and confirmed diagnosis ([Eur J Hum Genet 2024](https://www.nature.com/articles/s41431-024-01604-z)). Clario targets one slice of that: the months of capture before the visit, and the first 15 minutes of the visit itself.

## Demo

| Slot | File | Shows |
|---|---|---|
| GIF 1 | `docs/media/patient-flow.gif` (TODO: record) | Write a note, confirm terms, review queue |
| GIF 2 | `docs/media/share-and-clinic.gif` (TODO: record) | Share sealed to the clinic, open on the clinic console, brief with accept and reject |
| GIF 3 | `docs/media/amd-import.gif` (TODO: record) | Lab PDF import with pages per second and the live MI300X chip |
| Screenshot | `docs/media/cover.png` (TODO: capture) | Cover image, brief in `docs/SUBMISSION.md` |
| Live app | `{{APP_URL_PATIENT}}` and `{{APP_URL_CLINIC}}` | Filled after `deploy/amd/bootstrap.sh --app` prints the URLs |

## Runs on AMD

```
 Patient device (laptop / Ryzen AI PC)              Clinic server (one AMD Instinct MI300X, 192 GB)
 ┌────────────────────────────────────┐             ┌──────────────────────────────────────────────┐
 │ React app + FastAPI (patient mode) │             │ React console + FastAPI (clinic mode)        │
 │ encrypted vault (Argon2id+AES-GCM) │  sealed box │ inbox of sealed packages (X25519)            │
 │ extraction, HPO guardrails         │ ──────────► │ brief draft ── vLLM ROCm ── Gemma 4 31B      │
 │ pattern engine, review queue       │  expiring   │ vision lab import ── vLLM ── Gemma 4 E4B     │
 │ model calls pseudonymised          │             │ GPU telemetry (amd-smi) shown in the UI      │
 └────────────────────────────────────┘             └──────────────────────────────────────────────┘
        one OpenAI-compatible client everywhere: Ollama, Lemonade (Ryzen AI), vLLM on ROCm
```

What runs on the MI300X (see `deploy/amd/README.md`, all of it one command, `deploy/amd/bootstrap.sh`):

| Workload | Model | Where in the repo |
|---|---|---|
| Clinician brief and pattern re-check | Gemma 4 31B on vLLM (ROCm) | `backend/clario/brief.py`, `deploy/amd/docker-compose.yml` (`vllm-big`) |
| Patient extraction in the public demo | Gemma 4 E4B, optional LoRA adapter, vLLM | `deploy/amd/docker-compose.yml` (`vllm-small`), `PATIENT_LLM_MODEL` |
| Lab report import, many pages in parallel | Gemma 4 vision through the same endpoint | `backend/clario/documents.py`, `backend/clario/doc_routes.py` |
| Synthetic training data generation | Gemma 4 31B on vLLM | `train/synth.py`, `bootstrap.sh --synth N` |
| LoRA fine-tuning of the extractor | Gemma 4 E4B, PEFT + TRL on ROCm | `train/train_rocm.py`, `train/Dockerfile.rocm`, `bootstrap.sh --train` |
| Throughput and latency benchmark | Gemma 4 31B | `bench/bench.py`, `bootstrap.sh --bench` |

Visible in the demo: the clinic header shows "AMD Instinct MI300X · vLLM" when the backend is AMD, brief drafting streams tokens per second and latency, and the lab import page shows pages per second next to a live GPU chip fed by `GET /api/system/gpu` (`backend/clario/gpu.py`, reads `amd-smi`).

Status of the AMD claims: the compose stack, scripts and app image were validated off-box. Results from a real MI300X run are listed in "Measured results" and stay empty until that run is done.

## How we handle safety

The five Track 2 items, each mapped to a mechanism in code.

| Track 2 item | Mechanism | Where |
|---|---|---|
| Incorrect or unsupported answers | Every extracted term must quote a span that exists in the entry, or it is dropped. HPO ids come from ontology candidates only and must match the words, or the id is dropped. Brief items must cite entries inside the shared package. Pattern scores are computed in code from HPO annotations (close matches only, three specific terms for a card). The patient text is a template; the model drafts brief lines only for the clinician | `backend/clario/extract.py`, `backend/clario/knowledge.py`, `backend/clario/patterns.py`, `backend/clario/brief.py` |
| Sensitive data | Vault encrypted with Argon2id + AES-256-GCM, no recovery by design. Direct identifiers (email, phone, codice fiscale, IBAN, dates, addresses, first names) are replaced before any remote model call. Every model call is written to a hash-chained log the patient can verify. A share contains only confirmed terms and entries in a chosen period, sealed to the clinic's X25519 key, and expires. Clinic model runs on the clinic's own server | `backend/clario/vault.py`, `backend/clario/privacy.py`, `backend/clario/share.py` |
| Uncertain results | Confidence from self-consistency across samples. Anything under the threshold (default 0.7) goes to a review queue and counts for nothing until a person decides. Patterns show weak, moderate or strong with evidence counts (notes) and a "not recorded yet" list, never a percentage. Condition names are clinician-only: the patient sees at most two cards titled by the features they recorded, in everyday words, and no API response to the patient carries a condition name | `backend/clario/review.py`, `backend/clario/extract.py`, `backend/clario/patterns.py` |
| High-risk decisions | Emergency descriptions (chest pain with warning signs, trouble breathing, stroke signs, self-harm, heavy bleeding, long seizure, fainting with injury) get an immediate notice with the emergency number before anything else. A hedge validator rejects AI text with diagnostic or prescriptive language (doses, "you have", "confirms", percentages) and falls back to a template. Next-question suggestions never name a condition or medicine | `backend/clario/safety.py`, `backend/clario/next_question.py` |
| Human review | The patient confirms terms before they count. The clinician must accept, edit or reject every AI-drafted brief item. Finalize returns 409 while any item is pending. The printed brief says "AI-drafted items reviewed by the clinician" and the markdown export contains accepted and edited items only. Items never seen by a person are marked "not reviewed by a person" | `backend/clario/review.py`, `backend/clario/brief.py`, `frontend/src/clinic/BriefPanel.tsx` |

More: `docs/COMPLIANCE.md`.

## The model and the data

**Task.** Plain-language diary text to structured entities (`backend/clario/schemas/extraction_v3.json`, frozen): symptom span, HPO id, negation, family history, onset, severity, optional confidence.

**Why no public dataset fits.** We reviewed the candidate corpora (`docs/DATA_SOURCES.md`). None combines lay language, span-level symptoms, negation and HPO ids. The lay corpora that can be redistributed are small or carry other label sets, the largest well-known one (CADEC) forbids redistribution, we found no Italian lay symptom corpus, and clinical corpora (n2c2, MIMIC) cannot be shared or sent to a third-party API.

**Our data.** `train/synth.py` writes diary entries whose labels come from the ontology by construction: HPO terms and the `phenotype.hpoa` annotations, with layperson phrasings (`train/lay_terms.json`), English and Italian, family history, onset and severity cues, life-event distractors and hard negatives. Code validates every row and reports reject reasons. Generation runs on Gemma 4 31B on the MI300X. The generator refuses Anthropic endpoints, and Claude output never becomes a training target. `train/prep.py` splits by source disease so no disease appears in more than one of train, validation and test.

**Eval sets.**

| Set | What it is | Source |
|---|---|---|
| Held-out synthetic test | Disease-disjoint split of the generated data | `train/prep.py`, `data/v3/test.jsonl` |
| Reviewed gold | Hand-reviewed English and Italian entries, drafted by Claude Haiku and accepted or fixed by a person | `train/gold_draft.py`, `eval/gold/review.html` |
| PsyTAR mapped to HPO | Real lay text, lexical mapping, precision is a lower bound | `train/psytar_hpo.py` (CC BY 4.0, optional) |
| Lab documents | Synthetic Italian lab reports (PDF) with ground truth | `backend/scripts/make_referti.py`, `backend/scripts/eval_documents.py` |

Haiku is used for evaluation only: it drafts gold candidates for a person to review and acts as a comparison row. It never trains anything.

**Knowledge base shipped in the app.** 19,178 HPO terms and 12,820 annotated diseases (8,465 OMIM and 4,355 ORPHA entries from HPO `phenotype.hpoa`), compiled by `backend/scripts/build_knowledge.py` into `backend/clario/data/knowledge.json.gz`.

## Measured results

Nothing below is filled yet. Every cell comes from a result file written by a real run. Offline and dry-run files exist in `eval/results/` and are labelled as such. They check the scorer and are not results.

Extraction, held-out synthetic test split. Source file per row: `eval/results/extraction_<label>.json`. Rendered by `python eval/make_results_md.py` into `eval/RESULTS.md`.

| Model | Entity F1 | HPO-ID accuracy | Grounding | JSON valid | p50 / p95 latency (s) | n | Source file |
|---|---|---|---|---|---|---|---|
| Gemma 4 E4B base | `{{extraction.base-e4b.entity_f1}}` | `{{extraction.base-e4b.hpo_id_accuracy}}` | `{{extraction.base-e4b.quote_grounding_rate}}` | `{{extraction.base-e4b.json_validity_rate}}` | `{{extraction.base-e4b.latency_p50_s}}` / `{{extraction.base-e4b.latency_p95_s}}` | `{{extraction.base-e4b.n}}` | `extraction_base-e4b.json` |
| Gemma 4 E4B + LoRA r16 | `{{extraction.ft-e4b-r16.entity_f1}}` | `{{extraction.ft-e4b-r16.hpo_id_accuracy}}` | `{{extraction.ft-e4b-r16.quote_grounding_rate}}` | `{{extraction.ft-e4b-r16.json_validity_rate}}` | `{{extraction.ft-e4b-r16.latency_p50_s}}` / `{{extraction.ft-e4b-r16.latency_p95_s}}` | `{{extraction.ft-e4b-r16.n}}` | `extraction_ft-e4b-r16.json` |
| Claude Haiku (comparison only) | `{{extraction.haiku-test.entity_f1}}` | `{{extraction.haiku-test.hpo_id_accuracy}}` | `{{extraction.haiku-test.quote_grounding_rate}}` | `{{extraction.haiku-test.json_validity_rate}}` | `{{extraction.haiku-test.latency_p50_s}}` / `{{extraction.haiku-test.latency_p95_s}}` | `{{extraction.haiku-test.n}}` | `extraction_haiku-test.json` |

Repeat the table for the reviewed gold set (`--dataset gold-reviewed`) and PsyTAR (`--dataset psytar-hpo`) once those files exist.

Review queue: share of entities routed to review so that the auto-accepted rest stays within 1, 2 and 5 percent error: `{{review_curve.tolerances.1pct.entity.review_share}}`, `{{review_curve.tolerances.2pct.entity.review_share}}`, `{{review_curve.tolerances.5pct.entity.review_share}}` from `eval/results/review_curve_<label>.json`. This is a routing share, not accuracy or coverage, and it uses the confidence the model reports about itself (a run with `--confidence`); the file says so in `confidence_source`.

Throughput on the MI300X, Gemma 4 31B on vLLM. Source: `eval/results/bench_amd-mi300x-gemma4-31b.json` (fields n, dataset, model, backend, date, `results[]` with workload, concurrency, req_per_s, out_tok_per_s, p50_s, p95_s); the full run stays in `bench/results/`.

| Workload | Concurrency | Requests/s | Output tokens/s | p50 / p95 latency (s) |
|---|---|---|---|---|
| extract | 1 | `{{bench.extract.c1.req_per_s}}` | `{{bench.extract.c1.out_tok_per_s}}` | `{{bench.extract.c1.p50_s}}` / `{{bench.extract.c1.p95_s}}` |
| extract | 32 | `{{bench.extract.c32.req_per_s}}` | `{{bench.extract.c32.out_tok_per_s}}` | `{{bench.extract.c32.p50_s}}` / `{{bench.extract.c32.p95_s}}` |
| brief | 1 | `{{bench.brief.c1.req_per_s}}` | `{{bench.brief.c1.out_tok_per_s}}` | `{{bench.brief.c1.p50_s}}` / `{{bench.brief.c1.p95_s}}` |
| brief | 32 | `{{bench.brief.c32.req_per_s}}` | `{{bench.brief.c32.out_tok_per_s}}` | `{{bench.brief.c32.p50_s}}` / `{{bench.brief.c32.p95_s}}` |

Training on the MI300X: wall time `{{train.e4b-r16.train_wall_s}}`, tokens/s `{{train.e4b-r16.tokens_per_s_est}}`, peak memory GB `{{train.e4b-r16.peak_mem_gb}}`, from `eval/results/train_e4b-r16.json` (fields n, dataset, model, backend, date, train_wall_s, tokens_per_s_est, peak_mem_gb; a copy of `train/out/e4b-r16/metrics.json`).

Lab import: pages per second on the MI300X `{{documents.pages_per_sec}}`, from the lab import run output of `backend/scripts/eval_documents.py` once saved to `eval/results/`.

## Run it

**Offline, two commands, no GPU and no model download.** Deterministic fixtures stand in for the model so every screen works.

```bash
cd backend && uv sync && cd ../frontend && npm install && npm run build && cd ..
CLARIO_MODE=patient CLARIO_OFFLINE=1 uv --directory backend run python -m clario.app   # http://127.0.0.1:8765
```

For the clinic side, in a second terminal: `CLARIO_MODE=clinic CLARIO_OFFLINE=1 uv --directory backend run python -m clario.app` (http://127.0.0.1:8800). Open the patient app, set a passphrase of 12 or more characters, and load the demo patient. Offline output is for testing the product flow. It is not a model result.

**Tests.** `cd backend && uv run pytest -q`, `cd frontend && npx vitest run`, `cd train && ../backend/.venv/bin/python -m pytest -q`.

**On AMD Developer Cloud (one MI300X droplet).**

```bash
ssh root@<DROPLET_IP>
git clone <this repo> clario && cd clario
export HF_TOKEN=hf_...                      # accept the Gemma license on Hugging Face first
deploy/amd/bootstrap.sh --synth 3000 --train --eval --bench --app
```

Stages are flags and re-runs skip finished ones. `--app` alone starts the public stack: patient app at `https://<ip>.sslip.io`, clinic console at `https://clinic.<ip>.sslip.io`. Keys live in the environment (see `.env.example`), never in git. Full runbook, cost estimate and shut-down checklist: `deploy/amd/README.md`.

## Deploy

| Item | File |
|---|---|
| Containerised app image | `Dockerfile` (`docker build -t clario-app .`) |
| MI300X stack: two vLLM servers, GPU metrics sidecar, clinic, patient demo, Caddy HTTPS | `deploy/amd/docker-compose.yml`, `deploy/amd/Caddyfile` |
| Clinic-only stack, single model | `deploy/docker-compose.clinic.yml` |
| Reaching vLLM without public exposure | `deploy/amd/tunnel.md` |
| Every environment variable | `.env.example` |

vLLM never gets a public port. The demo instances set `CLARIO_DEMO_INSTANCE=1`, which shows the synthetic-data banner in both apps.

## Licences and attribution

| Component | Licence and notes |
|---|---|
| This repository | `{{REPO_LICENCE}}` (decide before publishing) |
| Human Phenotype Ontology (hp.json, phenotype.hpoa) | HPO licence: use with citation and version, no alteration of the files. The app ships a derived index (`backend/clario/data/knowledge.json.gz`) built from a pinned release. Cite: Gargano et al., The Human Phenotype Ontology in 2024, Nucleic Acids Res. https://hpo.jax.org |
| Orphanet annotations (ORPHA entries inside phenotype.hpoa) and OMIM annotations | Reached through the HPO annotation file. Orphanet is credited as a source of rare disease data ( https://www.orpha.net ). OMIM is a trademark of Johns Hopkins University ( https://omim.org ). No OMIM full text is included |
| Gemma 4 | Used under the licence printed on each model card (the 26B-A4B card lists Apache 2.0; TODO verify the 31B and E4B cards before publishing). Model ids `google/gemma-4-31B-it`, `google/gemma-4-E4B-it`. Weights are downloaded by the user with their own Hugging Face acceptance and are not in this repository. LoRA adapters derived from Gemma carry the Gemma terms |
| PsyTAR (only if used for the real-text eval) | CC BY 4.0. Zolnoori M, Fung KW, Patrick TB, et al. A systematic approach for developing a corpus of patient reported adverse drug events. J Biomed Inform 90 (2019). doi:10.1016/j.jbi.2018.12.005. Source: https://www.askapatient.com/research/pharmacovigilance/corpus-ades-psychiatric-medications.asp |
| Third-party libraries | Their own licences, see `backend/pyproject.toml` and `frontend/package.json` |

Per-dataset licence verdicts and the reasoning for what was left out: `docs/DATA_SOURCES.md` (an engineering reading, not legal advice).

## Documents

`docs/PLAN.md` (plan), `docs/API.md` (contract), `docs/COMPLIANCE.md`, `docs/SUBMISSION.md`, `docs/PITCH.md`, `docs/VIDEO_SCRIPT.md`, `train/README.md`, `bench/README.md`, `eval/RESULTS.md`.

## Team

Revived.
