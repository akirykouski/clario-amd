# Pitch: 3 minutes on stage, 10 slides, judge Q&A

Stage slot Sunday 18 Oct 2026, 17:00, Milan. Every number spoken or shown comes from `eval/results/*.json`, `bench/results/*.json` or `train/out/*/metrics.json`. Placeholders look like `{{...}}` and are filled from the file named in `README.md` "Measured results". If a placeholder is still empty at 12:00 on Sunday, cut that sentence. Do not improvise a number.

## 3-minute script

Speaking pace about 140 words per minute. Total about 400 words.

| Time | Slide | Say | On screen |
|---|---|---|---|
| 0:00 to 0:20 | 1 | "I am going to show you the notebook a patient never had. Clario is a private symptom diary that ends with a one-page brief a clinician has reviewed line by line." | Title, cover image |
| 0:20 to 0:45 | 2, 3 | "People with rare conditions wait years for an answer. The European survey says 4.7 years on average. Most of that wait sits after first contact with the health system, and the weeks before the visit are the least documented. The patient arrives with a memory of last week. The clinic has fifteen minutes." | Problem slide, one cited number with its source link |
| 0:45 to 1:20 | 4 | "Giulia writes in her own words. Clario finds the clinical terms and quotes her exact sentence next to each one. She confirms them. Anything the system is unsure about waits in a queue and counts for nothing until she decides. She picks eight weeks and sends them to her clinic. The package is sealed to the clinic's key and expires." | Live: Today, Review, Share |
| 1:20 to 1:50 | 4, 5 | "At the clinic, the console opens the package. Gemma 4 31B drafts the brief and cites her entries. The clinician accepts, edits or rejects every line. Finalize stays locked while one item is pending. Clario never says what Giulia has. Patterns show as weak, moderate or strong, with what is missing. A validator rejects any sentence that sounds like a diagnosis or a dose." | Live: clinic console, brief with accept and reject, signal chips |
| 1:50 to 2:15 | 6 | "The clinic model runs on one AMD Instinct MI300X with vLLM on ROCm. The same card generated our synthetic training data and fine-tuned the extractor with LoRA. You can see the card working in the app: pages per second on lab import and tokens per second on the brief." | Live: GPU chip, tokens per second. Slide: workload table |
| 2:15 to 2:35 | 7, 8 | "No public dataset has lay language, spans, negation and ontology ids together, so we built one with labels that come from the ontology. On a held-out set of diseases the model never saw, the fine-tuned extractor scores `{{extraction.ft-e4b-r16.entity_f1}}` entity F1 against `{{extraction.base-e4b.entity_f1}}` for the base model." | Results slide, filled from `eval/results` |
| 2:35 to 2:50 | 9 | "The buyer is the clinic. It receives a structured, patient-approved dossier instead of a pile of paper. How many minutes that saves per visit is what our first pilot measures." | Business slide |
| 2:50 to 3:00 | 10 | "We are looking for two Italian rare disease centres for a pilot. Clario organises. Clinicians decide." | Ask slide |

If the live demo fails, play the recorded video from the same timestamps. Keep the demo on the AMD URL, never on localhost, so the compute claim is real.

## Slide outline (10 slides)

| # | Slide | Content | Evidence source |
|---|---|---|---|
| 1 | Title | Clario, tagline "Patient-approved pre-visit dossier", team Revived, AMD and Gemma marks | `docs/SUBMISSION.md` |
| 2 | Problem | Long road to diagnosis, the weeks before the visit are undocumented, 15-minute visits | EURORDIS Rare Barometer, https://www.nature.com/articles/s41431-024-01604-z (4.7 years average, 6,507 respondents, 41 countries) |
| 3 | Who and why now | Patients with unexplained, multi-system symptoms and the clinics that see them. Why now: open models that run on a clinic's own hardware, AMD Instinct memory that holds a 31B model plus a small one on one card, and an ontology (HPO) that makes labels checkable | `deploy/amd/README.md`, `backend/clario/knowledge.py` |
| 4 | Product walk | Four screenshots: Today, Review queue, Share, Clinic brief | `frontend/src/patient/*`, `frontend/src/clinic/*` |
| 5 | Safety by design | The five Track 2 items, one mechanism each, one file each | README "How we handle safety" |
| 6 | AMD workload | Diagram patient device and MI300X. Table: brief on 31B, extraction on E4B, vision lab import, data generation, LoRA training, benchmark. Live GPU chip | README "Runs on AMD", `{{bench.brief.c32.tokens_per_s}}` |
| 7 | Model and data | Why no public set fits, labels by construction, disease-disjoint split, Claude used for eval only, never for training | `docs/DATA_SOURCES.md`, `train/README.md` |
| 8 | Results | Table: base vs LoRA on entity F1, HPO-ID accuracy, grounding, JSON validity, review-queue share. Throughput on MI300X | `eval/results/extraction_*.json`, `bench/results/*.json` |
| 9 | Business model | See below | hypotheses, labelled |
| 10 | Ask | Two pilot centres, intros to Italian rare disease networks, AMD cloud credits for the pilot period | n/a |

## Business value

**Buyer.** The clinic or hospital department. **User on the other side.** The patient, free.

**What the clinic gets.** A structured, patient-approved pre-visit dossier (confirmed terms with the patient's own quotes, a timeline, imported lab history) and a reviewable brief where every AI line carries a citation and a clinician decision.

**Value hypothesis, to be measured.** The brief reduces the time a clinician spends rebuilding the history at the start of a visit. We do not claim a number. The pilot measures minutes to first useful question with and without the dossier, and clinician acceptance rate per brief item (the console stores an accept, edit or reject decision per item; a counter over those decisions is a small addition, TODO).

**Pricing hypothesis, untested.** Per clinic subscription for the clinic console and the on-premise model server, set after pilot interviews: `{{PRICE_HYPOTHESIS}}`. The patient app stays free so that dossiers keep arriving. A hospital that prefers not to run a GPU can use a managed AMD-hosted clinic instance under a data processing agreement.

**Go-to-market in Italy.**

1. Start with reference centres for rare and undiagnosed diseases, where the diagnostic wait is longest and the visit is already a structured, multi-specialty process.
2. Work through patient associations (for example UNIAMO, the Italian federation of rare diseases) to recruit pilot patients, using the synthetic demo first.
3. Run a 90-day pilot at one or two centres with a measurement plan agreed upfront.
4. Italian and English from day one (the app and the data generator already handle both).
5. Expand by reference network once acceptance and time data exist.

## Judge Q&A prep (10 questions)

| # | Question | Answer |
|---|---|---|
| 1 | Is this a medical device? | Our position: no. Clario is a patient organiser and a note summariser. It does not give a diagnosis, a risk score or treatment advice, and code enforces that (hedge validator, no condition names to patients, no percentages). A regulatory assessment with a qualified advisor comes before any clinical deployment. Detail in `docs/COMPLIANCE.md`. This is our position, not legal advice |
| 2 | Why not just use GPT or Claude? | Three reasons. Health text is Article 9 data, so the clinic model runs on the clinic's own server and the patient side redacts identifiers before any remote call. Second, the extractor is a small model (E4B) with a laptop export path (`train/export.py`, not yet measured on a laptop). Third, the guardrails are in code (quotes, ontology, citations), so the base model matters less than the checks around it. We use Claude only to draft gold labels for human review and as an eval comparison, never for training |
| 3 | Where does the data go? | The diary stays in an encrypted vault on the patient's device. A share sends only confirmed terms and entries from a chosen period, sealed to the clinic's key, expiring. The clinic stores the opened package on its own server. The privacy page lists every model call and its hash chain. On the public demo everything is synthetic |
| 4 | How do you know the model is right? | We check it. Each term must quote the patient's words, each ontology id must match those words, and uncertain ones go to the patient. On the numbers: `{{extraction.ft-e4b-r16.entity_f1}}` entity F1 and `{{extraction.ft-e4b-r16.quote_grounding_rate}}` grounding on the held-out set, from `eval/results`. Known limit: part of the eval data is synthetic, so we also report a hand-reviewed gold set |
| 5 | Your training data is synthetic. Does it transfer? | Unproven, and we say so. Labels come from the ontology by construction, with disease-disjoint splits. We test on a hand-reviewed gold set and on PsyTAR mapped to HPO. The gap between the synthetic and the real rows in `eval/RESULTS.md` is the honest answer |
| 6 | What stops it from diagnosing? | Four layers. Patients never see condition names, only neutral feature groups. Pattern scores come from code, and the model writes only the hedged explanation. A validator rejects "you have", "confirms", doses and percentages and falls back to a template. A clinician must accept every AI line before finalize |
| 7 | What did AMD actually do here? | The clinic brief runs on Gemma 4 31B on vLLM with ROCm on one MI300X. The same card generated the training data and ran the LoRA fine-tune. Lab import runs vision calls in parallel on it. The app shows live GPU telemetry. Throughput numbers come from `bench/results` |
| 8 | Why would a clinic pay? | Our hypothesis is time and quality at the start of the visit. We have not measured it. The pilot is designed to measure minutes to first useful question and the clinician acceptance rate per item |
| 9 | What about a wrong or missing term in the brief? | Missing terms are the patient's to add, wrong ones the patient or clinician rejects. Rejected items never count and never leave the device. Every decision writes a correction record, which is also our improvement signal |
| 10 | What happens in an emergency? | The diary is not an emergency service and says so. Text that describes chest pain with warning signs, trouble breathing, stroke signs, heavy bleeding, a long seizure or self-harm gets an immediate notice with 112 before anything else. The app has no question-answering feature, so there is no place to ask about doses, and AI text with dose or treatment wording is rejected by the validator. (Plan docs mention a dosing interceptor; the code does not have one, so do not claim it on stage) |
