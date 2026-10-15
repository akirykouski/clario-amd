"""Pattern signals from confirmed terms. Never a diagnosis.

Score and signal level are computed in code (IC-weighted best-match overlap against HPO disease
annotations). The model is only asked to explain a match in hedged words, and its text must pass
the hedge validator, otherwise a template is used.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict

from pydantic import BaseModel

from .knowledge import Ontology
from .llm import LLM
from .models import Entry, Evidence, Pattern, Term
from .safety import is_hedged

MIN_TERMS = 3
MAX_PATTERNS = 3
SPECIFIC = 0.6  # a disease term counts as a match only if it keeps >= 60% of the patient term's IC
COMMON = 0.5  # "not recorded yet" lists only features present in at least half of described cases

RATIONALE_SYSTEM = """You help a patient prepare for a doctor's visit. You are given a rare condition whose \
typical features overlap with features the patient recorded. Write 2 short sentences in plain words: what overlaps, \
and that it is worth discussing with their doctor. Use hedged words such as "resembles", "may", "worth discussing". \
Never say the patient has the condition. Never mention treatment, medicines, doses or percentages. \
Return JSON: {"rationale": "..."}"""


class RationaleOut(BaseModel):
    rationale: str = ""


def evidence_from(entries: list[Entry], onto: Ontology) -> dict[str, Evidence]:
    """Confirmed, present (not negated) HPO terms with the entries that support them."""
    by_term: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in entries:
        for ent in e.entities:
            if ent.status == "confirmed" and ent.hpo_id and not ent.negated:
                by_term[ent.hpo_id].append((e.id, e.occurred_on))
    out = {}
    for hid, refs in by_term.items():
        dates = sorted(d for _, d in refs)
        out[hid] = Evidence(hpo_id=hid, label=onto.label(hid) or hid, entry_ids=sorted({i for i, _ in refs}),
                            first_seen=dates[0], last_seen=dates[-1], count=len(refs))
    return out


def signal_for(score: float, n_matched: int) -> str | None:
    if score >= 0.75 and n_matched >= 5:
        return "strong"
    if score >= 0.55 and n_matched >= 3:
        return "moderate"
    if score >= 0.4 and n_matched >= 2:
        return "weak"
    return None


def template_rationale(name: str, matched: list[Evidence]) -> str:
    feats = ", ".join(m.label.lower() for m in matched[:4])
    return (f"Some of what you recorded ({feats}) overlaps with features that are typical of {name}. "
            f"This may be worth discussing with your doctor, who can tell whether it is relevant to you.")


def close(onto: Ontology, p: str, d: str) -> bool:
    """Disease term d really matches patient term p: same term, a descendant, or a specific ancestor."""
    if d == p or p in onto.ancestors(d):
        return True
    return d in onto.ancestors(p) and onto.ic(d) >= SPECIFIC * onto.ic(p)


def missing_terms(onto: Ontology, disease, patient: set[str], k: int = 5) -> list[Term]:
    """Common features of the condition, in body systems the patient already wrote about, not yet recorded.

    General before specific: a patient can tell whether they have joint swelling, not a biopsy finding.
    """
    systems = set().union(*(onto.systems(p) for p in patient))
    cands = []
    for hid, w in disease.phenotypes.items():
        if w < COMMON or not (onto.systems(hid) & systems):
            continue
        if any(close(onto, p, hid) or hid in onto.ancestors(p) for p in patient):
            continue
        cands.append((-w, onto.ic(hid), hid))
    cands.sort()
    return [Term(hpo_id=h, label=onto.label(h) or h) for _, _, h in cands[:k]]


def display_name(name: str) -> str:
    """'Systemic lupus erythematosus 18' -> 'Systemic lupus erythematosus' (subtype numbers mean nothing to a patient)."""
    return re.sub(r"[\s,;-]*(type\s*)?\d+[a-z]?$", "", name, flags=re.I).strip() or name


def score_patterns(entries: list[Entry], onto: Ontology) -> list[Pattern]:
    ev = evidence_from(entries, onto)
    if len(ev) < MIN_TERMS:
        return []
    patient = set(ev)
    out: list[Pattern] = []
    families: set[str] = set()
    for disease, score, contrib in onto.top_diseases(patient, k=60):
        name = display_name(disease.name)
        if name.lower() in families:
            continue
        matched_ids = [p for p, d, c in contrib if c > 0 and close(onto, p, d)]
        sig = signal_for(score, len(matched_ids))
        if not sig:
            continue
        families.add(name.lower())
        matched = sorted((ev[p] for p in matched_ids if p in ev), key=lambda e: -e.count)
        out.append(Pattern(disease_id=disease.id, disease_name=name, signal=sig, score=round(score, 3),
                           matched=matched, missing=missing_terms(onto, disease, patient),
                           rationale=template_rationale(name, matched)))
    rank = {"strong": 0, "moderate": 1, "weak": 2}
    return sorted(out, key=lambda p: (rank[p.signal], -p.score))[:MAX_PATTERNS]


async def explain(llm: LLM, patterns: list[Pattern]) -> list[Pattern]:
    """Replace template rationales with model text where the model's text passes the hedge validator."""

    async def one(p: Pattern) -> Pattern:
        prompt = {"condition": p.disease_name, "overlapping_features": [m.label for m in p.matched],
                  "typical_features_not_recorded": [t.label for t in p.missing]}
        try:
            out, _ = await llm.json("rationale", [{"role": "system", "content": RATIONALE_SYSTEM},
                                                  {"role": "user", "content": str(prompt)}],
                                    RationaleOut, max_tokens=200, payload=prompt)
        except Exception:  # noqa: BLE001 - template stays
            return p
        text = out.rationale.strip()
        if text and is_hedged(text) and len(text) < 600:
            p.rationale, p.rationale_source = text, "model"
        return p

    return list(await asyncio.gather(*[one(p) for p in patterns]))

