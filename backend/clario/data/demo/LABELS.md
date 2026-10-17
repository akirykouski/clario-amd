# Demo labels: how the precomputed demo results were made

"Load the demo patient" and "Import the 3 sample referti" store reviewed, precomputed results. They make no model
call, so the demo opens at once and shows the same terms every time. A note the user types or dictates still goes
through the live model. Every stored term and lab row says so in its `model` field (it starts with `precomputed:`),
and the import screen says the sample results were read earlier and shows no speed, reader or GPU reading.

## Diary terms (`giulia_labels_en.json`, `giulia_labels_it.json`)

1. **Draft.** One extraction call per entry (19 English, 19 Italian) to Gemma-4-31B-IT on AMD Token Factory on
   2026-10-17: the app prompt in its confidence variant, the extraction_v3 schema, the app's grounding and ontology
   check, no HPO pick call, review threshold 0.7. 42 requests in all; 4 entries hit the rate limit (429) and were
   run again on their own.
2. **Review by hand.** Every entity was checked against the entry text and the shipped HPO ontology. Each entity
   records what happened in `source` and `review_note`:
   - `model`: kept as the model gave it.
   - `model, fixed in review`: kept, with a fix. The common fixes: onsets that were a time of day or a trigger
     ("in the morning", "dopo un pomeriggio di sole") removed; HPO ids the ontology check rejected or mapped to the
     wrong body part replaced by the right term or left without an id; duplicates merged; the Italian entries
     aligned with the English ones where the words say the same thing.
   - `model, unsure on purpose`: hedged sentences ("Maybe", "I think", "Forse", "Mi sembra"). Confidence set to 0.5,
     so the term travels marked and the clinician confirms or rejects it. The model's own value is kept in
     `confidence_source`.
   - `hand` / `hand, unsure on purpose`: added in review where the model missed a term (no confidence was measured,
     so `confidence` is null, except the unsure ones).
3. **Choices worth knowing.**
   - The relative's lupus (day 45) carries no HPO id: a relative's diagnosis is not the patient's phenotype, and the
     patient screens never show a condition name.
   - Day 17 (a pain-free Saturday) and day 2 (questions for the visit) carry no terms: nothing new was observed.
   - "Sun exposure" on day 41 has no id and is unsure on purpose, so the clinician can replace it with Cutaneous
     photosensitivity (the term-replace flow in the clinic).
   - English and Italian give the same counted terms day by day (a test pins this).
4. **Effect on patterns.** With these terms the top card has a lead of 0.035 over the runner-up, a moderate card.
   The old offline fixtures gave a leaner term list and a strong card.

The builder script and the raw model draft were kept outside the repo (they hold the call setup, not app code).
To redo the labels: run the extraction again with the settings in step 1, review as in step 2, and keep the test
`tests/test_demo_labels.py` green.

## Demo referti (`ref_7_00{1,2,3}.pdf`)

The rows are those in the truth sidecars (`ref_7_00N.truth.json`, written by `scripts/make_referti.py`). A live read
gives the same rows: MinerU2.5-Pro OCR on AMD Token Factory, table read in code, 48 rows of 48 found, none needing
review (`eval/results/documents_tf-mineru-table.json`, 2026-10-17). Flags are recomputed in code and every row gets
the table confidence, as on the live table path. Tests that need an unsure lab row mark some rows themselves
(`demo_referti_with_unsure` in `tests/conftest.py`).

Two rows of `ref_7_003` are stored as deliberate demo misreads, not from a live read, so the clinician's check of an
OCR error shows: Sodio 147 stored as 141 (a 7 read as 1; it looks in range and would hide a high sodium) and
Emoglobina 11,0 stored as 1,1 (a digit lost). The truth sidecar keeps the printed value and marks each with
`demo_read`; the stored row's `model` says `precomputed: deliberate demo misread`. The same code checks as the live
path compare every row with the PDF's own text layer, so exactly these two go to "Needs your check" (`not_on_page`,
plus `implausible` for the haemoglobin), each with a crop of its printed row. Until the clinician confirms or
corrects them they do not feed the differential.

## Earlier care (`giulia_care_en.json`, `giulia_care_it.json`)

Written by hand, no model involved, for the second-opinion demo (issue #20). Days count back from the day the demo is
loaded, like the diary, and fit it: the GP visit is day 47, after "work was stressful" (day 52) and before the fever and
swollen wrists (day 34), the chest pain (day 37) and the GP blood test (day 30).
- **Facts** (`tried`, `tested`), shared with every clinic: ibuprofen (an NSAID) as needed for 2 weeks, no effect; more
  rest and a regular sleep routine for 4 weeks, no effect; TSH, CRP and ESR in range and a hand X-ray without erosions
  (in range, so they do not contradict the referti), and the day-30 urine test and blood count from the diary. A
  treatment's `note` says what happened, never why it was given, so the facts do not hint at the earlier diagnosis.
- **Conclusions** (`previous`), only in a second-opinion package and shown to the new doctor after they sign: the GP's
  diagnosis (fibromyalgia, stress-related fatigue), conditions considered (fibromyalgia; rheumatoid arthritis with its
  OMIM id, so the comparison can match it), two accepted and two set-aside lines, and the notes. Fibromyalgia is not
  in the shipped ontology, so it has no id and is matched by name.
- English and Italian say the same thing item by item (a test pins the dates, effects, flags and ids).
- With the demo referti imported, the code-computed ranking puts SLE first for the second doctor, the same as for an
  ordinary share (`tests/test_second_opinion.py`); without them the diary alone ranks it second, so import the referti.


## Brief drafts (`giulia_briefs.json`)

"Generate brief" on the demo persona's package opens at once: the draft was generated once, live, and is stored.

- **How.** One brief call per language to Gemma-4-31B-IT on AMD Token Factory on 2026-10-17, through the clinic's own
  path (`make_llm` with the call log, so the input was pseudonymised as in production: dates as day numbers, entry
  ids as aliases `E1`, `E2`, ..., names and contacts replaced), the same system prompt and `briefing.model_input`. The
  package was "Load the demo patient" (Giulia, English; Giulia, Italian), "Import the 3 sample referti", then Share with
  the defaults (12 weeks, patterns on, no question for the doctor). English: 672 tokens, 10.6 tokens/s, 63.3 s;
  Italian: 552 tokens, 18.8 tokens/s, 29.4 s. The chips show these numbers with "precomputed" and the date. Every
  cite was a known alias and every line passes the checks: English 10 of 10, Italian 10 of 10. (The Italian brief was
  redone once: the first run garbled its pattern line, "clinicosembles", and the hedge guardrail dropped it; the run
  kept here is the next one, the first where all lines pass.)
- **What is stored.** The model output as parsed (`DraftOut`), not reviewed or edited: cited entries as positions
  (`E1` is the first shared entry), dates as the model wrote them from day numbers. Serving runs the same code as a
  live draft (`restore_days`, the citation check, the hedge and diagnosis guardrails), so a line the live run would drop
  is dropped here too. (An earlier run sent the real ids, which the pseudonymiser cut to `e_demo_[RECORD_NO]`, so the
  model cited ids that do not exist and 3 of 10 English lines were dropped; the aliases fixed that.)
- **When it is used.** Only when the package's model input is the one the draft was made from, up to the load day and
  the entry ids (`clario/demo_brief.py`: a hash of the input with ids as positions and dates as day offsets). A second
  opinion package of the same diary has the same input, so it gets the same draft. A note of one's own, a question
  for the doctor, another period, a term the clinic corrected, or loading the demo on another day than sharing it
  changes the input and the brief goes to the live model. "Regenerate live" always calls the model. There is no flag.
- To redo: generate as above with the stand's Token Factory settings and replace the file; `tests/test_demo_brief.py`
  must stay green.
