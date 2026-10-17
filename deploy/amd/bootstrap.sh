#!/usr/bin/env bash
# One command on a fresh AMD Developer Cloud MI300X droplet: every number the submission needs, resumable.
#
#   export HF_TOKEN=hf_...                      # required (Gemma weights are gated). Never written to disk.
#   [export VLLM_API_KEY=...]                   # optional; generated into deploy/amd/.env (chmod 600) if absent
#   deploy/amd/bootstrap.sh --all [--app]       # the whole pipeline (see steps), then optionally the public demo
#   deploy/amd/bootstrap.sh --step bench        # rerun ONE step alone (ignores its stamp)
#   deploy/amd/bootstrap.sh --list              # steps, stamps and what a run would do (no side effects)
#
# STEPS, in this order (each writes a stamp in deploy/amd/logs/stamps/; a finished step is skipped on rerun):
#   preflight  amd-smi/rocm-smi, /dev/kfd, docker, disk, HF_TOKEN, licence accepted for both Gemma models, hardware record
#   serve      pull images, start vllm-big (Gemma 4 31B)
#   health     wait for vllm-big (retries once with TRITON_ATTN if the attention backend is what failed)
#   smoke      structured-JSON check (smoke.sh)
#   lay        train/lay_expand.py: verified everyday English phrasings per HPO term (train/lay_lexicon.json, LAY_TERMS
#              most frequent terms, default 800); the synth step uses them to word the symptoms
#   synth      train/synth.py against vllm-big (SYNTH_N rows, default 3000), generator is never anthropic.com
#   prep       train/prep.py (disease-held-out train/val/test)
#   train      LoRA r16 on Gemma 4 E4B (train_rocm.py), eval/results/train_e4b-r16.json
#   eval       base vs tuned: extraction F1 (+ a --confidence run each, then eval/review_curve.py), then the conformal review
#              threshold: --sc-n ${CLARIO_SC_N:-5} run with the app prompt -> review_curve.py --source sc -> eval/conformal.py
#              -> eval/results/conformal_threshold.json (alpha ${CLARIO_REVIEW_ALPHA:-0.05} and 0.10; the app picks it up)
#   bench      bench/bench.py on vllm-big: tokens/s, p50/p95, concurrency 1/8/32, self-consistency n=5 cost, GPU util
#   results    eval/make_results_md.py --check (every result file has n, dataset, model, backend, date, hardware)
#   app        (not in --all) compose up clinic + patient-demo + gpu-metrics + caddy, prints the public URLs
# Back-compat flags: --lay, --synth N (synth+prep), --train, --eval, --bench, --app, --skip-smoke.
#
# FALLBACK (droplet late): --fallback runs lay, synth, prep, eval, bench, results against any OpenAI-compatible endpoint.
#   BASE_URL=https://host/v1 API_KEY=... MODEL=name [TUNED_MODEL=name] [BACKEND_LABEL=amd-hosted] [HARDWARE_LABEL="AMD Instinct MI300X"]
#   deploy/amd/bootstrap.sh --fallback --all
#   Results are labelled with BACKEND_LABEL (default hosted-openai-compatible) and the hardware you state (default
#   "unknown (hosted endpoint)"). anthropic.com is refused as a generator and as a bench target.
#
# Failure: the script stops, names the step, and prints the exact rerun command. Logs: deploy/amd/logs/bootstrap-<time>.log.
# Optional env: PUBLIC_HOST, LORA_PATH, HF_CACHE, VLLM_IMAGE, BIG_MODEL, SMALL_MODEL, WAIT_SECS, FORCE=1 (redo stamped
#   steps), SYNTH_N, LAY_TERMS (800), BENCH_CONC (default 1,8,32), BENCH_N (64), DISK_MIN_GB (200), EVAL_BIG=1 (also score the 31B).
set -euo pipefail
set +x  # never trace: the environment holds secrets

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
cd "$REPO"

ALL_STEPS="preflight serve health smoke lay synth prep train eval bench results"
FALLBACK_STEPS="lay synth prep eval bench results"
STAMPS="$HERE/logs/stamps"

WANT=""          # space separated steps requested
ONLY=""          # --step: rerun these alone, ignoring stamps
FALLBACK=0 LIST=0 DO_APP=0 SKIP_SMOKE=0
SYNTH_N="${SYNTH_N:-0}"
want() { case " $WANT " in *" $1 "*) ;; *) WANT="$WANT $1" ;; esac; }
valid_step() { case " $ALL_STEPS app " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
while [ $# -gt 0 ]; do
  case "$1" in
    --all) ALLFLAG=1; shift ;;
    --step) valid_step "${2:?--step needs a name}" || { echo "unknown step: $2 (try --list)" >&2; exit 2; }
            ONLY="$ONLY $2"; shift 2 ;;
    --fallback) FALLBACK=1; shift ;;
    --list) LIST=1; shift ;;
    --lay) want lay; shift ;;
    --synth) SYNTH_N="${2:?--synth needs a number}"; want synth; want prep; shift 2 ;;
    --train) want train; shift ;;
    --eval) want eval; shift ;;
    --bench) want bench; shift ;;
    --app) DO_APP=1; shift ;;
    --skip-smoke) SKIP_SMOKE=1; shift ;;
    -h|--help) sed -n '2,36p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1 (try --help)" >&2; exit 2 ;;
  esac
done
case "$SYNTH_N" in ''|*[!0-9]*) echo "SYNTH_N / --synth needs a whole number" >&2; exit 2 ;; esac

if [ "${ALLFLAG:-0}" = 1 ]; then
  if [ "$FALLBACK" = 1 ]; then for s in $FALLBACK_STEPS; do want "$s"; done
  else for s in $ALL_STEPS; do want "$s"; done; fi
  [ "$SYNTH_N" -gt 0 ] || SYNTH_N=3000
fi
[ "$SYNTH_N" -gt 0 ] || SYNTH_N=3000
if [ -z "$WANT$ONLY" ] && [ "$LIST" = 0 ] && [ "$DO_APP" = 0 ]; then
  echo "nothing to do: pass --all, --step NAME, --list or --app (see --help)" >&2; exit 2
fi
# Old behaviour: any partial flag run still performed the core (preflight..smoke) first.
if { [ -n "$WANT" ] || [ "$DO_APP" = 1 ]; } && [ "$FALLBACK" = 0 ] && [ -z "$ONLY" ]; then
  for s in preflight serve health; do want "$s"; done
  [ "$SKIP_SMOKE" = 1 ] || want smoke
fi
# Steps in canonical order.
ORDER=""
for s in $ALL_STEPS; do
  case " $WANT " in *" $s "*) ORDER="$ORDER $s" ;; esac
done
[ "$DO_APP" = 0 ] || [ -n "$ONLY" ] || ORDER="$ORDER app"
[ -z "$ONLY" ] || ORDER="$ONLY"
# A fallback run always starts with the endpoint check.
if [ "$FALLBACK" = 1 ] && [ -z "$ONLY" ] && [ -n "$ORDER" ]; then ORDER=" preflight$ORDER"; fi

stamp_file() { echo "$STAMPS/$1.done"; }
if [ "$LIST" = 1 ]; then
  echo "mode: $([ "$FALLBACK" = 1 ] && echo "fallback (BASE_URL endpoint)" || echo "droplet (vLLM ROCm compose)")"
  for s in $ALL_STEPS app; do
    mark="todo"; [ -f "$(stamp_file "$s")" ] && mark="done $(cat "$(stamp_file "$s")")"
    sel=" "; case " $ORDER " in *" $s "*) sel="*" ;; esac
    printf '  %s %-10s %s\n' "$sel" "$s" "$mark"
  done
  echo "(* = would run; FORCE=1 or --step redoes a finished step)"
  exit 0
fi

mkdir -p "$HERE/logs" "$STAMPS"
LOG="$HERE/logs/bootstrap-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
say() { printf '\n== %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
echo "log: $LOG"

# ---------------------------------------------------------------- env (every run, cheap, no side effects on the GPU)
ENV_FILE="$HERE/.env"
env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1 || true; }
env_set() { # never prints the value
  touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
  grep -v "^$1=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"; chmod 600 "$ENV_FILE"
}

FORCE="${FORCE:-0}"
BIG_MODEL="${BIG_MODEL:-google/gemma-4-31B-it}"
SMALL_MODEL="${SMALL_MODEL:-google/gemma-4-E4B-it}"
WAIT_SECS="${WAIT_SECS:-2400}"
RUN="e4b-r16"
ADAPTER_DEFAULT="$REPO/train/out/$RUN/adapter"
BENCH_CONC="${BENCH_CONC:-1,8,32}"
BENCH_N="${BENCH_N:-64}"
HF_CACHE_DIR="${HF_CACHE:-$HOME/.cache/huggingface}"
DC=(docker compose -f "$HERE/docker-compose.yml")
EVAL_DATASET="synthetic-v3-test"

if [ "$FALLBACK" = 1 ]; then
  : "${BASE_URL:?fallback needs BASE_URL (OpenAI-compatible, ending in /v1)}"
  : "${API_KEY:?fallback needs API_KEY}"
  : "${MODEL:?fallback needs MODEL}"
  case "$BASE_URL" in *anthropic.com*) die "anthropic.com is refused: Claude is never a generator or an AMD result" ;; esac
  BACKEND_LABEL="${BACKEND_LABEL:-hosted-openai-compatible}"
  BIG_URL="$BASE_URL"; SMALL_URL="$BASE_URL"; BIG_MODEL="$MODEL"; SMALL_MODEL="$MODEL"
  VLLM_API_KEY="$API_KEY"; export VLLM_API_KEY
  HW_NAME="${HARDWARE_LABEL:-unknown (hosted endpoint)}"
  CLARIO_HARDWARE="$(python3 -c 'import json,sys; print(json.dumps({"gpu_name": sys.argv[1], "gpu_count": None, "vram_total_gb": None, "source": "env"}))' "$HW_NAME")"
  export CLARIO_HARDWARE
  BENCH_LABEL="hosted-$(printf '%s' "$MODEL" | tr -c 'A-Za-z0-9\n' '-' | tr 'A-Z' 'a-z')"
  EVAL_BASE_LABEL="hosted-base"; EVAL_TUNED_LABEL="hosted-tuned"
else
  BACKEND_LABEL="vllm-rocm-mi300x"
  BIG_URL="http://127.0.0.1:8000/v1"; SMALL_URL="http://127.0.0.1:8001/v1"
  BENCH_LABEL="amd-mi300x-gemma4-31b"
  EVAL_BASE_LABEL="base-e4b"; EVAL_TUNED_LABEL="ft-e4b-r16"
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
  if [ -z "${VLLM_ATTENTION_BACKEND:-}" ]; then
    VLLM_ATTENTION_BACKEND="$(env_get VLLM_ATTENTION_BACKEND)"   # set by an earlier auto-retry
  fi
  export VLLM_ATTENTION_BACKEND="${VLLM_ATTENTION_BACKEND:-}"
  if [ -z "${PUBLIC_HOST:-}" ]; then
    PUBLIC_HOST="$(env_get PUBLIC_HOST)"
    if [ -z "$PUBLIC_HOST" ]; then
      ip="$(curl -fsS -m 8 https://api.ipify.org 2>/dev/null || curl -fsS -m 8 https://ifconfig.me 2>/dev/null || true)"
      case "$ip" in *[!0-9.]*|'') PUBLIC_HOST="" ;; *) PUBLIC_HOST="$ip.sslip.io" ;; esac
    fi
  fi
  [ -z "$PUBLIC_HOST" ] || { export PUBLIC_HOST; env_set PUBLIC_HOST "$PUBLIC_HOST"; }
  case " $ORDER " in *" app "*) [ -n "${PUBLIC_HOST:-}" ] || die "could not detect the public IP; export PUBLIC_HOST=<ip>.sslip.io" ;; esac
  [ -n "${PUBLIC_HOST:-}" ] || export PUBLIC_HOST=localhost
  # Hardware record: detected on the host (containers have no amd-smi), exported so every result file is labelled.
  if [ -f "$STAMPS/hardware.json" ] && [ "$FORCE" != 1 ]; then CLARIO_HARDWARE="$(tr -d '\n' < "$STAMPS/hardware.json")"
  else CLARIO_HARDWARE="$(python3 "$REPO/eval/hardware.py" | tr -d '\n')"; fi
  export CLARIO_HARDWARE
fi

# Keep the adapter wiring identical on every compose call, so a later `up` never silently drops it.
lora_env() {
  local p="${LORA_PATH:-}"
  [ -z "$p" ] && [ -f "$ADAPTER_DEFAULT/adapter_config.json" ] && p="$ADAPTER_DEFAULT"
  if [ -n "$p" ] && [ -f "$p/adapter_config.json" ]; then
    export LORA_PATH="$p"
    export SMALL_LORA_ARGS="--enable-lora --lora-modules clario-extract=/lora/clario-extract --max-lora-rank ${LORA_RANK:-16}"
  fi
}

# wait_http url label secs [service]: returns 1 (with logs) if the service exits or the time runs out.
wait_http() {
  local url="$1" label="$2" secs="$3" svc="${4:-}" t0; t0=$(date +%s)
  echo "waiting for $label (up to ${secs}s; first start downloads weights)"
  until curl -fsS -m 5 -H "Authorization: Bearer ${VLLM_API_KEY:-}" "$url" >/dev/null 2>&1; do
    if [ -n "$svc" ]; then
      local cid; cid="$("${DC[@]}" ps -aq "$svc" 2>/dev/null | head -n1)"
      if [ -n "$cid" ] && [ "$(docker inspect -f '{{.State.Status}}' "$cid")" = "exited" ]; then
        "${DC[@]}" logs --tail 80 "$svc" >&2 || true; echo "$svc exited" >&2; return 1
      fi
    fi
    if [ $(( $(date +%s) - t0 )) -ge "$secs" ]; then
      [ -z "$svc" ] || "${DC[@]}" logs --tail 80 "$svc" >&2 || true
      echo "$label not ready after ${secs}s" >&2; return 1
    fi
    sleep 10
  done
  echo "$label ready"
}

# Run a python script from the repo with uv (host uv if present, else a throwaway uv container).
pyrun() {
  if command -v uv >/dev/null 2>&1; then
    uv run --project backend --with requests python "$@"
  else
    docker run --rm --network host --user "$(id -u):$(id -g)" \
      -e HOME=/tmp -e UV_CACHE_DIR=/tmp/uv-cache -e UV_PROJECT_ENVIRONMENT=/tmp/venv -e VLLM_API_KEY -e LLM_API_KEY -e CLARIO_HARDWARE \
      -v "$REPO:/repo" -w /repo ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
      uv run --project backend --with requests python "$@"
  fi
}

need_big() { # the step needs the 31B server up; point at the step that starts it
  [ "$FALLBACK" = 1 ] && return 0
  curl -fsS -m 5 "http://127.0.0.1:8000/health" >/dev/null 2>&1 || die "vllm-big is not answering on :8000. Run: deploy/amd/bootstrap.sh --step serve --step health"
}

check_result() { # file: has the provenance fields incl. hardware
  [ -f "$1" ] || die "expected result file missing: $1"
  python3 - "$1" <<'PY' || die "result file lacks provenance fields: $1"
import json, sys
r = json.load(open(sys.argv[1]))
need = ("n", "dataset", "model", "backend", "date", "hardware")
miss = [k for k in need if k not in r]
if miss:
    print("missing", miss, file=sys.stderr); sys.exit(1)
print("ok", sys.argv[1].rsplit("/", 1)[-1], "n=%s backend=%s hardware=%s" % (r["n"], r["backend"], r["hardware"].get("gpu_name") if isinstance(r["hardware"], dict) else r["hardware"]))
PY
}

# ---------------------------------------------------------------- steps
hf_access() { # model: 0 when this token may download the weights
  local code
  code="$(printf 'header = "Authorization: Bearer %s"\n' "$HF_TOKEN" | curl -s -o /dev/null -w '%{http_code}' -m 25 -K - "https://huggingface.co/$1/resolve/main/config.json" || true)"
  case "$code" in
    200|302) echo "hf access ok: $1" ;;
    401) die "HF_TOKEN is invalid or expired (401 for $1)" ;;
    403) die "licence not accepted for $1. Open https://huggingface.co/$1 while logged in as the token's owner, accept the terms, rerun: deploy/amd/bootstrap.sh --step preflight" ;;
    404) die "model id not found: $1 (check BIG_MODEL / SMALL_MODEL)" ;;
    *) die "could not reach huggingface.co for $1 (HTTP ${code:-none}). Network or rate limit; rerun in a minute." ;;
  esac
}

step_preflight() {
  if [ "$FALLBACK" = 1 ]; then
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 15 -H "Authorization: Bearer $API_KEY" "$BASE_URL/models" || true)"
    case "$code" in 200) echo "endpoint ok: $BASE_URL" ;; *) die "GET $BASE_URL/models returned HTTP ${code:-none}; check BASE_URL / API_KEY" ;; esac
    echo "hardware label: $CLARIO_HARDWARE"; return 0
  fi
  command -v docker >/dev/null || die "docker not found"
  docker compose version >/dev/null 2>&1 || die "docker compose plugin not found"
  command -v python3 >/dev/null || die "python3 not found on the host (needed for result stamping)"
  if command -v amd-smi >/dev/null; then amd-smi static >/dev/null 2>&1 && echo "amd-smi: ok" || echo "WARN: amd-smi present but failed"
  elif command -v rocm-smi >/dev/null; then rocm-smi >/dev/null 2>&1 && echo "rocm-smi: ok" || echo "WARN: rocm-smi present but failed"
  else die "neither amd-smi nor rocm-smi found. Is this a ROCm (MI300X) droplet?"; fi
  [ -e /dev/kfd ] && [ -d /dev/dri ] || die "/dev/kfd or /dev/dri missing: no AMD GPU visible to this host"
  mkdir -p "$HF_CACHE_DIR"
  local avail_gb need_gb="${DISK_MIN_GB:-200}"
  avail_gb=$(( $(df -Pk "$HF_CACHE_DIR" | awk 'NR==2{print $4}') / 1048576 ))
  [ "$avail_gb" -ge "$need_gb" ] || die "only ${avail_gb} GB free under $HF_CACHE_DIR, need $need_gb GB (weights, images, checkpoints). Free space or set DISK_MIN_GB."
  echo "disk: ${avail_gb} GB free"
  hf_access "$BIG_MODEL"; hf_access "$SMALL_MODEL"
  CLARIO_HARDWARE="$(python3 "$REPO/eval/hardware.py" | tr -d '\n')"; export CLARIO_HARDWARE
  printf '%s\n' "$CLARIO_HARDWARE" > "$STAMPS/hardware.json"
  echo "hardware: $CLARIO_HARDWARE"
  case "$CLARIO_HARDWARE" in *'"source": "none"'*|*'"source":"none"'*) die "no GPU name could be read (amd-smi/rocm-smi failed). Results would carry no hardware field." ;; esac
}

step_serve() {
  lora_env
  mkdir -p "$REPO/bench/results"   # bind-mounted read-only into the apps (GET /api/bench)
  say "pull images"
  "${DC[@]}" pull --ignore-buildable vllm-big vllm-small gpu-metrics caddy
  command -v uv >/dev/null 2>&1 || docker pull ghcr.io/astral-sh/uv:python3.12-bookworm-slim >/dev/null
  say "start vllm-big ($BIG_MODEL)"
  "${DC[@]}" up -d vllm-big
}

step_health() {
  if wait_http "http://127.0.0.1:8000/health" "vllm-big" "$WAIT_SECS" vllm-big; then return 0; fi
  # One automatic retry: AMD documents TRITON_ATTN as the fallback attention backend when the default fails.
  if [ -z "${VLLM_ATTENTION_BACKEND:-}" ] && "${DC[@]}" logs --tail 200 vllm-big 2>&1 | grep -qiE 'attention|backend|aiter|triton'; then
    echo "retrying once with VLLM_ATTENTION_BACKEND=TRITON_ATTN (saved to deploy/amd/.env)"
    export VLLM_ATTENTION_BACKEND=TRITON_ATTN; env_set VLLM_ATTENTION_BACKEND TRITON_ATTN
    "${DC[@]}" up -d --force-recreate vllm-big
    wait_http "http://127.0.0.1:8000/health" "vllm-big (TRITON_ATTN)" "$WAIT_SECS" vllm-big && return 0
  fi
  die "vllm-big did not become healthy. Fix per deploy/amd/README.md (troubleshooting), then: deploy/amd/bootstrap.sh --step health"
}

step_smoke() {
  need_big
  BASE_URL="$BIG_URL" MODEL="$BIG_MODEL" bash "$HERE/smoke.sh"
}

step_lay() {
  need_big
  local lex="$REPO/train/lay_lexicon.json"
  pyrun train/lay_expand.py --base-url "$BIG_URL" --model "$BIG_MODEL" --api-key-env VLLM_API_KEY \
    --terms "${LAY_TERMS:-800}" --concurrency 32 || die "lay_expand failed: see the log above"
  [ -s "$lex" ] || die "lay_expand wrote no $lex"
  echo "lay lexicon: $lex"
}

step_synth() {
  need_big
  local out="$REPO/train/data/synth/synth.jsonl" have=0
  [ -f "$out" ] && have="$(wc -l < "$out" | tr -d ' ')"
  mkdir -p "$REPO/train/data/synth"
  # synth.py refuses anthropic.com itself; it resumes toward --n when the file exists.
  pyrun train/synth.py --base-url "$BIG_URL" --model "$BIG_MODEL" --api-key-env VLLM_API_KEY --n "$SYNTH_N" --concurrency 32
  have="$(wc -l < "$out" | tr -d ' ')"
  [ "$have" -gt 0 ] || die "synth wrote no rows to $out; see train/data/synth/synth.jsonl.stats.json"
  echo "synth rows: $have"
}

step_prep() {
  [ -s "$REPO/train/data/synth/synth.jsonl" ] || die "no synthetic data. Run: deploy/amd/bootstrap.sh --step synth"
  pyrun train/prep.py
  for f in train_sft val_sft test; do [ -s "$REPO/train/data/v3/$f.jsonl" ] || die "prep did not write train/data/v3/$f.jsonl"; done
  echo "split: $(wc -l < "$REPO/train/data/v3/train.jsonl" | tr -d ' ') train, $(wc -l < "$REPO/train/data/v3/test.jsonl" | tr -d ' ') test (see train/data/v3/SPLIT.md)"
}

step_train() {
  [ -s "$REPO/train/data/v3/train_sft.jsonl" ] || die "no training data. Run: deploy/amd/bootstrap.sh --step synth --step prep"
  say "train: LoRA on $SMALL_MODEL"
  "${DC[@]}" stop vllm-small >/dev/null 2>&1 || true   # free its GPU share for training
  docker build -f train/Dockerfile.rocm -t clario-train train
  mkdir -p "$REPO/train/out" "$REPO/eval/results" "$HF_CACHE_DIR"
  docker run --rm --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --shm-size 64G \
    --security-opt seccomp=unconfined -e HF_TOKEN \
    -v "$REPO/train:/workspace/train" -v "$REPO/eval:/workspace/eval" -v "$HF_CACHE_DIR:/workspace/hf-cache" clario-train \
    bash -c "python train_rocm.py --model $SMALL_MODEL --data data/v3/train_sft.jsonl --val-data data/v3/val_sft.jsonl --out out/$RUN --epochs 3 --rank 16 --alpha 32 --lr 2e-4 --bf16; rc=\$?; chown -R $(id -u):$(id -g) out data /workspace/eval/results 2>/dev/null; exit \$rc"
  [ -f "$ADAPTER_DEFAULT/adapter_config.json" ] || die "training finished without an adapter at $ADAPTER_DEFAULT"
  python3 "$REPO/eval/hardware.py" stamp "$REPO/eval/results/train_$RUN.json"
  check_result "$REPO/eval/results/train_$RUN.json"
}

# eval_run label model base_url dataset data [extra args]
eval_run() {
  local label="$1" model="$2" url="$3" dataset="$4" data="$5"; shift 5
  say "eval $label on $dataset"
  pyrun eval/extraction_eval.py --data "$data" --dataset "$dataset" --base-url "$url" --model "$model" --label "$label" \
    --backend "$BACKEND_LABEL" --api-key-env VLLM_API_KEY --concurrency 8 "$@"
  check_result "$REPO/eval/results/extraction_$label.json"
}

step_eval() {
  local test="$REPO/train/data/v3/test.jsonl"
  [ -s "$test" ] || die "no test split. Run: deploy/amd/bootstrap.sh --step synth --step prep"
  local tuned_model="" ds_list="$EVAL_DATASET:train/data/v3/test.jsonl"
  [ ! -s "$REPO/eval/gold/gold.jsonl" ] || ds_list="$ds_list gold-reviewed:eval/gold/gold.jsonl"
  [ ! -s "$REPO/eval/data/psytar_hpo.jsonl" ] || ds_list="$ds_list psytar-hpo:eval/data/psytar_hpo.jsonl"
  if [ "$FALLBACK" = 1 ]; then
    tuned_model="${TUNED_MODEL:-}"
  else
    lora_env
    [ -n "${LORA_PATH:-}" ] || die "no adapter found at $ADAPTER_DEFAULT. Run: deploy/amd/bootstrap.sh --step train (needed for base vs tuned)"
    "${DC[@]}" up -d --force-recreate vllm-small   # recreate so the adapter wiring is always the current one
    wait_http "http://127.0.0.1:8001/health" "vllm-small" "$WAIT_SECS" vllm-small || die "vllm-small did not start (LoRA rejected? see README troubleshooting), then: deploy/amd/bootstrap.sh --step eval"
    tuned_model="clario-extract"
  fi
  local pair name path suffix
  for pair in $ds_list; do
    name="${pair%%:*}"; path="${pair#*:}"; suffix=""
    [ "$name" = "$EVAL_DATASET" ] || suffix="-$name"
    eval_run "$EVAL_BASE_LABEL$suffix" "$SMALL_MODEL" "$SMALL_URL" "$name" "$path"
    [ -z "$tuned_model" ] || eval_run "$EVAL_TUNED_LABEL$suffix" "$tuned_model" "$SMALL_URL" "$name" "$path"
    # the same models again with the confidence prompt variant: input for the review curve (kept apart so F1 above is the plain prompt)
    if [ "$name" = "$EVAL_DATASET" ]; then
      eval_run "$EVAL_BASE_LABEL-conf" "$SMALL_MODEL" "$SMALL_URL" "$name" "$path" --confidence
      [ -z "$tuned_model" ] || eval_run "$EVAL_TUNED_LABEL-conf" "$tuned_model" "$SMALL_URL" "$name" "$path" --confidence
    fi
  done
  [ "${EVAL_BIG:-0}" != 1 ] || { need_big; eval_run "base-31b" "$BIG_MODEL" "$BIG_URL" "$EVAL_DATASET" train/data/v3/test.jsonl; }
  say "review curve"
  python3 "$REPO/eval/review_curve.py" "$REPO/eval/results/extraction_$EVAL_BASE_LABEL-conf.json" \
    $( [ -z "$tuned_model" ] || echo "$REPO/eval/results/extraction_$EVAL_TUNED_LABEL-conf.json" )
  local curves=0 f
  for f in "$REPO"/eval/results/review_curve_*conf.json; do
    [ -f "$f" ] || continue
    check_result "$f"; curves=$((curves + 1))
  done
  if [ "$curves" = 0 ]; then
    [ "$FALLBACK" = 1 ] && echo "WARN: no review curve (the endpoint's answers carried no confidence field)" \
      || die "no review curve written: the --confidence runs carried no per-entity confidence. Check train/prompt.py confidence variant and the raw samples in eval/results/extraction_$EVAL_BASE_LABEL-conf.json"
  fi
  say "review threshold with a guarantee (self-consistency, conformal)"
  # The app's own signal: agreement across CLARIO_SC_N samples, same app prompt (no --confidence). Scored on the tuned model
  # when there is one, else on the base (fallback with a single model). Writes eval/results/conformal_threshold.json.
  local sc_model sc_label
  if [ -n "$tuned_model" ]; then sc_model="$tuned_model"; sc_label="$EVAL_TUNED_LABEL-sc"; else sc_model="$SMALL_MODEL"; sc_label="$EVAL_BASE_LABEL-sc"; fi
  eval_run "$sc_label" "$sc_model" "$SMALL_URL" "$EVAL_DATASET" train/data/v3/test.jsonl --sc-n "${CLARIO_SC_N:-5}"
  pyrun eval/review_curve.py "eval/results/extraction_$sc_label.json" --source sc
  check_result "$REPO/eval/results/review_curve_$sc_label.json"
  pyrun eval/conformal.py "eval/results/extraction_$sc_label.json" --source sc --alpha "${CLARIO_REVIEW_ALPHA:-0.05}" --alpha 0.10 --delta 0.1
  python3 "$REPO/eval/hardware.py" stamp "$REPO/eval/results/conformal_threshold.json"
  check_result "$REPO/eval/results/conformal_threshold.json"
  [ -n "$tuned_model" ] || echo "WARN: no tuned model given (TUNED_MODEL); only the base was scored"
}

step_bench() {
  need_big
  local samples="$STAMPS/gpu-samples.jsonl" spid=""
  rm -f "$samples"
  if [ "$FALLBACK" = 0 ]; then
    python3 "$REPO/eval/hardware.py" sample --out "$samples" --interval 1 &
    spid=$!
    trap 'kill "$spid" 2>/dev/null || true' EXIT
  fi
  say "bench: $BIG_MODEL (concurrency $BENCH_CONC, n=$BENCH_N, self-consistency n=5)"
  local gs=""; [ "$FALLBACK" = 1 ] || gs="--gpu-samples /repo/deploy/amd/logs/stamps/gpu-samples.jsonl"
  # inside the uv container the repo is /repo; on the host it is $REPO. Same relative path either way.
  if command -v uv >/dev/null 2>&1; then gs="${gs/\/repo\//$REPO/}"; fi
  LLM_API_KEY="$VLLM_API_KEY" pyrun bench/bench.py --base-url "$BIG_URL" --model "$BIG_MODEL" --label "$BENCH_LABEL" \
    --backend "$BACKEND_LABEL" --workload all --concurrency "$BENCH_CONC" --n "$BENCH_N" --sc-n 5 --stream $gs
  [ -z "$spid" ] || kill "$spid" 2>/dev/null || true
  check_result "$REPO/eval/results/bench_$BENCH_LABEL.json"
  if [ "$FALLBACK" = 0 ]; then
    python3 - "$REPO/eval/results/bench_$BENCH_LABEL.json" <<'PY' || die "bench recorded no GPU utilisation: amd-smi sampling failed (is amd-smi on the host PATH?). Rerun: deploy/amd/bootstrap.sh --step bench"
import json, sys
r = json.load(open(sys.argv[1]))
bad = [x for x in r["results"] if x.get("gpu_util_mean_pct") is None]
if bad:
    print("no GPU samples for", len(bad), "levels", file=sys.stderr); sys.exit(1)
print("gpu util present for all", len(r["results"]), "levels")
PY
  fi
}

step_results() {
  python3 "$REPO/eval/make_results_md.py" --check >/dev/null
  echo "wrote eval/RESULTS.md; provenance check passed (n, dataset, model, backend, date, hardware)"
  head -n 60 "$REPO/eval/RESULTS.md"
}

step_app() {
  say "app: clinic + patient-demo + gpu-metrics + caddy"
  lora_env
  "${DC[@]}" up -d --build vllm-small gpu-metrics clinic patient-demo caddy
  wait_http "http://127.0.0.1:9100/" "gpu-metrics" 120 gpu-metrics || die "gpu-metrics did not start"
  echo "gpu telemetry: $(curl -fsS -m 5 http://127.0.0.1:9100/ || echo unavailable)"
  echo "waiting for the certificates (Caddy needs ports 80/443 reachable from the internet)"
  local u ok
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
}

# ---------------------------------------------------------------- runner
run_step() {
  local s="$1" rc
  if [ -z "$ONLY" ] && [ "$FORCE" != 1 ] && [ "$s" != app ] && [ -f "$(stamp_file "$s")" ]; then
    echo "skip $s (stamp: $(cat "$(stamp_file "$s")"); FORCE=1 or --step $s redoes it)"; return 0
  fi
  say "step: $s"
  set +e
  ( set -e; "step_$s" )
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    printf '\nSTEP FAILED: %s (exit %s)\n  fix the cause above, then rerun just this step:\n    %s --step %s%s\n  log: %s\n' \
      "$s" "$rc" "deploy/amd/bootstrap.sh" "$s" "$([ "$FALLBACK" = 1 ] && echo ' --fallback')" "$LOG" >&2
    exit "$rc"
  fi
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo nogit)" > "$(stamp_file "$s")"
}

for s in $ORDER; do
  if [ "$s" = "smoke" ] && [ "$SKIP_SMOKE" = 1 ]; then echo "skip smoke (--skip-smoke)"; continue; fi
  run_step "$s"
done
say "done. log: $LOG"
