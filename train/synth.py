"""M1 data factory: synthetic diary entries whose labels come from the ontology, not from the model.

For each sample we pick a disease from phenotype.hpoa, draw 3-6 of its phenotypes by annotated
frequency and add the distractors that break clinical NLP:
  - 0-2 absent symptoms ("no fever", "niente febbre")            -> negated=true
  - 0-1 family-history items ("my mother has ...", "mia madre ha ...") -> family_history=true,
    still listed in the target
  - onset phrases ("since Tuesday", "da tre giorni") and 0-10 ratings ("6/10") written verbatim
    next to a symptom                                             -> onset_hint, severity
  - irrelevant life events, which carry no label
  - hard negatives (about 8% of rows): entries with nothing clinical in them -> empty entities
An LLM writes the prose and reports the exact quote span for each concept. The HPO IDs, canonical
labels, flags, onset phrases and ratings in the output are the ones we sampled. A row is rejected
unless every check in `validate` passes (verbatim and unique quotes, negation and family cues
found in the left context agree with the label, no clinical label copied as a quote, onset and
rating present next to their symptom, no clinical cue in a hard negative). Reject reasons are
printed and written to <out>.stats.json.

Training data comes from an open-weights model (Gemma on vLLM on the MI300X). Claude output must
not become a training target, so Anthropic endpoints are refused here; Haiku is only used for
gold drafting and judging (gold_draft.py, eval).

    python synth.py --base-url http://localhost:8000/v1 --model google/gemma-4-31B-it --n 5000
    python synth.py --n 40 --offline        # no model, deterministic replies, pipeline check

Output rows use the schema prep.py reads (target.entities are v3 entities, confidence null).
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
RELATIONS = {"en": ["my mother", "my father", "my sister", "my brother", "my grandmother", "my uncle"],
             "it": ["mia madre", "mio padre", "mia sorella", "mio fratello", "mia nonna", "mio zio"]}
ONSET = {"en": ["since Tuesday", "since last weekend", "for three days", "for about two weeks",
                "since Monday morning"],
         "it": ["da martedì", "dallo scorso fine settimana", "da tre giorni", "da circa due settimane",
                "da lunedì mattina"]}
EVENTS = {"en": ["my cousin's wedding is on Saturday", "the car is at the garage again", "I finally repainted the hallway",
                 "work moved the deadline to Friday", "we adopted a very loud kitten", "the bus was late twice",
                 "I started a pottery class", "the neighbours are renovating"],
          "it": ["il matrimonio di mia cugina è sabato", "la macchina è di nuovo dal meccanico",
                 "ho finalmente ridipinto il corridoio", "in ufficio hanno spostato la consegna a venerdì",
                 "abbiamo preso un gattino rumorosissimo", "l'autobus è arrivato in ritardo due volte",
                 "ho iniziato un corso di ceramica", "i vicini stanno ristrutturando"]}

NEG = re.compile(r"(\b(no|not|without|never|nothing|none|nessun[ao]?|non|senza|niente|neanche|nemmeno|mai)\b|n't\b)"
                 r"[^.;!?]{0,30}$", re.I)
FAM = re.compile(r"\b(my|his|her|our)\s+(mother|mom|mum|father|dad|sister|brother|grandmother|grandfather|grandma|"
                 r"grandpa|aunt|uncle|cousin|son|daughter)\b|\b(mia|mio|miei|mie|sua|suo)\s+(madre|mamma|padre|"
                 r"pap[aà]|sorella|fratello|nonna|nonno|zia|zio|cugin[ao]|figli[ao])\b|"
                 r"\b(in my family|runs in the family|in famiglia)\b", re.I)
# Words that make an entry clinical; a hard negative may contain none of them.
CLINICAL_CUE = re.compile(r"pain|ache|hurt|sore\b|fever|tired|fatigue|exhaust|dizz|nause|cough|rash|swell|swoll|"
                          r"headache|sick|\bill\b|doctor|medic|pill|symptom|clinic|hospital|blood|dolor|mal di|"
                          r"febbre|stanc|vertigin|nausea|tosse|eruzion|gonf|malat|dottor|farmac|sintom|ospedal|"
                          r"sangue|pillol", re.I)
WINDOW = 70  # an onset phrase or rating must sit this close to its quote

SYSTEM = """You write realistic, private symptom diary entries for a medical NLP dataset.
The writer is an ordinary patient, not a clinician: plain everyday words, personal details,
some irrelevant life events, varied length (2 to 7 sentences), occasional typos are fine.
Never name a disease or diagnosis. Never use the medical label itself when a lay phrase exists.
Return ONLY JSON: {"diary": "...", "mentions": [{"id": "<id>", "quote": "<exact substring of diary>"}]}
Each quote must be copied character for character from the diary and cover only the symptom words,
not the negation word, not the relative, not the onset phrase, not the rating.
Include every id you were given exactly once. If you were given no ids, return "mentions": []."""


def term_ok(onto: Ontology, t: str) -> bool:
    return t in LAY and onto.ic(t) >= 2.0


def plan(onto: Ontology, diseases: list, rng: random.Random, it_frac: float = 0.4,
         p_hard_neg: float = 0.08) -> dict | None:
    d = rng.choice(diseases)
    lang = "it" if rng.random() < it_frac else "en"
    events = rng.sample(EVENTS[lang], rng.choice([0, 1, 1, 2]))
    if rng.random() < p_hard_neg:
        return {"disease": d.id, "lang": lang, "kind": "hard_negative", "present": [], "absent": [],
                "family": [], "onset": {}, "severity": {}, "events": events or rng.sample(EVENTS[lang], 1),
                "trigger": None, "days": 1}
    pool = [(t, w) for t, w in d.phenotypes.items() if term_ok(onto, t)]
    if len(pool) < 3:
        return None
    k = min(len(pool), rng.randint(3, 6))
    present: list[str] = []
    while len(present) < k:
        t = rng.choices([p for p, _ in pool], weights=[max(w, 0.05) for _, w in pool])[0]
        if t not in present:
            present.append(t)
    neg = [t for t in rng.sample(NEG_POOL, rng.choice([0, 0, 1, 2])) if t not in d.phenotypes and t not in present]
    family = []
    if rng.random() < 0.3:
        used = set(present) | set(neg)
        cands = [t for t in rng.sample(sorted(LAY), 200) if term_ok(onto, t) and t not in used]
        if cands:
            family = [{"id": cands[0], "relation": rng.choice(RELATIONS[lang])}]
    n_on = min(len(present), rng.choice([0, 1, 1, 2]))
    onset = dict(zip(rng.sample(present, n_on), rng.sample(ONSET[lang], n_on)))
    n_sev = min(len(present), rng.choice([0, 1, 1, 2]))
    severity = dict(zip(rng.sample(present, n_sev), rng.sample(range(1, 11), n_sev)))
    return {"disease": d.id, "lang": lang, "kind": "clinical", "present": present, "absent": neg,
            "family": family, "onset": onset, "severity": severity, "events": events,
            "trigger": rng.choice(TRIGGERS[lang]) if rng.random() < 0.35 else None,
            "days": rng.choice([1, 1, 1, 2, 3])}


def user_prompt(onto: Ontology, p: dict) -> str:
    def line(t):
        syn = ", ".join(LAY.get(t, onto.synonyms(t))[:3])
        return f'- {t}: {onto.label(t)}' + (f" (also: {syn})" if syn else "")
    lang = "Italian" if p["lang"] == "it" else "English"
    if p["kind"] == "hard_negative":
        return "\n".join([
            f"Language: {lang}. One day. The patient has NO health complaint today and mentions NO symptom, pain, "
            "tiredness, sickness, medicine or doctor. It is an ordinary diary entry about everyday life.",
            "Mention these everyday events in passing:", *[f"- {e}" for e in p["events"]]])
    parts = [f"Language: {lang}. Covers {p['days']} day(s); if more than one, start each day with a short date like 'Mon 3 Mar'.",
             "Symptoms the patient HAS (describe in lay words):", *map(line, p["present"])]
    if p["absent"]:
        parts += ["Symptoms the patient explicitly says they do NOT have (negate them, e.g. 'no fever'):",
                  *map(line, p["absent"])]
    if p["family"]:
        parts.append("A relative (not the patient) has this; write it as e.g. 'my mother has ...' "
                     "so it is clear it belongs to the relative:")
        parts += [f'{line(f["id"])}  [relative: "{f["relation"]}"]' for f in p["family"]]
    for t, ph in p["onset"].items():
        parts.append(f'Write this exact phrase right next to the symptom {t}: "{ph}"')
    for t, s in p["severity"].items():
        parts.append(f'Write this exact rating right next to the symptom {t}: "{s}/10"')
    if p["events"]:
        parts += ["Mention these unrelated life events in passing (no medical meaning):", *[f"- {e}" for e in p["events"]]]
    if p["trigger"]:
        parts.append(f'Also mention this circumstance verbatim somewhere: "{p["trigger"]}" (id: TRIGGER).')
    return "\n".join(parts)


def cues(diary: str, i: int) -> tuple[bool, bool]:
    """(negated, family) cues found in the left context of the span starting at i, same sentence."""
    pre = re.split(r"[.;!?\n]", diary[max(0, i - 80):i])[-1]
    return bool(NEG.search(pre[-40:])), bool(FAM.search(pre))


def _near(diary: str, i: int, j: int, token: str) -> bool:
    """token occurs exactly once in the diary and within WINDOW chars of the span [i, j)."""
    if diary.count(token) != 1:
        return False
    k = diary.find(token)
    return k + len(token) >= i - WINDOW and k <= j + WINDOW


def entity(quote: str, canonical: str, hpo_id, typ: str, negated=False, family=False, onset=None, severity=None) -> dict:
    return {"quote": quote, "canonical": canonical, "hpo_id": hpo_id, "type": typ, "negated": negated,
            "family_history": family, "onset_hint": onset, "severity": severity, "confidence": None}


def validate(onto: Ontology, p: dict, out: dict) -> tuple[dict | None, str]:
    diary = out.get("diary")
    if not isinstance(diary, str) or len(diary) < 40:
        return None, "no_diary"
    base = {"source_disease": p["disease"], "lang": p["lang"], "kind": p.get("kind", "clinical")}
    if p.get("kind") == "hard_negative":
        if out.get("mentions"):
            return None, "mentions_in_hard_negative"
        if CLINICAL_CUE.search(diary):
            return None, "clinical_in_hard_negative"
        return {"diary": diary, "target": {"entities": []}, **base}, "ok"
    quotes = {}
    for m in out.get("mentions") or []:
        if isinstance(m, dict) and isinstance(m.get("quote"), str):
            quotes[str(m.get("id"))] = m["quote"].strip()
    if p["trigger"]:
        quotes.setdefault("TRIGGER", p["trigger"])
    fam_ids = {f["id"] for f in p.get("family", [])}
    ents, spans = [], []
    for t in p["present"] + p["absent"] + [f["id"] for f in p.get("family", [])]:
        q = quotes.get(t)
        if not q or len(q) < 3:
            return None, "missing_mention"
        i = diary.find(q)
        if i < 0:
            return None, "quote_not_verbatim"
        if diary.count(q) > 1:
            return None, "ambiguous_quote"
        negated, family = cues(diary, i)
        absent, is_fam = t in p["absent"], t in fam_ids
        if negated != absent:
            return None, "negation_mismatch"
        if family != is_fam:
            return None, "family_mismatch"
        if not absent and q.lower() == onto.label(t).lower() and len(q.split()) > 1:
            return None, "clinical_label_used"
        onset, sev = p["onset"].get(t), p["severity"].get(t)
        if any(x and x in q for x in (onset, f"{sev}/10" if sev else None)):
            return None, "quote_overreach"
        if onset and not _near(diary, i, i + len(q), onset):
            return None, "onset_missing"
        if sev is not None and not _near(diary, i, i + len(q), f"{sev}/10"):
            return None, "severity_missing"
        spans.append((i, i + len(q)))
        ents.append(entity(q, onto.label(t), t, "symptom", absent, is_fam, onset, sev))
    if p["trigger"]:
        q = quotes["TRIGGER"]
        if q not in diary:
            return None, "trigger_missing"
        i = diary.find(q)
        spans.append((i, i + len(q)))
        ents.append(entity(q, p["trigger"], None, "trigger"))
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        return None, "overlapping_quotes"
    return {"diary": diary, "target": {"entities": ents}, **base}, "ok"


def _lay(onto: Ontology, t: str) -> str:
    """A lay phrase different from the clinical label when one exists."""
    opts = [x for x in LAY.get(t, []) if x.lower() != (onto.label(t) or "").lower()]
    return (opts or LAY.get(t) or [onto.label(t)])[0].lower()


def offline_reply(onto: Ontology, p: dict) -> dict:
    """Deterministic stand-in for the model, used to test the pipeline without any inference."""
    it = p["lang"] == "it"
    bits, mentions = [], []
    if p["kind"] == "hard_negative":
        bits = ["Giornata tranquilla, ho portato fuori il cane e cucinato la pasta." if it
                else "Quiet day, walked the dog and cooked pasta."]
        bits += [(e[0].upper() + e[1:] + ".") for e in p["events"]]
        return {"diary": " ".join(bits), "mentions": []}
    for t in p["present"]:
        q = _lay(onto, t)
        s = f"Ho notato {q}" if it else f"I noticed {q}"
        if t in p["onset"]:
            s += " " + p["onset"][t]
        if t in p["severity"]:
            s += f" ({p['severity'][t]}/10)"
        bits.append(s + ".")
        mentions.append({"id": t, "quote": q})
    for t in p["absent"]:
        q = onto.label(t).lower()
        bits.append((f"Per fortuna niente {q}." if it else f"At least no {q}."))
        mentions.append({"id": t, "quote": q})
    for f in p["family"]:
        q = _lay(onto, f["id"])
        bits.append(f"{f['relation'][0].upper() + f['relation'][1:]} {'ha' if it else 'has'} {q}.")
        mentions.append({"id": f["id"], "quote": q})
    for e in p["events"]:
        bits.append(e[0].upper() + e[1:] + ".")
    if p["trigger"]:
        bits.append(f"{'È iniziato' if it else 'It started'} {p['trigger']}.")
    return {"diary": " ".join(bits), "mentions": mentions}


async def draft(client, model: str, onto: Ontology, p: dict) -> tuple[dict, tuple[int, int]]:
    """One generator call. client is an AsyncOpenAI-like object. Returns (reply, (in_tokens, out_tokens))."""
    r = await client.chat.completions.create(
        model=model, temperature=1.0, max_tokens=900,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_prompt(onto, p)}])
    toks = (r.usage.prompt_tokens, r.usage.completion_tokens) if getattr(r, "usage", None) else (0, 0)
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", (r.choices[0].message.content or "").strip())
    return json.loads(txt), toks


def check_endpoint(base_url: str) -> None:
    if "anthropic.com" in base_url:
        sys.exit("refused: Claude output must not become training targets. Use Gemma on vLLM for synth.")


async def run(a, client=None) -> dict:
    onto = Ontology.load()
    diseases = [d for d in onto.diseases() if len(d.phenotypes) >= 3]
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = sum(1 for _ in open(out_path)) if out_path.exists() else 0
    rng = random.Random(a.seed + done)  # resumed runs draw fresh plans

    if client is None and not a.offline:
        check_endpoint(a.base_url)
        from openai import AsyncOpenAI
        key = os.environ.get(a.api_key_env) if a.api_key_env else "EMPTY"
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
                    reply, (ti, to) = await draft(client, a.model, onto, p)
                    stats["in_tok"] += ti
                    stats["out_tok"] += to
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
            plans = [p for p in (plan(onto, diseases, rng, a.it_frac, a.p_hard_neg) for _ in range(need)) if p]
            await asyncio.gather(*(one(p, f) for p in plans))
            print(f"{done + stats['ok']}/{a.n} rows  {reasons}  tokens in/out "
                  f"{stats['in_tok']}/{stats['out_tok']}  {time.time() - t0:.0f}s", flush=True)
            rounds += 1
            if rounds >= a.max_rounds:
                break
    summary = {"requested": a.n, "accepted_this_run": stats["ok"], "rows_in_file": done + stats["ok"],
               "reject_reasons": {k: v for k, v in sorted(reasons.items()) if k != "ok"},
               "generator": "offline" if client is None else a.model, "seconds": round(time.time() - t0, 1),
               "tokens_in": stats["in_tok"], "tokens_out": stats["out_tok"]}
    Path(str(out_path) + ".stats.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="target number of accepted rows in --out")
    ap.add_argument("--out", default=str(HERE / "data" / "synth" / "synth.jsonl"))
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--model", default="google/gemma-4-31B-it")
    ap.add_argument("--api-key-env", default="VLLM_API_KEY", help="'' for a vLLM server without a key")
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--max-rounds", type=int, default=8)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--it-frac", type=float, default=0.4, help="share of Italian entries")
    ap.add_argument("--p-hard-neg", type=float, default=0.08, help="share of nothing-clinical entries")
    ap.add_argument("--offline", action="store_true", help="no model; deterministic replies to test the pipeline")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
