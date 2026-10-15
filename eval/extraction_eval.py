"""T10 extraction eval entry point. Same scorer as train/eval.py, results land in eval/results/.

    python eval/extraction_eval.py --dry-run
    python eval/extraction_eval.py --data train/data/v3/test.jsonl --base-url http://localhost:8000/v1 \
        --model clario --label ft-a4b-r16 --backend vllm-rocm-mi300x
    python eval/extraction_eval.py --data eval/gold/gold.jsonl --dataset gold-reviewed --base-url https://api.anthropic.com/v1/ \
        --model claude-haiku-5-5 --api-key-env ANTHROPIC_API_KEY --label haiku-gold      # eval-only comparator
    python eval/extraction_eval.py --data eval/data/psytar_hpo.jsonl --dataset psytar-hpo ...

Pass --confidence to use the prompt variant that asks for a confidence field (needed for ECE and review_curve.py).
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = os.path.join(os.path.dirname(HERE), "train")


def _core():
    # Loaded by path: a bare `import eval` could resolve to this eval/ directory as a namespace package.
    sys.path.insert(0, TRAIN)
    spec = importlib.util.spec_from_file_location("clario_train_eval", os.path.join(TRAIN, "eval.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    core = _core()
    argv = sys.argv[1:]
    if "--out-dir" not in argv:
        argv += ["--out-dir", os.path.join(HERE, "results")]
    res = core.main(argv)
    # Provenance: add the hardware record (env CLARIO_HARDWARE from bootstrap.sh, else amd-smi on this host).
    sys.path.insert(0, HERE)
    import hardware
    path = os.path.join(argv[argv.index("--out-dir") + 1], f"extraction_{res['label']}.json")
    res["hardware"] = ({"gpu_name": "none (offline dry run)", "gpu_count": None, "vram_total_gb": None, "source": "none"}
                       if res.get("dry_run") else hardware.detect())
    json.dump(res, open(path, "w"), indent=2)
