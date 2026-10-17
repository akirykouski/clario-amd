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
Clario turns a patient's plain-language diary into clinical terms with quoted evidence. The patient shares a sealed, expiring dossier and a brief, drafted on the clinic's own AMD GPU server, that a clinician reviews line by line. It never diagnoses.
```

Length check before pasting: run `printf '%s' "<text>" | wc -c` and confirm 255 or fewer.

## Long description (about 250 words)

```
People with rare conditions often wait years for a diagnosis, and the months before the first specialist visit are the least documented. Clario covers that stretch.

The patient keeps a private diary on their own device, encrypted with a passphrase only they hold. They write the way they talk. Clario extracts clinical terms from the notes, each tied to the exact words the patient wrote, and shows the patient what it understood, with "Not right" and Undo on every term. Terms count unless the patient rejects them; anything the model is unsure about is flagged for the clinician. Lab reports can be imported as PDFs or photos and read in parallel.

Before a visit, the patient chooses a period and sends the clinic a package. Only the notes from that period and their terms (never rejected ones) leave the device, sealed to the clinic's public key, with an expiry. The clinic opens it on its own server, built for an AMD Instinct MI300X. Gemma 4 31B on vLLM drafts a one-page brief with citations back to the patient's entries. It opens as a PDF marked "AI draft, not reviewed" until a clinician edits and signs it.

Safety is enforced in code. Emergency descriptions get an immediate notice. A validator rejects diagnostic or treatment wording. Patterns appear as weak, moderate or strong signals with evidence counts, and they carry no diagnosis. Every model call is logged in a tamper-evident chain the patient can check.

On AMD: the clinic model is built to run on vLLM with ROCm on an MI300X, and GPU telemetry is shown live in the app when it does. Before text reaches a remote model, direct identifiers are replaced by rules, with no model involved. Clario organises information. Clinicians decide.
```

Word count about 260. Trim the lab-import sentence if a hard 250 limit applies.

Status of the AMD sentence: the stack has not run on an MI300X yet. After `deploy/amd/bootstrap.sh --all --app` has run and the files exist in `eval/results`, the AMD sentence may add that the synthetic training data was generated and the extractor fine-tuned with LoRA on the MI300X. Do not write that before then.

## Privacy statement (for the form and the repo page)

Before text reaches a remote model, Clario replaces direct identifiers with placeholders using rules and a first-name lexicon, with no model involved: emails, phone numbers, codice fiscale, tessera sanitaria and hospital record numbers, street addresses, full dates including dates of birth, and personal names recognised by title, label, relation, first-name list or "X said" pattern. Medical eponyms, doses, lab values, drug names and places of care are kept. On a synthetic English and Italian test set it misses 10.8% of identifiers when strictly held out, and 5.8% after fixes chosen by reading test failures (`eval/results/pii_leak.json`, test half, n = 712); first names that open a sentence and are not in the lexicon are the largest gap. Scanned images and photos are sent unredacted; the preview shows the exact text the model receives.

## Tags

`healthcare`, `health-and-wellbeing`, `AMD`, `AMD-Instinct`, `MI300X`, `ROCm`, `vLLM`, `Gemma`, `Gemma-4`, `privacy`, `GDPR`, `human-in-the-loop`, `rare-disease`, `HPO`, `synthetic-data`, `FastAPI`, `React`, `Docker`

## Cover image brief

| Item | Spec |
|---|---|
| Size | 16:9, 1920 x 1080 PNG, safe area 10 percent inside every edge |
| Subject | Left: a phone showing the Today screen with a short handwritten-style note. Right: a clinic console showing a brief with accept and reject chips. A thin sealed-envelope line connects them |
| Text | "Clario" large. One line under it: "Patient-approved pre-visit dossier." Small footer: "Runs on AMD Instinct MI300X" with the GPU chip from the app, only once the app runs on the droplet |
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
| Technology and partner prizes | AMD (MI300X, ROCm, vLLM), Google (Gemma 4) | README "Runs on AMD", `deploy/amd/docker-compose.yml` | confirm eligible-technology wording on the event page |
| Cover image | 1920 x 1080 PNG | brief above, real screenshots | TODO: design |
| Demo video | 2:30 to 3:00, uploaded, link | `docs/VIDEO_SCRIPT.md` | TODO: record after the AMD run |
| Slides | 10 slides, PDF | `docs/PITCH.md` outline | TODO: build |
| Public GitHub repo | Public URL, containerised, keys in env only | `Dockerfile`, `deploy/amd/`, `.env.example` | MIT (`LICENSE`). TODO: confirm no secrets in history, make public |
| App URL | Patient app `https://<ip>.sslip.io`, clinic console `https://clinic.<ip>.sslip.io` | `deploy/amd/bootstrap.sh --app` output | TODO: needs a real MI300X run |
| Measured numbers in README, video and slides | Only from result files. Today `eval/results/pii_leak.json` (10.8% miss rate held out; 5.8% after fixes chosen by reading test failures; n = 712) and `eval/results/pattern_calibration.json` (CPU ranking calibration, n = 1200) exist | `eval/results/*.json`, `bench/results/*.json`, `train/out/*/metrics.json` | TODO: measured on the AMD droplet by `deploy/amd/bootstrap.sh --all --app`, then fill README placeholders |
| Safety explanation (Track 2) | Five items mapped to mechanisms | README "How we handle safety", `docs/COMPLIANCE.md` | ready |
| Demo data statement | Synthetic patients only, banner on demo servers | `CLARIO_DEMO_INSTANCE=1` | ready |
| Team | Revived | README | confirm member names and emails for the form |
| After submitting | Destroy the droplet when the judging window ends, rotate keys | `deploy/amd/README.md` section 5 | TODO |
