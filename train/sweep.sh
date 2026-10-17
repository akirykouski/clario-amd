#!/usr/bin/env bash
# LoRA sweep on one rented GPU (CUDA or ROCm, no Docker): base on val, each config trained and its best
# half-epoch checkpoint picked on val, the winner across configs picked on val, then base and winner scored on
# test once. Resumable: a finished run (out/<run>/best.json) is skipped, so re-running after a crash continues.
#
#   bash sweep.sh                                   # Gemma 4 E4B, 4 configs
#   MODEL=google/gemma-4-26B-A4B-it TAG=a4b CONFIGS="32:1e-4" BSZ=4 GA=4 bash sweep.sh
#
# Env: MODEL, TAG, CONFIGS ("rank:lr" list), EPOCHS (3), BSZ (8), GA (2), VAL_LIMIT (200), Q4=1 for 4-bit QLoRA.
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${MODEL:-google/gemma-4-E4B-it}"
TAG="${TAG:-e4b}"
CONFIGS="${CONFIGS:-16:1e-4 16:2e-4 32:1e-4 32:2e-4}"
EPOCHS="${EPOCHS:-3}"; BSZ="${BSZ:-8}"; GA="${GA:-2}"; VAL_LIMIT="${VAL_LIMIT:-200}"
Q=(); [ "${Q4:-0}" = 1 ] && Q=(--load-in-4bit)
PY="${PYTHON:-python}"

for f in data/v3/train_sft.jsonl data/v3/val_sft.jsonl data/v3/val.jsonl data/v3/test.jsonl; do
  [ -s "$f" ] || { echo "missing $f: run prep.py first (docs/ENRICHMENT_RU.md)" >&2; exit 2; }
done
mkdir -p "out/sweep-$TAG"

if [ ! -f "out/sweep-$TAG/extraction_$TAG-base-val.json" ]; then
  "$PY" eval.py --hf-model "$MODEL" ${Q[@]+"${Q[@]}"} --data data/v3/val.jsonl --limit "$VAL_LIMIT" \
    --label "$TAG-base-val" --out-dir "out/sweep-$TAG"
fi

for cfg in $CONFIGS; do
  r="${cfg%%:*}"; lr="${cfg#*:}"; run="$TAG-r$r-lr$lr"
  if [ -f "out/$run/best.json" ]; then echo "skip $run (done)"; continue; fi
  if [ ! -f "out/$run/adapter/adapter_config.json" ]; then
    "$PY" train_rocm.py --model "$MODEL" ${Q[@]+"${Q[@]}"} --out "out/$run" --rank "$r" --alpha "$r" --lr "$lr" \
      --epochs "$EPOCHS" --bsz "$BSZ" --grad-accum "$GA"
  fi
  "$PY" select_ckpt.py --run "out/$run" --hf-model "$MODEL" ${Q[@]+"${Q[@]}"} --limit "$VAL_LIMIT"
done

"$PY" select_ckpt.py --summary --tag "$TAG"
WIN="$(cat "out/sweep-$TAG/WINNER")"

# test, once: the before and after numbers that go in the README
[ -f "../eval/results/extraction_base-$TAG.json" ] || "$PY" eval.py --hf-model "$MODEL" ${Q[@]+"${Q[@]}"} --label "base-$TAG"
"$PY" eval.py --hf-model "$MODEL" ${Q[@]+"${Q[@]}"} --adapter "$WIN" --label "ft-$TAG"
echo "done: eval/results/sweep_$TAG.json, extraction_base-$TAG.json, extraction_ft-$TAG.json"
