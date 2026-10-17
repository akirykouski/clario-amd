"""Serve the fine-tuned Gemma 4 E4B (LoRA merged into bf16 weights) with vLLM on a Modal L4, scale to zero.

OpenAI-compatible at https://<workspace>--clario-model.<region>.modal.run/v1, model name `clario-e4b`,
key from the Modal Secret `clario-model-key` (CLARIO_MODEL_API_KEY). Weights come from the clario-runs Volume,
written by `modal run train/modal_app.py::merge`.

    modal deploy deploy/modal/serve_model.py
    WARM=1 modal deploy deploy/modal/serve_model.py      # keep one GPU warm (pitch window), about $0.80/h
"""
import os
import subprocess

import modal

WEIGHTS = "/runs/out/merged-e4b"
WARM = int(os.environ.get("WARM", "0"))

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("vllm", "hf_transfer")
    .env({"HF_HOME": "/hf", "VLLM_LOGGING_LEVEL": "INFO", "WARM": str(WARM)})
)
runs = modal.Volume.from_name("clario-runs")
hf = modal.Volume.from_name("clario-hf", create_if_missing=True)
app = modal.App("clario-model", image=image)


@app.function(gpu="L4", volumes={"/runs": runs, "/hf": hf}, secrets=[modal.Secret.from_name("clario-model-key")],
              scaledown_window=10 * 60, min_containers=WARM, max_containers=2, timeout=24 * 60 * 60)
@modal.concurrent(max_inputs=32)
@modal.web_server(port=8000, startup_timeout=15 * 60, label="clario-model")
def serve():
    cmd = ["vllm", "serve", WEIGHTS, "--served-model-name", "clario-e4b", "--host", "0.0.0.0", "--port", "8000",
           "--api-key", os.environ["CLARIO_MODEL_API_KEY"], "--max-model-len", "4096", "--gpu-memory-utilization", "0.92",
           "--dtype", "bfloat16"]
    subprocess.Popen(cmd)
