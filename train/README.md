# Clario train/: data factory, LoRA SFT, GRPO and export for Gemma 4 on AMD MI300X (ROCm)

Status: data factory, prep, scorer, prompt, gold drafter and reward functions are tested offline (`python -m pytest -q`, no model, no GPU). `train_rocm.py`, `train_grpo.py` and `export.py` are **written but not yet run**. Every TODO cell below is filled from a real run on the droplet, and every number in the repo comes from `eval/results/*.json`.

Contract: `backend/clario/schemas/extraction_v3.json` (frozen). `prompt.py` is the single source for the system prompt, parsing and targets.

## Files
| file | role |
|---|---|
| `prompt.py` | v3 system prompt (+ a variant that asks for `confidence`), `build_messages`, lenient `parse`, `strict_valid`, `from_dataset_entities`. Stdlib only. Old outputs still parse |
| `synth.py` | M1 data factory: labels by construction from HPO + phenotype.hpoa, EN and IT, with family-history, onset, severity, life-event distractors and hard negatives. Code validates every row and reports reject reasons. Refuses Anthropic endpoints |
| `prep.py` | disease-held-out and language-stratified train/val/test, writes `data/v3/{train,val,test}.jsonl` and `*_sft.jsonl`, `check_sft` |
| `gold_draft.py` | Haiku drafts 50 EN + 30 IT entries with proposed labels into `eval/gold/drafts.jsonl` for human review (never training data) |
| `psytar_hpo.py` | PsyTAR (CC BY 4.0) spans mapped to HPO with the ontology, writes `eval/data/psytar_hpo.jsonl` |
| `eval.py` | scores any OpenAI-compatible endpoint, writes `eval/results/extraction_<label>.json` (also `eval/extraction_eval.py`) |
| `train_rocm.py` | PEFT LoRA + TRL SFT on the v3 chat files, `metrics.json` and `adapter/` |
| `train_grpo.py` | GRPO with F1 + grounding + flag accuracy - hallucination - Brier(confidence) reward (RLCR style) |
| `export.py` | merge LoRA to bf16 for vLLM, Ollama Modelfile for a GGUF Q4_K_M laptop build |
| `lay_terms.json` | HPO terms with layperson synonyms, the sampling pool for `synth.py` |
| `test_*.py` | unit tests for all of the above |

Related, at the repo root: `eval/review_curve.py` (risk-coverage at 1, 2, 5 % tolerated error), `eval/make_results_md.py` (renders `eval/RESULTS.md`), `eval/gold/review.html` (human review page for the gold drafts).

## Data and split
`synth.py` writes diary rows whose labels come from HPO and phenotype.hpoa. Targets are v3 entities with `confidence: null`. `prep.py` groups rows by `source_disease` so no disease is in more than one of train, val and test, keeps the EN/IT mix in each split, drops duplicate diaries and records counts in `data/v3/SPLIT.md`. Training data comes from Gemma on vLLM only. Claude output must not become a training target: Haiku drafts gold candidates for human review and serves as an eval comparator.
Real-text eval sources and licences: `docs/DATA_SOURCES.md`. Gold set: `gold_draft.py`, then a person reviews it in `eval/gold/review.html`.

## Local checks (no model, no GPU)
```
cd train && ../backend/.venv/bin/python -m pytest -q
python synth.py --n 300 --offline --out data/synth/offline.jsonl     # offline stand-in generator, labelled generator=offline
python prep.py --inputs data/synth/offline.jsonl
python eval.py --dry-run --data data/v3/test.jsonl --dataset offline-synth-v3-test   # gold vs gold, must print F1 1.000
python train_grpo.py --dry-run                                        # toy reward check
```
Offline rows come from a fixed template, not a model. They test the pipeline and are never a result.

## MI300X droplet, step by step
1. Create an AMD Developer Cloud MI300X droplet (ROCm + Docker image). Confirm: `rocm-smi`, `docker ps`.
2. `git clone` / copy `train/` to the droplet. `export HF_TOKEN=...` (Gemma 4 weights are on HF; accept the license if prompted). Never write the token to a file.
3. Container (pinned, tag checked on Docker Hub):
```
docker build -f Dockerfile.rocm -t clario-train .
docker run -it --rm --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --shm-size 64G \
  --security-opt seccomp=unconfined -v $PWD:/workspace/train -v $HOME/hf-cache:/workspace/hf-cache -e HF_TOKEN clario-train
python -c "import torch;print(torch.__version__, torch.version.hip, torch.cuda.get_device_name(0))"
```
4. Serve the generator (Gemma 4 31B, vLLM ROCm image from AMD's Gemma 4 page) on port 8000, then build the data (M1):
```
python synth.py --base-url http://localhost:8000/v1 --model google/gemma-4-31B-it --api-key-env VLLM_API_KEY --n 30000 --concurrency 64
cat data/synth/synth.jsonl.stats.json     # reject reasons and token counts
python prep.py                             # data/v3/{train,val,test}.jsonl and *_sft.jsonl, SPLIT.md
```
5. Gold and real-text sets. `ANTHROPIC_API_KEY=... python gold_draft.py`, then a person opens `eval/gold/review.html`, loads `eval/gold/drafts.jsonl`, accepts entries and exports `gold.jsonl` into `eval/gold/`. PsyTAR: download the workbook in a browser (the site blocks scripts, see `psytar_hpo.py`), save to `data/psytar/`, run `python psytar_hpo.py`.
6. Baselines on the held-out test split. Serve the untouched model, then:
```
python eval.py --base-url http://localhost:8000/v1 --model google/gemma-4-E4B-it --label base-e4b --backend vllm-rocm-mi300x --data data/v3/test.jsonl --confidence --concurrency 8
python eval.py --base-url https://api.anthropic.com/v1/ --model claude-haiku-5-5 --api-key-env ANTHROPIC_API_KEY --label haiku-test --data data/v3/test.jsonl
```
   Repeat with `--data ../eval/gold/gold.jsonl --dataset gold-reviewed` and `--data ../eval/data/psytar_hpo.jsonl --dataset psytar-hpo`.
7. SFT (M3). Start small to prove the stack, then scale:
```
python train_rocm.py --model google/gemma-4-E4B-it    --out out/e4b-r16  --epochs 3 --bf16
python train_rocm.py --model google/gemma-4-26B-A4B-it --out out/a4b-r16 --epochs 3 --bf16 --merge
```
   Defaults read `data/v3/train_sft.jsonl` and `val_sft.jsonl` and refuse old-format files. 31B dense: `--model google/gemma-4-31B-it` (bf16 weights about 62 GB, fits in 192 GB with LoRA + checkpointing). Read `out/<run>/metrics.json` (wall time, step time, tokens/s, peak memory, loss).
8. Serve the SFT model and evaluate it next to the base and Haiku rows:
```
vllm serve google/gemma-4-26B-A4B-it --enable-lora --max-lora-rank 16 --lora-modules clario=out/a4b-r16/adapter --max-model-len 4096 --port 8000
python eval.py --base-url http://localhost:8000/v1 --model clario --label ft-a4b-r16 --backend vllm-rocm-mi300x --data data/v3/test.jsonl --confidence --concurrency 8
```
   If vLLM rejects the adapter (MoE / multimodal module names), serve `out/<run>/merged` instead.
9. Optional GRPO (M4), from the merged SFT weights, then evaluate with `--confidence` and compare ECE:
```
python train_grpo.py --model out/a4b-r16/merged --data data/v3/train.jsonl --out out/a4b-grpo --steps 600
```
10. Report: `python ../eval/review_curve.py` (needs `--confidence` runs), `python ../eval/make_results_md.py`.
11. Export (M5): `python export.py merge --base google/gemma-4-26B-A4B-it --adapter out/a4b-r16/adapter --out out/a4b-r16/merged`, then the llama.cpp GGUF Q4_K_M steps in the `export.py` docstring and `python export.py modelfile --gguf clario-extract-v3-Q4_K_M.gguf`. Evaluate the GGUF as its own row (backend ollama).

## Results (fill from real runs only; see eval/RESULTS.md, rendered from eval/results/*.json)
Training columns (wall, step time, tokens/s, memory) come from `out/<run>/metrics.json`. Metric columns come from `eval/results/extraction_<label>.json`.

| run | model | train wall | step time | tokens/s | peak mem GB | test entity F1 | HPO-ID acc | JSON valid | grounding | p50 / p95 s |
|---|---|---|---|---|---|---|---|---|---|---|
| base | E4B | n/a | n/a | n/a | n/a | TODO | TODO | TODO | TODO | TODO |
| ft r16 | E4B | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| base | 26B-A4B | n/a | n/a | n/a | n/a | TODO | TODO | TODO | TODO | TODO |
| ft r16 | 26B-A4B | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| ft r16 | 31B | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |

## Research notes (2026-10-12) and open risks
- **Unsloth supports ROCm**, MI300 series (gfx940/941/942) marked "Full", Linux only; Gemma 4 listed. Install: `curl -fsSL https://unsloth.ai/install.sh | sh` or `uv pip install "unsloth[amd]"` over the image's torch. The same page advises against MoE QLoRA (dense 31B QLoRA is fine; 26B-A4B LoRA needs >40 GB). Not used here because plain PEFT+TRL is the fewest moving parts; keep as plan B if speed is short. https://unsloth.ai/docs/basics/amd , https://www.amd.com/en/developer/resources/technical-articles/2026/train-and-run-models-on-amd-gpus-with-unsloth.html , https://unsloth.ai/docs/models/gemma-4/train
- **Gemma 4 26B-A4B-it**: MoE, 25.2B total / 3.8B active, 30 layers, Apache 2.0, native `system` role; HF card loads it with `AutoModelForMultimodalLM` and says "latest transformers". `train_rocm.py` tries `AutoModelForCausalLM` first, then falls back. https://huggingface.co/google/gemma-4-26B-A4B-it
- **Unsloth Gemma 4 gotchas**: E2B/E4B give gibberish with `use_cache=False` (KV-shared layers; transformers issue #45242), 26B/31B had an `IndexError` when `num_kv_shared_layers=0`. Healthy SFT loss is about 1-3 for 26B/31B, 13-15 for E2B/E4B. If E4B output is garbage after training, suspect this first. https://unsloth.ai/docs/models/gemma-4/train
- **Day-0 AMD support for Gemma 4** (vLLM/ROCm serving; page timed out on fetch, read it for the exact vLLM image tag before step 8): https://www.amd.com/en/developer/resources/technical-articles/2026/day-0-support-for-gemma-4-on-amd-processors-and-gpus.html
- **Base image**: `rocm/pytorch:rocm7.14.1_ubuntu24.04_py3.12_pytorch_release_2.12.0` exists on Docker Hub (updated 2026-09-01). Newer `rocm10.1.0_*` tags exist (2026-10-05); not used, too new to trust for a hackathon. https://hub.docker.com/r/rocm/pytorch/tags
- **Attention**: default `sdpa` (works on ROCm without extra builds). flash-attn is not mentioned in Unsloth's AMD page; the AMD fine-tuning guide uses transformers+peft+trl with bf16 on MI300X: https://rocm.docs.amd.com/en/latest/how-to/rocm-for-ai/fine-tuning/single-gpu-fine-tuning-and-inference.html (that guide's tested setup is old: ROCm 6.1, Llama-2). Try `--attn flash_attention_2` only if a ROCm flash-attn wheel installs cleanly; do not assume.
- **Unverified**: no source found confirming TRL+PEFT on Gemma 4 on ROCm works unchanged. First droplet action is the E4B smoke run. LoRA target names for the MoE experts are unknown; defaults hit attention + dense MLP projections only (check `print_trainable_parameters` output).
