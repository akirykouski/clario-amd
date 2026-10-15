# Clario on AMD Developer Cloud (one MI300X, one command)

Result: a public HTTPS demo. The patient app (Gemma 4 E4B) at `https://<ip>.sslip.io`, the clinic console (Gemma 4 31B, live GPU panel) at `https://clinic.<ip>.sslip.io`, both on one MI300X (192 GB) through vLLM. Optional stages generate synthetic data, fine-tune a LoRA on the droplet, evaluate base vs LoRA, and benchmark.

Status: everything here was validated off-box only (compose files with `docker compose config`, the app image built and run locally). Nothing has run on a real MI300X yet. The "Unverified" list at the bottom says what to watch.

## 0. Facts checked (2026-10-12, docs only)
- Model ids: `google/gemma-4-31B-it` (31B dense, 1x MI300X in BF16, per the vLLM Gemma 4 recipe https://docs.vllm.ai/projects/recipes/en/latest/Google/Gemma4.html) and `google/gemma-4-E4B-it`.
- Image `vllm/vllm-openai-rocm:v0.31.0` exists on Docker Hub (tags also `v0.30.0`, `latest`, `nightly`). Pinned to `v0.31.0`.
- AMD's day-0 Gemma 4 note says the TRITON_ATTN attention backend is used on ROCm (from a search snippet, page not fetched): https://www.amd.com/en/developer/resources/technical-articles/2026/day-0-support-for-gemma-4-on-amd-processors-and-gpus.html

## 1. Create the droplet
1. Join the AMD AI Developer Program for credits (about $100): https://lablab.ai/ai-articles/from-zero-to-ai-builder-amd-developer-program
2. https://devcloud.amd.com: add a payment method (Create GPU Droplet stays disabled without one) and your SSH public key.
3. Create GPU Droplet: 1x MI300X, image "ROCm" or the vLLM Quick Start (needs Docker). Region: any with MI300X capacity.
4. Cloud firewall: inbound 22 (your IP only), 80, 443. Nothing else. vLLM never gets a public port (see `tunnel.md`).

## 2. Bootstrap
```bash
ssh root@<DROPLET_IP>
git clone <your repo url> clario && cd clario
export HF_TOKEN=hf_...            # accept the Gemma license on Hugging Face first. Never written to disk.
deploy/amd/bootstrap.sh --app     # core + public app
```
Core always runs: preflight (`amd-smi`/`rocm-smi`, `/dev/kfd`, docker), pull images, start `vllm-big`, wait healthy (first start downloads about 62 GB of weights), `smoke.sh`. `VLLM_API_KEY` is generated into `deploy/amd/.env` (chmod 600, git-ignored) unless you export one. `PUBLIC_HOST` defaults to `<public ip>.sslip.io`.

Pick stages with flags (order is fixed: synth, train, eval, bench, app):

| flag | what it does | needs |
|---|---|---|
| `--synth N` | `train/synth.py` against `vllm-big`, N accepted rows, then `train/prep.py` (split by disease) | core |
| `--train` | builds `train/Dockerfile.rocm`, `train_rocm.py` LoRA r16 on E4B, adapter in `train/out/e4b-r16/adapter` | `--synth` done once |
| `--eval` | starts `vllm-small` with the adapter, `train/eval.py` for `base-e4b` and `ft-e4b-r16` | `--train` done once |
| `--bench` | `bench/bench.py` on 31B, label `amd-mi300x-gemma4-31b`, concurrency 1,8,32,64 | core |
| `--app` | compose up clinic, patient-demo, gpu-metrics, caddy; prints the URLs | core |

Full run: `deploy/amd/bootstrap.sh --synth 3000 --train --eval --bench --app`. Re-running skips finished stages (`FORCE=1` redoes them). Logs: `deploy/amd/logs/bootstrap-<time>.log` (no secrets are printed).

## 3. Open the URL
- Patient app: `https://<ip>.sslip.io` (set a passphrase, load the demo patient).
- Clinic console: `https://clinic.<ip>.sslip.io`. In the patient app, share to that clinic address.
- Both show the banner "Demo server: synthetic data only. Do not enter real health information."
- GPU numbers: `curl -s https://clinic.<ip>.sslip.io/api/system/gpu` returns `{gpu_name, util_pct, vram_used_gb, vram_total_gb}`, or `null` if telemetry is unavailable.
- Certificates take about a minute on first start. If nothing answers: firewall ports 80/443, then `docker compose -f deploy/amd/docker-compose.yml logs caddy`.

## 4. Collect results (copy to your laptop before destroying)
```bash
scp -r root@<ip>:clario/train/results   ./results-train   # eval: base-e4b.json, ft-e4b-r16.json (+ .md tables)
scp -r root@<ip>:clario/bench/results   ./results-bench
scp -r root@<ip>:clario/train/out/e4b-r16 ./e4b-r16        # adapter + metrics.json (wall time, tokens/s, peak memory)
scp -r root@<ip>:clario/deploy/amd/logs ./bootstrap-logs
```
Only numbers from these result files go into the UI, README or slides. `GET /api/bench` on the clinic serves `bench/results` live.

To show the fine-tuned extractor in the patient demo: `export PATIENT_LLM_MODEL=clario-extract` and re-run `deploy/amd/bootstrap.sh --app` (only once eval shows it beats base).

## 5. SHUT DOWN (credits)
Powering off does NOT stop billing. Destroy the droplet in the AMD Developer Cloud dashboard once the results are copied. Before that, on the droplet:
```bash
docker compose -f deploy/amd/docker-compose.yml down -v   # removes shared demo data volumes
```
Then rotate `VLLM_API_KEY` (it dies with the droplet) and revoke the HF token if it was a throwaway.

## 6. Cost (assumption, check the dashboard)
Hourly rate ASSUMED at **$2.00 per MI300X-hour** (derived from "about $100 of credit is about 50 h" in the AMD Developer Program notes; the real rate may differ). Durations below are guesses until the first real run.

| stage | guessed wall time | cost at $2.00/h |
|---|---|---|
| droplet up, image pull, 31B weights download + load | 0.5 to 1 h | $1 to $2 |
| `--synth 3000` through 31B | 0.5 to 1 h | $1 to $2 |
| `--train` E4B LoRA, 3 epochs | 0.5 to 1.5 h | $1 to $3 |
| `--eval` (E4B up, base + LoRA) | 0.25 h | $0.50 |
| `--bench` | 0.25 to 0.5 h | $0.50 to $1 |
| demo kept online (per hour, and per day) | 1 h / 24 h | $2 / $48 |
| **full run, then destroy** | **about 2.5 to 4.5 h** | **about $5 to $9** |
| full run + demo online for 48 h | | about $100 to $105 |

The demo-online rows are what burns credits. Destroy right after the judging window.

## Files
| file | role |
|---|---|
| `bootstrap.sh` | the one command |
| `docker-compose.yml` | vllm-big, vllm-small, gpu-metrics, clinic, patient-demo, caddy |
| `Caddyfile` | HTTPS for `<ip>.sslip.io` (patient) and `clinic.<ip>.sslip.io` |
| `smoke.sh` | structured-JSON check against any vLLM endpoint (`BASE_URL`, `MODEL`, `LORA`) |
| `serve_vllm.sh` | single-container fallback (31B only, loopback 8001); do not run together with the compose stack |
| `../docker-compose.clinic.yml` | clinic-only stack, single model |
| `tunnel.md` | reaching the servers without public exposure |

Root `.env.example` documents every variable. Compose can be validated anywhere (no GPU needed):
```bash
PUBLIC_HOST=x.sslip.io VLLM_API_KEY=x HF_TOKEN=x docker compose -f deploy/amd/docker-compose.yml config -q && echo ok
```

## GPU memory split
Each vLLM process sizes itself as a fraction of the whole card: `vllm-big` 0.62 (about 119 GB: 31B bf16 weights about 62 GB plus KV cache), `vllm-small` 0.22 (about 42 GB: E4B about 16 GB plus LoRA and KV). About 15% stays free for workspaces. Training E4B runs while only `vllm-big` is up (bootstrap stops `vllm-small` first). Start order matters: big first, small after it is healthy (compose enforces this). Tune with `BIG_GPU_UTIL`, `SMALL_GPU_UTIL`; 0.95 and above can OOM on ROCm.

## Troubleshooting
- vLLM fails on attention at startup: `export VLLM_ATTENTION_BACKEND=TRITON_ATTN` (AMD's Gemma 4 note) or `BIG_EXTRA_ARGS="--attention-backend TRITON_ATTN"`, re-run bootstrap.
- Image tag will not start Gemma 4: `export VLLM_IMAGE=vllm/vllm-openai-rocm:latest` (or `:nightly`).
- LoRA rejected by vLLM (Gemma 4 module names): serve the merged checkpoint instead. Train with `--merge` and point `SMALL_MODEL` at `train/out/e4b-r16/merged`.
- `/api/system/gpu` is `null`: check `curl -s localhost:9100` on the droplet; if amd-smi is missing from the vLLM image the sidecar returns null by design.
- Model load times out: raise `WAIT_SECS`; look at `docker compose -f deploy/amd/docker-compose.yml logs vllm-big`.

## Unverified (watch on the first real run)
- Real `amd-smi metric --json` / `static --json` shape on MI300X. The parser (`backend/clario/gpu.py`) follows AMD's docs and is tested against a sample of that documented shape only.
- That `amd-smi` exists inside the `vllm/vllm-openai-rocm` image used by the `gpu-metrics` sidecar. Fallback: run `python3 backend/clario/gpu.py 9100` on the host (it is stdlib only) and set `CLARIO_GPU_METRICS_URL=http://host.docker.internal:9100/` style access.
- Two vLLM processes sharing one MI300X at the 0.62 / 0.22 split.
- LoRA serving and the `TRITON_ATTN` need for Gemma 4 on ROCm.
- `ghcr.io/astral-sh/uv` container used by `--synth/--eval/--bench` and the `rocm/pytorch` training image on the droplet.
- Cost figures (assumed rate, guessed durations).

## Safety checklist
- [ ] vLLM not reachable from outside: `curl -m 5 http://<IP>:8000/v1/models` and `:8001` fail
- [ ] 443 serves a valid certificate for both hosts
- [ ] `VLLM_API_KEY` random, not in git
- [ ] Only synthetic data on the demo (banner is on; `CLARIO_DEMO_INSTANCE=1`)
- [ ] Droplet destroyed and credits checked after the demo
