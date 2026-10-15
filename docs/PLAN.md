# Clario — plan (AMD Developer Hackathon ACT III, Track 2: Health and Wellbeing)

## One line
A private symptom diary for people on a long diagnostic journey. It turns everyday notes into
clinical terms with evidence, and lets a clinic review the full picture on its own AMD server.

## Track 2 rules, and how we meet them
| Rule | How |
|---|---|
| Improve one part of the patient journey | The months before diagnosis: capture, then a 15-minute visit that starts from the full picture |
| No autonomous diagnosis or treatment advice | Pattern signals only ("resembles", "consider discussing"), checked by a hedge validator in code; red-flag and dosing questions are intercepted before any model call |
| Sensitive data | Patient data encrypted at rest on the patient's device (Argon2id + AES-GCM). Sharing is per-visit, patient-selected, sealed to the clinic's public key, expiring. The clinic model runs on the clinic's own AMD server, never a third-party API |
| Uncertainty | Signal levels (weak/moderate/strong) from a deterministic score and the lead over the next condition (cut-offs calibrated on simulated patients, `eval/results/pattern_calibration.json`), evidence counts, "what is missing", no percentages |
| Human review | Patient confirms extracted terms; clinician accepts or rejects each AI-suggested item before the brief is final; nothing AI-written reaches the brief unreviewed |

## Architecture
```
Patient device (laptop / Ryzen AI PC)          Clinic server (AMD Instinct MI300X)
  React PWA                                       React clinician console
  FastAPI "patient" mode :8765                    FastAPI "clinic" mode :8800
   ├─ encrypted store (SQLite + AES-GCM)           ├─ share inbox (sealed boxes)
   ├─ extraction  ─► small Gemma (Ollama / Ryzen)  ├─ review queue (accept / reject)
   ├─ HPO guardrails (evidence + ontology)         ├─ brief draft ─► Gemma 4 31B on vLLM
   ├─ pattern engine (HPO IC overlap, Orphanet)    └─ pattern re-check with the larger model
   └─ share: select ► seal ► send / QR
Both talk to ONE OpenAI-compatible client: Ollama, vLLM on ROCm, Lemonade (Ryzen AI).
```

## Three AMD pieces
1. **Retrain on MI300X**: LoRA fine-tune of Gemma 4 (26B-A4B or 31B) for diary → HPO extraction with ROCm (PEFT + TRL). `train/` holds data prep, training, and an eval harness that scores any OpenAI-compatible endpoint (entity F1, HPO-ID accuracy) on a held-out split.
2. **Clinic server on AMD**: Gemma 4 31B on vLLM, MI300X. Drafts the clinician brief and re-checks patterns over shared data. Throughput and latency measured by `bench/`.
3. **Any backend via one API**: the same app runs against Ollama on a laptop, Lemonade on a Ryzen AI PC, or vLLM on Instinct.

## Deterministic guardrails (code, not prompt)
- Every extracted term must quote a verbatim span from the entry.
- HPO IDs must exist in the shipped ontology; label/synonym must match the quoted span's meaning bucket, else the ID is dropped and the term flagged.
- Pattern score = information-content-weighted overlap of the patient's confirmed HPO set with each disease's annotated phenotypes (HPO `phenotype.hpoa`). The patient sees a template note that names no condition; the LLM drafts hedged brief lines for the clinician only, citing entry ids.
- Hedge validator rejects any rationale with diagnostic or prescriptive language; falls back to a template.
- Red-flag interceptor: emergency symptoms and dosing/medication-change questions never reach a model.

## Demo (3 minutes)
Patient "Giulia" writes a few weeks of notes in plain words, confirms terms, sees moderate signals with evidence, shares the last 8 weeks with her clinic for Thursday. The clinician opens the package on the AMD clinic server, Gemma 4 31B drafts the brief, the clinician accepts and rejects items, prints a one-page brief. Compute panel shows MI300X throughput.
