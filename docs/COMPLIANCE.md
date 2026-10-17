# Compliance position (one page)

Status: hackathon prototype with synthetic data only. This page states our design position and the gaps. It is not legal advice and no regulator has reviewed it.

## GDPR, Article 9 (health data)

| Topic | What the product does | Where | Gap or next step |
|---|---|---|---|
| Lawful basis and consent | The patient decides what leaves the device. A share is explicit, per visit, and lists what goes (confirmed terms, entries in the chosen period, optional patterns, optional note). For a real deployment the basis is explicit consent (Art. 9(2)(a)) for the share and a separate clinic-side basis for care | `frontend/src/patient/SharePage.tsx`, `backend/clario/share.py` | Consent text and records need legal drafting |
| Data minimisation | Only `confirmed` and `corrected` entities are counted and shared. Rejected, negated, uncertain and unreviewed items stay on the device. The patient picks the period | `backend/clario/models.py` (`COUNTED`), `backend/clario/share.py` | None for the prototype |
| Pseudonymisation | Before text reaches a remote model, Clario replaces direct identifiers with placeholders using rules and a first-name lexicon, with no model involved: emails, phone numbers, codice fiscale, tessera sanitaria and hospital record numbers, street addresses, full dates including dates of birth, and personal names recognised by title, label, relation, first-name list or "X said" pattern. Medical eponyms, doses, lab values, drug names and places of care are kept. On a synthetic English and Italian test set it misses 10.8% of identifiers when strictly held out, and 5.8% after fixes chosen by reading test failures (`eval/results/pii_leak.json`, n = 712); first names that open a sentence and are not in the lexicon are the largest gap. Scanned images and photos are sent unredacted; the preview shows the exact text the model receives. The clinic sees a stable non-identifying alias in place of a name | `backend/clario/privacy.py`, `backend/clario/share.py` | The 10.8% held out (5.8% after fixes chosen by reading test failures) is measured on synthetic text written by the redactor's author, so real diaries will leak more. A real deployment adds a stronger recogniser and a miss rate measured on real, consented text |
| Encryption at rest, patient side | Argon2id-derived key, every record AES-256-GCM including dates. No recovery, by design | `backend/clario/vault.py` | Lost passphrase means lost data. A real product needs a clear recovery choice for the patient |
| Encryption at rest, clinic side | Opened packages are stored as JSON files in the clinic data directory. The application does not encrypt them itself | `backend/clario/app.py` (inbox) | Deploy on an encrypted volume today. Application-level encryption with a clinic-held key is the next step |
| Sharing sealed to the clinic key | libsodium sealed box (X25519). Only the clinic server can open the package. The patient compares the clinic key fingerprint before sending | `backend/clario/share.py` | Fingerprint check is manual |
| Expiry and deletion | Every package carries an expiry (24 hours to 30 days, default 3 days). The clinic rejects and purges expired packages. The patient can delete entries | `backend/clario/share.py`, `backend/clario/app.py` | Retention for the finalized brief is a clinic policy to define |
| Transparency and audit | Every model call is logged with a redacted preview and a payload hash in a hash chain the patient can verify, on both the patient and clinic side | `backend/clario/privacy.py`, `/api/privacy/verify` | Deleting the newest log records is not detectable by the chain alone |
| Data location | The clinic model runs on the clinic's own server. The demo runs on one AMD Developer Cloud droplet with synthetic data only | `deploy/amd/README.md` | Real deployments need a data processing agreement with any host and EU hosting |
| Automated decisions (Art. 22) | No decision about a person is made by the system. Output is a patient diary and a draft that a clinician reviews | `backend/clario/brief.py` | None |
| DPIA | Not done | n/a | Required before any real patient data. Health data at scale makes it mandatory |

## EU AI Act framing

Our reading, to be confirmed with counsel.

1. **What the system does.** It extracts terms from patient text, ranks pattern overlap with an ontology, and drafts a summary for a clinician to review.
2. **Risk framing.** The AI Act treats AI systems that are medical devices, or safety components of them, as high risk through the product-safety route. If a regulator finds the intended purpose is diagnosis or triage support, Clario would sit in that route. We design for the opposite intended purpose: organising patient-reported information, with a human deciding on every output. A written intended-purpose statement is the document everything else depends on.
3. **Transparency.** Users are told which text is AI-drafted (brief items carry an origin flag, the printed brief says AI-drafted items are clinician-reviewed) and which backend ran (the UI shows the model and whether it is AMD).
4. **Human oversight.** Built in at two points: patient confirmation, and the clinician edits the AI draft (a PDF watermarked "AI draft, not reviewed") as plain text, sees the citation check and hedge validator as warnings, and signs; only the signed PDF names the clinician. Signing is locked while any low-confidence lab reading is unchecked.
5. **Data governance and logging.** Synthetic training data with documented sources and licences (`docs/DATA_SOURCES.md`). Model calls are logged and tamper-evident.
6. **General purpose model obligations** sit with the model provider. We use open-weights Gemma 4 models. Our LoRA fine-tuning method is in `train/README.md`; the fine-tune itself is planned on the AMD droplet and has not run yet.

## MDR (Medical Device Regulation, EU 2017/745)

**Our position.** Clario is positioned as a patient organiser and note summariser that does not diagnose, predict, monitor or recommend treatment. Under MDR, software is a medical device when its manufacturer intends it for purposes such as diagnosis, prevention, monitoring, prediction, prognosis or treatment of disease. Why we think the current scope sits outside that:

| Design choice | Effect on intended purpose |
|---|---|
| Condition names are clinician-only. Patients see feature groups in everyday words and a signal level with evidence, never a condition name, a disease id or a percentage, on any screen or in any API response | No diagnostic output for the patient |
| Pattern text must pass a hedge validator, otherwise a template is used | No diagnostic or treatment wording from the model |
| Clinician sees pattern overlap labelled "worth discussing" with evidence and gaps | Decision support is limited to organising evidence the patient entered. Still the area a regulator would study most closely |
| No dose, medication or treatment content | No treatment function |

**Honest caveat.** The clinician-side "patterns worth discussing" section names candidate conditions from HPO annotations. A regulator could view this as decision support. For a real deployment we would either remove condition names from the clinician view, or run a formal qualification and classification under MDR Rule 11 with a regulatory advisor and treat the product as a device if required. Do not describe Clario as "not a medical device". Say "our position is that the current scope is outside MDR, pending a regulatory assessment".

## What would change for a real deployment

1. Written intended-purpose statement and a regulatory assessment (MDR qualification, AI Act classification).
2. DPIA, records of processing, data processing agreements, EU hosting, retention policy.
3. Clinic-side application-level encryption and key management, access control and per-clinician audit trail on the console (the prototype has one clinic key and no user accounts).
4. Consent management and patient rights tooling (export, erasure, withdrawal) beyond the local vault.
5. Clinical validation on real, consented, IRB-approved data. The synthetic and PsyTAR numbers in `eval/RESULTS.md` do not substitute for it.
6. Stronger identifier detection with a miss rate measured on real, consented text (today's 10.8% held out, 5.8% after fixes chosen by reading test failures, is synthetic), and a model-risk process (versioning, drift checks, incident handling).
7. Pilot under clinical governance with clinicians, measuring the time and acceptance hypotheses.
