"""Pick the LoRA checkpoint with the best extraction score on val, and summarise a sweep.

Lowest val loss and best extraction are often different checkpoints, so train_rocm.py saves one every half epoch and
this script scores each one with eval.py on the val split (never test). Each eval runs in its own process so GPU memory
is freed between checkpoints.

    python select_ckpt.py --run out/e4b-r32-lr1e-4 --hf-model google/gemma-4-E4B-it --limit 200
    python select_ckpt.py --summary --tag e4b          # after a sweep: winner across runs -> eval/results/sweep_e4b.json

Writes <run>/best.json and copies the winning adapter to <run>/best_adapter.
"""
import argparse, glob, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(os.path.dirname(HERE), "eval", "results")
METRIC = "resolved_entity_f1"  # what the app stores; falls back to entity_f1 when the resolver is unavailable


def checkpoints(run):
    """Adapter dirs of a run, in training order: checkpoint-<step>/ then the final adapter/."""
    cks = sorted((d for d in glob.glob(os.path.join(run, "checkpoint-*")) if os.path.exists(os.path.join(d, "adapter_config.json"))),
                 key=lambda d: int(re.sub(r"\D", "", os.path.basename(d)) or 0))
    final = os.path.join(run, "adapter")
    has_final = os.path.exists(os.path.join(final, "adapter_config.json"))
    if has_final and cks and _same_weights(cks[-1], final):  # the last checkpoint is the final adapter: score it once
        return cks
    return cks + ([final] if has_final else [])


def _same_weights(a, b):
    import hashlib
    def digest(d):
        p = os.path.join(d, "adapter_model.safetensors")
        return hashlib.sha1(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None
    da = digest(a)
    return da is not None and da == digest(b)


def value(res, metric=METRIC):
    v = res.get(metric)
    return res.get("entity_f1") if v is None else v


def pick(scores):
    """scores: [(name, value, result)] in training order -> the best; ties go to the earlier checkpoint (less training)."""
    best = None
    for s in scores:
        if s[1] is not None and (best is None or s[1] > best[1]):
            best = s
    return best


def raw_f1(run_summary):
    """Plain entity F1 of a run's chosen checkpoint: the tie-break between runs with the same selection metric."""
    return next((c.get("entity_f1") or 0 for c in run_summary.get("checkpoints", []) if c["checkpoint"] == run_summary.get("best")), 0)


def score_run(a):
    run = os.path.normpath(a.run); name = os.path.basename(run)
    out_dir = os.path.join(run, "val_evals"); os.makedirs(out_dir, exist_ok=True)
    scores = []
    for ck in checkpoints(run):
        label = f"{name}-{os.path.basename(ck)}-val"
        path = os.path.join(out_dir, f"extraction_{label}.json")
        if not os.path.exists(path):  # resumable: a scored checkpoint is not scored again
            cmd = [sys.executable, os.path.join(HERE, "eval.py"), "--hf-model", a.hf_model, "--adapter", ck, "--data", a.val,
                   "--label", label, "--out-dir", out_dir, "--limit", str(a.limit), "--batch-size", str(a.batch_size),
                   "--max-tokens", str(a.max_tokens)]
            if a.load_in_4bit:
                cmd.append("--load-in-4bit")
            subprocess.run(cmd, check=True)
        res = json.load(open(path))
        scores.append((os.path.basename(ck), value(res, a.metric), res))
        print(f"{os.path.basename(ck):>20}  {a.metric} {value(res, a.metric):.4f}  F1 {res['entity_f1']:.4f}")
    if not scores:
        raise SystemExit(f"no adapters under {run}")
    best = pick(scores)
    dst = os.path.join(run, "best_adapter")
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(os.path.join(run, best[0]), dst)
    summary = {"run": name, "metric": a.metric, "split": a.val, "limit": a.limit, "best": best[0], "value": best[1],
               "checkpoints": [{"checkpoint": n, a.metric: v, "entity_f1": r["entity_f1"], "json_validity_rate": r["json_validity_rate"]}
                               for n, v, r in scores]}
    json.dump(summary, open(os.path.join(run, "best.json"), "w"), indent=2)
    print(f"best {best[0]} {a.metric} {best[1]:.4f} -> {dst}")


def summary(a):
    """Winner across the runs of one sweep tag. Reads out/<tag>-*/best.json, writes eval/results/sweep_<tag>.json."""
    runs = []
    for p in sorted(glob.glob(os.path.join(a.out, f"{a.tag}-*", "best.json"))):
        b = json.load(open(p)); b["path"] = os.path.dirname(p)
        tr = os.path.join(b["path"], "metrics.json")
        if os.path.exists(tr):
            m = json.load(open(tr))
            b.update({k: m.get(k) for k in ("rank", "alpha", "lr", "epochs", "train_wall_s", "gpu", "precision", "load_in_4bit")})
        runs.append(b)
    if not runs:
        raise SystemExit(f"no {a.out}/{a.tag}-*/best.json; run select_ckpt.py --run on each run first")
    win = max(runs, key=lambda b: (b["value"] is not None, round(b["value"] or 0, 3), raw_f1(b)))
    base = os.path.join(a.out, f"sweep-{a.tag}", f"extraction_{a.tag}-base-val.json")
    body = {"label": f"sweep_{a.tag}", "metric": win["metric"], "split": "val", "winner": win["run"],
            "winner_adapter": os.path.join(win["path"], "best_adapter"), "winner_checkpoint": win["best"],
            "base_val": value(json.load(open(base)), win["metric"]) if os.path.exists(base) else None,
            "runs": [{k: r.get(k) for k in ("run", "best", "value", "rank", "alpha", "lr", "epochs", "train_wall_s", "gpu",
                                             "precision", "load_in_4bit")} for r in runs],
            "note": "selection on val only; test is scored once, on the winner, by sweep.sh"}
    os.makedirs(RESULTS, exist_ok=True)
    json.dump(body, open(os.path.join(RESULTS, f"sweep_{a.tag}.json"), "w"), indent=2)
    for r in body["runs"]:
        print(f"{r['run']:>28}  best {r['best']:<18} {body['metric']} {r['value']:.4f}")
    print(f"winner {win['run']} ({win['best']}) -> {body['winner_adapter']}")
    print(body["winner_adapter"], file=open(os.path.join(a.out, f"sweep-{a.tag}", "WINNER"), "w"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="training output dir with checkpoint-*/ and adapter/")
    ap.add_argument("--hf-model", default="google/gemma-4-E4B-it")
    ap.add_argument("--val", default=os.path.join(HERE, "data", "v3", "val.jsonl"))
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-tokens", type=int, default=1024, help="generation cap per diary while scoring checkpoints")
    ap.add_argument("--load-in-4bit", action="store_true")
    ap.add_argument("--metric", default=METRIC)
    ap.add_argument("--summary", action="store_true"); ap.add_argument("--tag", default="e4b")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    a = ap.parse_args(argv)
    if a.summary:
        summary(a)
    elif a.run:
        score_run(a)
    else:
        ap.error("--run or --summary")


if __name__ == "__main__":
    main()
