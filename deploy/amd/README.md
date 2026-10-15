# Clario clinic server on AMD Developer Cloud (MI300X + vLLM + Gemma 4 31B)

Goal: Clario in `CLARIO_MODE=clinic` (port 8800) behind HTTPS, talking to Gemma 4 31B on vLLM (loopback only) on one MI300X (192 GB). Optional: the fine-tuned extraction LoRA served from the same vLLM.

## 0. Facts checked (2026-10-12)
- vLLM Gemma 4 recipe lists `google/gemma-4-31B-it` (31B dense, min 1x 80 GB, AMD: 1x MI300X/MI325X/MI350X/MI355X, BF16) and a ROCm install path: https://docs.vllm.ai/projects/recipes/en/latest/Google/Gemma4.html
- Image `vllm/vllm-openai-rocm`: tags `v0.31.0` (2026-10-04), `v0.30.0`, `latest`, `nightly` exist on Docker Hub (https://hub.docker.com/r/vllm/vllm-openai-rocm/tags). The recipe's own ROCm docker example uses `:latest`. We pin `v0.31.0`.
- AMD day-0 note says Gemma 4 uses the TRITON_ATTN backend on ROCm: https://www.amd.com/en/developer/resources/technical-articles/2026/day-0-support-for-gemma-4-on-amd-processors-and-gpus.html (from a search snippet, page not fetched). If startup fails on attention, add `EXTRA_ARGS="--attention-backend TRITON_ATTN"` or env `VLLM_ATTENTION_BACKEND=TRITON_ATTN` (check `vllm serve --help` on the box).
- Gated model: accept the Gemma license on Hugging Face, export `HF_TOKEN`.
- NOT verified: LoRA serving for Gemma 4 on ROCm. vLLM's LoRA path (`--enable-lora --lora-modules name=path --max-lora-rank N`) is generic, but test on the box. If it fails, merge the adapter into the base weights and serve the merged checkpoint as a second model.
- NOT verified: that the MI300X Quick Start image has Docker preinstalled (previous project used it that way).

## 1. Get the GPU
1. Join the AMD AI Developer Program (~$100 credits, about 50 h of one MI300X): https://lablab.ai/ai-articles/from-zero-to-ai-builder-amd-developer-program
2. https://devcloud.amd.com: add a payment method (Create GPU Droplet stays disabled without one), add your SSH public key.
3. Create GPU Droplet: 1x MI300X, Quick Start image vLLM (or ROCm / Ubuntu with Docker). Guides: https://lablab.ai/ai-tutorials/amd-developer-cloud-host-llm-vllm
4. Powering off does NOT stop billing. Destroy the droplet when done.

## 2. Firewall first (health data)
Cloud firewall: inbound 22 (your IP only), 80, 443. Nothing else. No public vLLM port, ever. Details in `tunnel.md`.

## 3. Serve the model
Run on the droplet host shell (the Quick Start image may have its own `rocm` container on port 8000; ours is separate on 8001).
```bash
scp -r deploy root@<DROPLET_IP>:~/ && ssh root@<DROPLET_IP>
export HF_TOKEN=hf_...                                   # never commit
export VLLM_API_KEY=$(openssl rand -hex 24); echo "$VLLM_API_KEY"
cd ~/deploy/amd && ./serve_vllm.sh google/gemma-4-31B-it
```
Binds `127.0.0.1:8001`. First start downloads weights (several minutes). Tunables (env): `MAX_MODEL_LEN=16384 MAX_NUM_SEQS=64 GPU_MEM_UTIL=0.90 VLLM_IMAGE=... EXTRA_ARGS=...`. Fallback tags if v0.31.0 will not start Gemma 4: `latest`, `nightly`.

### Optional: fine-tuned extraction LoRA
Copy the adapter dir (must contain `adapter_config.json`, rank 16 or lower) to the droplet, then:
```bash
LORA_PATH=~/clario-extract-adapter ./serve_vllm.sh google/gemma-4-31B-it
```
This adds `--enable-lora --lora-modules clario-extract=/lora/clario-extract --max-lora-rank 16`. Clients select the adapter by sending `model: "clario-extract"`; the base model stays `google/gemma-4-31B-it`. Check with `LORA=clario-extract ./smoke.sh`. Raise `LORA_RANK` if the adapter was trained with a higher rank.

## 4. Verify
```bash
VLLM_API_KEY=... ./smoke.sh                       # on the droplet
```
Expect a models list and "OK: valid structured JSON".

## 5. Run Clario clinic
All-in-one (vLLM + Clario + Caddy HTTPS), from the repo root on the droplet:
```bash
export HF_TOKEN=... VLLM_API_KEY=... CLINIC_DOMAIN=clinic.<DROPLET_IP>.sslip.io
docker compose -f deploy/docker-compose.clinic.yml up -d --build
curl -i https://$CLINIC_DOMAIN/api/health        # mode=clinic, llm.is_amd expected true
```
Do not run `serve_vllm.sh` and the compose `vllm` service together (both want the GPU). Pick one. If you already run `serve_vllm.sh`, run Clario alone with:
```
CLARIO_MODE=clinic  LLM_BASE_URL=http://127.0.0.1:8001/v1  LLM_API_KEY=$VLLM_API_KEY  LLM_MODEL=google/gemma-4-31B-it
```
and put Caddy (`Caddyfile`, upstream `localhost:8800`) in front. Compose needs a Dockerfile at repo root (not yet present when this was written).

## 6. Benchmark on AMD
Numbers only count when produced on the droplet. See `bench/README.md`:
```bash
LLM_API_KEY=$VLLM_API_KEY uv run --with openai --with httpx python bench/bench.py \
  --base-url http://127.0.0.1:8001/v1 --model google/gemma-4-31B-it \
  --label amd-mi300x-gemma4-31b --workload both --concurrency 1,8,32,64 --n 64 --stream
```
Then `GET /api/bench` on the clinic returns the latest result file.

## 7. Serve-arg rationale (tune with the bench)
- `--max-num-seqs 64`: clinic load is a few clinicians, not a batch job; raise if p95 stays flat.
- `--max-model-len 16384`: the brief prompt is about 2k tokens plus output; headroom for bigger packages.
- `--gpu-memory-utilization 0.90`: ROCm can OOM at 0.95+ with large batches.
- `--enable-prefix-caching`: the shared package summary and system prompt repeat across brief calls.
- No `--reasoning-parser`: thinking off for JSON output.
- Structured output is per request (`response_format: json_schema`), no server flag.

## 8. Safety checklist
- [ ] vLLM not reachable from outside (`curl -m 5 http://<IP>:8001/v1/models` fails)
- [ ] 443 serves a valid certificate; 80 only redirects
- [ ] `VLLM_API_KEY` random, not in git, rotated after the event
- [ ] No patient data in bench prompts (bench uses synthetic snippets only)
- [ ] Droplet destroyed and volumes removed after the demo
