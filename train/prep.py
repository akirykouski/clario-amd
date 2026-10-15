"""Merge synthetic diary rows, split by disease and language, write the v3 ml-ready files.

Inputs are jsonl rows as written by synth.py:
    {"diary": str, "target": {"entities": [...]}, "source_disease": "ORPHA:..." | "OMIM:..." | null,
     "lang": "en" | "it", "kind": "clinical" | "hard_negative", ...}
Entities may be v3 or the older name_colloquial shape; both are normalised to v3 (confidence null).

Split: whole diseases go to one split only, so val and test are held out by disease, and the
test split is disjoint from val. Diseases are assigned greedily so each split keeps the language
mix of the whole set (stratified by language at the disease-group level).

Writes, under --data-dir (default data/v3):
    train.jsonl val.jsonl test.jsonl            rows with id, diary, target (v3), source_disease, lang, kind
    train_sft.jsonl val_sft.jsonl test_sft.jsonl  chat files (system, user, assistant=target JSON)
    SPLIT.md                                    counts and the disease-overlap check
"""
import argparse, glob, hashlib, json, os, random
from prompt import build_messages, from_dataset_entities, target_json

HERE = os.path.dirname(os.path.abspath(__file__))
LANGS = ("en", "it")


def load(patterns):
    rows = []
    for pat in patterns:
        for p in sorted(glob.glob(pat)):
            rows += [json.loads(l) for l in open(p) if l.strip()]
    return rows


def normalise_row(r):
    """Row -> ml-ready row: v3 entities, stable id, lang and kind always present."""
    ents = from_dataset_entities(r["target"]["entities"])
    return {"id": hashlib.sha1(r["diary"].encode()).hexdigest()[:12], "diary": r["diary"],
            "target": {"entities": ents}, "source_disease": r.get("source_disease"),
            "lang": r.get("lang", "en"), "kind": r.get("kind", "clinical" if ents else "hard_negative"),
            "generator": r.get("generator")}


def to_sft(r):
    msgs = build_messages(r["diary"]) + [{"role": "assistant", "content": target_json(r["target"]["entities"])}]
    return {"messages": msgs, "id": r["id"], "source_disease": r["source_disease"], "lang": r["lang"], "kind": r["kind"]}


def check_sft(path, limit=0):
    """Verify an SFT chat file is extraction_v3: system + user + assistant, assistant is strict v3 JSON.
    Returns {"rows": n, "empty_targets": k}; raises ValueError naming the first bad line."""
    from prompt import SYSTEM_PROMPT, strict_valid
    n = empty = 0
    for ln, line in enumerate(open(path), 1):
        if not line.strip():
            continue
        m = json.loads(line).get("messages") or []
        if [x.get("role") for x in m] != ["system", "user", "assistant"] or m[0]["content"] != SYSTEM_PROMPT:
            raise ValueError(f"{path}:{ln}: not a v3 chat row (roles or system prompt differ)")
        if not strict_valid(m[2]["content"]):
            raise ValueError(f"{path}:{ln}: assistant content is not strict extraction_v3 JSON")
        empty += not json.loads(m[2]["content"])["entities"]
        n += 1
        if limit and n >= limit:
            break
    if not n:
        raise ValueError(f"{path}: no rows")
    return {"rows": n, "empty_targets": empty}


def write(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def split(rows, val_frac=0.1, test_frac=0.1, seed=13):
    """-> (train, val, test). Disease-disjoint, language-stratified at group level."""
    groups = {}
    for i, r in enumerate(rows):
        groups.setdefault(r.get("source_disease") or f"row{i}", []).append(r)
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    keys.sort(key=lambda k: -len(groups[k]))  # big groups first, shuffled order breaks ties
    total = {l: sum(r["lang"] == l for r in rows) for l in LANGS}
    target = {"val": {l: val_frac * total[l] for l in LANGS}, "test": {l: test_frac * total[l] for l in LANGS}}
    count = {s: {l: 0 for l in LANGS} for s in ("val", "test")}
    assign = {}
    for k in keys:
        g = {l: sum(r["lang"] == l for r in groups[k]) for l in LANGS}
        best, best_gain = "train", 0.0
        for s in ("val", "test"):
            gain = sum(min(g[l], max(0.0, target[s][l] - count[s][l])) for l in LANGS) \
                - sum(max(0.0, count[s][l] + g[l] - target[s][l]) for l in LANGS) * 0.5
            if gain > best_gain:
                best, best_gain = s, gain
        assign[k] = best
        if best != "train":
            for l in LANGS:
                count[best][l] += g[l]
    out = {"train": [], "val": [], "test": []}
    for k in keys:
        out[assign[k]] += groups[k]
    return out["train"], out["val"], out["test"]


def describe(rs):
    dis = {r["source_disease"] for r in rs if r.get("source_disease")}
    return (f"{len(rs)} rows, {len(dis)} diseases, en {sum(r['lang'] == 'en' for r in rs)} / it "
            f"{sum(r['lang'] == 'it' for r in rs)}, hard negatives {sum(not r['target']['entities'] for r in rs)}, "
            f"entities {sum(len(r['target']['entities']) for r in rs)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", default=[os.path.join(HERE, "data", "synth", "*.jsonl")])
    ap.add_argument("--data-dir", default=os.path.join(HERE, "data", "v3"))
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--test-frac", type=float, default=0.1)
    a = ap.parse_args()
    raw = load(a.inputs)
    if not raw:
        raise SystemExit(f"no rows in {a.inputs}; run synth.py first")
    seen, rows = set(), []
    for r in map(normalise_row, raw):
        if r["id"] not in seen:  # exact duplicate diaries add nothing and can leak across splits
            seen.add(r["id"])
            rows.append(r)
    tr, va, te = split(rows, a.val_frac, a.test_frac, a.seed)
    dis = lambda rs: {r["source_disease"] for r in rs if r.get("source_disease")}
    assert not (dis(tr) & dis(va) or dis(tr) & dis(te) or dis(va) & dis(te)), "disease overlap between splits"
    for name, rs in (("train", tr), ("val", va), ("test", te)):
        write(os.path.join(a.data_dir, f"{name}.jsonl"), rs)
        write(os.path.join(a.data_dir, f"{name}_sft.jsonl"), [to_sft(r) for r in rs])
    with open(os.path.join(a.data_dir, "SPLIT.md"), "w") as f:
        f.write(f"# Split (extraction v3)\n\nInputs: {a.inputs}\nDisease-held-out and language-stratified, seed {a.seed}, "
                f"{len(raw) - len(rows)} duplicate diaries dropped\n"
                f"- train: {describe(tr)}\n- val: {describe(va)}\n- test: {describe(te)}\n"
                f"- disease overlap train/val/test: 0\n")
    print(f"train {len(tr)}  val {len(va)}  test {len(te)}  diseases {len(dis(tr))}/{len(dis(va))}/{len(dis(te))}")


if __name__ == "__main__":
    main()
