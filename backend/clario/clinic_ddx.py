"""Clinician-side differential: named conditions worth considering, and the one finding that would best separate them.

Clinic mode only; nothing here is sent to the patient. Scores come from the pattern engine (close HPO matches against
`phenotype.hpoa`, never a model). The question is the feature with the highest expected information gain over the
top conditions, worded clinically, with the annotated frequency in each condition on screen so the clinician sees why
it was picked. Answers are applied as present or absent terms and the list is scored again.
"""

from __future__ import annotations

import numpy as np

from .i18n import disease_name, term_label
from .knowledge import Ontology
from .models import ClinicQuestion, Condition, ConditionFeature, Entity, Entry
from .next_question import EPS, FLOOR, MIN_PF, expected_gain
from .patterns import (DEFAULT_FREQ, MIN_TERMS, annotated_freq, evidence_from, has_frequency_info, is_generic,
                       negated_ids, scored_diseases)

MAX_CONDITIONS = 4
FOCUS = 3  # conditions the question tries to separate
ALSO_MIN = 0.2  # unsignaled candidates above this score fill the list as "weaker match"
LISTED = 0.5  # P(feature | condition) when the condition lists the feature without a frequency
COMMON_MISSING = 0.3  # "not recorded yet" lists features seen in at least 30% of described cases

# Short organ-system keys for the heat map, picked by keywords in the label of the top-level HPO branch.
SYSTEM_KEYS = [("integument", "skin"), ("musculoskeletal", "joints"), ("limbs", "joints"), ("connective", "joints"),
               ("genitourinary", "kidney"), ("blood", "blood"), ("immune", "immune"), ("nervous", "nervous"),
               ("cardiovascular", "heart"), ("respiratory", "lungs"), ("digestive", "digestive"), ("eye", "eye"),
               ("endocrine", "endocrine"), ("metabolism", "metabolism"), ("head or neck", "head"),
               ("constitutional", "general")]
SYSTEM_ORDER = [k for _, k in SYSTEM_KEYS]
# HPO files some symptoms under a branch a reader would not look for (arthralgia under "Constitutional symptom").
LABEL_KEYS = [("arthr", "joints"), ("joint", "joints"), ("stiffness", "joints"), ("myalg", "joints"),
              ("pleur", "lungs"), ("fever", "general")]


def system_key(onto: Ontology, hpo_id: str | None) -> str:
    """One organ-system key for a term ("skin", "joints", ...), "other" when unknown."""
    if not hpo_id:
        return "other"
    own = (onto.label(hpo_id) or "").lower()
    for word, key in LABEL_KEYS:
        if word in own:
            return key
    labels = [(onto.label(t) or "").lower() for t in onto.systems(hpo_id)]
    for word, key in SYSTEM_KEYS:
        if any(word in l for l in labels):
            return key
    return "other"


def disease_url(disease_id: str) -> str | None:
    db, _, num = disease_id.partition(":")
    if db == "ORPHA" and num:
        return f"https://www.orpha.net/en/disease/detail/{num}"
    if db == "OMIM" and num:
        return f"https://omim.org/entry/{num}"
    return None


def real_freq(w: float) -> float | None:
    """Annotated frequency, or None when the annotation carries none (the 0.5 default, or 1.0 from case reports)."""
    return None if w == DEFAULT_FREQ or w >= 0.98 else round(w, 2)


def with_answers(entries: list[Entry], answers: list[dict], rejected: set[str]) -> list[Entry]:
    """The package's entries with the clinician's decisions applied: rejected terms dropped, answers added as terms."""
    out = []
    for e in entries:
        ents = [x if x.id not in rejected else x.model_copy(update={"review": "rejected"}) for x in e.entities]
        out.append(e.model_copy(update={"entities": ents}))
    asked = [a for a in answers if a.get("answer") in ("yes", "no")]
    if asked:
        ents = [Entity(id=f"qa_{i}", entry_id="clinic_answers", type="symptom", quote=a["label"], canonical=a["label"],
                       hpo_id=a["feature_id"], hpo_label=a["label"], negated=a["answer"] == "no", review="confirmed",
                       flags=["clinician_answer"], model="clinician")
                for i, a in enumerate(asked)]
        out.append(Entry(id="clinic_answers", created_at="", occurred_on="9999-12-31", text="", extraction="done",
                         entities=ents))
    return out


def shortlist(onto: Ontology, entries: list[Entry], ev=None, limit: int = MAX_CONDITIONS) -> list:
    """Signalled conditions first, then the best-scoring others above ALSO_MIN, up to `limit`."""
    scored = scored_diseases(entries, onto, ev)
    top = [s for s in scored if s.signal][:limit]
    top += [s for s in scored if not s.signal and s.score >= ALSO_MIN][:max(0, limit - len(top))]
    return top


def conditions(onto: Ontology, entries: list[Entry], lang: str = "en", limit: int = MAX_CONDITIONS) -> list[Condition]:
    ev = evidence_from(entries, onto)
    if len(ev) < MIN_TERMS:
        return []
    patient = set(ev)
    out = []
    for s in shortlist(onto, entries, ev, limit):
        matched = [ConditionFeature(hpo_id=p, label=term_label(p, onto.label(p) or p, lang), count=ev[p].count)
                   for p in sorted((p for p in s.matched_ids if p in ev), key=lambda p: (-ev[p].count, p))]
        out.append(Condition(disease_id=s.disease.id, name=disease_name(s.name, lang), full_name=s.disease.name, signal=s.signal,  # type: ignore[arg-type]
                             score=round(s.score, 3), rank=len(out) + 1, url=disease_url(s.disease.id), matched=matched,
                             missing=missing_features(onto, s.disease, patient, lang)))
    return out


def feature_prob(onto: Ontology, disease, feature: str) -> tuple[float, float | None]:
    """(likelihood used for scoring, frequency to show). Annotations without real frequencies count as LISTED and show none."""
    w = annotated_freq(onto, disease, feature, FLOOR)
    if w <= FLOOR:
        return FLOOR, 0.0
    if has_frequency_info(disease) and real_freq(w) is not None:
        return w, real_freq(w)
    return LISTED, None


def missing_features(onto: Ontology, disease, patient: set[str], lang: str = "en", k: int = 6) -> list[ConditionFeature]:
    """Features of the condition the patient has not recorded. With real frequencies: the most common first. Without:
    the broadest recognisable features first, never two from the same branch. Labs and exam findings included."""
    covered = set(patient)
    for p in patient:
        covered |= onto.ancestors(p)
    freq_known = has_frequency_info(disease)
    cands = []
    for hid, w in disease.phenotypes.items():
        if hid in covered or is_generic(onto, hid) or onto.label(hid) is None:
            continue
        f = real_freq(w)
        if freq_known and (f is None or f < COMMON_MISSING):
            continue
        if any(p in onto.descendants(hid) for p in patient):
            continue
        cands.append(((-w if freq_known else 0.0), onto.ic(hid) if not freq_known else -onto.ic(hid), hid))
    cands.sort()
    out: list[str] = []
    for _, _, h in cands:
        if any(h in onto.ancestors(o) or o in onto.ancestors(h) for o in out):
            continue  # one feature per branch: no five kinds of glomerular lesion
        out.append(h)
        if len(out) == k:
            break
    return [ConditionFeature(hpo_id=h, label=term_label(h, onto.label(h) or h, lang),
                             freq=real_freq(disease.phenotypes[h]) if freq_known else None) for h in out]


def question(onto: Ontology, entries: list[Entry], answered: set[str], lang: str = "en", k: int = 15) -> ClinicQuestion | None:
    """The finding with the highest expected information gain over the top conditions."""
    ev = evidence_from(entries, onto)
    if len(ev) < MIN_TERMS:
        return None
    scored = scored_diseases(entries, onto, ev)[:k]
    focus_ids = {s.disease.id for s in shortlist(onto, entries, ev)[:FOCUS]}
    focus = [s for s in scored if s.disease.id in focus_ids]
    if len(scored) < 2 or not focus:
        return None
    blocked: set[str] = set(answered)
    for h in set(ev) | answered:
        blocked |= {h} | onto.ancestors(h)
    for h in negated_ids(entries) | answered:
        blocked |= onto.descendants(h)
    cand: dict[str, int] = {}
    for s in focus:
        for q, w in s.disease.phenotypes.items():
            if q in cand or q in blocked or is_generic(onto, q) or onto.label(q) is None:
                continue
            cand[q] = len(cand)
    if not cand:
        return None
    ids = list(cand)
    lik = np.full((len(scored), len(ids)), FLOOR)
    shown: dict[tuple[int, int], float | None] = {}
    for i, s in enumerate(scored):
        for j, f in enumerate(ids):
            lik[i, j], shown[i, j] = feature_prob(onto, s.disease, f)
    prior = np.array([s.score + EPS for s in scored])
    ig, pf = expected_gain(prior, lik)
    for j in np.argsort(-ig):
        if pf[j] < MIN_PF or ig[j] <= 1e-6:
            continue
        f = ids[j]
        label = term_label(f, onto.label(f) or f, lang)
        text = f"Il paziente presenta: {label}?" if lang == "it" else f"Does the patient have: {label}?"
        freq_by = [{"name": disease_name(s.name, lang), "freq": shown[i, j]} for i, s in enumerate(scored) if s in focus]
        return ClinicQuestion(feature_id=f, label=label, question=text, ig=round(float(ig[j]), 4), freq_by=freq_by)
    return None
