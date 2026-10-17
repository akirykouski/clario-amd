"""Run the LoRA sweep on Modal: one GPU container per rank:lr config in parallel, then winner on val, test once.

Same scripts as on any GPU box (train_rocm.py, select_ckpt.py, eval.py); Modal only supplies the GPUs and two
Volumes: clario-hf (Hugging Face cache, so Gemma is downloaded once) and clario-runs (data, checkpoints, results).

One-time setup:
    modal secret create huggingface HF_TOKEN=hf_...        # read token, Gemma 4 licence accepted on Hugging Face
    modal volume create clario-hf && modal volume create clario-runs

Smoke test (synthetic offline rows, 0.05 epoch, a few minutes, well under $1):
    modal run train/modal_app.py --smoke

Real sweep (data from docs/ENRICHMENT_RU.md, uploaded once):
    modal volume put clario-runs train/data/v3 data/v3
    modal run train/modal_app.py                                          # E4B, 4 configs on 4 x L40S
    modal run train/modal_app.py --tag a4b --model google/gemma-4-26B-A4B-it --configs 32:1e-4 --gpu RTX-PRO-6000 --bsz 4 --ga 4

Results back to the repo:
    modal volume get clario-runs results eval/ --force
"""
import os
import pathlib
import subprocess

import modal

ROOT = pathlib.Path(__file__).resolve().parent.parent if modal.is_local() else pathlib.Path("/")
HOURS = 60 * 60

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.8.0", index_url="https://download.pytorch.org/whl/cu128")
    .pip_install_from_requirements(str(ROOT / "train" / "requirements-cuda.txt"))
    .pip_install("hf_transfer", "pydantic>=2.8", "fastapi>=0.115", "httpx>=0.27", "cryptography>=43", "argon2-cffi>=23.1", "pynacl>=1.5")  # the eval resolver imports clario
    .env({"HF_HOME": "/hf", "HF_HUB_ENABLE_HF_TRANSFER": "1", "PYTHONUNBUFFERED": "1"})
    .add_local_dir(ROOT / "train", "/work/train", ignore=["data", "out", "out-*", "__pycache__", ".venv*", "*.pyc"])
    .add_local_dir(ROOT / "backend" / "clario", "/work/backend/clario", ignore=["__pycache__", "*.pyc"])
)
hf = modal.Volume.from_name("clario-hf", create_if_missing=True)
runs = modal.Volume.from_name("clario-runs", create_if_missing=True)
app = modal.App("clario-finetune", image=image)
OPTS = dict(volumes={"/hf": hf, "/runs": runs}, secrets=[modal.Secret.from_name("huggingface")], timeout=6 * HOURS)


def _layout(smoke):
    """Point train/data, train/out and eval/results at the runs Volume (smoke runs live apart from real ones)."""
    sfx = "-smoke" if smoke else ""
    for link, target in (("/work/train/data", f"/runs/data{sfx}"), ("/work/train/out", f"/runs/out{sfx}"),
                         ("/work/eval/results", f"/runs/results{sfx}")):
        os.makedirs(target, exist_ok=True)
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if os.path.islink(link):
            os.unlink(link)
        os.symlink(target, link)
    if smoke and not os.path.exists("/work/train/data/v3/test.jsonl"):  # deterministic rows, no model involved
        _sh("python synth.py --offline --n 80 --out data/synth/smoke.jsonl && python prep.py --inputs data/synth/smoke.jsonl")


def _sh(cmd, **env):
    print("+", cmd, flush=True)
    subprocess.run(["bash", "-c", cmd], cwd="/work/train", check=True, env={**os.environ, **env})


@app.function(**OPTS)
def fetch(model: str):
    """Download the weights once into the clario-hf Volume, so the GPU containers start from the cache."""
    from huggingface_hub import snapshot_download
    snapshot_download(model)
    hf.commit()


@app.function(gpu="L40S", **OPTS)
def base_val(tag: str, model: str, val_limit: int, smoke: bool = False):
    _layout(smoke)
    os.makedirs(f"/work/train/out/sweep-{tag}", exist_ok=True)
    _sh(f"python eval.py --hf-model {model} --data data/v3/val.jsonl --limit {val_limit} "
        f"--label {tag}-base-val --out-dir out/sweep-{tag}")
    runs.commit()


def _train(cfg):
    tag, model, rank, lr, epochs, bsz, ga, val_limit, smoke = (cfg[k] for k in
        ("tag", "model", "rank", "lr", "epochs", "bsz", "ga", "val_limit", "smoke"))
    every, sel_tokens = cfg.get("eval_every", 1.0), cfg.get("sel_max_tokens", 768)
    _layout(smoke)
    run = f"{tag}-r{rank}-lr{lr}"
    if not os.path.exists(f"/work/train/out/{run}/adapter/adapter_config.json"):
        _sh(f"python train_rocm.py --model {model} --out out/{run} --rank {rank} --alpha {rank} --lr {lr} "
            f"--epochs {epochs} --bsz {bsz} --grad-accum {ga} --eval-every {every}")
        runs.commit()
    _sh(f"python select_ckpt.py --run out/{run} --hf-model {model} --limit {val_limit} --max-tokens {sel_tokens}")
    runs.commit()
    return run


@app.function(gpu="L40S", **OPTS)
def train_l40s(cfg: dict):
    return _train(cfg)


@app.function(gpu="RTX-PRO-6000", **OPTS)
def train_pro6000(cfg: dict):
    return _train(cfg)


@app.function(gpu="L40S", **OPTS)
def finish(tag: str, model: str, test_limit: int = 0, smoke: bool = False):
    """Winner across configs on val, then base and winner on test, once."""
    _layout(smoke)
    lim = f"--limit {test_limit}" if test_limit else ""
    _sh(f"python select_ckpt.py --summary --tag {tag}")
    win = open(f"/work/train/out/sweep-{tag}/WINNER").read().strip()
    if not os.path.exists(f"/work/eval/results/extraction_base-{tag}.json"):
        _sh(f"python eval.py --hf-model {model} --label base-{tag} {lim}")
    _sh(f"python eval.py --hf-model {model} --adapter {win} --label ft-{tag} {lim}")
    runs.commit()
    return win


@app.function(gpu="L40S", **OPTS)
def score(model: str, label: str, adapter: str = "", limit: int = 0):
    """One extra eval on test with the same scorer (e.g. a subset shared with API models)."""
    _layout(False)
    ad = f"--adapter {adapter}" if adapter else ""
    lim = f"--limit {limit}" if limit else ""
    _sh(f"python eval.py --hf-model {model} {ad} --label {label} {lim}")
    runs.commit()


@app.function(gpu="L40S", **OPTS)
def merge(adapter: str = "/work/train/out/e4b-r16-lr2e-4/best_adapter", base: str = "google/gemma-4-E4B-it",
          out: str = "/runs/out/merged-e4b"):
    """Adapter + base -> bf16 weights for vLLM, with the base's processor and chat-template files alongside."""
    import glob, shutil
    from huggingface_hub import snapshot_download
    _layout(False)
    _sh(f"python export.py merge --base {base} --adapter {adapter} --out {out}")
    snap = snapshot_download(base)
    for f in glob.glob(f"{snap}/*"):
        name = os.path.basename(f)
        if not name.endswith(".safetensors") and "index" not in name and not os.path.exists(f"{out}/{name}"):
            shutil.copy(f, f"{out}/{name}")
    print(sorted(os.listdir(out)))
    runs.commit()


@app.local_entrypoint()
def score_subset(limit: int = 100, model: str = "google/gemma-4-E4B-it",
                 adapter: str = "/work/train/out/e4b-r16-lr2e-4/best_adapter"):
    """Base and fine-tuned E4B on the first `limit` test rows, in parallel."""
    calls = [score.spawn(model, f"base-e4b-test{limit}", "", limit), score.spawn(model, f"ft-e4b-test{limit}", adapter, limit)]
    for c in calls:
        c.get()
    print(f"results: modal volume get clario-runs results/extraction_base-e4b-test{limit}.json results/extraction_ft-e4b-test{limit}.json")


@app.local_entrypoint()
def main(tag: str = "e4b", model: str = "google/gemma-4-E4B-it", configs: str = "16:1e-4,16:2e-4,32:1e-4,32:2e-4",
         gpu: str = "L40S", epochs: float = 3, bsz: int = 8, ga: int = 2, val_limit: int = 100, smoke: bool = False,
         eval_every: float = 1.0, sel_max_tokens: int = 768):
    if smoke:
        tag, configs, epochs, val_limit = f"smoke-{tag}", "16:1e-4", 0.05, 8
    cfgs = [dict(tag=tag, model=model, rank=int(c.split(":")[0]), lr=c.split(":")[1], epochs=epochs, bsz=bsz, ga=ga,
                 val_limit=val_limit, smoke=smoke, eval_every=eval_every, sel_max_tokens=sel_max_tokens)
            for c in configs.split(",")]
    fetch.remote(model)
    trainer = train_pro6000 if gpu == "RTX-PRO-6000" else train_l40s
    base = base_val.spawn(tag, model, val_limit, smoke)
    done = list(trainer.map(cfgs))   # one container per config, in parallel
    base.get()
    print("trained:", done)
    win = finish.remote(tag, model, 8 if smoke else 0, smoke)
    print("winner adapter:", win)
    print("results: modal volume get clario-runs results" + ("-smoke" if smoke else "") + " eval/ --force")
