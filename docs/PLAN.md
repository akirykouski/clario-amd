# Clario plan (AMD Developer Hackathon ACT III, Track 2: Health and Wellbeing)

Updated 17 Oct 2026, morning. **Submission closes 18 Oct, 12:00 CEST** (target: submitted by 11:00). Live pitch 18 Oct, 17:00, Milan.

## One line
A private symptom diary for people on a long road to a diagnosis, and a review console for the clinic that receives them. Everyday notes become clinical terms with a quoted source; the clinic sees a plain-words overview, named conditions to consider and the one question that would separate them. Clario organises information, it never diagnoses.

## Where AMD and Gemma 4 run (as of now)
We have **AMD Token Factory** (team key, OpenAI-compatible API, Gemma-4-31B-IT plus vision and document models). We have **no** AMD Developer Cloud droplet (credits never arrived) and no AMD notebook GPU.

```
Patient device (laptop)                         AMD Token Factory (Gemma 4 31B on AMD)
  React PWA + FastAPI "patient" :8765            ├─ data factory: lay lexicon + 2,992 diaries (done)
   ├─ encrypted vault (Argon2id + AES-GCM)       ├─ extraction for the public demo
   ├─ extraction: fine-tuned Gemma 4 E4B (local) ├─ CASCADE: verifies what the small model doubts
   ├─ pseudonymiser before any remote call ────► ├─ clinician brief
   └─ share: select, seal, expire                └─ lab report pages (vision model)
Clinic console: FastAPI "clinic" :8800 ─────────►  same API
```
Fine-tuning runs off AMD (own GPU or Kaggle) and the README says so. The AMD rule ("a meaningful part of the workload on AMD, part of the product shown to the judges") is met by every model call in the product and by the data factory. Google prize: Gemma 4 everywhere, running on AMD.

---

## Done (evidence in the repo)
| Area | What | Where |
|---|---|---|
| Patient | Terms count without clicks; unsure terms dashed and optional to fix; no "to review" nagging | `frontend/src/patient/EntryCard.tsx`, `EntryPage.tsx` |
| Patient | Timeline heat map by organ system, mood row, click a cell for its notes | `components/HeatStrip.tsx`, `patient/TimelinePage.tsx` |
| Patient | Patterns without condition names, next question, "before your visit" card | `patient/PatternsPage.tsx`, `backend/clario/next_question.py` |
| Patient | Labs: no confirm step for patients, the clinician checks uncertain readings | `patient/LabsPage.tsx` |
| Patient | Optional age and sex on the share screen | `patient/SharePage.tsx`, `GET/PUT /api/profile` |
| Privacy | Pseudonymiser, "personal details hidden" badge, hash-chained call log, leak eval | `backend/clario/privacy.py`, `eval/results/pii_leak.json` |
| Clinic | "Patient at a glance" in plain words, questions taken from the notes | `backend/clario/overview.py`, `clinic/PackagePage.tsx` |
| Clinic | Named conditions to consider (Orphanet/OMIM links, recorded vs typical missing), interactive next best question with per-condition frequency, live re-rank | `backend/clario/clinic_ddx.py`, `clinic/Differential.tsx` |
| Clinic | Unsure terms and lab readings listed for confirm/reject | `clinic/PackagePage.tsx` (NeedsCheck) |
| Patterns | Signal cut-offs calibrated on 1,200 simulated patients | `eval/results/pattern_calibration.json` |
| Data | Lay lexicon + 2,992 synthetic diaries (train 2,392 / val 300 / test 300) by Gemma 4 31B on AMD Token Factory, published | [HF: m0rtyddd/clario-synth-v3](https://huggingface.co/datasets/m0rtyddd/clario-synth-v3) |
| Training | QLoRA on 16 GB GPUs, in-process eval, retries for shared quotas | `train/train_rocm.py`, `train/eval.py` |
| Runbooks | Data on Token Factory, fine-tune on own GPU or Kaggle | `docs/ENRICHMENT_RU.md`, `docs/FINETUNE_RU.md` |
| Repo | MIT licence, tests green (backend 503, train 104, frontend 59) | `LICENSE` |

---

## To do, in priority order
Owners are proposals: confirm in the team chat. "Claude" = done with the coding agent.

| # | Task | Owner | By | Done when |
|---|---|---|---|---|
| T1 | **Fine-tune Gemma 4 E4B** on the v3 set (own GPU or Kaggle), eval base vs LoRA, plus the Gemma 4 31B (Token Factory) comparison row | Maksim / Arseniy | 17 Oct 20:00 | `eval/results/extraction_base-e4b.json`, `extraction_ft-e4b-r16.json`, `train_e4b-r16.json`, `extraction_tf-gemma4-31b.json` committed; adapter on HF |
| T2 | **Wire the app to Token Factory**: base URL, key, `Gemma-4-31B-IT` for clinic and the public patient demo; label "Gemma 4 31B · AMD Token Factory" instead of "AMD Instinct MI300X · vLLM"; GPU chip only when telemetry exists | Valentina + Claude | 17 Oct 14:00 | Clinic brief and patient extraction run against Token Factory; header label correct; tests green |
| T3 | **Cascade** (killer feature K1, spec below) | Valentina + Claude | 17 Oct 19:00 | Demo shows "Gemma 4 31B on AMD resolved N of M doubts, X left for you"; eval numbers in `eval/results/cascade_*.json` |
| T4 | **Lab import on AMD vision**: try Gemma-4-31B with images, else MinerU2.5-Pro or MiniCPM-V-4.7-35B (`LLM_VISION_MODEL`) | Claude | 17 Oct 15:00 | Three demo referti import through Token Factory, values land in Labs, pages/s shown |
| T5 | **Public deploy**: patient demo and clinic console with `CLARIO_DEMO_INSTANCE=1`, models on Token Factory (no GPU needed; e.g. two Hugging Face Docker Spaces or one small VPS) | Arseniy | 17 Oct 22:00 | Two public HTTPS URLs; share from patient to clinic works end to end from outside |
| T6 | **Numbers for the slide**: real conformal threshold and review-routing curve via Token Factory (today's `conformal_threshold.json` is a dry run), bench against Token Factory (latency, tokens/s, self-consistency cost) | Maksim + Claude | 17 Oct 22:00 | `eval/results/conformal_threshold.json` with a real model, `eval/results/bench_tf-*.json` |
| T7 | **Docs match reality**: README, PITCH, SUBMISSION, VIDEO_SCRIPT, DEMO_SCRIPT. Remove "own MI300X" and "patient confirms terms"; Token Factory + off-AMD fine-tune stated plainly; fill `{{...}}` only from `eval/results`; verify Gemma 4 31B/E4B licence lines | Valentina + Claude | 18 Oct 08:00 | No `{{`, no MI300X claim we cannot show, every number traced to a result file |
| T8 | **Media**: 3 GIFs, cover 1920x1080, slides (10, PDF), video 2:30 to 3:00 on the live deploy | Valentina | 18 Oct 10:00 | Files in `docs/media/`, video link |
| T9 | **Repo public**: secret scan of the history (the Token Factory key must never appear), make public | Arseniy | 18 Oct 10:00 | Scan clean, repo public |
| T10 | **Submit on lablab** (title, short/long description, track, tech tags, cover, video, slides, repo, app URL) | Valentina | 18 Oct 11:00 | Submitted, link in chat |
| T11 | Small: loading the demo persona twice no longer duplicates the diary | Claude | if time | Second load replaces the first |

---

## Killer features (what makes judges stop)

### K1. Cascade: device model → Gemma 4 31B on AMD → clinician (must have)
The small fine-tuned model reads every note on the patient's device. Only what it doubts goes further, and only after the pseudonymiser.
1. **Device:** fine-tuned Gemma 4 E4B (Ollama, `clario-extract`) extracts terms with self-consistency confidence. Confident terms are done.
2. **AMD:** each low-confidence term is sent, pseudonymised, to Gemma 4 31B on Token Factory with the quote and the ontology candidates. 31B confirms, rejects or picks another candidate, sampled a few times; agreement becomes its confidence.
3. **Clinician:** only terms that 31B also doubts reach the "needs your check" block.
- Code: a `verify` step after extraction (`backend/clario/extract.py`), its own endpoint settings (`CASCADE_BASE_URL`, `CASCADE_MODEL`, key from env), offline fixture for tests, every call in the hash-chained log with purpose `verify`.
- UI: clinic check block says "Checked by Gemma 4 31B on AMD: 7 of 9 doubts resolved, 2 left for you"; patient sees nothing new.
- Proof: eval on the v3 test split, share of terms routed to the clinician and error of auto-accepted terms, device only vs cascade (`eval/results/cascade_*.json`).
- Pitch line: privacy (the device does the bulk), accuracy (AMD settles the doubts), human time (the clinician sees the rest).

### K2. Confidence that means something (have the code, need the numbers)
Self-consistency agreement routes terms; the threshold comes from a statistical guarantee (`eval/results/conformal_threshold.json`). Run it for real on Token Factory: "at X% routed to a person, auto-accepted terms are wrong at most Y% of the time".

### K3. Paper mountain on AMD (T4)
Drop the referti, pages read in parallel by a vision model on AMD, lab timeline builds itself, uncertain values go to the clinician.

### K4. AMD numbers on screen (T6)
Bench against Token Factory: latency p50/p95, tokens/s, cost of self-consistency. Shown in the clinic from `GET /api/bench`, labelled as Token Factory, never as our own GPU.

### Already in the product, show them in the demo
Interactive differential with live re-rank, plain-words overview, heat map, privacy badge plus "what the cloud saw", red-flag interceptor.

### Stretch (only if everything above is green)
Voice note → transcript on Token Factory (OmniVoice, check what it does first); AMD Ryzen AI / Radeon laptop running the device model, so AMD is on both ends.

---

## Demo (3 minutes, live deploy)
1. Giulia's diary: plain words, no clicks needed; one entry shows "2 personal details hidden".
2. Timeline heat map: rash, joints, mouth sores cluster in September.
3. Lab referti dropped in, read on AMD.
4. Share to the clinic: "Patient at a glance", the question from her notes.
5. Cascade: "Gemma 4 31B on AMD resolved 7 of 9 doubts, 2 left for you"; clinician rejects one.
6. Conditions to consider; clinician answers the next question, list re-ranks.
7. Brief accepted and printed. Close on the numbers: fine-tune lift, routing share, latency.

## Track 2 rules, and how we meet them
| Rule | How |
|---|---|
| Improve one part of the patient journey | The months before a diagnosis and the first 15 minutes of the visit |
| No autonomous diagnosis or treatment | Patient never sees condition names; clinician sees "conditions to consider" computed from annotations; hedge validator; red-flag and dosing questions intercepted before any model call |
| Sensitive data | Encrypted vault, pseudonymiser before any remote call, hash-chained call log, sealed expiring shares, synthetic data only on demo servers |
| Uncertain results | Self-consistency confidence, calibrated signals, "typical, not recorded" lists, low-confidence readings marked |
| Human review | Cascade sends what both models doubt to the clinician; every AI brief line accepted, edited or rejected before the brief is final |

## Risks
| Risk | Mitigation |
|---|---|
| Token Factory daily quota (shared key) runs out | Stagger runs, backoff on 429, small `--limit` for evals, keep demo traffic separate from batch jobs, check "Check Usage" |
| Fine-tune not better than base | Ship base E4B on the device, show the numbers honestly; the cascade still works |
| Vision through Token Factory fails | Fall back to MinerU2.5-Pro or MiniCPM-V; last resort, show the import offline and say so |
| Deploy host issues | Run both apps on one laptop with a tunnel for the pitch; keep the recorded video |
| Time | Feature freeze 18 Oct 08:00; only docs, media and submission after that |
