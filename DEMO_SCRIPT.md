# Clario demo script (one take, 3 minutes)

Two browser windows side by side: patient app (phone width, port 8765) and clinic console (laptop width, port 8800, on the AMD server for the real run). Italian UI on both. Persona "Giulia (IT)" already loaded, vault unlocked, 3 sample referti NOT yet imported. Use "No" when the app asks the next question, so no extra condition is confirmed.

Start command for the rehearsal without a GPU: `CLARIO_OFFLINE=1 CLARIO_PSEUDONYMIZE=1 CLARIO_DEMO_INSTANCE=1`. Offline output comes from fixtures, so every number seen in that mode is a test number and is not quoted.

| # | Time | Do | Say (Italian first, English in brackets) | What it proves |
|---|---|---|---|---|
| 1 | 0:00 | Patient, Importa documenti. Tap "Usa i 3 referti di esempio" (or drop the PDFs). Point at the pages per second and the GPU chip. | "Questi sono referti di carta. Vengono letti in parallelo." (Paper reports, read in parallel.) | **AMD workload**: batch vision reading, many concurrent requests on one MI300X (vLLM batching). Pages/s is measured by the app. **Track 2 safety**: pages stored encrypted, every low-confidence row waits for a person |
| 2 | 0:30 | Today. Write: "Sono Giulia Rossi, il mio numero è 333 123 4567. Oggi la febbre è tornata e ho di nuovo una piaga in bocca, mi sembra peggio." Save. | "Scrivo come parlo, in italiano." (I write the way I talk.) | **Gemma**: colloquial Italian to clinical terms with a verbatim quote per term. **Sensitive data**: nothing but this device has the text yet |
| 3 | 0:50 | Header chip "da rivedere". Open it. Confirm one entity, correct one, reject one, confirm one lab row. | "Dove il sistema non è sicuro, decido io." (Where it is unsure, I decide.) | **Track 2 human review**: entities and lab rows share one queue. Confidence is self-consistency over n samples; the model's own claim is not used. Every decision is a correction record |
| 4 | 1:10 | Da discutere. Read the question card, tap "No". Watch the order of the cards change. | "Una domanda sola, quella che aiuta di più." (One question, the most useful.) | **Track 2 no diagnosis**: the question never names a condition or a medicine, red-flag and dosing terms are never asked. Information gain is computed in code. Gemma only words it |
| 5 | 1:35 | Open the entry, tap "Cosa ha visto il cloud". | "Ecco cosa è partito: nome e telefono sostituiti." (Name and phone were replaced.) | **Sensitive data**: pseudonymization before the model call, tamper-evident call log (shield icon, "Registro verificato"). Names are recognised by title, label, relation, first-name list or "X said" pattern; a surname with no cue can still pass. Misses 5.8% of identifiers on the synthetic test half (`eval/results/pii_leak.json`, n = 712). Scanned images are sent unredacted. Do not claim full anonymization |
| 6 | 1:55 | Da discutere, scroll the cards (at most two). Point at a feature row: everyday words first, the clinical name in brackets. | "Solo le prove, in parole mie. Nessun nome di malattia: quello lo vede il medico. Non è una diagnosi." (Only the evidence, in my words. No condition name: the clinician sees that.) | **Track 2 uncertainty and no diagnosis**: condition names are clinician-only, signal words, evidence per note, a card needs three specific terms. Family history and negations do not count ("mia madre ha il lupus", "niente febbre") |
| 7 | 2:10 | Condividi. Check the clinic, write the question for the doctor, send. Show the QR. Read the counts ("N menzioni di M termini"). | "Mando solo quello che ho confermato, sigillato per la clinica." (Only what I confirmed, sealed to the clinic.) | **Sensitive data**: sealed box to the clinic key, expiry, key fingerprint compared on both screens. Nothing the patient left in review leaves. Rows read from documents and not yet checked leave marked. A relative's condition travels only as family history |
| 8 | 2:25 | Clinic window. Open the package: terms, lab history per test (the earlier positive ANA next to the later negative, anti-dsDNA), family history apart. Every lab row marked "Da documenti, da verificare" needs "Accetta" or "Scarta" first; "Rendi definitivo" stays disabled until each one has a decision. "Prepara la bozza". Point at the chips (model, tokens/s, latency, GPU). Accept two items, edit one, and point at the decision line (lines accepted, edited, rejected, time to finalize). **Reject the line flagged "Citazione non corrispondente"** (the fatigue date that its cited entry does not support). "Rendi definitivo". Tap "Copia per il paziente". | "Il modello della clinica scrive la bozza. Questa riga cita una nota dove la stanchezza non c'è: il codice l'ha segnalata, io la scarto." (The model drafts. This line cites a note without fatigue: code flagged it, I reject it.) | **AMD workload** (real run only): Gemma 4 31B on the clinic's own MI300X, tokens/s shown live (offline rehearsal shows "Demo model (offline)" and no speed). **Track 2 human review**: finalize is blocked while any AI item or unchecked lab row is pending; a wrong citation is caught in code and rejected by the clinician. The patient copy has plain words and no condition names |

## Where the AMD numbers come from

Never type a number that is not in a file.

| Number | Source | Status |
|---|---|---|
| Pages per second (step 1) | Shown by the app from the batch it just ran (`/api/documents/batch/{id}/events`). For the slide: `backend/scripts/make_referti.py` makes a 200 page batch, run it on the droplet, keep the screenshot | Real run on the droplet NOT done. The 3-page offline run is a fixture speed |
| GPU name and load | `GET /api/system/gpu` (amd-smi on the droplet or the sidecar in `backend/clario/gpu.py`) | amd-smi JSON shape is from AMD docs, unverified on hardware |
| Tokens/s and latency (step 8) | Per call, from the vLLM usage field, shown in the brief panel. Aggregated runs: `bench/results/*.json` via `GET /api/bench` | Not run yet |
| Extraction quality (F1, HPO id accuracy, JSON validity, base vs LoRA) | `eval/results/extraction_*.json` (fields n, dataset, model, backend, date), rendered in `eval/RESULTS.md` | Only dry-run and offline files exist until the droplet run |
| Review-curve numbers | `eval/review_curve.py` over a results file | Same |
| Pseudonymisation miss rate (step 5) | `eval/results/pii_leak.json`, test half: 5.8% of identifiers, n = 712, synthetic, rules only | Measured (CPU, no model). Optimistic: written by the redactor's author |
| Minutes saved per visit (pilot metric) | `GET /api/clinic/metrics`: lines accepted, edited, rejected and time to finalize per brief | Counter exists. No pilot has run, so no figure is quoted |

If a result file is missing, the slide says "measured on the droplet, see repo" and shows no figure.

## Safety lines to have ready

- Emergency text ("non riesco a respirare") shows the notice first, saves the note.
- A dosing question ("posso aumentare la dose?") is answered with "ask your doctor or pharmacist", saved, and no model call is made.
- Brief items that sound like a diagnosis or a dose are dropped in code before the clinician sees them.
- A brief line that names a term none of its cited entries confirms is flagged "citation mismatch" and stays pending until the clinician rejects or accepts it. It never reaches the patient copy.
- The dosing interceptor lives in `backend/clario/safety.py` (`check_entry`).

## Reset between takes

Stop both servers by PID, delete the two data dirs, start again. Setup vault, "Dati dimostrativi", "Giulia (IT)", "Carica il diario". The language follows the browser; the switcher is in both headers.
