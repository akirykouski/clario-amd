# PsyTAR spot check: what the "false positives" are

PsyTAR marks only the symptom mentions that map cleanly to HPO (29% of them, `eval/data/psytar_hpo.stats.json`), so a correct term the annotators did not mark is scored as a false positive. To see how much that understates precision, we drew 30 unmatched terms at random (seed 18) from each model's answers on the first 300 sentences and judged each one by hand.

Judged by Claude (Anthropic) for the team, not by a clinician. "Near" means the HPO term is a reasonable match but not the one a coder would pick first. Sources: `extraction_ft-e4b-q4km-psytar300.json` and `extraction_base-e4b-q4km-psytar300.json` (raw answers cached locally; rerun with the same model, URL and `--cache-dir` to reproduce).

| Verdict | Fine-tune | Base |
|---|---|---|
| Real symptom, correct or near HPO code | 14 | 18 |
| Real symptom, imprecise or wrong code | 4 | 1 |
| Real symptom, no code | 4 | 4 |
| Not a symptom (drug name, dose, improvement) | 6 | 6 |
| Wrong | 2 | 1 |

Scored precision and an estimate that counts the "real symptom, correct or near code" share of false positives as correct (n = 30 per model, so roughly ±0.15):

| | Fine-tune | Base |
|---|---|---|
| Precision as scored | 0.297 (233 / 785) | 0.420 (253 / 602) |
| Estimated precision | about 0.62 | about 0.77 |

The scored precision understates both models by about half. The order of the two models does not change.

## Fine-tune, 30 unmatched terms

| # | Quote | Model's term (HPO) | Verdict |
|---|---|---|---|
| 1 | major headaches | Migraine (HP:0002076) | real, imprecise code |
| 2 | severe constipation | Chronic constipation (HP:0012450) | real, near |
| 3 | was just generally unhappy | Depressed mood (HP:5200273) | real, correct |
| 4 | tremors(spasms) | Myoclonus (HP:0001336) | real, imprecise code |
| 5 | chronic depression | Depression (HP:0000716) | real, correct |
| 6 | minor muscle spasms | Myoclonus (HP:0001336) | real, near |
| 7 | constant fatigue | Chronic fatigue (HP:0012432) | real, correct |
| 8 | trembling feeling | Tremor (HP:0001337) | real, correct |
| 9 | anxiety & depression | (no code) | real, no code |
| 10 | Cymbalta | Duloxetine (no code) | not a symptom |
| 11 | At 60mg | (no code) | not a symptom |
| 12 | Inderal | Propranolol (no code) | not a symptom |
| 13 | a little happier | Improved mood (no code) | not a symptom |
| 14 | lowered mental capacity | Moderate intellectual disability (HP:0002342) | real, wrong code |
| 15 | sexual side effects | Sexual dysfunction (HP:0040307) | real, correct |
| 16 | short term memory lapses | Memory impairment (HP:0002354) | real, correct |
| 17 | delayed processing | (no code) | real, no code |
| 18 | loss of appetite | Anorexia (HP:0002039) | real, near |
| 19 | low libido | Hypogonadism (HP:0000135) | real, wrong code |
| 20 | feeling of being "strung out" | Polyneuropathy (HP:0001271) | wrong |
| 21 | dizziness, brain zaps | Migraine (HP:0002076) | wrong |
| 22 | diarrhea then constipation | Alternating bowel habits (no code) | real, no code |
| 23 | high pulse | Tachycardia (HP:0001649) | real, correct |
| 24 | No Taste For Food | Anorexia (HP:0002039) | real, near |
| 25 | zoloft | Sertraline (no code) | not a symptom |
| 26 | insomnia accompanied by increased nighttime anxiety, ... | Anxiety (HP:0000739) | real, correct (long quote) |
| 27 | hot flashes | Vasomotor disturbance (no code) | real, no code |
| 28 | night sweats | Hyperhidrosis (HP:0000975) | real, near |
| 29 | hand tremors | Hand tremor (HP:0002378) | real, correct |
| 30 | effexor | Effexor (no code) | not a symptom |

## Base model, 30 unmatched terms

| # | Quote | Model's term (HPO) | Verdict |
|---|---|---|---|
| 1 | extreme anxiety | Anxiety (HP:0000739) | real, correct |
| 2 | withdrawal | Withdrawal (no code) | not a symptom |
| 3 | sleeping better | Improved sleep (no code) | not a symptom |
| 4 | Much improvement from the suicidal ideation, dysphoria, depression. | (no code) | not a symptom |
| 5 | craving for sugar | Sugar craving (no code) | real, no code |
| 6 | brain zaps | Paresthesia (HP:0003401) | real, near |
| 7 | Very tired | Fatigue (HP:0012378) | real, correct |
| 8 | crying episode | Crying (no code) | real, no code |
| 9 | severe constipation | Constipation (HP:0002019) | real, correct |
| 10 | loss of depression | Improvement in mood (no code) | not a symptom |
| 11 | lithium | Lithium (no code) | not a symptom |
| 12 | gas | Flatulence (HP:0033589) | real, correct |
| 13 | i dont seem 2 care | Emotional blunting (HP:0030213) | real, correct |
| 14 | felt much less weighed down by my thoughts | Depressed mood (HP:5200273) | wrong (an improvement) |
| 15 | lousy | Malaise (HP:0033834) | real, near |
| 16 | dehydration | Dehydration (HP:0001944) | real, correct |
| 17 | dizzy | Dizziness (HP:0002321) | real, correct |
| 18 | crying spells | Crying spells (no code) | real, no code |
| 19 | racing heart | Palpitations (HP:0001962) | real, near |
| 20 | Wellbutrin XL | Bupropion (no code) | not a symptom |
| 21 | hot hot hot | Fever (HP:0001945) | real, imprecise code |
| 22 | high pulse | Tachycardia (HP:0001649) | real, correct |
| 23 | loss of sleep | Insomnia (HP:0100785) | real, correct |
| 24 | increased nighttime anxiety | Anxiety (HP:0000739) | real, correct |
| 25 | nervous | Nervousness (no code) | real, no code |
| 26 | libido started taking strain | Decreased libido (HP:0046504) | real, correct |
| 27 | extreme nausea | Nausea (HP:0002018) | real, correct |
| 28 | a mental 'haze' | Cognitive impairment (HP:0100543) | real, near |
| 29 | trouble sleeping | Insomnia (HP:0100785) | real, near |
| 30 | major headaches | Headache (HP:0002315) | real, correct |
