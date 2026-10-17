"""Score TypeSafe Jev (a decision model: typed questions in, probabilities out) on the extraction test rows.

Jev does not write text, so it cannot emit the extraction JSON. It is run as the decision step of a
retrieve-then-decide pipeline that uses the app's own ontology:
  1. candidates: the HPO terms the app's ontology search returns for each clause of the diary (top K per clause,
     at most MAX_CANDIDATES per diary). Their recall against gold is reported as the pipeline's ceiling.
  2. Jev answers three yes/no questions per candidate: the writer has it, the writer says they do not have it,
     a relative of the writer has it.
  3. A candidate becomes one predicted entity when a probability passes 0.5 (own > denied > relative).
Predictions are scored by train/eval.py's score() exactly like the generative models (HPO id + negation + family).
Quote, onset and severity are not produced, so those columns do not apply.

    python eval/jev_eval.py --limit 100 --label jev-test100          # key from env JEV_API_KEY
Writes eval/results/extraction_<label>.json.
"""
import argparse, gzip, json, os, random, re, sys, time
from concurrent.futures import ThreadPoolExecutor

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "train"), os.path.join(ROOT, "backend")]
from eval import build_result, load_gold, score, table  # noqa: E402  (train/eval.py)
from clario.knowledge import DEFAULT_PATH, Ontology  # noqa: E402

URL = "https://api.typesafe.ai/v1/systemone"
PER_CLAUSE, MAX_CANDIDATES, QUESTIONS_PER_CALL = 8, 60, 45


def clauses(text):
    parts = re.split(r"[.!?;\n]+|,\s+(?:but|ma|and|e|though|però)\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 3]


def candidates(onto, diary):
    seen, out = set(), []
    for c in clauses(diary):
        for t in onto.search(c, PER_CLAUSE):
            if t.hpo_id not in seen:
                seen.add(t.hpo_id); out.append(t)
    return out[:MAX_CANDIDATES]


def questions(terms):
    q = {}
    for i, t in enumerate(terms):
        q[f"own_{i}"] = {"type": "noul", "instructions": f"Does the writer say they themselves currently have or had: {t.label}?"}
        q[f"neg_{i}"] = {"type": "noul", "instructions": f"Does the writer explicitly say they do NOT have: {t.label}?"}
        q[f"fam_{i}"] = {"type": "noul", "instructions": f"Does the writer say a relative (not the writer) has: {t.label}?"}
    return q


def ask(client, key, model, diary, qs, retries=8):
    for attempt in range(retries):
        r = client.post(URL, headers={"Authorization": f"Bearer {key}"},
                        json={"model": model, "state": diary, "questions": qs}, timeout=120)
        if r.status_code in (429, 529, 502, 503):
            time.sleep(min(30, 2 ** attempt)); continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def oracle_candidates(onto, diary, gold_ids, n=30, seed=0):
    """Gold terms plus retrieved distractors, shuffled: isolates Jev's decision quality from retrieval."""
    from clario.models import Term
    terms = [Term(hpo_id=h, label=onto.label(h) or h) for h in sorted(gold_ids)]
    terms += [t for t in candidates(onto, diary) if t.hpo_id not in gold_ids][:max(0, n - len(terms))]
    random.Random(seed).shuffle(terms)
    return terms


def predict(client, key, model, onto, diary, thr=0.5, terms=None):
    terms = terms if terms is not None else candidates(onto, diary)
    qs = questions(terms); answers = {}; used = None; toks = 0
    items = list(qs.items())
    for i in range(0, len(items), QUESTIONS_PER_CALL):
        res = ask(client, key, model, diary, dict(items[i:i + QUESTIONS_PER_CALL]))
        answers.update({k: v.get("noul") for k, v in res["answers"].items()})
        used = res.get("model"); toks += sum((res.get("usage") or {}).values())
    pred = []
    for i, t in enumerate(terms):
        own, neg, fam = (answers.get(f"{k}_{i}") or 0.0 for k in ("own", "neg", "fam"))
        best = max((own, "own"), (neg, "neg"), (fam, "fam"))
        if best[0] >= thr:
            pred.append({"quote": "", "canonical": t.label, "hpo_id": t.hpo_id, "type": "symptom",
                         "negated": best[1] == "neg", "family_history": best[1] == "fam",
                         "onset_hint": None, "severity": None, "confidence": round(best[0], 4)})
    return pred, [t.hpo_id for t in terms], used, toks


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(ROOT, "train", "data", "v3", "test.jsonl"))
    ap.add_argument("--limit", type=int, default=100); ap.add_argument("--label", default="jev-test100")
    ap.add_argument("--model", default="jev-latest"); ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out-dir", default=os.path.join(HERE, "results"))
    ap.add_argument("--lexicon", default="", help="lay lexicon JSON {hpo_id: [phrases]} added to the search index (clario-synth-v3)")
    ap.add_argument("--oracle", action="store_true", help="candidates = gold terms + retrieved distractors (decision quality only)")
    a = ap.parse_args(argv)
    key = os.environ["JEV_API_KEY"]
    if a.lexicon:
        onto = Ontology(json.load(gzip.open(DEFAULT_PATH, "rt", encoding="utf-8")), json.load(open(a.lexicon)))
    else:
        onto = Ontology.load()
    gold = load_gold(a.data)[:a.limit]
    t0 = time.time(); done = [0]; versions = set(); tokens = [0]; cand_hit = [0, 0]
    with httpx.Client() as client:
        def one(g):
            try:
                gids = {e["hpo_id"] for e in g["gold"] if e.get("hpo_id")}
                terms = oracle_candidates(onto, g["diary"], gids) if a.oracle else None
                pred, cands, ver, toks = predict(client, key, a.model, onto, g["diary"], terms=terms)
                versions.add(ver); tokens[0] += toks
                cand_hit[0] += len(gids & set(cands)); cand_hit[1] += len(gids)
                rec = {**g, "pred": pred, "strict": True, "err": None}
            except Exception as e:  # noqa: BLE001
                rec = {**g, "pred": None, "strict": False, "err": repr(e)[:200]}
            done[0] += 1
            if done[0] % 10 == 0:
                print(f"  {done[0]}/{len(gold)} rows, {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
            return rec
        with ThreadPoolExecutor(a.concurrency) as ex:
            recs = list(ex.map(one, gold))
    m = score(recs)
    m.update(wall_s=time.time() - t0, errors=sum(r["err"] is not None for r in recs), latency_p50_s=0.0, latency_p95_s=0.0,
             tokens_per_s=0.0, candidate_recall=cand_hit[0] / cand_hit[1] if cand_hit[1] else None,
             total_tokens=tokens[0])
    res = build_result(m, a.label, "v3/test.jsonl", "typesafe " + ",".join(sorted(v for v in versions if v)),
                       "typesafe-api", dry_run=False, oracle_candidates=a.oracle, lexicon=bool(a.lexicon), pipeline=(
                           ("ORACLE candidates: gold terms + retrieved distractors (30), " if a.oracle else
                            f"retrieve-then-decide: app ontology search{' + lay lexicon' if a.lexicon else ''} top {PER_CLAUSE} per clause (max {MAX_CANDIDATES}), ") +
                           "Jev noul own/denied/relative per candidate, threshold 0.5; no quotes, onset or severity"),
                       note="Jev is a decision model; candidate_recall is the ceiling the retrieval step allows")
    res["samples"] = [{"diary": r["diary"][:300], "pred": (r["pred"] or [])[:5], "err": r["err"]} for r in recs[:3]]
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(res, open(os.path.join(a.out_dir, f"extraction_{a.label}.json"), "w"), indent=2)
    print(table(a.label, res)); print("candidate recall (ceiling):", m["candidate_recall"], "| errors", m["errors"])


if __name__ == "__main__":
    main()
