# 4B model benchmark: diary extraction

How well a fine-tuned 4B model (Gemma 4 E4B with a LoRA adapter) turns everyday diary text into clinical terms, compared with larger general models and a decision model. Every number below is read from the result file named in its row (`eval/results/extraction_<file>.json`).

## Task

Input: one diary entry in everyday English or Italian. Output: every symptom, finding, lab or medication, each with a verbatim quote, a clinical term, its HPO code, and two flags: denied by the writer ("no fever") and belonging to a relative ("my mother has lupus").

A predicted entity counts as correct only when its HPO code **and** both flags match the gold entity. A right term with the wrong "who" counts as wrong.

## Data

- Test split of [clario-synth-v3](https://huggingface.co/datasets/m0rtyddd/clario-synth-v3): synthetic diaries written by Gemma 4 31B through the AMD Token Factory API, with gold labels by construction.
- Split held out **by condition**: no disease in the test set appears in training or validation.
- Comparison set: the first **100** test rows (407 gold entities), the same rows for every model. The fine-tuned and base E4B were also scored on all 300 test rows (table 2).

## 1. Comparison on the same 100 test rows

F1 is measured after the app's deterministic HPO check (`clario.extract.resolve_hpo`), which is what Clario stores. Raw F1 uses the model's own HPO codes. Jev picks codes from the ontology itself, so its raw and checked numbers are the same.

| Model | Precision | Recall | **F1** | Raw F1 | Denied recall | Relative recall | JSON valid | Time per entry (p50) | Where it ran | File |
|---|---|---|---|---|---|---|---|---|---|---|
| **Clario: Gemma 4 E4B + LoRA, served by vLLM on Modal** | 0.693 | 0.693 | 0.693 | 0.607 | 1.000 | 0.000 | 1.000 | 11.5 s | Modal L4, vLLM 0.31 | `ft-e4b-vllm-test100` |
| **Clario: Gemma 4 E4B + LoRA, training eval** | 0.686 | 0.688 | 0.687 | 0.604 | 1.000 | 0.000 | 1.000 | 1.5 s | Modal L40S, transformers | `ft-e4b-test100` |
| DeepSeek-V4-Flash | 0.478 | 0.514 | 0.495 | 0.400 | 0.759 | 0.045 | 1.000 | 18.4 s | AMD Token Factory API | `tf-deepseek-v4-flash-test100` |
| Gemma 4 31B IT | 0.459 | 0.484 | 0.471 | 0.048 | 0.103 | 0.000 | 1.000 | 20.6 s | AMD Token Factory API | `tf-gemma-4-31b-it-test100` |
| Gemma 4 E4B IT, base (no fine-tune) | 0.349 | 0.364 | 0.356 | 0.002 | 0.000 | 0.000 | 1.000 | 2.2 s | Modal L40S, transformers | `base-e4b-test100` |
| Jev 1.13 (TypeSafe), retrieve-then-decide | 0.335 | 0.314 | 0.324 | 0.324 | 0.483 | 0.227 | 1.000 | n/a | TypeSafe API | `jev-test100` |
| Jev 1.13, oracle candidates (upper bound, not a fair comparison) | 0.704 | 0.735 | 0.719 | 0.719 | 0.897 | 0.864 | 1.000 | n/a | TypeSafe API | `jev-oracle-test100` |

## 2. Fine-tune vs base, full test split (300 rows)

| Model | Precision | Recall | **F1** | Raw F1 | HPO-code accuracy | Denied recall | Relative recall | Strict schema valid | File |
|---|---|---|---|---|---|---|---|---|---|
| Gemma 4 E4B + LoRA | 0.701 | 0.702 | 0.701 | 0.629 | 0.497 | 1.000 | 0.139 | 1.000 | `ft-e4b` |
| Gemma 4 E4B, base | 0.353 | 0.354 | 0.353 | 0.003 | 0.001 | 0.000 | 0.000 | 0.983 | `base-e4b` |

## 3. How the adapter was chosen

LoRA on the language model's attention and MLP layers only (258 layers, the vision and audio encoders frozen), bf16, 3 epochs, effective batch 16, max length 1,536, loss on the answer only. Four configurations, one checkpoint per epoch, each scored on 100 validation rows; the best checkpoint of the best run was then scored on test once (`sweep_e4b.json`).

| Rank (alpha = rank) | Learning rate | Best checkpoint | Val F1 after HPO check |
|---|---|---|---|
| r16 | 0.0001 | checkpoint-450 | 0.674 |
| r16 | 0.0002 | checkpoint-450 | 0.715 |
| r32 | 0.0001 | checkpoint-450 | 0.690 |
| r32 | 0.0002 | checkpoint-450 | 0.714 |

Winner: rank 16, learning rate 2e-4, epoch 3. Training: 2,392 rows, about 59 minutes per run on a Modal NVIDIA L40S (`train_e4b-*.json`).

## 4. How the other models were run

- **Gemma 4 31B and DeepSeek-V4-Flash**: the same system prompt and scorer as the fine-tuned model, through the AMD Token Factory API, 3 calls in parallel on a shared team key. Their time per entry includes queueing.
- **Jev 1.13 (TypeSafe)** is a decision model: it answers typed questions with probabilities and does not write text. It runs as the decision step of a retrieve-then-decide pipeline (`eval/jev_eval.py`): the app's ontology search plus the v3 lay lexicon proposes up to 60 candidate HPO terms per entry, and Jev answers three yes/no questions per candidate (the writer has it, the writer denies it, a relative has it). The right term was among the candidates for 47% of gold entities, which caps its recall. The oracle row puts the gold terms in the candidate list on purpose, to measure the decision step alone; it is an upper bound and no real system can reach it.
- **Qwen3.8-27B** (Token Factory) is left out: with a 2,048-token budget it spent the whole budget on hidden reasoning and returned empty answers for 85 of 100 entries. That is a setup failure, so no score is reported.

## What it shows

1. A 4B model fine-tuned for the task scores **0.69 F1** against **0.47 to 0.50** for 27B to 31B general models on the same rows, and gets through an entry every 1.5 s on one GPU in batches of 16.
2. The fine-tune taught the HPO codes themselves: raw F1 goes from 0.003 to 0.629 on all 300 test rows, and denied symptoms are caught every time (recall 1.000).
3. The weak spot is family history: relative recall is 0.139 on 300 rows. Jev's oracle run is strong on exactly this flag (0.864), which suggests checking the "who has it" flag with a decision model as a second step.
4. The served endpoint scores the same as the training eval (0.693 against 0.687 on the same rows), so the live demo runs the measured model.

## Limits

- Test diaries are synthetic and come from the same generator as the training data, which favours a model trained on that style. These numbers are no evidence of performance on real patient text.
- 100 rows (407 entities) is a small set: differences below about 0.05 F1 are within noise.
- Time per entry is not one comparable latency. The training-eval rows divide a batch of 16 by 16; the served endpoint's 11.5 s was measured with 16 requests in flight on one L4; the API models include queueing on a shared key.

## Reproduce

```bash
modal run train/modal_app.py                       # sweep, winner on val, base and winner on test
modal run train/modal_app.py::score_subset         # base and fine-tuned E4B on the first 100 test rows
python train/eval.py --base-url $TF_BASE_URL --api-key-env TF_API_KEY --model Gemma-4-31B-IT \
    --label tf-gemma-4-31b-it-test100 --limit 100 --concurrency 3 --max-retries 10 --max-tokens 2048
python eval/jev_eval.py --limit 100 --lexicon train/data/lay_lexicon_v3.json --label jev-test100
```
