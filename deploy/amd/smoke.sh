#!/usr/bin/env bash
# Usage: VLLM_API_KEY=... [BASE_URL=http://127.0.0.1:8001/v1] [MODEL=google/gemma-4-31B-it] [LORA=clario-extract] ./smoke.sh
set -euo pipefail
BASE_URL="${BASE_URL:-http://127.0.0.1:8001/v1}"
MODEL="${MODEL:-google/gemma-4-31B-it}"
: "${VLLM_API_KEY:?set VLLM_API_KEY}"

call() { # $1 = model name
curl -fsS "$BASE_URL/chat/completions" \
  -H "Authorization: Bearer $VLLM_API_KEY" -H "Content-Type: application/json" \
  -d "$(cat <<JSON
{"model":"$1","temperature":0,"max_tokens":300,
 "messages":[{"role":"user","content":"Diary note: my knees were really stiff this morning for about an hour, and I was exhausted by 3pm. Return the entities as JSON."}],
 "response_format":{"type":"json_schema","json_schema":{"name":"entities","strict":true,
  "schema":{"type":"object","properties":{"entities":{"type":"array","items":{"type":"object","properties":{"span":{"type":"string"},"concept":{"type":"string"}},"required":["span","concept"],"additionalProperties":false}}},
  "required":["entities"],"additionalProperties":false}}}}
JSON
)"
}
check() { python3 -c '
import sys, json
c = json.load(sys.stdin)["choices"][0]["message"]["content"]
d = json.loads(c)
assert isinstance(d.get("entities"), list) and d["entities"], d
print("OK: valid structured JSON ->", d)'; }

echo "== GET $BASE_URL/models"
curl -fsS "$BASE_URL/models" -H "Authorization: Bearer $VLLM_API_KEY"; echo
echo "== base model: $MODEL"
call "$MODEL" | check
if [ -n "${LORA:-}" ]; then
  echo "== LoRA adapter: $LORA"
  call "$LORA" | check
fi
