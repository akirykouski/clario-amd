# Clario demo script (one take, 3 minutes)

Two browser windows side by side: patient app (phone width, port 8765) and clinic console (laptop width, port 8800, on the AMD server for the real run). Italian UI on both. Persona "Giulia (IT)" already loaded, vault unlocked, 3 sample referti NOT yet imported. Use "No" when the app asks the next question, so no extra condition is confirmed.

Start command for the rehearsal without a GPU: `CLARIO_OFFLINE=1 CLARIO_PSEUDONYMIZE=1 CLARIO_DEMO_INSTANCE=1`. Offline output comes from fixtures, so every number seen in that mode is a test number, never quoted.

| # | Time | Do | Say (Italian first, English in brackets) | What it proves |
|---|---|---|---|---|
| 1 | 0:00 | Patient, Importa documenti. Tap "Usa i 3 referti di esempio" (or drop the PDFs). Point at the pages per second and the GPU chip. | "Questi sono referti di carta. Vengono letti in parallelo." (Paper reports, read in parallel.) | **AMD workload**: batch vision reading, many concurrent requests on one MI300X (vLLM batching). Pages/s is measured by the app. **Track 2 safety**: pages stored encrypted, every low-confidence row waits for a person |
| 2 | 0:30 | Today. Write: "Sono Giulia Rossi, il mio numero è 333 123 4567. Oggi la febbre è tornata e ho di nuovo una piaga in bocca, mi sembra peggio." Save. | "Scrivo come parlo, in italiano." (I write the way I talk.) | **Gemma**: colloquial Italian to clinical terms with a verbatim quote per term. **Sensitive data**: nothing but this device has the text yet |
| 3 | 0:50 | Header chip "da rivedere". Open it. Confirm one entity, correct one, reject one, confirm one lab row. | "Dove il sistema non è sicuro, decido io." (Where it is unsure, I decide.) | **Track 2 human review**: entities and lab rows share one queue. Confidence is self-consistency over n samples, not a model claim. Every decision is a correction record |
| 4 | 1:10 | Da discutere. Read the question card, tap "No". Watch the order of the cards change. | "Una domanda sola, quella che aiuta di più." (One question, the most useful.) | **Track 2 no diagnosis**: the question never names a condition or a medicine, red-flag and dosing terms are never asked. Information gain is computed in code. Gemma only words it |
| 5 | 1:35 | Open the entry, tap "Cosa ha visto il cloud". | "Ecco cosa è partito: nome e telefono sostituiti." (Name and phone were replaced.) | **Sensitive data**: pseudonymization before the model call, tamper-evident call log (shield icon, "Registro verificato"). The surname is NOT replaced today (first-name list only): do not claim full anonymization |
| 6 | 1:55 | Da discutere, scroll the cards. Tap "Mostra a cosa somiglia" on one card only. | "Prima le prove, il nome solo se lo apro. Non è una diagnosi." (Evidence first, the name only if I open it.) | **Track 2 uncertainty and no diagnosis**: signal words, evidence per note, "not recorded yet" list, hedge validator on every sentence. Family history and negations do not count ("mia madre ha il lupus", "niente febbre") |
| 7 | 2:10 | Condividi. Check the clinic, write the question for the doctor, send. Show the QR. | "Mando solo quello che ho confermato, sigillato per la clinica." (Only what I confirmed, sealed to the clinic.) | **Sensitive data**: sealed box to the clinic key, expiry, key fingerprint compared on both screens. Nothing unreviewed leaves |
| 8 | 2:25 | Clinic window. Open the package. "Prepara la bozza". Accept two items, edit one, reject the unsafe one if shown. "Rendi definitivo". Tap "Copia per il paziente". | "Il modello della clinica scrive la bozza, il medico decide ogni riga." (The clinic model drafts, the clinician decides each line.) | **AMD workload**: Gemma 4 31B on the clinic's own MI300X, tokens/s shown live. **Track 2 human review**: finalize is blocked while any AI item is pending. The patient copy has plain words and no condition names |

## Where the AMD numbers come from

Never type a number that is not in a file.

| Number | Source | Status |
|---|---|---|
| Pages per second (step 1) | Shown by the app from the batch it just ran (`/api/documents/batch/{id}/events`). For the slide: `backend/scripts/make_referti.py` makes a 200 page batch, run it on the droplet, keep the screenshot | Real run on the droplet NOT done. The 3-page offline run is a fixture speed |
| GPU name and load | `GET /api/system/gpu` (amd-smi on the droplet or the sidecar in `backend/clario/gpu.py`) | amd-smi JSON shape is from AMD docs, unverified on hardware |
| Tokens/s and latency (step 8) | Per call, from the vLLM usage field, shown in the brief panel. Aggregated runs: `bench/results/*.json` via `GET /api/bench` | Not run yet |
| Extraction quality (F1, HPO id accuracy, JSON validity, base vs LoRA) | `eval/results/extraction_*.json` (fields n, dataset, model, backend, date), rendered in `eval/RESULTS.md` | Only dry-run and offline files exist until the droplet run |
| Review-curve numbers | `eval/review_curve.py` over a results file | Same |

If a result file is missing, the slide says "measured on the droplet, see repo" and shows no figure.

## Safety lines to have ready

- Emergency text ("non riesco a respirare") shows the notice first, saves the note.
- A dosing question ("posso aumentare la dose?") is answered with "ask your doctor or pharmacist", saved, never sent to a model.
- Brief items that sound like a diagnosis or a dose are dropped in code before the clinician sees them.

## Reset between takes

Stop both servers by PID, delete the two data dirs, start again. Setup vault, "Dati dimostrativi", "Giulia (IT)", "Carica il diario". The language follows the browser; the switcher is in both headers.
