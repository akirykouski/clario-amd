"""Lay lexicon: everyday English ways patients describe each HPO term, generated and then verified.

HPO's own "layperson" synonyms are few (about 1.8 per term) and often still clinical ("Lack of bladder control due
to nervous system injury"). Patients write "my knee is itchy". This step asks the generator model (Gemma 4 31B on
vLLM) for many short everyday phrasings per term, in different registers, then keeps a phrase only if:
  1. code checks pass: 2 to 9 words, no copy of the clinical label, no Latin/Greek clinical word endings, no digits;
  2. a second, blind call maps it back: the model sees the phrase and the target among similar distractor terms
     (siblings in the ontology) in shuffled order, and must pick the target.
synth.py then samples the wording of each symptom from this lexicon, so the diaries look like patients wrote them.

    python lay_expand.py --base-url http://localhost:8000/v1 --model google/gemma-4-31B-it --terms 800
    python lay_expand.py --offline --terms 50          # no model: pipeline check

Writes train/lay_lexicon.json ({hpo_id: [phrase, ...]}) and lay_lexicon.json.stats.json. Same rule as synth.py:
Anthropic endpoints are refused (training data must come from an open model).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import string
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
from clario.knowledge import Ontology  # noqa: E402
from prompt import _extract_json  # noqa: E402

LAY: dict[str, list[str]] = json.loads((HERE / "lay_terms.json").read_text())
OUT = HERE / "lay_lexicon.json"
N_DISTRACTORS = 4
# Word endings that mark clinical vocabulary; a patient phrase must not contain them.
CLINICAL_WORD = re.compile(r"\b\w+(itis|osis|emia|aemia|algia|opathy|plasia|trophy|megaly|penia|rrhea|rrhoea|uria|"
                           r"ectasia|carcinoma|edema|oedema|cytosis|phagia|phasia|plegia|paresis)\b"
                           r"|\b(syndrome|lesion|nodule|tremor|erythema|pruritus|dyspnea|dyspnoea|fatigue|malaise|"
                           r"anemia|anaemia|lymph|bilateral|chronic|acute|recurrent|abnormal\w*)\b", re.I)

SYSTEM = """You help build a medical NLP dataset. Write how ordinary English-speaking patients describe a symptom in
their own words, in a private diary or a text message to a friend. No medical vocabulary at all.
Return ONLY JSON: {"phrases": ["...", "..."]}"""

STYLES = ["a teenager texting a friend", "a retired person writing a diary", "a busy office worker typing fast",
          "someone who is not a native English speaker", "someone describing exactly where on the body it happens",
          "someone describing what it feels like (a comparison or image)", "someone who makes small typos"]

VERIFY_SYSTEM = """You are checking a dataset. For each patient phrase, pick the ONE medical term it describes, by its
letter, or "none" if it fits none of them or fits several equally. Return ONLY JSON: {"answers": ["A", "none", ...]}
with one answer per phrase, in order."""


def candidate_terms(onto: Ontology, limit: int) -> list[str]:
    """Terms synth.py can sample (same rule as synth.term_ok), most often annotated in diseases first."""
    freq: Counter = Counter()
    for d in onto.diseases():
        for t in d.phenotypes:
            if t in LAY:
                freq[t] += 1
    pool = [t for t in LAY if onto.ic(t) >= 2.0 and onto.label(t)]
    pool.sort(key=lambda t: (-freq[t], t))
    return pool[:limit] if limit else pool


def gen_prompt(onto: Ontology, t: str, n: int) -> str:
    syns = [s for s in LAY.get(t, []) if s.lower() != (onto.label(t) or "").lower()][:3]
    return "\n".join([
        f"Symptom: {onto.label(t)}" + (f" (also called: {', '.join(syns)})" if syns else ""),
        f"Give {n} different short phrases (2 to 8 words each) a patient could write for this symptom, as they would",
        "appear inside a sentence. Make them clearly different from each other. Mix these voices:",
        *[f"- {s}" for s in STYLES],
        f'Never use the words "{onto.label(t)}" or any medical term. No full sentences, no explanations.'])


def code_ok(onto: Ontology, t: str, phrase: str) -> str | None:
    """None when the phrase passes the code checks, else the reject reason."""
    p = phrase.strip().strip(string.punctuation + " ")
    words = p.split()
    if not 2 <= len(words) <= 9 or len(p) > 70:
        return "length"
    label = (onto.label(t) or "").lower()
    if label and (p.lower() == label or (len(label.split()) > 1 and label in p.lower())):
        return "clinical_label"
    if CLINICAL_WORD.search(p):
        return "clinical_word"
    if re.search(r"\d", p):
        return "digit"
    return None


def distractors(onto: Ontology, t: str, pool: list[str], rng: random.Random, k: int = N_DISTRACTORS) -> list[str]:
    """Similar terms the phrase must NOT map to: siblings under the most specific ancestor, then same organ system."""
    related = onto.ancestors(t) | onto.descendants(t)
    anc = sorted(onto.ancestors(t), key=lambda a: -onto.ic(a))
    out: list[str] = []
    for a in anc:
        sib = [x for x in pool if x != t and x not in related and a in onto.ancestors(x) and x not in out]
        rng.shuffle(sib)
        out += sib[:k - len(out)]
        if len(out) >= k:
            break
    if len(out) < k:
        sysm = onto.systems(t)
        rest = [x for x in pool if x != t and x not in related and x not in out and onto.systems(x) & sysm]
        rng.shuffle(rest)
        out += rest[:k - len(out)]
    return out[:k]


def verify_prompt(onto: Ontology, options: list[str], phrases: list[str]) -> str:
    letters = string.ascii_uppercase
    return "\n".join(["Medical terms:", *[f"{letters[i]}) {onto.label(o)}" for i, o in enumerate(options)],
                      "", "Patient phrases:", *[f"{i + 1}. {p}" for i, p in enumerate(phrases)]])


def offline_phrases(onto: Ontology, t: str, n: int) -> list[str]:
    """Deterministic stand-in for the generator (pipeline check only, never a result)."""
    base = [s.lower() for s in LAY.get(t, [])] or [(onto.label(t) or t).lower()]
    out = []
    for i in range(n):
        b = base[i % len(base)]
        out.append(["my " + b + " again", "this " + b + " thing", "kinda " + b, "the " + b + " is back"][i % 4])
    return out


async def chat(client, model: str, system: str, user: str, max_tokens: int, temperature: float) -> dict:
    r = await client.chat.completions.create(model=model, temperature=temperature, max_tokens=max_tokens,
                                             messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    obj = _extract_json(r.choices[0].message.content or "")
    if obj is None:
        raise json.JSONDecodeError("no JSON object in the reply", "", 0)
    return obj


async def expand_term(client, a, onto: Ontology, t: str, pool: list[str], rng: random.Random, reasons: Counter) -> list[str]:
    if client is None:
        raw = offline_phrases(onto, t, a.per_term)
    else:
        obj = await chat(client, a.model, SYSTEM, gen_prompt(onto, t, a.per_term), 600, 1.0)
        raw = [p for p in obj.get("phrases") or [] if isinstance(p, str)]
    seen, kept = set(), []
    for p in raw:
        p = p.strip().strip(string.punctuation + " ").lower()
        why = code_ok(onto, t, p) or ("duplicate" if p in seen else None)
        reasons[why or "code_ok"] += 1
        if not why:
            seen.add(p)
            kept.append(p)
    if not kept:
        return []
    if client is None:
        reasons["verified"] += len(kept)
        return kept
    options = [t] + distractors(onto, t, pool, rng)
    rng.shuffle(options)
    target = string.ascii_uppercase[options.index(t)]
    obj = await chat(client, a.model, VERIFY_SYSTEM, verify_prompt(onto, options, kept), 300, 0.0)
    answers = [str(x).strip().upper()[:1] if str(x).strip().lower() != "none" else "none" for x in (obj.get("answers") or [])]
    good = [p for p, ans in zip(kept, answers) if ans == target]
    reasons["verified"] += len(good)
    reasons["failed_round_trip"] += len(kept) - len(good)
    return good


def check_endpoint(base_url: str) -> None:
    if "anthropic.com" in base_url:
        sys.exit("refused: Claude output must not become training data. Use Gemma on vLLM.")


async def run(a, client=None) -> dict:
    onto = Ontology.load()
    terms = candidate_terms(onto, a.terms)
    pool = candidate_terms(onto, 0)
    out_path = Path(a.out)
    lex: dict[str, list[str]] = json.loads(out_path.read_text()) if out_path.exists() and not a.fresh else {}
    todo = [t for t in terms if t not in lex]
    if client is None and not a.offline:
        check_endpoint(a.base_url)
        from openai import AsyncOpenAI
        key = os.environ.get(a.api_key_env) if a.api_key_env else "EMPTY"
        if not key:
            sys.exit(f"set {a.api_key_env}")
        client = AsyncOpenAI(base_url=a.base_url, api_key=key, timeout=120, max_retries=3)
    sem = asyncio.Semaphore(a.concurrency)
    reasons: Counter = Counter()
    rng = random.Random(a.seed)
    t0 = time.time()

    async def one(t: str) -> None:
        async with sem:
            try:
                got = await expand_term(client, a, onto, t, pool, random.Random(rng.random()), reasons)
            except Exception as e:  # network, bad JSON: count and move on, a re-run picks the term up again
                reasons[type(e).__name__] += 1
                return
            if got:
                lex[t] = got

    for i in range(0, len(todo), 200):  # save every 200 terms so an interrupted run resumes
        await asyncio.gather(*(one(t) for t in todo[i:i + 200]))
        out_path.write_text(json.dumps(lex, ensure_ascii=False, indent=0, sort_keys=True))
        print(f"{min(i + 200, len(todo))}/{len(todo)} terms  {dict(reasons)}  {time.time() - t0:.0f}s", flush=True)
    phrases = sum(len(v) for v in lex.values())
    summary = {"terms_requested": len(terms), "terms_with_phrases": len(lex), "phrases": phrases,
               "phrases_per_term": round(phrases / max(1, len(lex)), 2), "reasons": dict(reasons),
               "generator": "offline" if client is None else a.model, "seconds": round(time.time() - t0, 1)}
    Path(str(out_path) + ".stats.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", type=int, default=800, help="how many terms, most frequent in diseases first (0 = all)")
    ap.add_argument("--per-term", type=int, default=10, help="phrases requested per term")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--model", default="google/gemma-4-31B-it")
    ap.add_argument("--api-key-env", default="VLLM_API_KEY", help="'' for a vLLM server without a key")
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--fresh", action="store_true", help="ignore an existing lexicon file and start over")
    ap.add_argument("--offline", action="store_true", help="no model; deterministic phrases to test the pipeline")
    print(json.dumps(asyncio.run(run(ap.parse_args())), indent=2))


if __name__ == "__main__":
    main()
