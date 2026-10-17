# Submission pack

lablab.ai AMD Developer Hackathon ACT III, Track 2 Health and Wellbeing. Deadline Sunday 18 Oct 2026 16:00 CEST. Pitch on stage 17:00, Milan.

## Title

| Option | Note |
|---|---|
| **Clario: the patient-approved pre-visit dossier** (recommended) | Names the product and the B2B deliverable in one line |
| Clario: a private diary your clinic can read | Clearer for patients, weaker on the business angle |
| Clario | Short, relies on the description to carry meaning |

Recommended: **Clario: the patient-approved pre-visit dossier**

## Short description (255 characters or fewer)

```
Clario turns a patient's plain-language diary into clinical terms with quoted evidence. The patient shares a sealed, expiring dossier; Gemma 4 31B on AMD drafts a brief that a clinician edits and signs. It never diagnoses.
```

Length check before pasting: run `printf '%s' "<text>" | wc -c` and confirm 255 or fewer.

## Long description (about 250 words)

```
People with rare conditions often wait years for a diagnosis, and the months before the first specialist visit are the least documented. Clario covers that stretch.

The patient keeps a private diary, encrypted with a passphrase only they hold, and writes the way they talk. A fine-tuned Gemma 4 E4B turns each note into clinical terms, each tied to the patient's exact words. Every term counts unless the patient taps "Not right"; anything the model is unsure about is flagged for the clinician. Lab reports are read by OCR and checked in code.

Before a visit, the patient sends the clinic a package sealed to its key, with an expiry. The clinician checks lab readings that failed a code check, and Gemma 4 31B drafts a one-page brief from pseudonymised data. It stays a PDF marked "AI draft, not reviewed" until the clinician edits and signs it. For a second opinion, the new doctor sees the facts, not the previous doctor's conclusions, until they have signed.

On AMD Token Factory: our training data generation, lab OCR, the clinician brief and the large-model benchmark. On synthetic test diaries held out by disease, the fine-tuned 4B model scores 0.63 entity F1; DeepSeek-V4-Flash scores 0.40 and Gemma 4 31B 0.05 on our format.

Clario organises information. It does not diagnose and gives no treatment advice. Clinicians decide.
```

Word count about 225. Numbers: `eval/results/extraction_ft-e4b.json` (300 rows), `extraction_tf-deepseek-v4-flash-test100.json` and `extraction_tf-gemma-4-31b-it-test100.json` (100 rows), rendered in `eval/RESULTS.md`.

What not to write: that anything ran on an MI300X. The fine-tune and the E4B serving ran on Modal NVIDIA (L40S, L4), because AMD Developer Cloud credits never arrived; README "Where the models run" says so.

## Privacy statement (for the form and the repo page)

Before text reaches a remote model, Clario replaces direct identifiers with placeholders using rules and a first-name lexicon, with no model involved: emails, phone numbers, codice fiscale, tessera sanitaria and hospital record numbers, street addresses, full dates including dates of birth, and personal names recognised by title, label, relation, first-name list or "X said" pattern. Medical eponyms, doses, lab values, drug names and places of care are kept. On a synthetic English and Italian test set it misses 10.8% of identifiers when strictly held out, and 5.8% after fixes chosen by reading test failures (`eval/results/pii_leak.json`, test half, n = 712); first names that open a sentence and are not in the lexicon are the largest gap. Scanned images and photos are sent unredacted; the preview shows the exact text the model receives. The clinic's brief prompt is pseudonymised the same way, with diary dates turned into day numbers, and the brief PDF says so.

## Tags

`healthcare`, `health-and-wellbeing`, `AMD`, `AMD-Token-Factory`, `Gemma`, `Gemma-4`, `fine-tuning`, `LoRA`, `OCR`, `privacy`, `GDPR`, `human-in-the-loop`, `rare-disease`, `HPO`, `synthetic-data`, `FastAPI`, `React`, `Docker`

## Cover image brief

| Item | Spec |
|---|---|
| Size | 16:9, 1920 x 1080 PNG, safe area 10 percent inside every edge |
| Subject | Left: a phone showing the Today screen with a short handwritten-style note. Right: a clinic console showing the brief PDF with "Reviewed and signed by". A thin sealed-envelope line connects them |
| Text | "Clario" large. One line under it: "Patient-approved pre-visit dossier." Small footer: "Gemma 4 on AMD Token Factory" |
| Style | Use the app's own palette and display typeface so the image matches the product. Calm paper background. No stock photos of doctors, no stethoscopes, no brain or DNA clip art |
| Must not show | Real patient data (use Giulia, the synthetic persona), any diagnosis name, invented statistics |
| Source | Real screenshots from the live demo, captured at 390 px and 1440 px widths, composed in a design tool |

## Checklist: every submission field

| Field | Content | Source | Status |
|---|---|---|---|
| Title | Recommended title above | this file | ready |
| Short description | Block above | this file | ready, verify length |
| Long description | Block above | this file | ready |
| Tags | List above | this file | ready |
| Track | Track 2 Health and Wellbeing | lablab.ai | select |
| Technology and partner prizes | AMD (Token Factory), Google (Gemma 4) | README "Where the models run" | confirm eligible-technology wording on the event page |
| Cover image | 1920 x 1080 PNG | brief above, real screenshots | TODO: design |
| Demo video | About 4 minutes, uploaded, link | `docs/VIDEO_SCRIPT.md` | TODO: record on the public deploy |
| Slides | 10 slides, PDF | `docs/PITCH.md` outline | TODO: build |
| Public GitHub repo | Public URL, containerised, keys in env only | `Dockerfile`, `deploy/amd/`, `.env.example` | MIT (`LICENSE`). TODO: confirm no secrets in history, make public |
| App URL | Patient app and clinic console, public HTTPS | `deploy/modal/apps.py` output (issue #6) | TODO: paste the two URLs |
| Measured numbers in README, video and slides | Only from result files, each named next to its number | `eval/results/*.json`, `eval/RESULTS.md` | ready |
| Safety explanation (Track 2) | Five items mapped to mechanisms | README "How we handle safety", `docs/COMPLIANCE.md` | ready |
| Demo data statement | Synthetic patients only, banner on demo servers | `CLARIO_DEMO_INSTANCE=1` | ready |
| Team | Revived | README | confirm member names and emails for the form |
| After submitting | Scale the Modal model server to zero when judging ends, rotate the Token Factory key | `deploy/modal/serve_model.py` | TODO |
