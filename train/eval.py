"""Score any OpenAI-compatible endpoint on extraction v3 gold rows. Usage:
  python eval.py --dry-run                                  # gold vs gold, offline, must print F1 1.000
  python eval.py --base-url http://localhost:8000/v1 --model NAME --label base-e4b --api-key-env KEY
  python eval.py --base-url https://api.anthropic.com/v1/ --model claude-haiku-5-5 --api-key-env ANTHROPIC_API_KEY \
      --label haiku-baseline            # eval-only comparator; Claude output never becomes training data

Writes <out-dir>/extraction_<label>.json with n, dataset, model, backend, date and every metric.
Metrics: entity F1 (HPO id), fuzzy-name F1, HPO-ID accuracy, negation / family-history / onset /
severity accuracy on matched entities, quote grounding, JSON validity (lenient parse) and strict
v3 schema validity, ECE and Brier when the model emits confidence, latency p50/p95.
With the backend importable (it is in this repo), predictions are also scored after the app's deterministic HPO
resolver (clario.extract.resolve_hpo: keep the model's id only when the ontology agrees with the words, else the
ontology's own best match). Those are the resolved_* metrics: what the app stores, minus the optional model pick.
Gold rows: {"diary", "target": {"entities": [...]}} in v3 or the older dataset shape.
A row with "gold_complete": false (PsyTAR) means unlabelled mentions exist, so precision is a lower bound.
"""
import argparse, copy, datetime, difflib, json, os, re, sys, time, unicodedata
from concurrent.futures import ThreadPoolExecutor
from prompt import build_messages, from_dataset_entities, parse, strict_valid

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(os.path.dirname(HERE), "eval", "results")
DEFAULT_DATA = os.path.join(HERE, "data", "v3", "test.jsonl")


def _norm(s):
    return " ".join(str(s).lower().split())


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    r = tp / (tp + fn) if tp + fn else (1.0 if fp == 0 else 0.0)
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def ekey(e):
    """Identity of an entity: its HPO id (or the normalised quote when it has none), plus negated and family_history.

    "No fever" and "fever" are different entities: a model that drops the negation scores a miss and a false positive."""
    h = (e.get("hpo_id") or "").upper()
    base = h if h else "Q:" + _norm(e.get("quote", ""))
    return f"{base}|neg={int(bool(e.get('negated')))}|fam={int(bool(e.get('family_history')))}"


def match_counts(gold, pred, key):
    """Multiset match on key(entity). Returns tp, fp, fn."""
    g = [key(e) for e in gold]; tp = 0
    for e in pred:
        k = key(e)
        if k in g:
            g.remove(k); tp += 1
    return tp, len(pred) - tp, len(gold) - tp


def pred_correct(gold, pred, key=ekey):
    """Per-prediction tp flag under the multiset match on key (first come, first served)."""
    g = [key(e) for e in gold]; flags = []
    for e in pred:
        k = key(e)
        ok = k in g
        if ok:
            g.remove(k)
        flags.append(ok)
    return flags


def pair_entities(gold, pred):
    """One-to-one (gold, pred) pairs: same key first, then same normalised quote."""
    pairs, gf, pf = [], list(range(len(gold))), list(range(len(pred)))
    for rule in (lambda e: ekey(e), lambda e: _norm(e.get("quote", ""))):  # same identity first, then same words (flags then scored)
        for gi in list(gf):
            for pi in pf:
                if rule(gold[gi]) == rule(pred[pi]):
                    pairs.append((gold[gi], pred[pi])); gf.remove(gi); pf.remove(pi)
                    break
    return pairs


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


# ---- self-consistency: the SAME signal the app routes on (mirrors backend/clario/extract.py find_quote / _same /
# self_consistency; train stays standalone, backend/tests/test_sc_parity.py pins the two together).
def _fold(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _quote_in(text, quote):
    q = re.sub(r"\s+", " ", _fold(quote).strip(" .,;:\"'"))
    if len(q) < 2:
        return False
    return bool(re.search(re.escape(q).replace(r"\ ", r"\s+"), _fold(text)))


def _same(a, b):
    """The app's match key: same negation flag, and the same canonical name (case-insensitive) or the same HPO id."""
    if bool(a.get("negated")) != bool(b.get("negated")):
        return False
    if str(a.get("canonical", "")).strip().lower() == str(b.get("canonical", "")).strip().lower():
        return True
    return bool(a.get("hpo_id")) and a.get("hpo_id") == b.get("hpo_id")


def self_consistency(pred, samples, diary):
    """Per predicted entity: share of the n samples that hold the same (term, negated) pair with a quote found in the
    diary. An unparsable sample (None) counts as a miss. Returns None per entity when there are no samples."""
    if not samples:
        return [None] * len(pred)
    return [round(sum(1 for s in samples if any(_quote_in(diary, q.get("quote", "")) and _same(p, q) for q in (s or [])))
                  / len(samples), 4) for p in pred]


def calibration(points, bins=10):
    """points: [(confidence, correct)] -> (ece, brier). Equal-width bins; None when there are no points."""
    if not points:
        return None, None
    n = len(points); ece = 0.0; table = {}
    for c, ok in points:
        b = min(bins - 1, int(c * bins))
        table.setdefault(b, []).append((c, ok))
    for rows in table.values():
        conf = sum(c for c, _ in rows) / len(rows); acc = sum(ok for _, ok in rows) / len(rows)
        ece += abs(conf - acc) * len(rows) / n
    return ece, sum((c - ok) ** 2 for c, ok in points) / n


def _acc(num, den):
    return num / den if den else None


def score(records):
    """records: [{diary, gold:[entity], pred:[entity]|None}] -> metrics dict."""
    hp = [0, 0, 0]; fz = [0, 0, 0]; n_valid = 0; n_strict = 0; gq = 0; nq = 0
    idok = idn = 0
    flag_recall = {"negated": [0, 0], "family_history": [0, 0]}  # [found, gold] per flag, over all gold entities
    neg = [0, 0]; fam = [0, 0]; ons = [0, 0]; sev = [0, 0]
    points = []; per_item = []; complete = True
    for r in records:
        pred = r["pred"]
        if pred is not None:
            n_valid += 1
        if r.get("strict"):
            n_strict += 1
        pred = pred or []
        gold = r["gold"]
        complete = complete and r.get("gold_complete", True)
        for i, v in enumerate(match_counts(gold, pred, ekey)): hp[i] += v
        for i, v in enumerate(fuzzy_counts(gold, pred)): fz[i] += v
        for e in pred:
            nq += 1; gq += grounded(r["diary"], e["quote"])
        pkeys = [ekey(p) for p in pred]
        for g in gold:
            for flag in flag_recall:
                if g.get(flag):
                    flag_recall[flag][1] += 1
                    flag_recall[flag][0] += ekey(g) in pkeys  # found with the flag set, not just the term
        # HPO-ID accuracy: gold entity with an id whose quote is matched (case-insens) by a pred with the same id
        for g in gold:
            if not g.get("hpo_id"):
                continue
            idn += 1
            idok += any(_norm(p["quote"]) == _norm(g["quote"]) and (p.get("hpo_id") or "").upper() == g["hpo_id"].upper()
                        for p in pred)
        if r.get("gold_complete", True) and not r.get("partial"):
            for g, p in pair_entities(gold, pred):
                neg[1] += 1; neg[0] += bool(g.get("negated")) == bool(p.get("negated"))
                fam[1] += 1; fam[0] += bool(g.get("family_history")) == bool(p.get("family_history"))
                if g.get("onset_hint"):
                    ons[1] += 1; ons[0] += _norm(p.get("onset_hint") or "") == _norm(g["onset_hint"])
                if g.get("severity") is not None:
                    sev[1] += 1; sev[0] += p.get("severity") == g["severity"]
        flags = pred_correct(gold, pred)
        ents = []
        for e, ok in zip(pred, flags):
            if e.get("confidence") is not None:
                points.append((e["confidence"], int(ok)))
                row = {"confidence": e["confidence"], "correct": int(ok)}
                if e.get("verbalized") is not None:  # the model's own number, kept next to the self-consistency one
                    row["confidence_verbalized"] = e["verbalized"]
                ents.append(row)
        per_item.append({"id": r.get("id"), "n_gold": len(gold), "n_pred": len(pred), "entities": ents})
    p, rc, f = _prf(*hp); fp_, fr_, ff_ = _prf(*fz)
    n = len(records)
    ece, brier = calibration(points)
    out = {
        "n": n,
        "entity_precision": p, "entity_recall": rc, "entity_f1": f,
        "fuzzy_precision": fp_, "fuzzy_recall": fr_, "fuzzy_f1": ff_,
        "hpo_id_accuracy": _acc(idok, idn), "n_gold_with_hpo_id": idn,
        "negated_recall": _acc(*flag_recall["negated"]), "n_negated_gold": flag_recall["negated"][1],
        "family_history_recall": _acc(*flag_recall["family_history"]), "n_family_history_gold": flag_recall["family_history"][1],
        "negation_accuracy": _acc(*neg), "family_history_accuracy": _acc(*fam),
        "onset_accuracy": _acc(*ons), "severity_accuracy": _acc(*sev),
        "json_validity_rate": n_valid / n if n else 0.0,
        "schema_valid_rate": n_strict / n if n else 0.0,
        "quote_grounding_rate": _acc(gq, nq), "n_predicted_entities": nq,  # None, not 1.0, when nothing was predicted
        "ece": ece, "brier": brier, "n_confidence_entities": len(points),
        "confidence_coverage": len(points) / nq if nq else None,
        "tp": hp[0], "fp": hp[1], "fn": hp[2], "n_gold_entities": hp[0] + hp[2],
        "n_matched_pairs": neg[1], "gold_complete": complete,
    }
    if points:
        out["per_item"] = per_item
    return out


def make_resolver():
    """-> resolve(entity) -> hpo_id | None using the app's ontology check, or None when the backend is not importable."""
    backend = os.path.join(os.path.dirname(HERE), "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    try:
        from clario.extract import resolve_hpo
        from clario.knowledge import Ontology
    except Exception as e:  # noqa: BLE001 - optional; plain metrics still work
        print("resolver unavailable:", repr(e)[:160])
        return None
    onto = Ontology.load()

    def resolve(e):
        return resolve_hpo(e.get("hpo_id"), e.get("quote") or "", e.get("canonical") or "", onto)[0]
    return resolve


def resolved_metrics(records, resolve):
    """Score the same predictions after the resolver rewrote every hpo_id. Returns resolved_* keys."""
    recs = []
    for r in records:
        pred = copy.deepcopy(r["pred"]) if r["pred"] is not None else None
        for e in pred or []:
            e["hpo_id"] = resolve(e)
        recs.append({**r, "pred": pred})
    m = score(recs)
    keep = ("entity_precision", "entity_recall", "entity_f1", "hpo_id_accuracy", "tp", "fp", "fn")
    return {f"resolved_{k}": m[k] for k in keep}


def load_gold(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    return [{"id": r.get("id"), "diary": r["diary"], "gold": from_dataset_entities(r["target"]["entities"]),
             "gold_complete": r.get("gold_complete", True), "partial": r.get("partial", False)} for r in rows]


def make_complete(base_url, model, key, max_tokens=1024, timeout=300, confidence=False, max_retries=2):
    """-> complete(diary) -> (text, seconds, completion_tokens) against an OpenAI-compatible endpoint."""
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=key or "none", timeout=timeout, max_retries=max_retries)

    def complete(diary):
        t0 = time.time()
        r = client.chat.completions.create(model=model, messages=build_messages(diary, confidence=confidence),
                                           temperature=0, max_tokens=max_tokens)
        dt = time.time() - t0
        return r.choices[0].message.content or "", dt, (r.usage.completion_tokens if r.usage else 0)

    def samples(diary, n, temperature=0.7):
        """n sampled answers in one call (the app's llm.samples does the same with n=CLARIO_SC_N, temperature 0.7)."""
        r = client.chat.completions.create(model=model, messages=build_messages(diary, confidence=confidence),
                                           temperature=temperature, max_tokens=max_tokens, n=n)
        return [c.message.content or "" for c in r.choices]
    complete.samples = samples
    return complete


def make_complete_hf(model_id, adapter=None, load_in_4bit=False, max_tokens=1024, confidence=False):
    """-> complete(diary) running the model in this process (transformers, one GPU), optionally with a LoRA adapter.
    For a card or Kaggle notebook without an OpenAI-compatible server. Calls are serialised (one GPU)."""
    import threading
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    try:
        tok = AutoTokenizer.from_pretrained(adapter or model_id)
    except Exception:  # noqa: BLE001 - a bare checkpoint dir may hold no tokenizer files
        tok = AutoTokenizer.from_pretrained(model_id)
    tok.padding_side = "left"  # batched generation: prompts end at the same position
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    kw = dict(torch_dtype=dtype, device_map={"": 0})
    if load_in_4bit:
        from transformers import BitsAndBytesConfig
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True)
    try:
        model = AutoModelForCausalLM.from_pretrained(model_id, **kw)
    except Exception:  # Gemma 4 card loads with AutoModelForMultimodalLM
        from transformers import AutoModelForMultimodalLM
        model = AutoModelForMultimodalLM.from_pretrained(model_id, **kw)
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    lock = threading.Lock()

    def complete(diary):
        enc = tok.apply_chat_template(build_messages(diary, confidence=confidence), add_generation_prompt=True,
                                      return_tensors="pt", return_dict=True).to(model.device)
        t0 = time.time()
        with lock, torch.no_grad():
            out = model.generate(**enc, max_new_tokens=max_tokens, do_sample=False, use_cache=True)
        gen = out[0, enc["input_ids"].shape[1]:]
        return tok.decode(gen, skip_special_tokens=True), time.time() - t0, int(gen.shape[0])

    def samples(diary, n, temperature=0.7):
        """n sampled answers (same signal as llm.samples in the app), generated in one batch on the GPU."""
        enc = tok.apply_chat_template(build_messages(diary, confidence=confidence), add_generation_prompt=True,
                                      return_tensors="pt", return_dict=True).to(model.device)
        with lock, torch.no_grad():
            out = model.generate(**enc, max_new_tokens=max_tokens, do_sample=True, temperature=temperature,
                                 num_return_sequences=n, use_cache=True)
        k = enc["input_ids"].shape[1]
        return [tok.decode(o[k:], skip_special_tokens=True) for o in out]
    def batch(diaries):
        """Greedy answers for several diaries in one padded batch: the same outputs as complete(), much faster."""
        enc = tok.apply_chat_template([build_messages(d, confidence=confidence) for d in diaries], add_generation_prompt=True,
                                      return_tensors="pt", return_dict=True, padding=True).to(model.device)
        t0 = time.time()
        with lock, torch.no_grad():
            out = model.generate(**enc, max_new_tokens=max_tokens, do_sample=False, use_cache=True,
                                 pad_token_id=tok.pad_token_id)
        dt = (time.time() - t0) / len(diaries)
        k = enc["input_ids"].shape[1]
        res = []
        for o in out:
            gen = o[k:]
            n = int((gen != tok.pad_token_id).sum())
            res.append((tok.decode(gen, skip_special_tokens=True), dt, n))
        return res
    complete.samples = samples
    complete.batch = batch
    return complete


def run_records(gold, complete, concurrency=4, sc_n=0, batch_size=1):
    """Run complete(diary) over gold rows. Returns (records, wall_seconds).
    sc_n > 1: also draw sc_n samples per row and set every predicted entity's confidence to its self-consistency
    (agreement rate across the samples, the app's signal); a verbalized confidence the model wrote moves to `verbalized`."""
    def one(g):
        try:
            text, dt, toks = complete(g["diary"])
            pred = parse(text)
            if sc_n > 1 and pred:
                sampled = [parse(t) for t in complete.samples(g["diary"], sc_n)]
                for e, c in zip(pred, self_consistency(pred, sampled, g["diary"])):
                    e["verbalized"] = e.get("confidence")
                    e["confidence"] = c
            return {**g, "pred": pred, "strict": strict_valid(text), "dt": dt, "toks": toks, "raw": text, "err": None}
        except Exception as e:
            return {**g, "pred": None, "strict": False, "dt": 0.0, "toks": 0, "raw": "", "err": repr(e)}
    t0 = time.time()
    if getattr(complete, "batch", None) and sc_n <= 1 and batch_size > 1:  # in-process model: padded batches
        recs = []
        for i in range(0, len(gold), batch_size):
            chunk = gold[i:i + batch_size]
            try:
                outs = complete.batch([g["diary"] for g in chunk])
            except Exception as e:  # noqa: BLE001 - e.g. out of memory: fall back to one at a time
                print("batch failed, one by one:", repr(e)[:160])
                recs += [one(g) for g in chunk]
                continue
            for g, (text, dt, toks) in zip(chunk, outs):
                recs.append({**g, "pred": parse(text), "strict": strict_valid(text), "dt": dt, "toks": toks,
                             "raw": text, "err": None})
        return recs, time.time() - t0
    with ThreadPoolExecutor(concurrency) as ex:
        recs = list(ex.map(one, gold))
    return recs, time.time() - t0


def pct(xs, q):
    if not xs: return 0.0
    xs = sorted(xs); return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def infer_backend(url):
    u = (url or "").lower()
    if "anthropic.com" in u: return "anthropic-openai-compat"
    if "11434" in u: return "ollama"
    return "openai-compatible"


def table(label, m):
    def f(v): return "n/a" if v is None else f"{v:.3f}"
    rows = [("entity F1 (HPO id)", m["entity_f1"]), ("entity F1 after resolver", m.get("resolved_entity_f1")), ("precision", m["entity_precision"]), ("recall", m["entity_recall"]),
            ("fuzzy-name F1", m["fuzzy_f1"]), (f"HPO-ID accuracy (n={m.get('n_gold_with_hpo_id', 0)})", m["hpo_id_accuracy"]),
            (f"negated recall (n={m.get('n_negated_gold', 0)})", m.get("negated_recall")),
            (f"family-history recall (n={m.get('n_family_history_gold', 0)})", m.get("family_history_recall")),
            ("negation accuracy", m["negation_accuracy"]), ("family-history accuracy", m["family_history_accuracy"]),
            ("onset accuracy", m["onset_accuracy"]), ("severity accuracy", m["severity_accuracy"]),
            ("quote grounding", m["quote_grounding_rate"]), ("JSON validity", m["json_validity_rate"]),
            ("schema valid (strict)", m["schema_valid_rate"]), ("ECE", m["ece"]), ("Brier", m["brier"])]
    out = [f"| metric ({label}, n={m['n']}) | value |", "|---|---|"]
    out += [f"| {k} | {f(v)} |" for k, v in rows]
    for k in ("latency_p50_s", "latency_p95_s", "tokens_per_s"):
        if k in m: out.append(f"| {k} | {m[k]:.2f} |")
    return "\n".join(out)


def build_result(m, label, dataset, model, backend, **extra):
    """Result file body: provenance fields first, then metrics. Every number in the repo traces to one of these."""
    head = {"label": label, "dataset": dataset, "model": model, "backend": backend,
            "date": datetime.date.today().isoformat(), "n": m["n"]}
    return {**head, **{k: v for k, v in m.items() if k != "n"}, **extra}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url"); ap.add_argument("--model"); ap.add_argument("--api-key-env", default="")
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--dataset", default="", help="dataset name recorded in the result (default: file path tail)")
    ap.add_argument("--backend", default="", help="e.g. vllm-rocm-mi300x, ollama, lemonade (default: inferred from URL)")
    ap.add_argument("--label", default="run"); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--confidence", action="store_true", help="ask for a confidence field (prompt variant): verbalized confidence")
    ap.add_argument("--sc-n", type=int, default=0,
                    help="self-consistency: draw N samples per diary, confidence = agreement rate (the signal the app routes on). "
                         "With --confidence too, the verbalized number is kept as confidence_verbalized for comparison")
    ap.add_argument("--concurrency", type=int, default=4); ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--timeout", type=float, default=300); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-retries", type=int, default=2, help="API retries with backoff on 429/5xx (shared-quota APIs: 8)")
    ap.add_argument("--out-dir", default=DEFAULT_OUT)
    ap.add_argument("--hf-model", default="", help="run this HF model in-process instead of calling --base-url")
    ap.add_argument("--adapter", default="", help="LoRA adapter dir for --hf-model")
    ap.add_argument("--load-in-4bit", action="store_true", help="--hf-model in 4-bit (16 GB GPUs)")
    ap.add_argument("--batch-size", type=int, default=16, help="--hf-model: diaries per padded generate() call")
    ap.add_argument("--no-resolve", action="store_true", help="skip the resolved_* metrics (app HPO resolver)")
    a = ap.parse_args(argv)
    gold = load_gold(a.data)
    if a.limit: gold = gold[:a.limit]
    os.makedirs(a.out_dir, exist_ok=True)
    dataset = a.dataset or "/".join(os.path.normpath(a.data).split(os.sep)[-2:])
    if a.dry_run:
        recs = [{**g, "pred": parse(json.dumps({"entities": g["gold"]})), "strict": True} for g in gold]
        m = score(recs); label = "dryrun-gold-vs-gold"
        m.update(latency_p50_s=0.0, latency_p95_s=0.0, tokens_per_s=0.0)
        res = build_result(m, label, dataset, "gold-copy", "offline-dry-run", dry_run=True,
                           note="gold scored against itself, no model; checks the scorer only, not a model result")
    else:
        if a.hf_model:
            complete = make_complete_hf(a.hf_model, a.adapter or None, a.load_in_4bit, a.max_tokens, a.confidence)
            a.model = a.hf_model + (f"+{os.path.basename(os.path.normpath(a.adapter))}" if a.adapter else "")
            a.backend = a.backend or ("transformers-4bit" if a.load_in_4bit else "transformers")
            a.concurrency = 1
        else:
            if not (a.base_url and a.model): ap.error("--base-url and --model required (or --hf-model)")
            key = os.environ.get(a.api_key_env, "") if a.api_key_env else "none"
            complete = make_complete(a.base_url, a.model, key, a.max_tokens, a.timeout, a.confidence, a.max_retries)
        recs, wall = run_records(gold, complete, a.concurrency, a.sc_n, a.batch_size if a.hf_model else 1)
        m = score(recs); label = a.label
        resolve = None if a.no_resolve else make_resolver()
        if resolve:
            m.update(resolved_metrics(recs, resolve), resolver="clario.extract.resolve_hpo (ontology check, no model pick)")
        lat = [r["dt"] for r in recs if r["err"] is None]
        m.update(latency_p50_s=pct(lat, .5), latency_p95_s=pct(lat, .95),
                 tokens_per_s=sum(r["toks"] for r in recs) / wall if wall else 0.0,
                 wall_s=wall, errors=sum(r["err"] is not None for r in recs), concurrency=a.concurrency)
        res = build_result(m, label, dataset, a.model, a.backend or infer_backend(a.base_url), dry_run=False,
                           confidence_prompt=a.confidence, base_url=a.base_url or None, sc_n=a.sc_n,
                           confidence_source=("self_consistency" if a.sc_n > 1 else "verbalized" if a.confidence else None))
        res["samples"] = [{"diary": r["diary"], "raw": r["raw"][:600], "err": r["err"]} for r in recs[:3]]
    with open(os.path.join(a.out_dir, f"extraction_{label}.json"), "w") as f: json.dump(res, f, indent=2)
    print(table(label, res))
    if a.dry_run and abs(res["entity_f1"] - 1.0) > 1e-9: sys.exit(1)
    return res


if __name__ == "__main__":
    main()
