# Clario bench

Measures an OpenAI-compatible endpoint on two Clario workloads:
- **extract**: 30 synthetic colloquial diary snippets (`prompts.py`) -> entities JSON
- **brief**: shared ~2k-token package summary -> clinician brief JSON (exercises prefix caching)

Records per concurrency level: req/s, aggregate output tokens/s, p50/p95 latency, TTFT (with `--stream`), errors, mean prompt/output tokens. Output: `results/<label>-<timestamp>.json` plus a `.md` table.

## AMD numbers
**AMD MI300X numbers exist only if this is run on the droplet against the real vLLM endpoint.** Nothing in `results/` labelled `amd-*` may come from anywhere else. Run on the droplet (see `deploy/amd/README.md`):
```bash
LLM_API_KEY=$VLLM_API_KEY uv run --with openai --with httpx python bench/bench.py \
  --base-url http://127.0.0.1:8001/v1 --model google/gemma-4-31B-it \
  --label amd-mi300x-gemma4-31b --workload both --concurrency 1,8,32,64 --n 64 --stream
```
For the LoRA adapter, repeat with `--model clario-extract --workload extract --label amd-mi300x-clario-extract-lora`.

## Local baseline (Ollama)
```bash
uv run --with openai --with httpx python bench/bench.py --base-url http://localhost:11434/v1 \
  --allow-no-key --model <ollama-model> --label local-ollama-<model>-baseline \
  --workload extract --concurrency 1,4 --n 8 --json-object
```
Use `--json-object` if the endpoint rejects `json_schema`. Latency is wall-clock from the client, so run the client close to the server.

`GET /api/bench` on the clinic returns the latest `results/*.json`.
