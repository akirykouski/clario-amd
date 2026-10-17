"""Public demo on Modal: the patient app and the clinic console, each a public HTTPS URL.

Both run the same FastAPI + React build as the Dockerfile, with CLARIO_DEMO_INSTANCE=1 (synthetic data banner) and
their own Modal Volume for /data. One container each, so the demo's files live in one place.

Models (OpenAI-compatible endpoints, keys from Modal Secrets, never in the image):
  clinic   Gemma 4 31B on AMD Token Factory                       secret `tokenfactory` (TF_API_KEY, TF_BASE_URL)
  patient  PATIENT_LLM=tf (default): the same Gemma 4 31B on Token Factory
           PATIENT_LLM=modal: our fine-tuned Gemma 4 E4B served by deploy/modal/serve_model.py
                                                                    secret `clario-model-key` (CLARIO_MODEL_API_KEY)

    modal deploy deploy/modal/apps.py                         # patient on Token Factory
    PATIENT_LLM=modal modal deploy deploy/modal/apps.py       # patient on the fine-tuned E4B

URLs: https://<workspace>--clario-patient.<region>.modal.run and https://<workspace>--clario-clinic.<region>.modal.run
"""
import os
import pathlib
import subprocess

import modal

ROOT = pathlib.Path(__file__).resolve().parents[2] if modal.is_local() else pathlib.Path("/")  # the image is only built locally
PATIENT_LLM = os.environ.get("PATIENT_LLM", "tf")
TF_MODEL = "Gemma-4-31B-IT"
E4B_MODEL = "clario-e4b"  # served-model-name in serve_model.py

image = (
    modal.Image.from_registry("node:20-slim", add_python="3.12")
    .add_local_dir(ROOT / "frontend", "/web", copy=True, ignore=["node_modules", "dist", "coverage"])
    .run_commands("cd /web && npm ci --no-audit --no-fund && npm run build")
    .pip_install_from_pyproject(str(ROOT / "backend" / "pyproject.toml"))
    .env({"FRONTEND_DIST": "/web/dist", "CLARIO_HOST": "0.0.0.0", "CLARIO_PORT": "8800", "CLARIO_DATA_DIR": "/data",
          "CLARIO_DEMO_INSTANCE": "1", "PYTHONUNBUFFERED": "1", "PATIENT_LLM": PATIENT_LLM})
    .add_local_file(ROOT / "train" / "prompt.py", "/app/train/prompt.py")
    .add_local_dir(ROOT / "eval" / "results", "/app/eval/results")
    .add_local_dir(ROOT / "backend", "/app/backend", ignore=[".venv", "tests", "__pycache__", "*.pyc", ".pytest_cache"])
)
app = modal.App("clario-demo", image=image)
patient_vol = modal.Volume.from_name("clario-demo-patient", create_if_missing=True)
clinic_vol = modal.Volume.from_name("clario-demo-clinic", create_if_missing=True)


def _web_url(app_name, fn):
    """Public URL of a deployed web function (Modal adds a region to the host, so it is looked up, not built)."""
    try:
        return modal.Function.from_name(app_name, fn).get_web_url()
    except Exception as e:  # noqa: BLE001 - not deployed yet: the share screen just starts empty
        print(f"no URL for {app_name}.{fn}: {e!r}"[:200])
        return None


def _serve(mode, llm):
    env = {**os.environ, "CLARIO_MODE": mode, **llm}
    subprocess.Popen(["python", "-m", "clario.app"], cwd="/app/backend", env=env)


COMMON = dict(max_containers=1, scaledown_window=20 * 60, timeout=24 * 60 * 60)


@app.function(volumes={"/data": clinic_vol}, secrets=[modal.Secret.from_name("tokenfactory")], **COMMON)
@modal.concurrent(max_inputs=100)
@modal.web_server(8800, startup_timeout=120, label="clario-clinic")
def clinic():
    _serve("clinic", {"LLM_BASE_URL": os.environ["TF_BASE_URL"], "LLM_API_KEY": os.environ["TF_API_KEY"],
                      "LLM_MODEL": TF_MODEL, "CLARIO_CLINIC_NAME": "Clario demo clinic"})


@app.function(volumes={"/data": patient_vol},
              secrets=[modal.Secret.from_name("tokenfactory"), modal.Secret.from_name("clario-model-key")], **COMMON)
@modal.concurrent(max_inputs=100)
@modal.web_server(8800, startup_timeout=120, label="clario-patient")
def patient():
    clinic_url = os.environ.get("CLARIO_CLINIC_URL") or _web_url("clario-demo", "clinic")
    if os.environ.get("PATIENT_LLM") == "modal":
        llm = {"LLM_BASE_URL": _web_url("clario-model", "serve") + "/v1", "LLM_API_KEY": os.environ["CLARIO_MODEL_API_KEY"],
               "LLM_MODEL": E4B_MODEL}
    else:
        llm = {"LLM_BASE_URL": os.environ["TF_BASE_URL"], "LLM_API_KEY": os.environ["TF_API_KEY"], "LLM_MODEL": TF_MODEL}
    _serve("patient", {**llm, "CLARIO_PSEUDONYMIZE": "1", **({"CLARIO_CLINIC_URL": clinic_url} if clinic_url else {})})
