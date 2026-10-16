#!/usr/bin/env bash
# One command on a fresh AMD Developer Cloud MI300X droplet: checks, pulls, starts the 31B model, smoke-tests it,
# then runs whichever optional stages you ask for.
#
#   export HF_TOKEN=hf_...                      # required (Gemma weights are gated). Never written to disk.
#   [export VLLM_API_KEY=...]                   # optional; generated into deploy/amd/.env (chmod 600) if absent
#   deploy/amd/bootstrap.sh [--synth N] [--train] [--eval] [--bench] [--app] [--skip-smoke]
#
# Stages run in this order: core (always) -> --synth -> --train -> --eval -> --bench -> --app
#   core      preflight, pull images, start vllm-big (Gemma 4 31B), wait healthy, smoke.sh
#   --synth N train/synth.py against vllm-big, N accepted rows, then train/prep.py
#   --train   train/Dockerfile.rocm image, train_rocm.py on Gemma 4 E4B (LoRA r16)
#   --eval    serve E4B + the adapter on vllm-small, train/eval.py for base and LoRA
#   --bench   bench/bench.py against vllm-big
#   --app     compose up clinic + patient-demo + gpu-metrics + caddy, prints the public URLs
# Idempotent: re-running skips finished stages (FORCE=1 redoes them). Logs: deploy/amd/logs/bootstrap-<time>.log.
# Optional env: PUBLIC_HOST (default <public-ip>.sslip.io), LORA_PATH (adapter dir, default train/out/e4b-r16/adapter),
#   HF_CACHE, VLLM_IMAGE, BIG_MODEL, SMALL_MODEL, WAIT_SECS, FORCE, PATIENT_LLM_MODEL (see .env.example).
set -euo pipefail
set +x  # never trace: the environment holds secrets

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
cd "$REPO"

SYNTH_N=0 DO_TRAIN=0 DO_EVAL=0 DO_BENCH=0 DO_APP=0 DO_SMOKE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --synth) SYNTH_N="${2:?--synth needs a number}"; shift 2 ;;
    --train) DO_TRAIN=1; shift ;;
    --eval) DO_EVAL=1; shift ;;
    --bench) DO_BENCH=1; shift ;;
    --app) DO_APP=1; shift ;;
    --skip-smoke) DO_SMOKE=0; shift ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done
case "$SYNTH_N" in ''|*[!0-9]*) echo "--synth needs a whole number" >&2; exit 2 ;; esac

mkdir -p "$HERE/logs"
LOG="$HERE/logs/bootstrap-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
say() { printf '\n== %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
echo "log: $LOG"

# ---------------------------------------------------------------- env
ENV_FILE="$HERE/.env"
env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1 || true; }
env_set() { # never prints the value
  touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
  grep -v "^$1=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"; chmod 600 "$ENV_FILE"
}

say "preflight"
command -v docker >/dev/null || die "docker not found"
docker compose version >/dev/null 2>&1 || die "docker compose plugin not found"
if command -v amd-smi >/dev/null; then amd-smi static >/dev/null 2>&1 && echo "amd-smi: ok" || echo "WARN: amd-smi present but failed"
elif command -v rocm-smi >/dev/null; then rocm-smi >/dev/null 2>&1 && echo "rocm-smi: ok" || echo "WARN: rocm-smi present but failed"
else die "neither amd-smi nor rocm-smi found. Is this a ROCm (MI300X) droplet?"; fi
[ -e /dev/kfd ] && [ -d /dev/dri ] || die "/dev/kfd or /dev/dri missing: no AMD GPU visible to this host"
[ -n "${HF_TOKEN:-}" ] || die "export HF_TOKEN=hf_... first (Gemma weights are gated; accept the license on Hugging Face)"
export HF_TOKEN

if [ -z "${VLLM_API_KEY:-}" ]; then
  VLLM_API_KEY="$(env_get VLLM_API_KEY)"
  if [ -z "$VLLM_API_KEY" ]; then
    VLLM_API_KEY="$(openssl rand -hex 24)"; env_set VLLM_API_KEY "$VLLM_API_KEY"
    echo "generated VLLM_API_KEY, stored in deploy/amd/.env (chmod 600, git-ignored)"
  else
    echo "VLLM_API_KEY: from deploy/amd/.env"
  fi
fi
export VLLM_API_KEY

if [ -z "${PUBLIC_HOST:-}" ]; then
  PUBLIC_HOST="$(env_get PUBLIC_HOST)"
  if [ -z "$PUBLIC_HOST" ]; then
    ip="$(curl -fsS -m 8 https://api.ipify.org 2>/dev/null || curl -fsS -m 8 https://ifconfig.me 2>/dev/null || true)"
    case "$ip" in *[!0-9.]*|'') PUBLIC_HOST="" ;; *) PUBLIC_HOST="$ip.sslip.io" ;; esac
  fi
fi
[ -n "$PUBLIC_HOST" ] && { export PUBLIC_HOST; env_set PUBLIC_HOST "$PUBLIC_HOST"; }
[ -n "${PUBLIC_HOST:-}" ] || { [ "$DO_APP" = 0 ] || die "could not detect the public IP; export PUBLIC_HOST=<ip>.sslip.io"; export PUBLIC_HOST=localhost; }

DC=(docker compose -f "$HERE/docker-compose.yml")
BIG_MODEL="${BIG_MODEL:-google/gemma-4-31B-it}"
SMALL_MODEL="${SMALL_MODEL:-google/gemma-4-E4B-it}"
BIG_URL="http://127.0.0.1:8000/v1"
SMALL_URL="http://127.0.0.1:8001/v1"
WAIT_SECS="${WAIT_SECS:-2400}"
RUN="e4b-r16"
ADAPTER_DEFAULT="$REPO/train/out/$RUN/adapter"
FORCE="${FORCE:-0}"

# Keep the adapter wiring identical on every compose call, so a later `up` never silently drops it.
lora_env() {
  local p="${LORA_PATH:-}"
  [ -z "$p" ] && [ -f "$ADAPTER_DEFAULT/adapter_config.json" ] && p="$ADAPTER_DEFAULT"
  if [ -n "$p" ] && [ -f "$p/adapter_config.json" ]; then
    export LORA_PATH="$p"
    export SMALL_LORA_ARGS="--enable-lora --lora-modules clario-extract=/lora/clario-extract --max-lora-rank ${LORA_RANK:-16}"
  fi
}

wait_http() { # url label secs service
  local url="$1" label="$2" secs="$3" svc="${4:-}" t0; t0=$(date +%s)
  echo "waiting for $label (up to ${secs}s; first start downloads weights)"
  until curl -fsS -m 5 "$url" >/dev/null 2>&1; do
    if [ -n "$svc" ]; then
      local cid; cid="$("${DC[@]}" ps -aq "$svc" 2>/dev/null | head -n1)"
      if [ -n "$cid" ] && [ "$(docker inspect -f '{{.State.Status}}' "$cid")" = "exited" ]; then
        "${DC[@]}" logs --tail 60 "$svc" >&2; die "$svc exited. See logs above and deploy/amd/README.md (troubleshooting)"
      fi
    fi
    [ $(( $(date +%s) - t0 )) -lt "$secs" ] || { [ -z "$svc" ] || "${DC[@]}" logs --tail 60 "$svc" >&2; die "$label not ready after ${secs}s"; }
    sleep 10
  done
  echo "$label ready"
}

# Run a python script from the repo in a throwaway uv container (host needs nothing but docker).
pyrun() {
  docker run --rm --network host --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e UV_CACHE_DIR=/tmp/uv-cache -e UV_PROJECT_ENVIRONMENT=/tmp/venv -e VLLM_API_KEY \
    -v "$REPO:/repo" -w /repo ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
    uv run --project backend --with requests python "$@"
}

# ---------------------------------------------------------------- core
lora_env
mkdir -p "$REPO/bench/results"   # bind-mounted read-only into the apps (GET /api/bench)
say "pull images"
"${DC[@]}" pull --ignore-buildable vllm-big vllm-small gpu-metrics caddy
docker pull ghcr.io/astral-sh/uv:python3.12-bookworm-slim >/dev/null

say "start vllm-big ($BIG_MODEL)"
"${DC[@]}" up -d vllm-big
wait_http "http://127.0.0.1:8000/health" "vllm-big" "$WAIT_SECS" vllm-big

if [ "$DO_SMOKE" = 1 ]; then
  say "smoke test"
  BASE_URL="$BIG_URL" MODEL="$BIG_MODEL" bash "$HERE/smoke.sh"
fi

# ---------------------------------------------------------------- --synth
if [ "$SYNTH_N" -gt 0 ]; then
  say "synth: $SYNTH_N rows from $BIG_MODEL"
  OUT="$REPO/train/data/synth/synth.jsonl"
  have=0; [ -f "$OUT" ] && have="$(wc -l < "$OUT" | tr -d ' ')"
  if [ "$FORCE" != 1 ] && [ "$have" -ge "$SYNTH_N" ]; then
    echo "skip: $OUT already has $have rows (FORCE=1 to redo)"
  else
    mkdir -p "$REPO/train/data/synth"
    pyrun train/synth.py --base-url "$BIG_URL" --model "$BIG_MODEL" --api-key-env VLLM_API_KEY --n "$SYNTH_N" --concurrency 32
  fi
  pyrun train/prep.py
fi

# ---------------------------------------------------------------- --train
if [ "$DO_TRAIN" = 1 ]; then
  say "train: LoRA on $SMALL_MODEL"
  if [ "$FORCE" != 1 ] && [ -f "$ADAPTER_DEFAULT/adapter_config.json" ]; then
    echo "skip: adapter exists at $ADAPTER_DEFAULT (FORCE=1 to retrain)"
  else
    [ -f "$REPO/train/data/v3/train_sft.jsonl" ] || pyrun train/prep.py || die "no training data: run with --synth N first"
    [ -f "$REPO/train/data/v3/train_sft.jsonl" ] || die "prep.py wrote no train/data/v3/train_sft.jsonl: run with --synth N first"
    "${DC[@]}" stop vllm-small >/dev/null 2>&1 || true   # free its GPU share for training
    docker build -f train/Dockerfile.rocm -t clario-train train
    mkdir -p "$REPO/train/out" "${HF_CACHE:-$HOME/.cache/huggingface}"
    docker run --rm --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --shm-size 64G \
      --security-opt seccomp=unconfined -e HF_TOKEN \
      -v "$REPO/train:/workspace/train" -v "${HF_CACHE:-$HOME/.cache/huggingface}:/workspace/hf-cache" clario-train \
      bash -c "python train_rocm.py --model $SMALL_MODEL --data data/v3/train_sft.jsonl --out out/$RUN --epochs 3 --bf16; rc=\$?; chown -R $(id -u):$(id -g) out data || true; exit \$rc"       || die "training failed: see the log above (train/out/$RUN may be incomplete)"
  fi
  lora_env
fi

# ---------------------------------------------------------------- --eval
if [ "$DO_EVAL" = 1 ]; then
  say "eval: base vs LoRA on $SMALL_MODEL"
  [ -f "$REPO/train/data/v3/test.jsonl" ] || pyrun train/prep.py || die "no test split: run with --synth N first"
  lora_env
  "${DC[@]}" up -d vllm-small
  wait_http "http://127.0.0.1:8001/health" "vllm-small" "$WAIT_SECS" vllm-small
  RES="$REPO/eval/results"   # eval.py writes extraction_<label>.json here
  if [ "$FORCE" = 1 ] || [ ! -f "$RES/extraction_base-e4b.json" ]; then
    pyrun train/eval.py --base-url "$SMALL_URL" --model "$SMALL_MODEL" --label base-e4b --api-key-env VLLM_API_KEY --concurrency 8
  else echo "skip base-e4b (results exist)"; fi
  if [ -n "${LORA_PATH:-}" ]; then
    if [ "$FORCE" = 1 ] || [ ! -f "$RES/extraction_ft-e4b-r16.json" ]; then
      pyrun train/eval.py --base-url "$SMALL_URL" --model clario-extract --label ft-e4b-r16 --api-key-env VLLM_API_KEY --concurrency 8
    else echo "skip ft-e4b-r16 (results exist)"; fi
  else
    echo "WARN: no adapter found (run --train first); evaluated the base model only"
  fi
fi

# ---------------------------------------------------------------- --bench
if [ "$DO_BENCH" = 1 ]; then
  say "bench: $BIG_MODEL on MI300X"
  LABEL="amd-mi300x-gemma4-31b"
  if [ "$FORCE" != 1 ] && ls "$REPO"/bench/results/"$LABEL"-*.json >/dev/null 2>&1; then
    echo "skip: bench/results/$LABEL-*.json exists (FORCE=1 to redo)"
  else
    mkdir -p "$REPO/bench/results"
    LLM_API_KEY="$VLLM_API_KEY" pyrun bench/bench.py --base-url "$BIG_URL" --model "$BIG_MODEL" --label "$LABEL" \
      --workload both --concurrency 1,8,32,64 --n 64 --stream
  fi
fi

# ---------------------------------------------------------------- --app
if [ "$DO_APP" = 1 ]; then
  say "app: clinic + patient-demo + gpu-metrics + caddy"
  lora_env
  "${DC[@]}" up -d --build vllm-small gpu-metrics clinic patient-demo caddy
  wait_http "http://127.0.0.1:9100/" "gpu-metrics" 120 gpu-metrics
  echo "gpu telemetry: $(curl -fsS -m 5 http://127.0.0.1:9100/ || echo unavailable)"
  echo "waiting for the certificates (Caddy needs ports 80/443 reachable from the internet)"
  for u in "https://$PUBLIC_HOST" "https://clinic.$PUBLIC_HOST"; do
    ok=0
    for _ in $(seq 1 30); do
      curl -fsS -m 8 "$u/api/health" >/dev/null 2>&1 && { ok=1; break; }; sleep 6
    done
    [ "$ok" = 1 ] && echo "up: $u" || echo "WARN: $u not answering yet (check the cloud firewall and: ${DC[*]} logs caddy)"
  done
  cat <<EOF

  Patient app (demo)  https://$PUBLIC_HOST
  Clinic console      https://clinic.$PUBLIC_HOST
  GPU telemetry       https://clinic.$PUBLIC_HOST/api/system/gpu

  vLLM is bound to this host's loopback only. When you are done: destroy the droplet (powering off still bills).
EOF
fi

say "done. log: $LOG"
