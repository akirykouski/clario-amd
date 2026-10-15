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
Clario turns a patient's plain-language diary into clinical terms with quoted evidence. The patient shares a sealed, expiring dossier and the clinic's AMD MI300X server drafts a brief that a clinician reviews line by line. It never diagnoses.
```

Length check before pasting: run `printf '%s' "<text>" | wc -c` and confirm 255 or fewer.

## Long description (about 250 words)

```
People with rare conditions often wait years for a diagnosis, and the months before the first specialist visit are the least documented. Clario covers that stretch.

The patient keeps a private diary on their own device, encrypted with a passphrase only they hold. They write the way they talk. Clario extracts clinical terms from the notes, each tied to the exact words the patient wrote, and asks the patient to confirm them. Anything the system is unsure about waits in a review queue and counts for nothing until a person decides. Lab reports can be imported as PDFs or photos and read in parallel.

Before a visit, the patient chooses a period and sends the clinic a package. Only confirmed terms and notes from that period leave the device, sealed to the clinic's public key, with an expiry. The clinic opens it on its own AMD Instinct MI300X server. Gemma 4 31B on vLLM drafts a one-page brief with citations back to the patient's entries. A clinician accepts, edits or rejects every AI-written line before the brief can be finalized.

Safety is enforced in code. Emergency descriptions get an immediate notice. A validator rejects diagnostic or treatment wording. Patterns appear as weak, moderate or strong signals with evidence counts and what is missing, never as a diagnosis. Every model call is logged in a tamper-evident chain the patient can check.

On AMD: the clinic model runs on vLLM with ROCm, the synthetic training data was generated on the MI300X, the extractor was fine-tuned with LoRA on ROCm, and GPU telemetry is shown live in the app. Clario organises information. Clinicians decide.
```

Word count about 255. Trim the lab-import sentence if a hard 250 limit applies.

## Tags

`healthcare`, `health-and-wellbeing`, `AMD`, `AMD-Instinct`, `MI300X`, `ROCm`, `vLLM`, `Gemma`, `Gemma-4`, `LoRA`, `fine-tuning`, `privacy`, `GDPR`, `human-in-the-loop`, `rare-disease`, `HPO`, `synthetic-data`, `FastAPI`, `React`, `Docker`

## Cover image brief

| Item | Spec |
|---|---|
| Size | 16:9, 1920 x 1080 PNG, safe area 10 percent inside every edge |
| Subject | Left: a phone showing the Today screen with a short handwritten-style note. Right: a clinic console showing a brief with accept and reject chips. A thin sealed-envelope line connects them |
| Text | "Clario" large. One line under it: "Patient-approved pre-visit dossier." Small footer: "Runs on AMD Instinct MI300X" with the GPU chip from the app |
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
| Public GitHub repo | Public URL, containerised, keys in env only | `Dockerfile`, `deploy/amd/`, `.env.example` | TODO: confirm no secrets in history, choose licence, make public |
| App URL | Patient app `https://<ip>.sslip.io`, clinic console `https://clinic.<ip>.sslip.io` | `deploy/amd/bootstrap.sh --app` output | TODO: needs a real MI300X run |
| Measured numbers in README, video and slides | Only from result files | `eval/results/*.json`, `bench/results/*.json`, `train/out/*/metrics.json` | TODO: run on the droplet, then fill README placeholders |
| Safety explanation (Track 2) | Five items mapped to mechanisms | README "How we handle safety", `docs/COMPLIANCE.md` | ready |
| Demo data statement | Synthetic patients only, banner on demo servers | `CLARIO_DEMO_INSTANCE=1` | ready |
| Team | Revived | README | confirm member names and emails for the form |
| After submitting | Destroy the droplet when the judging window ends, rotate keys | `deploy/amd/README.md` section 5 | TODO |
