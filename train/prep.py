"""Merge local diary datasets, split by disease, write chat SFT jsonl.

Inputs are jsonl rows of the form produced by synth.py:
    {"diary": str, "target": {"entities": [{name_colloquial, name_canonical, hpo_id, type, negated}]},
     "source_disease": "ORPHA:..." | "OMIM:..." | null, "lang": "en" | "it", ...}
Rows are grouped by source_disease so no disease appears in both train and val.
"""
import argparse, glob, json, os, random
from prompt import build_messages, from_dataset_entities, target_json

HERE = os.path.dirname(os.path.abspath(__file__))


def load(patterns):
    rows = []
    for pat in patterns:
        for p in sorted(glob.glob(pat)):
            rows += [json.loads(l) for l in open(p) if l.strip()]
    return rows


def to_sft(r):
    ents = from_dataset_entities(r["target"]["entities"])
    msgs = build_messages(r["diary"]) + [{"role": "assistant", "content": target_json(ents)}]
    return {"messages": msgs, "source_disease": r.get("source_disease")}


def write(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def split(rows, val_frac, seed):
    groups = {}
    for i, r in enumerate(rows):
        groups.setdefault(r.get("source_disease") or f"row{i}", []).append(r)
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    val, n = set(), 0
    for k in keys:
        if n >= val_frac * len(rows):
            break
        val.add(k)
        n += len(groups[k])
    tr = [r for k in keys if k not in val for r in groups[k]]
    va = [r for k in keys if k in val for r in groups[k]]
    return tr, va


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", default=[os.path.join(HERE, "data", "synth", "*.jsonl")])
    ap.add_argument("--data-dir", default=os.path.join(HERE, "data"))
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--val-frac", type=float, default=0.1)
    a = ap.parse_args()
    rows = load(a.inputs)
    if not rows:
        raise SystemExit(f"no rows in {a.inputs}; run synth.py first")
    tr, va = split(rows, a.val_frac, a.seed)
    dis = lambda rs: {r["source_disease"] for r in rs if r.get("source_disease")}
    assert not dis(tr) & dis(va)
    write(os.path.join(a.data_dir, "train_sft.jsonl"), [to_sft(r) for r in tr])
    write(os.path.join(a.data_dir, "val_sft.jsonl"), [to_sft(r) for r in va])
    write(os.path.join(a.data_dir, "val_gold.jsonl"), va)  # raw rows for eval.py
    langs = lambda rs: {l: sum(r.get("lang") == l for r in rs) for l in ("en", "it")}
    with open(os.path.join(a.data_dir, "SPLIT.md"), "w") as f:
        f.write(f"# Split\n\nInputs: {a.inputs}\nDisease-held-out, seed {a.seed}\n"
                f"- train: {len(tr)} rows, {len(dis(tr))} diseases, {langs(tr)}\n"
                f"- val: {len(va)} rows, {len(dis(va))} diseases, {langs(va)}\n"
                f"- disease overlap train/val: 0\n")
    print(f"train {len(tr)}  val {len(va)}  diseases {len(dis(tr))}/{len(dis(va))}")


if __name__ == "__main__":
    main()
