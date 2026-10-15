#!/usr/bin/env bash
# Idempotent: pull image, (re)start vLLM ROCm container bound to loopback, wait for health.
# Usage: VLLM_API_KEY=... [HF_TOKEN=...] [LORA_PATH=/abs/path/to/adapter] ./serve_vllm.sh [model-id]
# LORA_PATH set -> adds --enable-lora --lora-modules clario-extract=<mounted path> --max-lora-rank 16
set -euo pipefail

MODEL="${1:-${MODEL:-google/gemma-4-31B-it}}"
# Pin: newest release tag on Docker Hub on 2026-10-16 (https://hub.docker.com/r/vllm/vllm-openai-rocm/tags). Flags follow the vLLM Gemma 4
# recipe (https://docs.vllm.ai/projects/recipes/en/latest/Google/Gemma4.html); TRITON_ATTN is only a fallback (see docker-compose.yml).
IMAGE="${VLLM_IMAGE:-vllm/vllm-openai-rocm:v0.31.0}"
NAME="${CONTAINER_NAME:-clario-vllm}"
PORT="${PORT:-8001}"
MAX_LEN="${MAX_MODEL_LEN:-16384}"
MAX_SEQS="${MAX_NUM_SEQS:-64}"
GPU_UTIL="${GPU_MEM_UTIL:-0.90}"
WAIT_SECS="${WAIT_SECS:-1800}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"
LORA_PATH="${LORA_PATH:-}"
LORA_NAME="${LORA_NAME:-clario-extract}"
LORA_RANK="${LORA_RANK:-16}"
: "${VLLM_API_KEY:?set VLLM_API_KEY (the bearer token clients must send)}"

command -v docker >/dev/null || { echo "docker not found" >&2; exit 1; }
mkdir -p "$HF_CACHE"

LORA_ARGS=()
LORA_MOUNT=()
if [ -n "$LORA_PATH" ]; then
  [ -d "$LORA_PATH" ] || { echo "LORA_PATH $LORA_PATH is not a directory" >&2; exit 1; }
  [ -f "$LORA_PATH/adapter_config.json" ] || { echo "no adapter_config.json in $LORA_PATH" >&2; exit 1; }
  LORA_MOUNT=(-v "$(cd "$LORA_PATH" && pwd):/lora/$LORA_NAME:ro")
  LORA_ARGS=(--enable-lora --lora-modules "$LORA_NAME=/lora/$LORA_NAME" --max-lora-rank "$LORA_RANK")
fi

# Replace any existing container; config is cheap to re-apply and weights are cached.
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "replacing existing container $NAME"
  docker rm -f "$NAME" >/dev/null
fi

docker pull "$IMAGE"
docker run -d --name "$NAME" --restart unless-stopped \
  --ipc=host --shm-size 16G \
  --device /dev/kfd --device /dev/dri \
  --group-add video --cap-add SYS_PTRACE --security-opt seccomp=unconfined \
  -p "127.0.0.1:$PORT:$PORT" \
  -v "$HF_CACHE:/root/.cache/huggingface" \
  "${LORA_MOUNT[@]}" \
  -e HF_TOKEN="${HF_TOKEN:-}" \
  -e VLLM_API_KEY="$VLLM_API_KEY" \
  -e HIP_FORCE_DEV_KERNARG=1 \
  -e VLLM_ROCM_USE_AITER="${VLLM_ROCM_USE_AITER:-0}" \
  "$IMAGE" \
  --model "$MODEL" \
  --served-model-name "$MODEL" \
  --host 0.0.0.0 --port "$PORT" \
  --dtype bfloat16 \
  --max-model-len "$MAX_LEN" \
  --max-num-seqs "$MAX_SEQS" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --enable-prefix-caching \
  "${LORA_ARGS[@]}" \
  ${EXTRA_ARGS:-}

echo "waiting up to ${WAIT_SECS}s for http://127.0.0.1:$PORT/health (first start downloads weights)"
start=$(date +%s)
until curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; do
  if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "container exited; last logs:" >&2; docker logs --tail 60 "$NAME" >&2; exit 1
  fi
  if [ $(( $(date +%s) - start )) -gt "$WAIT_SECS" ]; then
    echo "timeout; last logs:" >&2; docker logs --tail 60 "$NAME" >&2; exit 1
  fi
  sleep 10
done
echo "READY: model=$MODEL${LORA_PATH:+ lora=$LORA_NAME} bind=127.0.0.1:$PORT  (logs: docker logs -f $NAME)"
