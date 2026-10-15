"""The next question that would help most: expected information gain over the current top patterns.

Prior over candidate conditions = the pattern engine's scores on the confirmed terms (negated answers
lower a condition). Likelihood P(feature | condition) = the annotated HPO frequency, counting a more specific
annotated descendant, else a small floor. IG(f) = H(D) - [P(f) H(D|yes) + (1-P(f)) H(D|no)].

The model only phrases the winning feature as one plain yes/no question. Code validates the text (no
condition or medicine names, no clinical wording, no advice) and falls back to a template. Red-flag symptoms,
medicine terms and lab-only terms are never asked.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from .knowledge import Ontology, _norm
from .llm import LLM
from .models import Entry, NextQuestion, RankedPattern
from .patterns import MIN_TERMS, display_name, evidence_from, negated_ids, negation_factor, neutral_label
from .safety import hedge_problems, is_hedged, is_red_flag_term, is_unnoticeable_term

LAY_PATH = Path(__file__).parent / "data" / "lay_terms.json"
EPS = 0.02  # prior smoothing: a condition with a low score stays in play
FLOOR = 0.02  # P(feature | condition) when the condition is not annotated with it
MIN_PF = 0.03  # skip features almost nobody among the candidates would have
MAX_Q_WORDS = 22

QUESTION_SYSTEM = """You write ONE short yes/no question for a person who keeps a symptom diary. You get a plain \
description of one thing to ask about. Rules: use only everyday words, never medical terms. Never name a disease, \
a condition or a medicine. No advice, no explanation, no diagnosis. At most 18 words. Write in the requested \
language. Return JSON: {"question": "..."}"""

LANG_NAME = {"en": "English", "it": "Italian"}
_DRUG_WORDS = re.compile(
    r"\b(ibuprofen|aspirin|paracetamol|acetaminophen|prednisone|prednisolone|cortisone|hydroxychloroquine|methotrexate|"
    r"metformin|insulin|warfarin|heparin|statin|antibiotic|antidepressant|opioid|steroid|vaccine|chemotherapy|"
    r"dose|doses|dosage|tablets?|pills?|capsules?|medication|medicine|drugs?|prescri\w*|supplements?)\b"
    r"|\b\w{3,}(mab|nib|pril|sartan|statin|azole|cillin|mycin|oxacin|olol|prazole|triptan|profen|vudine|platin|"
    r"mide|barbital|zepam|zolam)\b", re.I)


class QuestionOut(BaseModel):
    question: str = ""


@lru_cache(maxsize=1)
def default_lay_terms() -> dict[str, list[str]]:
    return json.loads(LAY_PATH.read_text(encoding="utf-8")) if LAY_PATH.exists() else {}


# Structural or congenital wording: a person cannot confirm it from how they feel day to day.
_STRUCTURAL = re.compile(r"abnormal|anomal|malform|hypoplas|aplasia|dysplas|agenesis|atresia|congenital|aberrant|morpholog|"
                         r"defect|dysmorph|deformit|underdevelop|overgrowth|undergrowth|asymmetr|shape|position", re.I)


def lay_phrase(syns: list[str]) -> str | None:
    """A synonym a layperson could recognise: short, no 'abnormality of ...' or structural wording."""
    ok = [s for s in syns if 3 <= len(s) <= 60 and not re.match(r"(decreased|increased|reduced|elevated)", s, re.I)
          and len(s.split()) <= 5 and not _STRUCTURAL.search(s) and not re.search(r"\d|\bof the\b.*\bof the\b", s)]
    return min(ok, key=len).lower() if ok else None


@dataclass
class Ranked:
    disease: object
    name: str
    score: float
    label: str


def rank_diseases(onto: Ontology, entries: list[Entry], k: int = 15) -> list[Ranked]:
    """Top conditions by pattern score on the confirmed present terms; 'no' answers lower a condition."""
    ev = evidence_from(entries, onto)
    if not ev:
        return []
    neg = negated_ids(entries)
    out: list[Ranked] = []
    seen: set[str] = set()
    for d, score, contrib in onto.top_diseases(set(ev), k=60):
        name = display_name(d.name)
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        labels = [ev[p].label for p, _q, v in sorted(contrib, key=lambda c: -c[2]) if p in ev]
        out.append(Ranked(d, name, round(score * negation_factor(onto, neg, d), 4), neutral_label(labels)))
    out.sort(key=lambda r: -r.score)
    return out[:k]


def as_ranked_patterns(ranked: list[Ranked], n: int = 5) -> list[RankedPattern]:
    return [RankedPattern(disease_id=r.disease.id, label=r.label, score=r.score, rank=i + 1)
            for i, r in enumerate(ranked[:n])]


# ---------------------------------------------------------------- information gain
def _entropy(m: np.ndarray) -> np.ndarray:
    """Column-wise Shannon entropy in bits of a (D, F) matrix of distributions."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return -np.where(m > 0, m * np.log2(m), 0.0).sum(axis=0)


def expected_gain(prior: np.ndarray, lik: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """prior (D,), lik (D, F) = P(f|d). Returns (IG per feature in bits, P(f))."""
    p = prior / prior.sum()
    pf = np.clip(p @ lik, 1e-9, 1 - 1e-9)
    yes = p[:, None] * lik / pf
    no = p[:, None] * (1.0 - lik) / (1.0 - pf)
    h0 = _entropy(p[:, None])[0]
    return h0 - (pf * _entropy(yes) + (1.0 - pf) * _entropy(no)), pf


@dataclass
class Choice:
    feature_id: str
    ig: float
    p_feature: float
    lay: str
    splits: list[str]


def _askable(onto: Ontology, hid: str, lay: dict[str, list[str]]) -> str | None:
    """The plain-words phrase for a term, or None when it must not be asked about."""
    syns = lay.get(hid)
    label = onto.label(hid)
    if not syns or not label:
        return None
    if is_red_flag_term(label, *syns) or is_unnoticeable_term(label, *syns) or _STRUCTURAL.search(label):
        return None
    return lay_phrase(syns)


def choose(onto: Ontology, entries: list[Entry], lay: dict[str, list[str]] | None = None,
           skip: set[str] | None = None, min_terms: int = MIN_TERMS, k: int = 15, top: int = 12) -> list[Choice]:
    """Candidate features best first by expected information gain."""
    lay = default_lay_terms() if lay is None else lay
    ev = evidence_from(entries, onto)
    if len(ev) < min_terms:
        return []
    ranked = rank_diseases(onto, entries, k)
    if len(ranked) < 2:
        return []
    neg = negated_ids(entries)
    answered = {ent.hpo_id for e in entries for ent in e.entities if ent.hpo_id and ent.status == "confirmed"} | (skip or set())
    blocked: set[str] = set()
    for h in answered | set(ev):
        blocked.add(h)
        blocked |= onto.ancestors(h)  # already implied by what the patient has
    for h in neg | (skip or set()):
        blocked |= onto.descendants(h)  # a 'no' covers everything more specific

    systems = set().union(*(onto.systems(p) for p in ev))
    phr: dict[str, str | None] = {}
    cand: dict[str, int] = {}
    # A person can answer about body areas they already wrote about; widen to every area only if that leaves nothing.
    for same_system in (True, False):
        for r in ranked:
            for q in r.disease.phenotypes:
                for a in {q} | onto.ancestors(q):
                    if a in cand or a in blocked or (same_system and not (onto.systems(a) & systems)):
                        continue
                    if a not in phr:
                        phr[a] = _askable(onto, a, lay)
                    if phr[a]:
                        cand[a] = len(cand)
        if cand:
            break
    if not cand:
        return []
    ids = list(cand)
    lik = np.full((len(ranked), len(ids)), FLOOR)
    for i, r in enumerate(ranked):
        for q, w in r.disease.phenotypes.items():
            for a in {q} | onto.ancestors(q):
                j = cand.get(a)
                if j is not None and w > lik[i, j]:
                    lik[i, j] = min(w, 0.98)
    prior = np.array([r.score + EPS for r in ranked])
    ig, pf = expected_gain(prior, lik)
    out = []
    for j in np.argsort(-ig)[:top]:
        if pf[j] < MIN_PF or ig[j] <= 1e-6:
            continue
        col = lik[:, j]
        head = min(len(ranked), 5)
        hi, lo = int(np.argmax(col[:head])), int(np.argmin(col[:head]))
        splits = [ranked[hi].disease.id, ranked[lo].disease.id] if hi != lo and col[hi] - col[lo] >= 0.2 else []
        out.append(Choice(ids[j], float(ig[j]), float(pf[j]), phr[ids[j]] or "", splits))
    return out


# ---------------------------------------------------------------- phrasing and validation
@lru_cache(maxsize=4)
def _all_names(onto: Ontology) -> frozenset[str]:
    names = set()
    for d in onto.diseases():
        for n in (d.name, display_name(d.name)):
            n = _norm(n)
            if len(n) >= 5:
                names.add(n)
    return frozenset(names)


def question_problems(q: str, onto: Ontology, label: str | None = None, lay: str | None = None) -> list[str]:
    """Empty = acceptable. A question never names a condition or a medicine and never uses clinical wording."""
    q = (q or "").strip()
    problems = []
    if not q.endswith("?") or q.count("?") != 1 or re.search(r"[.!;]\s", q):
        problems.append("not one question")
    if len(q.split()) > MAX_Q_WORDS:
        problems.append("too long")
    problems += [p for p in hedge_problems(q) if p != "no hedging language"]
    padded = f" {_norm(q)} "
    if any(f" {n} " in padded for n in _all_names(onto)):
        problems.append("names a condition")
    if _DRUG_WORDS.search(q):
        problems.append("names a medicine")
    if label and _norm(label) != _norm(lay or "") and f" {_norm(label)} " in padded:
        problems.append("clinical term")
    return problems


def template_question(lay: str, lang: str) -> str:
    return f"Le capita di avere: {lay}?" if lang == "it" else f"Do you sometimes have: {lay}?"


def why_text(lang: str, splits: list[str]) -> str:
    if lang == "it":
        return ("La tua risposta potrebbe aiutare a distinguere due degli schemi mostrati."
                if splits else "La tua risposta potrebbe aiutare il medico a capire meglio gli schemi mostrati.")
    return ("Your answer may help tell apart two of the patterns shown here."
            if splits else "Your answer may help your clinician see which patterns are worth discussing.")


async def phrase(llm: LLM, onto: Ontology, c: Choice, lang: str) -> tuple[str, str] | None:
    """(question, source) or None when neither the model text nor the template is acceptable."""
    label = onto.label(c.feature_id)
    payload = {"plain_description": c.lay, "language": LANG_NAME.get(lang, "English")}
    try:
        out, _ = await llm.json("next_question", [{"role": "system", "content": QUESTION_SYSTEM},
                                                  {"role": "user", "content": json.dumps(payload)}],
                                QuestionOut, max_tokens=80, payload=payload | {"lang": lang})
        q = out.question.strip()
        if q and not question_problems(q, onto, label, c.lay):
            return q, "model"
    except Exception:  # noqa: BLE001 - template below
        pass
    q = template_question(c.lay, lang)
    return (q, "template") if not question_problems(q, onto, label, c.lay) else None


async def next_question(llm: LLM, onto: Ontology, entries: list[Entry], lang: str = "en", *,
                        lay: dict[str, list[str]] | None = None, skip: set[str] | None = None,
                        min_terms: int = MIN_TERMS) -> NextQuestion | None:
    lang = lang if lang in LANG_NAME else "en"
    for c in choose(onto, entries, lay, skip, min_terms)[:6]:
        got = await phrase(llm, onto, c, lang)
        if not got:
            continue
        why = why_text(lang, c.splits)
        assert lang != "en" or is_hedged(why)
        return NextQuestion(feature_id=c.feature_id, question=got[0], why=why, ig=round(c.ig, 4),
                            splits=c.splits, question_source=got[1])  # type: ignore[arg-type]
    return None
