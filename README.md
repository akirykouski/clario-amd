# Clario

A private symptom diary for people on a long road to a diagnosis, and a review console for the clinic that receives them.

Clario turns everyday notes ("my knuckles are stiff when I wake up") into clinical terms with a quoted source, shows the patient what it understood so they can say "not right", and lets the patient send a clinic a sealed, expiring dossier before the visit. A fine-tuned Gemma 4 E4B reads the diary. At the clinic, Gemma 4 31B on AMD Token Factory drafts a one-page brief from pseudonymised input. The draft opens as a PDF marked "AI draft, not reviewed"; the clinician edits it as plain text and signs it before it is used.

Clario organises information. It does not diagnose and gives no treatment advice. A clinician edits and signs every brief. Our position is that this scope is outside the EU Medical Device Regulation, pending a regulatory assessment (`docs/COMPLIANCE.md`; not legal advice).

Built for the lablab.ai AMD Developer Hackathon ACT III, Track 2 (Health and Wellbeing). Team: **Revived**.

> Demo servers hold synthetic patients only. Do not enter real health information.

**For judges, in one minute**

- **Try it:** [patient app](https://se4wer--clario-patient.us-east.modal.run) ("Open the demo diary", no passphrase) and [clinic console](https://se4wer--clario-clinic.us-east.modal.run), both live with synthetic patients.
- **On AMD:** Gemma 4 31B on AMD Token Factory wrote our 2,992-diary training set, reads lab reports (MinerU, 48 of 48 rows) and drafts the clinician brief. Our fine-tuned Gemma 4 E4B runs offline on an AMD Ryzen CPU. Details: [Where the models run](#where-the-models-run).
- **Key result:** on the same 100 held-out test diaries, our 4B model scores F1 0.693 (0.644 as a 5.3 GB GGUF on a Ryzen CPU) against 0.471 for Gemma 4 31B and 0.356 before fine-tuning. Synthetic test set; on real patient text (PsyTAR) the gain does not transfer yet, and we report that too. Every number links to a file in `eval/results/`.
- **Safety:** every term quotes the patient's words, the brief is watermarked "AI draft, not reviewed" until a named clinician edits and signs it, and the product never names a condition to the patient.

## The problem

People with rare or hard-to-name conditions wait years for an answer, and the weeks before the first specialist visit are the least documented part of the journey. Patients recall the last few days well and the last few months poorly. Clinics get a 15-minute slot and a pile of paper.

The EURORDIS Rare Barometer survey of 6,507 people living with a rare disease in 41 European countries puts the average time to diagnosis at 4.7 years, of which about 4.3 years pass between first medical contact and confirmed diagnosis ([Eur J Hum Genet 2024](https://www.nature.com/articles/s41431-024-01604-z)). Clario targets one slice of that: the months of capture before the visit, and the first 15 minutes of the visit itself.

## Demo

![Clario: the patient app's week organizer and a note with its understood terms](docs/media/cover/cover.png)

| What | Where | Shows |
|---|---|---|
| Patient app (live) | [se4wer--clario-patient.us-east.modal.run](https://se4wer--clario-patient.us-east.modal.run) | "Demo data (synthetic)" loads Giulia; write a note, see the terms with their quotes, fix one with "Not right", share sealed to the clinic |
| Clinic console (live) | [se4wer--clario-clinic.us-east.modal.run](https://se4wer--clario-clinic.us-east.modal.run) | Inbox, two lab readings to check, brief PDF marked "AI draft, not reviewed", edit and sign, second opinion |
| Project page | [akirykouski.github.io/clario-amd](https://akirykouski.github.io/clario-amd) | Overview and the results table |
| Clip: the brief, from AI draft to signed (17 s) | [`docs/media/video/brief-review.mp4`](docs/media/video/brief-review.mp4) | Draft watermark, every line cites a diary note, code flags an unsupported line, the doctor edits and signs |
| Clip: under the hood (45 s) | [`docs/media/video/under-the-hood.mp4`](docs/media/video/under-the-hood.mp4) | Gemma 4 end to end, the 2,992-diary dataset, the fine-tune and its F1 against Gemma 4 31B |

Both live apps hold synthetic patients only. The cold start on Modal can take up to a minute.

The clinic console with a received package, as it runs live (captured 18 Oct 2026). Left: the patient at a glance, with what was already tried. Right: the brief Gemma 4 31B drafted on AMD Token Factory, marked "AI draft, not reviewed", with its tokens/s and latency:

![Clinic console: a received package and its AI-drafted brief](docs/media/screens/clinic-package.png)

[![The brief, from AI draft to signed](docs/media/video/brief-review.jpg)](docs/media/video/brief-review.mp4)

## What it does

Patient app:
- **Diary to terms.** Each note becomes clinical terms (HPO) with the patient's own words quoted. Every term counts unless the patient taps "Not right". Terms the model was unsure about are marked and travel marked to the clinician.
- **Past events.** "I had knee surgery 5 years ago" is stored as past history with an approximate date, not as today's symptom. Past terms are shared but never counted as current (`backend/clario/past.py`).
- **Lab reports.** PDFs or photos are read by OCR and checked in code. A reading that fails a check waits for the clinician.
- **Share.** The patient picks a period and sends a sealed, expiring package to the clinic. "Get a second opinion" sends it to a new doctor without the previous doctor's conclusions.

Clinic console:
- **OCR value check.** Every lab reading is checked in code against the PDF text layer, the OCR text, a plausible range per test and unit, the printed range and flag. A reading that fails goes to "items need your check" with the reason and a crop of its printed row. The clinician confirms, rejects or corrects it (value and unit as printed). Such a reading feeds the differential only after that (`backend/clario/documents.py`, issue #19).
- **Specialty.** A simple selector (general practice, rheumatology, nephrology) reorders the brief and hides lines of other specialties. It is set in code from the HPO organ system, with no model call (`backend/clario/specialty.py`).
- **Brief as a PDF.** "Generate brief" drafts a one-page PDF watermarked "AI draft, not reviewed". "Edit and sign" opens it as cards, one per section: edit a line in place, remove it (with undo) or add one; labs are a read-only table; the citation check and the hedge validator flag the line they concern, and a flagged line is edited, removed or kept anyway before Sign. The demo patient's draft was generated live once and opens at once ("precomputed" in the chips, "Regenerate live" calls the model). Only the signed PDF carries "Reviewed and signed by", the date, the model and where it ran (`backend/clario/brief.py`, `backend/clario/brief_pdf.py`).
- **Second opinion.** The package is split in code into facts (diary, quotes, labs, what was already tried and with what effect, what was already tested) and conclusions (the previous doctor's diagnosis and notes). The new doctor sees only the facts. After signing their own brief, "Compare with the previous opinion" shows both side by side, with disagreements marked (`backend/clario/second_opinion.py`).

Demo: "Demo data (synthetic)" loads Giulia, a synthetic patient, and "Import the 3 sample referti" adds her lab reports. Loading the demo again replaces it instead of duplicating it.

## Where the models run

```
 Patient app (FastAPI + React, patient mode)          Clinic console (FastAPI + React, clinic mode)
 encrypted vault, HPO checks, patterns                inbox of sealed packages (X25519)
 pseudonymiser before any remote call   ── sealed ──► pseudonymiser before any remote call
        │                                 expiring          │
        ├─ diary extraction: fine-tuned Gemma 4 E4B         ├─ brief: Gemma 4 31B, AMD Token Factory
        │  on the patient's own AMD Ryzen (llama.cpp,       │
        │  offline), or vLLM on Modal for the public demo   │
        └─ lab OCR: MinerU2.5-Pro, AMD Token Factory        └─ one OpenAI-compatible client everywhere
```

**Every inference workload in Clario has run on AMD hardware, and each one has a result file:**

| Workload | Model | AMD platform | Evidence |
|---|---|---|---|
| Training data generation | Gemma 4 31B IT | AMD Token Factory | Published set [m0rtyddd/clario-synth-v3](https://huggingface.co/datasets/m0rtyddd/clario-synth-v3) (2,992 diaries), `train/synth.py` |
| Lab report OCR | MinerU2.5-Pro, table read in code | AMD Token Factory | 48 of 48 rows, `eval/results/documents_tf-mineru-table.json` |
| Clinician brief, pseudonymised input | Gemma 4 31B IT | AMD Token Factory | `backend/clario/brief.py`, `eval/results/bench_tf-gemma4-31b.json` |
| Large-model benchmark | Gemma 4 31B IT, DeepSeek-V4-Flash | AMD Token Factory | `eval/results/extraction_tf-*.json` |
| **Patient diary extraction, offline** | **Our fine-tuned Gemma 4 E4B**, merged and quantised to GGUF Q4_K_M | **AMD Ryzen 7 7700**, llama.cpp CPU backend, no network | F1 0.644 after the HPO check on the same 100 test diaries (bf16 on vLLM: 0.693; Gemma 4 31B on Token Factory: 0.471), median 23 s per diary, `eval/results/extraction_ft-e4b-q4km-ryzen-test100.json`; server log, machine and GGUF hash in `eval/results/ryzen_run/` |

Token Factory does not report its GPUs, so those result files say "hardware not disclosed", and we do not claim a GPU model. On the event Discord, the organisers confirmed on 16 Oct that Token Factory is the expected way to build ("You don't need credit to participate in this hackathon. Just the api from the tokenfactory."), and an AMD mentor confirmed on 18 Oct that a GPU instance is not required ("you dont need the gpu instance").

**Why the patient model runs on a Ryzen.** The patient's diary is the most sensitive data in the product, so the model that reads it belongs on the patient's own computer, and that computer is a laptop or desktop, not an Instinct server. A 4-billion-parameter model that beats the 31-billion-parameter one is what makes this possible. We measured it on an ordinary 8-core AMD Ryzen 7 7700 desktop CPU with no GPU: quantised to 5.3 GB it still beats Gemma 4 31B on our task, and the result file records the machine. To run it yourself, see "Run the patient model on your own AMD machine" below.

**Not on AMD: training, and why.** The LoRA fine-tune of Gemma 4 E4B ran on a Modal NVIDIA L40S, and the public demo serves the bf16 fine-tune with vLLM on a Modal NVIDIA L4, because we had no AMD GPU to train on. The same training script (`train/train_rocm.py`, `train/Dockerfile.rocm`) and a one-command MI300X runbook (`deploy/amd/bootstrap.sh`, `deploy/amd/README.md`) are ready and have not run on an MI300X.

<details>
<summary>AMD Developer Cloud access: what we tried</summary>

- We requested AMD Developer Cloud credits from three team accounts.
- We added funds to the AMD Developer Cloud console to rent a GPU droplet ourselves. Creating an MI300X droplet still asked us to "request complimentary credit or a limit increase", which we did.
- 16 Oct: we escalated on the event Discord (ticket and channel), more than 48 hours after the first request. The answer we got was that Token Factory is enough to take part (quoted above). Other teams reported the same access problem in the same channels.
- 17 Oct: at the on-site event we asked the mentors to escalate.
- As of 18 Oct we have no GPU droplet access. If access is granted before judging, `deploy/amd/bootstrap.sh --train --eval` reruns the fine-tune and the eval on an MI300X and writes the result files with `amd-smi` provenance.

</details>

## Roadmap

- Patient model on the patient's device: done on an AMD Ryzen CPU with llama.cpp (see "Where the models run"). Next: the Ryzen AI NPU through Lemonade, whose OpenAI-compatible API the app client already speaks; not yet tested on Ryzen AI hardware.
- Clinician brief on the clinic's own AMD Instinct servers, so the diary never leaves the clinic.
- OCR on our own server in production (open weights), because real reports carry personal data. The demo uses synthetic reports only.
- Fine-tuned Gemma 4 31B: trained, deployment pending (no serving resources during the hackathon).
- Second opinion: uploaded letters often carry the previous diagnosis. Stripping those sections from second-opinion shares is planned, not built.
- Second opinion: send the previous conclusions to the new doctor only after they sign, instead of holding them back on the clinic server.
- Specialties beyond the simple selector.

## How we handle safety

The five Track 2 items, each mapped to a mechanism in code.

| Track 2 item | Mechanism | Where |
|---|---|---|
| Incorrect or unsupported answers | Every extracted term must quote a span that exists in the entry, or it is dropped. HPO ids come from ontology candidates only and must match the words, or the id is dropped. Brief items must cite entries inside the shared package. Pattern scores are computed in code from HPO annotations (close matches only, three specific terms for a card). The patient text is a template; the model drafts brief lines only for the clinician | `backend/clario/extract.py`, `backend/clario/knowledge.py`, `backend/clario/patterns.py`, `backend/clario/brief.py` |
| Sensitive data | Vault encrypted with Argon2id + AES-256-GCM, no recovery by design. Direct identifiers are replaced by rules before any remote model call, with no model involved (see "Privacy: what leaves the device"). Every model call is written to a hash-chained log the patient can verify. A share contains only confirmed terms and entries in a chosen period, sealed to the clinic's X25519 key, and expires. The clinic's brief prompt is pseudonymised too, with dates turned into day numbers | `backend/clario/vault.py`, `backend/clario/privacy.py`, `backend/clario/share.py` |
| Uncertain results | Confidence from self-consistency across samples. Anything under the threshold (default 0.7) goes to a review queue and counts for nothing until a person decides. Patterns show weak, moderate or strong with evidence counts (notes) and a "not recorded yet" list. No percentage is shown. Condition names are clinician-only: the patient sees one card titled by the features they recorded, in everyday words, and no API response to the patient carries a condition name | `backend/clario/review.py`, `backend/clario/extract.py`, `backend/clario/patterns.py` |
| High-risk decisions | Emergency descriptions (chest pain with warning signs, trouble breathing, stroke signs, self-harm, heavy bleeding, long seizure, fainting with injury) get an immediate notice with the emergency number before anything else. A hedge validator rejects AI text with diagnostic or prescriptive language (doses, "you have", "confirms", percentages) and falls back to a template. Next-question suggestions never name a condition or medicine | `backend/clario/safety.py`, `backend/clario/next_question.py` |
| Human review | Every extracted term counts unless the patient rejects it; terms the model was unsure about are flagged for the clinician, who confirms or rejects them. Lab readings that fail a code check wait for the clinician to confirm, reject or correct them. The brief opens as a one-page PDF watermarked "AI draft, not reviewed". The clinician edits it line by line ("Edit and sign"), with the citation check and the hedge validator shown on the line they flag, and signs; only the signed PDF carries "Reviewed and signed by" with the clinician's name, the date, the model and where it ran. The markdown export holds the signed lines only. Only checked lab readings print, and signing waits for the rest. In a second opinion the previous doctor's conclusions stay hidden until the new doctor signs | `backend/clario/review.py`, `backend/clario/brief.py`, `backend/clario/second_opinion.py`, `frontend/src/clinic/BriefPanel.tsx` |

More: `docs/COMPLIANCE.md`.

## Privacy: what leaves the device

Before text reaches a remote model, Clario replaces direct identifiers with placeholders using rules and a first-name lexicon, with no model involved: emails, phone numbers, codice fiscale, tessera sanitaria and hospital record numbers, street addresses, full dates including dates of birth, and personal names recognised by title, label, relation, first-name list or "X said" pattern. Medical eponyms, doses, lab values, drug names and places of care are kept. On a synthetic English and Italian test set it misses 10.8% of identifiers when strictly held out, and 5.8% after fixes chosen by reading test failures (`eval/results/pii_leak.json`, test half, n = 712 identifiers in 850 documents); first names that open a sentence and are not in the lexicon are the largest gap. Scanned images and photos are sent unredacted; the preview shows the exact text the model receives. The clinic's brief prompt is pseudonymised the same way whenever its model is remote (AMD Token Factory), with diary dates turned into day numbers, and the brief PDF says "sent pseudonymised". Roadmap: run the brief on the clinic's own AMD Instinct servers, so the diary never leaves the clinic at all.

Caveat on that number: the corpus was written by the redactor's author, so it measures the formats and phrasings we thought of, and real diaries will leak more. The vocabulary and templates of the dev and test halves are disjoint and the redactor was tuned on the dev half, but a second round of generic fixes was chosen after reading test failures, so the 5.8% is optimistic; the strictly held-out 10.8% is the figure to quote. Hard negatives (medical eponyms, drugs, places of care, lab values, number phrases; n = 220) were redacted 0 times. Per category and per language rates are in the file.

## The model and the data

**Task.** Plain-language diary text to structured entities (`backend/clario/schemas/extraction_v3.json`, frozen): symptom span, HPO id, negation, family history, onset, severity, optional confidence.

**Why no public dataset fits.** We reviewed the candidate corpora (`docs/DATA_SOURCES.md`). None combines lay language, span-level symptoms, negation and HPO ids. The lay corpora that can be redistributed are small or carry other label sets, the largest well-known one (CADEC) forbids redistribution, we found no Italian lay symptom corpus, and clinical corpora (n2c2, MIMIC) cannot be shared or sent to a third-party API.

**Our data.** `train/synth.py` writes diary entries whose labels come from the ontology by construction: HPO terms and the `phenotype.hpoa` annotations, with layperson phrasings (`train/lay_terms.json`), English and Italian, family history, onset and severity cues, life-event distractors and hard negatives. Code validates every row and reports reject reasons. The generator refuses Anthropic endpoints, and Claude output never becomes a training target. `train/prep.py` splits by source disease so no disease appears in more than one of train, validation and test.

**Published dataset.** The v3 set generated this way is public on Hugging Face: [m0rtyddd/clario-synth-v3](https://huggingface.co/datasets/m0rtyddd/clario-synth-v3). It has 2,992 rows (train 2,392, validation 300, test 300) and the English lay lexicon. Gemma 4 31B IT wrote it through the AMD Token Factory API on 16 and 17 October 2026. The dataset card covers how it was built and its licences.

**Fine-tune.** LoRA on Gemma 4 E4B (language layers only), four configurations, the winner chosen on validation rows only: rank 16, learning rate 2e-4 (`eval/results/sweep_e4b.json`). One run took 3,547 s on a Modal NVIDIA L40S, peak memory 20.6 GB (`eval/results/train_e4b-r16-lr2e-4.json`). Details: `docs/BENCHMARK_4B.md`.

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

Every number below is read from the file named next to it. All files are in `eval/results/` and rendered by `python eval/make_results_md.py` into `eval/RESULTS.md`. Offline and dry-run files are labelled there and are not results.

**Extraction.** Same 100 held-out test rows (407 gold entities). Test diaries are synthetic, from the same generator as the training data, and held out by disease. The larger models run zero-shot with the same prompt. A prediction counts as correct only when its HPO code, negation and family flags all match. Precision, recall and F1 below are after the app's HPO check (`clario.extract.resolve_hpo`), which is what Clario stores. Jev picks codes from the ontology, so its checked and raw numbers are the same. Qwen3.8-27B is left out: it returned empty answers on 85 of 100 rows. Raw F1, latency and hardware are in `docs/BENCHMARK_4B.md`.

| Model | Precision | Recall | F1 | Source file |
|---|---|---|---|---|
| Clario fine-tuned E4B, served on Modal | 0.693 | 0.693 | 0.693 | `extraction_ft-e4b-vllm-test100.json` |
| Clario fine-tuned E4B, training eval | 0.686 | 0.688 | 0.687 | `extraction_ft-e4b-test100.json` |
| Clario fine-tuned E4B, GGUF Q4_K_M on an AMD Ryzen 7 7700 CPU, offline | 0.648 | 0.641 | 0.644 | `extraction_ft-e4b-q4km-ryzen-test100.json` |
| DeepSeek-V4-Flash | 0.478 | 0.514 | 0.495 | `extraction_tf-deepseek-v4-flash-test100.json` |
| Gemma 4 31B | 0.459 | 0.484 | 0.471 | `extraction_tf-gemma-4-31b-it-test100.json` |
| Base Gemma 4 E4B | 0.349 | 0.364 | 0.356 | `extraction_base-e4b-test100.json` |
| Jev, retrieve-then-decide | 0.335 | 0.314 | 0.324 | `extraction_jev-test100.json` |

On all 300 test rows, F1 after the HPO check is 0.353 for the base E4B and 0.701 for the fine-tune (`extraction_base-e4b.json`, `extraction_ft-e4b.json`). Raw F1 on those 300 rows is 0.003 and 0.629. The weak spot is family history: relative recall 0.139 on 300 rows (`extraction_ft-e4b.json`). Jev returns no quotes, so grounding does not apply to it. Latencies are not one comparable measure (batching, a shared API key); see `docs/BENCHMARK_4B.md`. For real patient text, see the PsyTAR results below.

**On real patient text (PsyTAR).** To check that the model is not only good at our own synthetic style, we ran it on 300 sentences from PsyTAR: real, unedited drug reviews written by patients, with symptom spans marked by experts and mapped to HPO by `train/psytar_hpo.py` (CC BY 4.0, Zolnoori et al. 2019). Same GGUF Q4_K_M builds for both models; this is a quality eval only and ran on an NVIDIA RTX 5060 Ti for speed.

| On 300 real patient sentences (491 marked symptoms) | Clario fine-tune | Gemma 4 E4B, no fine-tune | File |
|---|---|---|---|
| Answers in valid JSON | **97.7%** | 89.3% | `extraction_*-psytar300.json` |
| Every term quoted from the patient's words | **99.7%** | 98.8% | |
| F1 on the model's own HPO codes (raw) | **0.150** | 0.009 | |
| Recall after the HPO check | 0.475 | 0.515 | |
| F1 after the HPO check | 0.365 | 0.463 | |

What this shows. **On real text the fine-tune does not beat the base model on F1 after the HPO check (0.365 against 0.463): the gain we measure on synthetic diaries does not transfer yet.** What does carry over:
- **Reliability.** On real patient language the fine-tune returns valid JSON 97.7% of the time and quotes the patient for 99.7% of terms, so each term points to words the patient actually wrote. The base model loses one answer in nine to broken output, which in the app means a note read as empty.
- **The ontology itself.** Scored on its own HPO codes, before any lookup, its F1 is 17 times the base model's (0.150 against 0.009); the base model gets almost no codes right without our ontology check.
- **Most of its "errors" are real symptoms.** It proposes more terms than the base model (785 against 602), and PsyTAR marks only the mentions that map cleanly to HPO (29%), so unmarked but correct terms count against it. A hand check of 30 random "false positives" found 14 real symptoms with a correct or near HPO code, which puts its precision on real text near 0.62 rather than the scored 0.30; the same check on the base model gives about 0.77, so the order does not change (`eval/results/psytar_spotcheck.md`, judged by Claude for the team, not by a clinician).

The next training round mixes real lay text into the synthetic diaries, and these files are the baseline it has to beat.

**Review queue.** With Gemma 4 31B and self-consistency over 5 samples, keeping the auto-accepted rest within 1, 2 or 5 percent error would send every entity to review: share 1.000 at each tolerance (`eval/results/review_curve_tf-gemma4-31b-sc5.json`, 150 test diaries). It measures how many entities go to a person, not accuracy or coverage; the file says which confidence it used in `confidence_source`.

The review queue threshold is chosen by a statistical guarantee. We score the app's own confidence signal, the agreement rate across CLARIO_SC_N sampled extractions, on labelled synthetic diaries, then use split calibration and Learn-then-Test (exact binomial test, Bonferroni over candidate thresholds) on one half of the diaries to find the lowest threshold whose auto-accepted entities have an error rate of at most alpha, with probability at least 90 percent. The binomial test treats entities as independent, while entities in one diary are correlated, so the 90 percent is approximate. The first real run (`eval/results/conformal_threshold.json`, Gemma 4 31B on Token Factory) certified no threshold, so the file says `no_valid_threshold` and the app keeps the fixed threshold 0.7.

**Gemma 4 31B on AMD Token Factory** (hosted API on a shared team key, 6 requests per row, `eval/results/bench_tf-gemma4-31b.json`):

| Workload | Concurrency | Requests/s | Output tokens/s | p50 / p95 latency (s) |
|---|---|---|---|---|
| extract | 1 | 0.085 | 8.4 | 10.08 / 24.56 |
| extract | 4 | 0.344 | 34.1 | 8.72 / 10.55 |
| brief | 1 | 0.013 | 9.3 | 72.06 / 104.02 |
| brief | 4 | 0.039 | 27.6 | 54.56 / 100.56 |

**What the brief saves, as a proxy** (`eval/results/impact_proxy.json`, written by `eval/impact_proxy.py`). For the demo patient Giulia, what she shares is 939 words: 19 diary notes (337), what she already tried and tested (78) and three lab reports as printed (524), about 3.9 minutes of reading at 238 words per minute (Brysbaert 2019). The brief's AI-written summary, timeline and questions are 128 words, about 0.5 minutes: 7.3 times less to read, before the clinician opens anything else. Gemma 4 31B on AMD Token Factory drafted it in 63 s, and the gateway reported a cost of $0.00005 to $0.00006 per brief (6 briefs each at concurrency 1 and 4, `bench_tf-gemma4-31b.json`). The patient model on a Ryzen costs nothing per note and needs no network. This is one synthetic patient and a count of text, not a timed clinician; real patients bring months of notes and longer reports, and a clinician pilot that times "Edit and sign" (`GET /api/clinic/metrics` already records time to sign and lines kept, edited and removed) is the measurement we do not have yet.

**Lab import on AMD Token Factory.** MinerU2.5-Pro OCR with the table read in code found 48 of 48 rows on the 3 synthetic demo referti, every field exact, none needing review, in 39 s for 3 pages sent at once (0.08 pages per second; `eval/results/documents_tf-mineru-table.json`).

Patterns engine, CPU only, no model. 1,200 simulated patients (frequency-weighted terms from a stratified set of the shipped disease annotations, imprecise terms, noise terms, negation) through the app's scorer. Source: `eval/results/pattern_calibration.json`, written by `python eval/pattern_calibration.py` (about a minute on 8 cores). The tier cut-offs come from a separate, larger calibration run, the numbers below from a held-out run that draws only condition families the calibration run never used. A hit is the right condition family (subtypes of one condition count as one). The patient sees at most one card, because only the top-ranked condition can lead.

| Measure | Value |
|---|---|
| True condition family ranked 1st / in the top 3 / in the top 10, equal share per stratum | 50% / 65% / 77% |
| Same, weighted by each stratum's share of the eligible conditions | 47% / 63% / 76% |
| Strong card is the simulated condition family | 82% (95% interval 78 to 86) |
| Moderate card is the simulated condition family | 44% (40 to 50) |
| Weak card is the simulated condition family | 28% (22 to 35) |

The simulated patients are not real people, and the annotations describe typical presentations, so these numbers measure how well the scorer reads the knowledge it ships. How it does in a clinic is untested. Tiers are set by how far the top card leads the next condition, because the raw score alone never reaches 80% precision.

## Run it

**Offline, two commands, no GPU and no model download.** Deterministic fixtures stand in for the model so every screen works.

```bash
cd backend && uv sync && cd ../frontend && npm install && npm run build && cd ..
CLARIO_MODE=patient CLARIO_OFFLINE=1 uv --directory backend run python -m clario.app   # http://127.0.0.1:8765
```

For the clinic side, in a second terminal: `CLARIO_MODE=clinic CLARIO_OFFLINE=1 uv --directory backend run python -m clario.app` (http://127.0.0.1:8800). Open the patient app, set a passphrase of 12 or more characters, and load the demo patient. Offline output is for testing the product flow. It is not a model result.

**Run the patient model on your own AMD machine.** The fine-tuned E4B as a 5.3 GB GGUF runs on an AMD Ryzen CPU with llama.cpp, with no GPU and no network. Point the patient app at it:

```bash
llama-server -m clario-e4b-v3-q4_k_m.gguf --device none -ngl 0 -c 8192 --port 8093 --jinja
LLM_BASE_URL=http://127.0.0.1:8093/v1 LLM_API_KEY=local LLM_MODEL=clario-e4b CLARIO_MODE=patient uv --directory backend run python -m clario.app
```

The GGUF is on Hugging Face: [m0rtyddd/clario-gemma4-e4b-v3-gguf](https://huggingface.co/m0rtyddd/clario-gemma4-e4b-v3-gguf). It is our LoRA ([seawer/clario-gemma-4-e4b-lora](https://huggingface.co/seawer/clario-gemma-4-e4b-lora)) merged with `train/export.py merge`, converted with llama.cpp `convert_hf_to_gguf.py` and quantised with `llama-quantize ... Q4_K_M`. The eval that produced the Ryzen row above: `python eval/extraction_eval.py --base-url http://127.0.0.1:8093/v1 --model clario-e4b-v3-q4_k_m --limit 100 --label ft-e4b-q4km-ryzen-test100`.

**Tests.** `cd backend && uv run pytest -q`, `cd frontend && npx vitest run`, `cd train && ../backend/.venv/bin/python -m pytest -q`.

**Public demo on Modal.** `modal deploy deploy/modal/apps.py` starts the patient app and the clinic console, with Gemma 4 31B on AMD Token Factory; `PATIENT_LLM=modal` reads the diary with the fine-tuned E4B served by `deploy/modal/serve_model.py`. Keys come from Modal Secrets.

**On AMD Developer Cloud (one MI300X droplet). Prepared, not run: we had no droplet access (see "AMD Developer Cloud access" above).**

```bash
ssh root@<DROPLET_IP>
git clone <this repo> clario && cd clario
export HF_TOKEN=hf_...                      # accept the Gemma license on Hugging Face first
deploy/amd/bootstrap.sh --synth 3000 --train --eval --bench --app
```

Stages are flags and re-runs skip finished ones. `--app` alone starts the public stack: patient app at `https://<ip>.sslip.io`, clinic console at `https://clinic.<ip>.sslip.io`. Keys live in the environment (see `.env.example`) and stay out of git. Full runbook, cost estimate and shut-down checklist: `deploy/amd/README.md`.

## Deploy

| Item | File |
|---|---|
| Containerised app image | `Dockerfile` (`docker build -t clario-app .`) |
| Public demo: patient app and clinic console | `deploy/modal/apps.py` |
| Fine-tuned E4B served by vLLM (Modal NVIDIA L4) | `deploy/modal/serve_model.py` |
| MI300X stack, prepared and not run: two vLLM servers, GPU metrics sidecar, clinic, patient demo, Caddy HTTPS | `deploy/amd/docker-compose.yml`, `deploy/amd/Caddyfile` |
| Clinic-only stack, single model | `deploy/docker-compose.clinic.yml` |
| Reaching vLLM without public exposure | `deploy/amd/tunnel.md` |
| Every environment variable | `.env.example` |

vLLM never gets a public port. The demo instances set `CLARIO_DEMO_INSTANCE=1`, which shows the synthetic-data banner in both apps.

## Licences and attribution

| Component | Licence and notes |
|---|---|
| This repository | MIT, see `LICENSE` (Copyright (c) 2026 Clario contributors). The third-party components below keep their own licences |
| Human Phenotype Ontology (hp.json, phenotype.hpoa) | HPO licence: use with citation and version, no alteration of the files. The app ships a derived index (`backend/clario/data/knowledge.json.gz`) built from a pinned release. Cite: Gargano et al., The Human Phenotype Ontology in 2024, Nucleic Acids Res. https://hpo.jax.org |
| Orphanet annotations (ORPHA entries inside phenotype.hpoa) and OMIM annotations | Reached through the HPO annotation file. Orphanet is credited as a source of rare disease data ( https://www.orpha.net ). OMIM is a trademark of Johns Hopkins University ( https://omim.org ). No OMIM full text is included |
| Gemma 4 | Apache 2.0, as listed on the Hugging Face model cards of `google/gemma-4-31B-it` and `google/gemma-4-E4B-it` (checked 17 Oct 2026). Weights are not in this repository. Our LoRA adapter and merged weights are derived from Gemma 4 E4B and keep its licence and notices |
| PsyTAR (only if used for the real-text eval) | CC BY 4.0. Zolnoori M, Fung KW, Patrick TB, et al. A systematic approach for developing a corpus of patient reported adverse drug events. J Biomed Inform 90 (2019). doi:10.1016/j.jbi.2018.12.005. Source: https://www.askapatient.com/research/pharmacovigilance/corpus-ades-psychiatric-medications.asp |
| Third-party libraries | Their own licences, see `backend/pyproject.toml` and `frontend/package.json` |

Per-dataset licence verdicts and the reasoning for what was left out: `docs/DATA_SOURCES.md` (an engineering reading that is not legal advice).

## Documents

`docs/PLAN.md` (plan), `docs/API.md` (contract), `docs/COMPLIANCE.md`, `docs/BENCHMARK_4B.md`, `docs/SUBMISSION.md`, `docs/PITCH.md`, `docs/VIDEO_SCRIPT.md`, `DEMO_SCRIPT.md`, `train/README.md`, `bench/README.md`, `eval/RESULTS.md`.

## Team

Revived.
