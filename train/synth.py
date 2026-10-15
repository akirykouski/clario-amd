"""Generate synthetic diary entries whose labels come from the ontology, not from the model.

For each sample we pick a disease from phenotype.hpoa, draw 3-6 of its phenotypes by
annotated frequency, add 0-2 absent symptoms and sometimes a trigger, then ask an LLM to
write a short patient diary that mentions them in lay words and to report the exact span it
used for each one. The HPO IDs and canonical labels in the output are the ones we sampled;
the model only contributes the prose and the quote spans, and every row is rejected unless
each quote appears verbatim, each absent symptom is negated in its left context, and no
present symptom is.

Any OpenAI-compatible endpoint works: Claude Haiku via Anthropic's compatibility layer,
or Gemma 4 on vLLM on the MI300X (same flags, different --base-url/--model).

    ANTHROPIC_API_KEY=... python synth.py --n 2000                     # Haiku
    python synth.py --base-url http://<droplet>:8000/v1 --model google/gemma-4-31B-it --api-key-env VLLM_API_KEY
    python synth.py --n 20 --offline                                    # no model, pipeline check

Output rows use the schema prep.py reads.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
from clario.knowledge import Ontology  # noqa: E402

# HPO terms a patient could notice themselves: those with HPO layperson synonyms, minus the
# metabolism, blood and immune lab branches (built from hp.json, see lay_terms.json).
LAY: dict[str, list[str]] = json.loads((HERE / "lay_terms.json").read_text())
NEG_POOL = ["HP:0001945", "HP:0002315", "HP:0012378", "HP:0002018", "HP:0002014", "HP:0002829",
            "HP:0000989", "HP:0002094", "HP:0001369", "HP:0012531"]  # fever, headache, fatigue, nausea...
TRIGGERS = {"en": ["after a long day in the sun", "after a stressful week at work", "after a cold swim",
                   "after a big meal", "after a poor night's sleep"],
            "it": ["dopo una giornata al sole", "dopo una settimana stressante", "dopo un bagno freddo",
                   "dopo una cena abbondante", "dopo una notte insonne"]}
NEG = re.compile(r"\b(no|not|without|never|nessun[ao]?|non|senza|niente|neanche|nemmeno)\b[^.;!?]{0,30}$", re.I)

SYSTEM = """You write realistic, private symptom diary entries for a medical NLP dataset.
The writer is an ordinary patient, not a clinician: plain everyday words, personal details,
some irrelevant life events, varied length (2 to 7 sentences), occasional typos are fine.
Never name a disease or diagnosis. Never use the medical label itself when a lay phrase exists.
Return ONLY JSON: {"diary": "...", "mentions": [{"id": "<id>", "quote": "<exact substring of diary>"}]}
Each quote must be copied character for character from the diary and cover only the symptom words,
not the negation word. Include every id you were given exactly once."""


def term_ok(onto: Ontology, t: str) -> bool:
    return t in LAY and onto.ic(t) >= 2.0


def plan(onto: Ontology, diseases: list, rng: random.Random) -> dict | None:
    d = rng.choice(diseases)
    pool = [(t, w) for t, w in d.phenotypes.items() if term_ok(onto, t)]
    if len(pool) < 3:
        return None
    k = min(len(pool), rng.randint(3, 6))
    present: list[str] = []
    while len(present) < k:
        t = rng.choices([p for p, _ in pool], weights=[max(w, 0.05) for _, w in pool])[0]
        if t not in present:
            present.append(t)
    neg = [t for t in rng.sample(NEG_POOL, rng.choice([0, 0, 1, 2])) if t not in d.phenotypes]
    lang = "it" if rng.random() < 0.3 else "en"
    return {"disease": d.id, "lang": lang, "present": present, "absent": neg,
            "trigger": rng.choice(TRIGGERS[lang]) if rng.random() < 0.35 else None,
            "days": rng.choice([1, 1, 1, 2, 3])}


def user_prompt(onto: Ontology, p: dict) -> str:
    def line(t):
        syn = ", ".join(LAY.get(t, onto.synonyms(t))[:3])
        return f'- {t}: {onto.label(t)}' + (f" (also: {syn})" if syn else "")
    lang = "Italian" if p["lang"] == "it" else "English"
    parts = [f"Language: {lang}. Covers {p['days']} day(s); if more than one, start each day with a short date like 'Mon 3 Mar'.",
             "Symptoms the patient HAS (describe in lay words):", *map(line, p["present"])]
    if p["absent"]:
        parts += ["Symptoms the patient explicitly says they do NOT have (negate them, e.g. 'no fever'):",
                  *map(line, p["absent"])]
    if p["trigger"]:
        parts.append(f'Also mention this circumstance verbatim somewhere: "{p["trigger"]}" (id: TRIGGER).')
    return "\n".join(parts)


def validate(onto: Ontology, p: dict, out: dict) -> tuple[dict | None, str]:
    diary = out.get("diary")
    if not isinstance(diary, str) or len(diary) < 40:
        return None, "no_diary"
    quotes = {}
    for m in out.get("mentions") or []:
        if isinstance(m, dict) and isinstance(m.get("quote"), str):
            quotes[str(m.get("id"))] = m["quote"].strip()
    if p["trigger"]:
        quotes.setdefault("TRIGGER", p["trigger"])
    ents = []
    for t in p["present"] + p["absent"]:
        q = quotes.get(t)
        if not q or len(q) < 3:
            return None, "missing_mention"
        i = diary.find(q)
        if i < 0:
            return None, "quote_not_verbatim"
        negated = bool(NEG.search(diary[max(0, i - 40):i]))
        absent = t in p["absent"]
        if negated != absent:
            return None, "negation_mismatch"
        if not absent and q.lower() == onto.label(t).lower() and len(q.split()) > 1:
            return None, "clinical_label_used"
        ents.append({"name_colloquial": q, "name_canonical": onto.label(t), "hpo_id": t,
                     "type": "symptom", "negated": absent})
    if p["trigger"]:
        q = quotes["TRIGGER"]
        if q not in diary:
            return None, "trigger_missing"
        ents.append({"name_colloquial": q, "name_canonical": p["trigger"], "hpo_id": "",
                     "type": "trigger", "negated": False})
    return {"diary": diary, "target": {"entities": ents}, "source_disease": p["disease"],
            "lang": p["lang"]}, "ok"


def offline_reply(onto: Ontology, p: dict) -> dict:
    """Deterministic stand-in for the model, used to test the pipeline without any inference."""
    bits, mentions = [], []
    for t in p["present"]:
        q = (LAY.get(t) or [onto.label(t)])[0].lower()
        bits.append(f"Today I noticed {q}.")
        mentions.append({"id": t, "quote": q})
    for t in p["absent"]:
        q = onto.label(t).lower()
        bits.append(f"At least no {q}.")
        mentions.append({"id": t, "quote": q})
    if p["trigger"]:
        bits.append(f"It started {p['trigger']}.")
    return {"diary": " ".join(bits), "mentions": mentions}


async def run(a) -> None:
    onto = Ontology.load()
    diseases = [d for d in onto.diseases() if len(d.phenotypes) >= 3]
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = sum(1 for _ in open(out_path)) if out_path.exists() else 0
    rng = random.Random(a.seed + done)  # resumed runs draw fresh plans

    client = None
    if not a.offline:
        from openai import AsyncOpenAI
        key = os.environ.get(a.api_key_env)
        if not key:
            sys.exit(f"set {a.api_key_env}")
        client = AsyncOpenAI(base_url=a.base_url, api_key=key, timeout=120, max_retries=3)

    sem = asyncio.Semaphore(a.concurrency)
    stats = {"ok": 0, "in_tok": 0, "out_tok": 0}
    reasons: dict[str, int] = {}
    t0 = time.time()

    async def one(p: dict, f) -> None:
        async with sem:
            try:
                if client is None:
                    reply = offline_reply(onto, p)
                else:
                    r = await client.chat.completions.create(
                        model=a.model, temperature=1.0, max_tokens=900,
                        messages=[{"role": "system", "content": SYSTEM},
                                  {"role": "user", "content": user_prompt(onto, p)}])
                    if r.usage:
                        stats["in_tok"] += r.usage.prompt_tokens
                        stats["out_tok"] += r.usage.completion_tokens
                    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", (r.choices[0].message.content or "").strip())
                    reply = json.loads(txt)
            except Exception as e:  # network, rate limit, bad JSON: count and move on
                reasons[type(e).__name__] = reasons.get(type(e).__name__, 0) + 1
                return
            row, why = validate(onto, p, reply)
            reasons[why] = reasons.get(why, 0) + 1
            if row:
                row["generator"] = "offline" if client is None else a.model
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                stats["ok"] += 1

    rounds = 0
    with open(out_path, "a") as f:
        while done + stats["ok"] < a.n:
            need = a.n - done - stats["ok"]
            plans = [p for p in (plan(onto, diseases, rng) for _ in range(need)) if p]
            await asyncio.gather(*(one(p, f) for p in plans))
            print(f"{done + stats['ok']}/{a.n} rows  {reasons}  tokens in/out "
                  f"{stats['in_tok']}/{stats['out_tok']}  {time.time() - t0:.0f}s", flush=True)
            if client is None and stats["ok"] == 0:
                break
            rounds += 1
            if rounds >= a.max_rounds:
                break


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="target number of accepted rows in --out")
    ap.add_argument("--out", default=str(HERE / "data" / "synth" / "synth.jsonl"))
    ap.add_argument("--base-url", default="https://api.anthropic.com/v1/")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--api-key-env", default="ANTHROPIC_API_KEY")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--max-rounds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--offline", action="store_true", help="no model; deterministic replies to test the pipeline")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
