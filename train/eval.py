"""Score any OpenAI-compatible endpoint on the val split. Usage:
  python eval.py --dry-run
  python eval.py --base-url http://localhost:8000/v1 --model NAME --label base --api-key-env KEY --limit 20
"""
import argparse, difflib, json, os, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor
from prompt import build_messages, from_dataset_entities, parse

HERE = os.path.dirname(os.path.abspath(__file__))


def _norm(s):
    return " ".join(str(s).lower().split())


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    r = tp / (tp + fn) if tp + fn else (1.0 if fp == 0 else 0.0)
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def match_counts(gold, pred, key):
    """Multiset match on key(entity). Returns tp, fp, fn."""
    g = [key(e) for e in gold]; tp = 0
    for e in pred:
        k = key(e)
        if k in g:
            g.remove(k); tp += 1
    return tp, len(pred) - tp, len(gold) - tp


def fuzzy_counts(gold, pred, thr=0.85):
    """Greedy one-to-one match on canonical-name similarity >= thr."""
    free = list(range(len(gold))); tp = 0
    for e in pred:
        best, bi = 0.0, None
        for i in free:
            s = difflib.SequenceMatcher(None, _norm(e["canonical"]), _norm(gold[i]["canonical"])).ratio()
            if s > best:
                best, bi = s, i
        if bi is not None and best >= thr:
            free.remove(bi); tp += 1
    return tp, len(pred) - tp, len(gold) - tp


def grounded(diary, quote):
    return bool(quote) and quote.lower() in diary.lower()


def score(records):
    """records: [{diary, gold:[entity], pred:[entity]|None}] -> metrics dict."""
    hp = [0, 0, 0]; fz = [0, 0, 0]; n_valid = 0; gq = 0; nq = 0
    idok = 0; idn = 0
    for r in records:
        pred = r["pred"]
        if pred is not None:
            n_valid += 1
        pred = pred or []
        for i, v in enumerate(match_counts(r["gold"], pred, lambda e: e["hpo_id"].upper())): hp[i] += v
        for i, v in enumerate(fuzzy_counts(r["gold"], pred)): fz[i] += v
        for e in pred:
            nq += 1; gq += grounded(r["diary"], e["quote"])
        # HPO-ID accuracy: gold entity whose quote is matched (case-insens) by a pred with the same id
        for g in r["gold"]:
            idn += 1
            idok += any(_norm(p["quote"]) == _norm(g["quote"]) and p["hpo_id"].upper() == g["hpo_id"].upper() for p in pred)
    p, rc, f = _prf(*hp); fp_, fr_, ff_ = _prf(*fz)
    n = len(records)
    return {
        "n": n,
        "entity_precision": p, "entity_recall": rc, "entity_f1": f,
        "fuzzy_precision": fp_, "fuzzy_recall": fr_, "fuzzy_f1": ff_,
        "hpo_id_accuracy": idok / idn if idn else 1.0,
        "json_validity_rate": n_valid / n if n else 0.0,
        "quote_grounding_rate": gq / nq if nq else (1.0 if n else 0.0),
        "tp": hp[0], "fp": hp[1], "fn": hp[2],
    }


def load_gold(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    return [{"diary": r["diary"], "gold": from_dataset_entities(r["target"]["entities"])} for r in rows]


def call(base_url, model, key, diary, max_tokens, timeout):
    import requests
    t0 = time.time()
    resp = requests.post(base_url.rstrip("/") + "/chat/completions",
                         headers={"Authorization": f"Bearer {key}"} if key else {},
                         json={"model": model, "messages": build_messages(diary), "temperature": 0,
                               "max_tokens": max_tokens}, timeout=timeout)
    dt = time.time() - t0
    resp.raise_for_status()
    j = resp.json()
    text = j["choices"][0]["message"].get("content") or ""
    toks = (j.get("usage") or {}).get("completion_tokens", 0)
    return text, dt, toks


def pct(xs, q):
    if not xs: return 0.0
    xs = sorted(xs); return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def table(label, m):
    rows = [("entity F1 (HPO id)", m["entity_f1"]), ("precision", m["entity_precision"]), ("recall", m["entity_recall"]),
            ("fuzzy-name F1", m["fuzzy_f1"]), ("HPO-ID accuracy", m["hpo_id_accuracy"]),
            ("JSON validity", m["json_validity_rate"]), ("quote grounding", m["quote_grounding_rate"])]
    out = [f"| metric ({label}, n={m['n']}) | value |", "|---|---|"]
    out += [f"| {k} | {v:.3f} |" for k, v in rows]
    for k in ("latency_p50_s", "latency_p95_s", "tokens_per_s"):
        if k in m: out.append(f"| {k} | {m[k]:.2f} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url"); ap.add_argument("--model"); ap.add_argument("--api-key-env", default="")
    ap.add_argument("--data", default=os.path.join(HERE, "data", "val_gold.jsonl"))
    ap.add_argument("--label", default="run"); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=4); ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--timeout", type=float, default=300); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out-dir", default=os.path.join(HERE, "results"))
    a = ap.parse_args()
    gold = load_gold(a.data)
    if a.limit: gold = gold[:a.limit]
    os.makedirs(a.out_dir, exist_ok=True)
    if a.dry_run:
        recs = [{**g, "pred": parse(json.dumps({"entities": g["gold"]}))} for g in gold]
        m = score(recs); label = "dry-run-gold-vs-gold"
        m.update(latency_p50_s=0.0, latency_p95_s=0.0, tokens_per_s=0.0)
    else:
        if not (a.base_url and a.model): ap.error("--base-url and --model required")
        key = os.environ.get(a.api_key_env, "") if a.api_key_env else "none"
        def one(g):
            try:
                text, dt, toks = call(a.base_url, a.model, key, g["diary"], a.max_tokens, a.timeout)
                return {**g, "pred": parse(text), "dt": dt, "toks": toks, "raw": text, "err": None}
            except Exception as e:
                return {**g, "pred": None, "dt": 0.0, "toks": 0, "raw": "", "err": repr(e)}
        t0 = time.time()
        with ThreadPoolExecutor(a.concurrency) as ex: recs = list(ex.map(one, gold))
        wall = time.time() - t0
        m = score(recs); label = a.label
        lat = [r["dt"] for r in recs if r["err"] is None]
        m.update(latency_p50_s=pct(lat, .5), latency_p95_s=pct(lat, .95),
                 tokens_per_s=sum(r["toks"] for r in recs) / wall if wall else 0.0,
                 wall_s=wall, errors=sum(r["err"] is not None for r in recs),
                 model=a.model, base_url=a.base_url, concurrency=a.concurrency)
        m["samples"] = [{"diary": r["diary"], "raw": r["raw"][:600], "err": r["err"]} for r in recs[:3]]
    m["label"] = label
    with open(os.path.join(a.out_dir, f"{label}.json"), "w") as f: json.dump(m, f, indent=2)
    print(table(label, m))
    if a.dry_run and abs(m["entity_f1"] - 1.0) > 1e-9: sys.exit(1)


if __name__ == "__main__":
    main()
