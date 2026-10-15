"""The next question that would help most: expected information gain over the current top patterns.

Prior over candidate conditions = the pattern engine's scores on the confirmed terms (negated answers
lower a condition). Likelihood P(feature | condition) = the annotated HPO frequency, counting a more specific
annotated descendant, else a small floor. IG(f) = H(D) - [P(f) H(D|yes) + (1-P(f)) H(D|no)].

The model only phrases the winning feature as one plain yes/no question. Code validates the text (no
condition or medicine names, no clinical wording, no advice) and falls back to a template. Red-flag symptoms,
medicine terms and lab-only terms are never asked.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from pydantic import BaseModel

from .i18n import lay_it
from .knowledge import Ontology, _norm
from .llm import LLM
from .models import Entry, NextQuestion, RankedPattern
from .lay import default_lay_terms, patient_noticeable
from .patterns import (MIN_TERMS, PATIENT_CARDS, display_name, evidence_from, negated_ids, neutral_label, patient_label,
                       scored_diseases, shown_cards)
from .safety import hedge_problems, is_hedged

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


@dataclass
class Ranked:
    disease: object
    name: str
    score: float
    card_id: str
    signal: str | None  # the signal when this condition is one of the cards on screen, else None


def rank_diseases(onto: Ontology, entries: list[Entry], k: int = 15) -> list[Ranked]:
    """Top conditions by close-match score on the confirmed present terms; 'no' answers lower a condition.

    The cards on screen (at most PATIENT_CARDS) are always included and carry their signal; the rest are contrast only.
    """
    ev = evidence_from(entries, onto)
    if not ev:
        return []
    scored = scored_diseases(entries, onto, ev)
    shown = {s.disease.id: s for s in shown_cards(scored, PATIENT_CARDS)}
    top = scored[:k] + [s for s in shown.values() if s not in scored[:k]]
    return [Ranked(s.disease, s.name, s.score, s.card_id, s.signal if s.disease.id in shown else None) for s in top]


def as_ranked_patterns(onto: Ontology, entries: list[Entry], lang: str = "en") -> list[RankedPattern]:
    """The cards on screen, in order, with their plain-words title."""
    ev = evidence_from(entries, onto)
    out = []
    for i, s in enumerate(shown_cards(scored_diseases(entries, onto, ev), PATIENT_CARDS)):
        ids = sorted((p for p in s.matched_ids if p in ev), key=lambda p: (-ev[p].count, p))
        out.append(RankedPattern(card_id=s.card_id, label=neutral_label([patient_label(onto, p, lang) for p in ids]),
                                 score=s.score, rank=i + 1))
    return out


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


def choose(onto: Ontology, entries: list[Entry], lay: dict[str, list[str]] | None = None,
           skip: set[str] | None = None, min_terms: int = MIN_TERMS, k: int = 15, top: int = 12) -> list[Choice]:
    """Candidate features best first by expected information gain."""
    lay = default_lay_terms() if lay is None else lay
    ev = evidence_from(entries, onto)
    if len(ev) < min_terms:
        return []
    ranked = rank_diseases(onto, entries, k)
    focus = [r for r in ranked if r.signal in ("moderate", "strong")]
    if len(ranked) < 2 or not focus:
        return []  # nothing on screen is at least a moderate signal: weak cards alone never prompt a question
    neg = negated_ids(entries)
    answered = {ent.hpo_id for e in entries for ent in e.entities if ent.hpo_id and ent.review in ("confirmed", "corrected")} | (skip or set())
    blocked: set[str] = set()
    for h in answered | set(ev):
        blocked.add(h)
        blocked |= onto.ancestors(h)  # already implied by what the patient has
    for h in neg | (skip or set()):
        blocked |= onto.descendants(h)  # a 'no' covers everything more specific

    systems = set().union(*(onto.systems(p) for p in ev))
    phr: dict[str, str | None] = {}
    cand: dict[str, int] = {}
    # Only features of the cards on screen at moderate or stronger signal; the other conditions are contrast.
    # A person can answer about body areas they already wrote about; widen to every area only if that leaves nothing.
    for same_system in (True, False):
        for r in focus:
            for q in r.disease.phenotypes:
                for a in {q} | onto.ancestors(q):
                    if a in cand or a in blocked or (same_system and not (onto.systems(a) & systems)):
                        continue
                    if a not in phr:
                        phr[a] = patient_noticeable(onto, a, lay)
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
        on_screen = [i for i, r in enumerate(ranked) if r.signal]
        splits: list[str] = []
        if len(on_screen) == 2:  # the answer separates the two cards on screen, never a condition the patient cannot see
            hi, lo = sorted(on_screen, key=lambda i: -col[i])
            if col[hi] - col[lo] >= 0.2:
                splits = [ranked[hi].card_id, ranked[lo].card_id]
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
    return f"Ti capita di avere {lay}?" if lang == "it" else f"Do you ever notice {lay}?"


def why_text(lang: str, splits: list[str]) -> str:
    if lang == "it":
        return ("La tua risposta potrebbe aiutare a distinguere due degli schemi mostrati."
                if splits else "La tua risposta potrebbe aiutare il medico a capire meglio gli schemi mostrati.")
    return ("Your answer may help tell apart two of the patterns shown here."
            if splits else "Your answer may help your clinician see which patterns are worth discussing.")


async def phrase(llm: LLM, onto: Ontology, c: Choice, lang: str) -> tuple[str, str] | None:
    """(question, source) or None when neither the model text nor the template is acceptable."""
    label = onto.label(c.feature_id)
    lay = lay_it().get(c.feature_id, "") if lang == "it" else c.lay  # Italian: only phrases we wrote in Italian
    if not lay:
        return None
    c = Choice(c.feature_id, c.ig, c.p_feature, lay, c.splits)
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
    top = 12 if lang == "it" else 6
    for c in (await asyncio.to_thread(choose, onto, entries, lay, skip, min_terms, top=top))[:top]:
        got = await phrase(llm, onto, c, lang)
        if not got:
            continue
        why = why_text(lang, c.splits)
        assert lang != "en" or is_hedged(why)
        return NextQuestion(feature_id=c.feature_id, question=got[0], why=why, ig=round(c.ig, 4),
                            splits=c.splits, question_source=got[1])  # type: ignore[arg-type]
    return None
