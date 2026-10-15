# Clario on AMD Developer Cloud (one MI300X, one command)

Result: a public HTTPS demo. The patient app (Gemma 4 E4B) at `https://<ip>.sslip.io`, the clinic console (Gemma 4 31B, live GPU panel) at `https://clinic.<ip>.sslip.io`, both on one MI300X (192 GB) through vLLM. Optional stages generate synthetic data, fine-tune a LoRA on the droplet, evaluate base vs LoRA, and benchmark.

Status: everything here was validated off-box only (compose files with `docker compose config`, the app image built and run locally, the step runner against a stand-in HTTP endpoint). Nothing has run on a real MI300X yet. The "Unverified" list at the bottom says what to watch.

## Quick start: every number in one command
```bash
export HF_TOKEN=hf_...                    # accept the Gemma licence on Hugging Face first
deploy/amd/bootstrap.sh --all --app       # preflight, serve, health, smoke, synth, prep, train, eval, bench, results, then the public demo
```
A failure stops the run, names the step and prints the exact rerun line. A finished step leaves a stamp in `deploy/amd/logs/stamps/` and is skipped next time, so rerunning `--all` resumes where it stopped. Useful forms:
```bash
deploy/amd/bootstrap.sh --list                 # steps, stamps, what would run
deploy/amd/bootstrap.sh --step bench           # rerun one step alone (ignores its stamp)
FORCE=1 deploy/amd/bootstrap.sh --all          # redo everything
SYNTH_N=1500 deploy/amd/bootstrap.sh --all     # smaller data set (default 3000)
```

## 0. Facts checked (2026-10-12, docs only)
- Model ids: `google/gemma-4-31B-it` (31B dense, 1x MI300X in BF16, per the vLLM Gemma 4 recipe https://docs.vllm.ai/projects/recipes/en/latest/Google/Gemma4.html) and `google/gemma-4-E4B-it`.
- Image `vllm/vllm-openai-rocm:v0.31.0` exists on Docker Hub (tags also `v0.30.0`, `latest`, `nightly`). Pinned to `v0.31.0`.
- Re-checked 2026-10-16: `v0.31.0` is still the newest release tag (pushed 2026-10-04; `v0.30.0` before it). The vLLM Gemma 4 recipe names `vllm/vllm-openai-rocm:latest` for MI300X and gives no attention flag, no max-model-len for AMD (32768 appears in its other examples), mentions `--kv-cache-dtype fp8` as a memory option and `--no-enable-prefix-caching` only for benchmarking, and relies on `response_format` json_schema for structured output: https://docs.vllm.ai/projects/recipes/en/latest/Google/Gemma4.html
- AMD's ROCm guide prefers the default ROCM_ATTN backend and offers TRITON_ATTN as the fallback: https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/optimization/vllm-v1-optimization.html . AMD's day-0 Gemma 4 note (https://www.amd.com/en/developer/resources/technical-articles/2026/day-0-support-for-gemma-4-on-amd-processors-and-gpus.html) timed out on fetch, so the earlier claim that Gemma 4 needs TRITON_ATTN is unconfirmed. Default backend first, automatic TRITON_ATTN retry second.
- Settings kept: `--max-model-len 16384` (big) and 8192 (small) cover the prompts here with room; `--enable-prefix-caching` on (the brief workload shares a 2k-token prefix); fp8 KV cache off by default.

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

Older per-stage flags still work (order is fixed: synth, train, eval, bench, app):

| flag | what it does | needs |
|---|---|---|
| `--synth N` | `train/synth.py` against `vllm-big`, N accepted rows, then `train/prep.py` (split by disease) | core |
| `--train` | builds `train/Dockerfile.rocm`, `train_rocm.py` LoRA r16 on E4B, adapter in `train/out/e4b-r16/adapter` | `--synth` done once |
| `--eval` | starts `vllm-small` with the adapter, `train/eval.py` for `base-e4b` and `ft-e4b-r16` | `--train` done once |
| `--bench` | `bench/bench.py` on 31B, label `amd-mi300x-gemma4-31b`, concurrency 1,8,32,64 | core |
| `--app` | compose up clinic, patient-demo, gpu-metrics, caddy; prints the URLs | core |

Full run: `deploy/amd/bootstrap.sh --all --app`. Logs: `deploy/amd/logs/bootstrap-<time>.log` (no secrets are printed).

### The steps
| step | what it does | writes |
|---|---|---|
| `preflight` | amd-smi or rocm-smi present, `/dev/kfd`, docker, free disk (`DISK_MIN_GB`, default 200), `HF_TOKEN` valid, licence accepted for both Gemma models (HTTP check on each `config.json`), hardware record | `logs/stamps/hardware.json` |
| `serve` | pull images, start `vllm-big` | |
| `health` | wait for `vllm-big`; if it exits on an attention error, retries once with `VLLM_ATTENTION_BACKEND=TRITON_ATTN` and remembers that in `deploy/amd/.env` | |
| `smoke` | structured-JSON check via `smoke.sh` | |
| `synth` | `train/synth.py` against `vllm-big` (refuses anthropic.com) | `train/data/synth/synth.jsonl` |
| `prep` | `train/prep.py`, split held out by disease | `train/data/v3/*` |
| `train` | LoRA r16 on Gemma 4 E4B (`train_rocm.py`) | `train/out/e4b-r16/`, `eval/results/train_e4b-r16.json` |
| `eval` | base vs tuned on the held-out split (plain prompt for F1, a `--confidence` run each for the review curve), plus gold and PsyTAR sets when present, then `eval/review_curve.py` | `eval/results/extraction_*.json`, `review_curve_*.json` |
| `bench` | `bench/bench.py` on the 31B: tokens/s, p50/p95, TTFT, concurrency 1/8/32, self-consistency n=5 cost, GPU utilisation from amd-smi sampled on the host | `eval/results/bench_amd-mi300x-gemma4-31b.json`, `bench/results/*` |
| `results` | `eval/make_results_md.py --check`: every result file must carry n, dataset, model, backend, date and a `hardware` field | `eval/RESULTS.md` |

Every result file records `hardware` (`gpu_name`, `gpu_count`, `vram_total_gb`, `source`) detected once on the host by `eval/hardware.py`, so containers without amd-smi still label their output. `EVAL_BIG=1` also scores the 31B on the extraction set.

### Fallback: any OpenAI-compatible endpoint
If the droplet is late, run the same synth, prep, eval, bench and results steps against a hosted endpoint:
```bash
export BASE_URL=https://<host>/v1 API_KEY=... MODEL=<served model name>
export TUNED_MODEL=<adapter name>            # optional; scored as hosted-tuned next to hosted-base
export BACKEND_LABEL=amd-hosted              # what the result files call the backend (default hosted-openai-compatible)
export HARDWARE_LABEL="AMD Instinct MI300X"  # only claim what the provider states (default: unknown (hosted endpoint))
deploy/amd/bootstrap.sh --fallback --all
```
No docker, GPU or HF token is needed. GPU utilisation columns stay empty because amd-smi is not on the box. A hosted result must keep its `backend` label: only runs on the droplet may be called `vllm-rocm-mi300x`. anthropic.com is refused as a generator and as a bench target.

## 3. Open the URL
- Patient app: `https://<ip>.sslip.io` (set a passphrase, load the demo patient).
- Clinic console: `https://clinic.<ip>.sslip.io`. In the patient app, share to that clinic address.
- Both show the banner "Demo server: synthetic data only. Do not enter real health information."
- GPU numbers: `curl -s https://clinic.<ip>.sslip.io/api/system/gpu` returns `{gpu_name, util_pct, vram_used_gb, vram_total_gb}`, or `null` if telemetry is unavailable.
- Certificates take about a minute on first start. If nothing answers: firewall ports 80/443, then `docker compose -f deploy/amd/docker-compose.yml logs caddy`.

## 4. Collect results (copy to your laptop before destroying)
```bash
scp -r root@<ip>:clario/eval/results    ./results-eval    # extraction_*.json, review_curve_*.json, train_*.json, bench_*.json, ../RESULTS.md
scp    root@<ip>:clario/eval/RESULTS.md ./RESULTS.md
scp -r root@<ip>:clario/bench/results   ./results-bench
scp -r root@<ip>:clario/train/out/e4b-r16 ./e4b-r16        # adapter + metrics.json (wall time, tokens/s, peak memory)
scp -r root@<ip>:clario/deploy/amd/logs ./bootstrap-logs
```
Only numbers from these result files go into the UI, README or slides. `GET /api/bench` on the clinic serves `bench/results` live.

To show the fine-tuned extractor in the patient demo: `export PATIENT_LLM_MODEL=clario-extract` and re-run `deploy/amd/bootstrap.sh --app` (only once eval shows it beats base).

## 4b. Capture checklist for the demo video and screenshots
Take these on the droplet while the stack is up. Do the first two before `--step bench` ends, since the load is the point.
| # | what | how | file name |
|---|---|---|---|
| 1 | amd-smi during load | second SSH window: `watch -n1 amd-smi metric`, then run `deploy/amd/bootstrap.sh --step bench`; record at least 60 s covering concurrency 8 and 32 | `01-amd-smi-under-load.mp4` |
| 2 | bench terminal output | the `bench: ...` step and its final markdown table (tokens/s, p50/p95, GPU util columns) | `02-bench-output.png` |
| 3 | GPU panel in the app | clinic console in the browser with the GPU panel visible while a brief is generating | `03-gpu-panel.png` |
| 4 | `/api/system/gpu` | `curl -s https://clinic.<ip>.sslip.io/api/system/gpu` in the terminal next to amd-smi | `04-api-system-gpu.png` |
| 5 | model on MI300X | `amd-smi static` and `docker ps` showing vllm-big and vllm-small on one card | `05-amd-smi-static.png` |
| 6 | training | the `train:` step with the step time and tokens/s lines, then `eval/results/train_e4b-r16.json` | `06-training.png` |
| 7 | base vs tuned | the `eval` step tables for `base-e4b` and `ft-e4b-r16`, then `eval/RESULTS.md` | `07-eval-base-vs-tuned.png` |
| 8 | review curve | `review_curve_*conf.json` lines (share routed to review at 1, 2, 5 percent) | `08-review-curve.png` |
| 9 | the one-command run | a single screen recording of `deploy/amd/bootstrap.sh --list` and the tail of an `--all` run ending in `done` | `09-one-command.mp4` |
| 10 | patient and clinic apps | both public URLs with the synthetic-data banner visible | `10-apps.png` |
Convert any screen recording to .mp4 (h264) before submitting.

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
| `bootstrap.sh` | the one command (`--all`, `--step`, `--list`, `--fallback`) |
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
- vLLM fails on attention at startup: bootstrap retries once with `VLLM_ATTENTION_BACKEND=TRITON_ATTN` on its own. By hand: `export VLLM_ATTENTION_BACKEND=TRITON_ATTN` or `BIG_EXTRA_ARGS="--attention-backend TRITON_ATTN"`, then `deploy/amd/bootstrap.sh --step health`.
- A step failed: the message ends with the rerun line. Fix the cause, run that line, then `deploy/amd/bootstrap.sh --all` continues after it.
- `licence not accepted`: open the model page on Hugging Face with the account that owns the token, accept the terms, `--step preflight`.
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
