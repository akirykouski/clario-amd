# Clario train/: LoRA fine-tune of Gemma 4 on AMD MI300X (ROCm)

Status: prep, scorer and prompt are tested locally. `train_rocm.py` is **written but not yet run** (no GPU here). Every TODO cell below is filled from a real run on the droplet.

## Files
| file | role |
|---|---|
| `prompt.py` | system prompt, `build_messages`, `parse`, dataset-to-schema mapping. Stdlib only; the app imports this file unchanged |
| `prep.py` | merges local datasets (`data/synth/*.jsonl` from `synth.py`), splits by disease, writes `data/*_sft.jsonl` and `data/val_gold.jsonl` |
| `train_rocm.py` | PEFT LoRA + TRL SFT, writes `out/<run>/metrics.json` and `adapter/` |
| `eval.py` | scores any OpenAI-compatible endpoint, writes `results/<label>.json` |
| `synth.py` | generates labelled diary rows through any OpenAI-compatible endpoint (`--offline` for a no-model check) |
| `lay_terms.json` | HPO terms with layperson synonyms, the sampling pool for `synth.py` |
| `test_eval.py`, `test_synth.py` | scorer and generator unit tests |

## Data and split
`synth.py` writes diary rows whose labels come from HPO and phenotype.hpoa (see its docstring). `prep.py` groups rows by `source_disease` so no disease is in both train and val, and records counts in `data/SPLIT.md`. Real-text eval sources and licences: `docs/DATA_SOURCES.md`.

## Local checks
```
uv run --with pytest --with requests python -m pytest -q test_eval.py
python eval.py --dry-run      # gold vs gold, must print F1 1.000
```

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
4. Data: `python synth.py --base-url http://localhost:8000/v1 --model google/gemma-4-31B-it --api-key-env VLLM_API_KEY --n 5000`, then `python prep.py`
5. Baseline of the untouched model (serve it, see step 8 without `--lora-modules`), then:
```
python eval.py --base-url http://localhost:8000/v1 --model google/gemma-4-E4B-it --label base-e4b --concurrency 8
```
6. Train. Start small to prove the stack, then scale:
```
python train_rocm.py --model google/gemma-4-E4B-it    --data data/train_sft.jsonl --out out/e4b-r16  --epochs 3 --bf16
python train_rocm.py --model google/gemma-4-26B-A4B-it --data data/train_sft.jsonl --out out/a4b-r16 --epochs 3 --bf16 --merge
```
   31B dense: same command with `--model google/gemma-4-31B-it` (bf16 weights about 62 GB, fits in 192 GB with LoRA + checkpointing).
7. Read `out/<run>/metrics.json` (wall time, step time, tokens/s, peak memory GB, loss).
8. Serve with vLLM on ROCm (use AMD's vLLM ROCm image from the AMD Gemma 4 page; confirm the tag there):
```
vllm serve google/gemma-4-26B-A4B-it --enable-lora --max-lora-rank 16 \
  --lora-modules clario=out/a4b-r16/adapter --max-model-len 4096 --port 8000
python eval.py --base-url http://localhost:8000/v1 --model clario --label ft-a4b-r16 --concurrency 8
```
   If vLLM rejects the adapter (MoE / multimodal module names), serve `out/<run>/merged` instead.

## Results (fill from real runs only)
| run | model | train wall | step time | tokens/s | peak mem GB | val entity F1 | HPO-ID acc | JSON valid | grounding | p50 / p95 s |
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
