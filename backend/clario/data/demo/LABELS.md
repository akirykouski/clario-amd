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
