# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Patients on a long road to a diagnosis**, typically a rare or hard-to-name condition, in the weeks and months before a specialist visit. They write short everyday notes about how they feel, in English or Italian, in a desktop browser, and want to arrive at the visit with something better than memory.
- **Clinicians** (a specialist or the clinic that receives the patient) with a short visit slot. They open a shared package, check what the model understood against the patient's own words, decide on uncertain items, and sign a one-page brief.

## Product Purpose

Clario is a private symptom diary and a review console for the clinic that receives it. It turns everyday notes into clinical terms (HPO codes) with the patient's own quote as the source, shows the patient what it understood so they can say "not right", and lets the patient send a sealed, expiring package to a clinic before the visit. The clinician reviews it and signs a one-page brief. Success: the clinician understands months of symptoms in minutes, and every line in the brief traces back to something the patient wrote.

## Positioning

Clario organises information; it never diagnoses. Every clinical term carries a verbatim quote from the patient, and a person always reviews: uncertain terms and lab readings go to the clinician to confirm or reject. Condition names are shown to clinicians only, never on patient screens.

## Operating Context

- Desktop browser app for both patients and clinicians; layouts are designed for desktop widths first.
- Patient side: private diary entries, photos of lab reports, a timeline, patterns across notes, and a share step that picks a time window and seals the package for one clinic.
- Clinic side: an inbox of sealed packages, a plain-words patient overview, conditions to consider with the one question that would separate them, lab tables, and a brief the clinician edits and signs.
- Languages: English and Italian, on both sides.
- Public demo runs with synthetic patients only, with a visible demo banner.

## Capabilities and Constraints

- Diary is encrypted on the patient side (Argon2id + AES-256-GCM); names and ID numbers in text are replaced before any remote model call.
- Extraction by a fine-tuned Gemma 4 E4B (LoRA); clinic brief by Gemma 4 31B on AMD Token Factory.
- Emergency descriptions trigger an immediate notice with the emergency number before anything else.
- Copy rules: no em dashes, no exclamation marks, no "X, not Y" constructions.
- Frontend: React + Vite + Tailwind in `frontend/`, one build serving both the patient app and the clinic console.

## Brand Commitments

- Name: Clario.
- Voice: plain, calm, precise; never alarming, never diagnostic.

## Evidence on Hand

- Benchmark on held-out synthetic diaries: `docs/BENCHMARK_4B.md`, numbers in `eval/results/*.json`.
- Public synthetic dataset: `m0rtyddd/clario-synth-v3` on Hugging Face.
- No real patients, testimonials, customers or clinical validation exist; none may be implied.

## Product Principles

1. Every claim traces to the patient's own words.
2. A person decides; the model proposes.
3. Private by default: the least data leaves the patient's side.
4. Calm under pressure: the interface lowers anxiety for patients and saves minutes for clinicians.

## Accessibility & Inclusion

Patients may be tired, in pain or anxious: large click targets, readable text, strong contrast. The product is a desktop browser app; small widths must stay usable but are not the design target. Two languages throughout.
