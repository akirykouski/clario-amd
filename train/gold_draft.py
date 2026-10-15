"""Draft the gold eval set with Claude Haiku, for HUMAN review. Drafts are never training data and never gold.

Haiku writes 50 English and 30 Italian realistic diary entries together with proposed labels
(quote, canonical, type, negated, family_history, onset_hint, severity). Code then:
  - drops any entity whose quote is not verbatim in the entry,
  - replaces Haiku's HPO guess with the ontology's best match for the canonical term (hpo_id stays null when
    the match score is below 0.8) and attaches the top 5 ontology candidates for the reviewer,
  - flags entities whose negation or family cue in the left context disagrees with the proposed flag.
Output: eval/gold/drafts.jsonl, one row per entry, "status": "draft". A person opens eval/gold/review.html,
loads drafts.jsonl, edits and accepts each entity and exports eval/gold/gold.jsonl ("status": "reviewed",
reviewer initials). Only reviewed rows count as gold. Uses Anthropic's OpenAI-compatible endpoint.

    ANTHROPIC_API_KEY=... python gold_draft.py                       # 50 en + 30 it
    python gold_draft.py --n-en 5 --n-it 3 --out /tmp/drafts.jsonl   # small trial
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
from clario.knowledge import Ontology  # noqa: E402
from prompt import TYPES, _extract_json  # noqa: E402
from synth import cues  # noqa: E402

DEFAULT_OUT = HERE.parent / "eval" / "gold" / "drafts.jsonl"
MIN_HPO_SCORE = 0.8

SYSTEM = """You draft evaluation data for a symptom-diary extraction model. Write ONE realistic private diary entry from an ordinary patient (not a clinician) and label it.

Return ONLY JSON:
{"diary": "...", "entities": [{"quote": "...", "canonical": "...", "type": "symptom", "negated": false, "family_history": false, "onset_hint": null, "severity": null}]}

Label rules:
- quote: exact substring of the diary, covering the symptom words only (not the negation word, not the relative, not the time phrase).
- canonical: standard clinical English term, for example "Malar rash".
- type: one of symptom, finding, lab, medication, trigger, body_site.
- negated: true when the diary says it is absent ("no fever", "niente febbre").
- family_history: true when it belongs to a relative ("my mother has ...", "mia madre ha ..."). List such items too.
- onset_hint: the time phrase from the diary ("since Tuesday", "da tre giorni"), else null.
- severity: integer 0-10 only if the diary gives a rating like "6/10", else null.
- Never name a disease as a label. Do not label irrelevant life events. If the entry has nothing clinical, "entities" is [].
Write natural, slightly messy text: plain words, personal detail, irrelevant life events, occasional typos."""

FEATURES = ["a negated symptom (no fever / niente febbre)", "a relative's condition (family history)",
            "an onset phrase (since Tuesday / da tre giorni)", "a severity rating like 6/10",
            "an irrelevant life event", "a trigger (after a long day in the sun)", "a vague or hedged symptom",
            "a body site with pain", "a medication or supplement taken", "a lab value the patient was told"]
STYLES = ["short note", "messaging-app style", "voice-dictation transcript", "longer reflective entry",
          "list-like bullets in plain words"]


def make_plans(n_en: int, n_it: int, seed: int = 11) -> list[dict]:
    """Spread features and styles so the 80 drafts are varied; about 1 in 7 is a hard negative."""
    rng = random.Random(seed)
    plans = []
    for lang, n in (("en", n_en), ("it", n_it)):
        for i in range(n):
            hard = i % 7 == 3
            plans.append({"id": f"gold-{lang}-{i + 1:03d}", "lang": lang, "hard_negative": hard,
                          "features": [] if hard else rng.sample(FEATURES, rng.choice([2, 3, 3, 4])),
                          "style": rng.choice(STYLES), "n_symptoms": rng.randint(2, 5)})
    return plans


def user_prompt(p: dict) -> str:
    lang = "Italian" if p["lang"] == "it" else "English"
    if p["hard_negative"]:
        return (f"Language: {lang}. Style: {p['style']}. Write an everyday entry with NO health content at all "
                "(no symptom, pain, tiredness, medicine, doctor). entities must be [].")
    return (f"Language: {lang}. Style: {p['style']}. About {p['n_symptoms']} different symptoms or findings. "
            "Include: " + "; ".join(p["features"]) + ".")


def _json(text: str | None) -> dict:
    obj = _extract_json(text or "")
    if obj is None:
        raise json.JSONDecodeError("no JSON object in the reply", text or "", 0)
    return obj


def ground(onto: Ontology, canonical: str):
    """Ontology best match for a canonical term -> (hpo_id|None, score, top-5 candidates)."""
    cands = [{"id": t.hpo_id, "label": t.label} for t in onto.search(canonical, 5)]
    m = onto.best_match(canonical)
    if m and m[1] >= MIN_HPO_SCORE:
        return m[0].hpo_id, m[1], cands
    return None, (m[1] if m else 0.0), cands


def build_row(onto: Ontology, p: dict, reply: dict, model: str) -> tuple[dict | None, str]:
    diary = reply.get("diary")
    if not isinstance(diary, str) or len(diary) < 25:
        return None, "no_diary"
    ents, dropped = [], 0
    for e in reply.get("entities") or []:
        q = str(e.get("quote", "")).strip() if isinstance(e, dict) else ""
        i = diary.find(q) if q else -1
        if i < 0:
            dropped += 1
            continue
        hid, score, cands = ground(onto, str(e.get("canonical", "")))
        negated, family = cues(diary, i)
        flags = []
        if bool(e.get("negated")) != negated:
            flags.append("negation cue disagrees with proposed flag")
        if bool(e.get("family_history")) != family:
            flags.append("family cue disagrees with proposed flag")
        if hid is None:
            flags.append("no confident HPO match, pick one")
        sev = e.get("severity")
        t = str(e.get("type", "symptom")).lower()
        ents.append({"quote": q, "canonical": str(e.get("canonical", "")), "hpo_id": hid,
                     "type": t if t in TYPES else "symptom", "negated": bool(e.get("negated")),
                     "family_history": bool(e.get("family_history")), "onset_hint": e.get("onset_hint") or None,
                     "severity": sev if isinstance(sev, int) and not isinstance(sev, bool) and 0 <= sev <= 10 else None,
                     "confidence": None, "hpo_candidates": cands, "hpo_match_score": score, "review_flags": flags})
    if p["hard_negative"] and ents:
        return None, "entities_in_hard_negative"
    return {"id": p["id"], "lang": p["lang"], "status": "draft", "kind": "hard_negative" if p["hard_negative"] else "clinical",
            "diary": diary, "target": {"entities": ents}, "dropped_not_verbatim": dropped,
            "drafted_by": model, "drafted_on": datetime.date.today().isoformat(), "reviewer": None}, "ok"


def draft_one(client, model: str, onto: Ontology, p: dict) -> tuple[dict | None, str]:
    try:
        r = client.chat.completions.create(model=model, temperature=1.0, max_tokens=900,
                                           messages=[{"role": "system", "content": SYSTEM},
                                                     {"role": "user", "content": user_prompt(p)}])
        reply = _json(r.choices[0].message.content)
    except Exception as e:
        return None, type(e).__name__
    return build_row(onto, p, reply, model)


def run(client, model: str, plans: list[dict], out: Path, concurrency: int = 4) -> dict:
    onto = Ontology.load()
    with ThreadPoolExecutor(concurrency) as ex:
        results = list(ex.map(lambda p: draft_one(client, model, onto, p), plans))
    rows = [r for r, _ in results if r]
    reasons: dict[str, int] = {}
    for _, why in results:
        reasons[why] = reasons.get(why, 0) + 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return {"requested": len(plans), "drafted": len(rows), "reasons": reasons, "out": str(out)}


REVIEW_HTML = HERE.parent / "eval" / "gold" / "review.html"


def term_list(onto: Ontology) -> list[list[str]]:
    """Bundled HPO search list for review.html: the patient-noticeable terms (id, label, up to 3 lay synonyms)."""
    lay = json.loads((HERE / "lay_terms.json").read_text())
    return [[t, onto.label(t), "|".join(s for s in lay[t][:3] if s.lower() != onto.label(t).lower())]
            for t in sorted(lay) if onto.label(t)]


def build_review_html(path: Path = REVIEW_HTML) -> int:
    """Inject the term list into review.html (the page stays one self-contained file). Returns the term count."""
    terms = term_list(Ontology.load())
    html = path.read_text()
    new, n = re.subn(r"const TERMS = .*?;\n", lambda m: "const TERMS = " + json.dumps(terms, ensure_ascii=False,
                     separators=(",", ":")).replace("</", "<\\/") + ";\n", html, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("TERMS marker not found in review.html")
    path.write_text(new)
    return len(terms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-review", action="store_true", help="refresh the HPO term list inside eval/gold/review.html and exit")
    ap.add_argument("--n-en", type=int, default=50)
    ap.add_argument("--n-it", type=int, default=30)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--base-url", default="https://api.anthropic.com/v1/")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--api-key-env", default="ANTHROPIC_API_KEY")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    if a.build_review:
        print(f"review.html: {build_review_html()} terms")
        return
    key = os.environ.get(a.api_key_env)
    if not key:
        sys.exit(f"set {a.api_key_env}")
    from openai import OpenAI
    client = OpenAI(base_url=a.base_url, api_key=key, timeout=120, max_retries=3)
    print(json.dumps(run(client, a.model, make_plans(a.n_en, a.n_it, a.seed), Path(a.out), a.concurrency), indent=2))


if __name__ == "__main__":
    main()
