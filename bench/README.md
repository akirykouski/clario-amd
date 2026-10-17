# Clario bench

Measures an OpenAI-compatible endpoint on two Clario workloads:
- **extract**: 30 synthetic colloquial diary snippets (`prompts.py`) -> entities JSON
- **brief**: shared ~2k-token package summary -> clinician brief JSON (exercises prefix caching)

Records per concurrency level: req/s, aggregate output tokens/s, p50/p95 latency, TTFT (with `--stream`), errors, mean prompt/output tokens. Output: `results/<label>-<timestamp>.json` plus a `.md` table.

Workloads in `--workload`: `extract`, `brief`, `both` (default), `sc`, `all`. `sc` is the self-consistency path: the extract prompt with `n=--sc-n` (default 5) samples per request at temperature 0.7. The result carries `self_consistency` rows: latency, output tokens per item and items per second as multiples of plain `extract` at the same concurrency. GPU utilisation and peak VRAM per level come from `--gpu-samples FILE` (the host sampler `python3 eval/hardware.py sample --out FILE`, used by `deploy/amd/bootstrap.sh`) or, when amd-smi is on PATH, from an in-process 1 Hz sampler. Every run also writes `eval/results/bench_<label>.json` with `hardware`. anthropic.com is refused.

## AMD numbers
`deploy/amd/bootstrap.sh --step bench` runs the command below with the sampler attached.
**AMD MI300X numbers exist only if this is run on the droplet against the real vLLM endpoint.** Nothing in `results/` labelled `amd-*` may come from anywhere else. Run on the droplet (see `deploy/amd/README.md`):
```bash
LLM_API_KEY=$VLLM_API_KEY uv run --with openai --with httpx python bench/bench.py \
  --base-url http://127.0.0.1:8001/v1 --model google/gemma-4-31B-it \
  --label amd-mi300x-gemma4-31b --workload both --concurrency 1,8,32,64 --n 64 --stream
```
For the LoRA adapter, repeat with `--model clario-extract --workload extract --label amd-mi300x-clario-extract-lora`.

## AMD Token Factory (hosted Gemma 4 31B)
Token Factory is a hosted API, not our GPU: label its results "Gemma 4 31B · AMD Token Factory" and set `hardware` from `CLARIO_HARDWARE` (the bench has no GPU telemetry there). The gateway rejects `n > 1`, so `extract_sc` sends `--sc-n` separate requests per item. `--workload tf` runs extract, brief, extract_sc and `app` (the app's own `clario.extract.extract` at `--sc-n` and at 1, counting HTTP requests and tokens per note); `app` needs the backend importable, so run it with `backend/.venv/bin/python`. Keep inside the key's limits with `--rpm` and `--max-inflight`; a 429 waits for Retry-After.
```bash
CLARIO_HARDWARE='{"gpu_name": "AMD Token Factory (hosted API; GPU not disclosed, not our own GPU)", "source": "env"}' \
TF_API_KEY=... backend/.venv/bin/python bench/bench.py --base-url https://developer.amd.com.cn/radeon/api/v1 \
  --api-key-env TF_API_KEY --model Gemma-4-31B-IT --label tf-gemma4-31b --backend amd-token-factory \
  --display-label "Gemma 4 31B · AMD Token Factory" --workload tf --concurrency 1,4 --n 8 --sc-n 5 --stream \
  --rpm 18 --max-inflight 6
```

## Local baseline (Ollama)
```bash
uv run --with openai --with httpx python bench/bench.py --base-url http://localhost:11434/v1 \
  --allow-no-key --model <ollama-model> --label local-ollama-<model>-baseline \
  --workload extract --concurrency 1,4 --n 8 --json-object
```
Use `--json-object` if the endpoint rejects `json_schema`. Latency is wall-clock from the client, so run the client close to the server.

`GET /api/bench` on the clinic returns the latest `results/*.json`.
