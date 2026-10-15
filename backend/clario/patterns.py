"""Pattern signals from confirmed terms. Never a diagnosis.

Score and signal level are computed in code (IC-weighted best-match overlap against HPO disease annotations, counting
only close matches). A card needs at least three specific matched terms; fever, headache and fatigue alone never make
one. Condition names stay on the clinic side: the patient gets cards titled by the features they recorded, in plain
words, with a template note that names no condition.
"""

from __future__ import annotations

import re
import secrets
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256

from .i18n import hpo_it, lay_it, term_label
from .knowledge import Disease, Ontology
from .lay import default_lay_terms, en_label, patient_noticeable
from .models import COUNTED, Entity, Entry, Evidence, Pattern, PatientEvidence, PatientPattern, PatientTerm, Term

MIN_TERMS = 3
NO_FLOOR = 0.7  # one 'no' cuts a score by at most 30%, so a single answer cannot drop a moderate card below weak
MIN_SPECIFIC = 3  # a card needs this many matched terms that are not everyday symptoms
MAX_PATTERNS = 3  # clinic package
PATIENT_CARDS = 2  # patient screen
SPECIFIC = 0.6  # a disease term counts as a match only if it keeps >= 60% of the patient term's IC
COMMON = 0.5  # "not recorded yet" lists only features present in MORE than half of described cases
# Frequency weights in the shipped knowledge (backend/scripts/build_knowledge.py): 1.0 means an explicit "Obligate" or
# "100%" annotation only. No frequency info is DEFAULT_FREQ (0.5). A 1/1 case report is shrunk to 2/3 (Laplace
# (n+1)/(d+2)), so a single reported patient never reads as "every patient has it". Scores, the next-question pick and
# the 'no' penalty all read these weights as P(feature | condition), so they stay honest only while that holds.
DEFAULT_FREQ = 0.5
SINGLE_CASE = 2 / 3  # what a lone 1/1 case report becomes; carries no frequency information either
MIN_FREQ_ANNOT = 10  # a disease needs this many annotations with a real frequency before its list is trusted
# Everyday symptoms that nearly every condition lists: never enough evidence on their own.
GENERIC = frozenset({"HP:0001945",  # Fever
                     "HP:0002315",  # Headache
                     "HP:0012378",  # Fatigue
                     "HP:0002018",  # Nausea
                     "HP:0002013",  # Vomiting
                     "HP:0033050"})  # Malaise
_SALT = secrets.token_hex(8)  # card ids are opaque and change when the server restarts


def card_id(disease_id: str) -> str:
    """What the patient side calls a card: stable while the server runs, says nothing about the condition."""
    return "c_" + sha256(f"{_SALT}:{disease_id}".encode()).hexdigest()[:10]


def counts_as_evidence(ent: Entity) -> bool:
    return bool(ent.hpo_id) and ent.review in COUNTED and not ent.negated and not ent.family_history


def evidence_from(entries: list[Entry], onto: Ontology) -> dict[str, Evidence]:
    """HPO terms a person confirmed or corrected, about the patient (not negated, not a relative's), with their entries.

    Entities that are unreviewed, in the review queue (needs_review) or rejected never count. `count` is the number of
    notes that mention the term (two mentions in one note are one note).
    """
    by_term: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in entries:
        for ent in e.entities:
            if counts_as_evidence(ent):
                by_term[ent.hpo_id].append((e.id, e.occurred_on))
    out = {}
    for hid, refs in by_term.items():
        dates = sorted(d for _, d in refs)
        ids = sorted({i for i, _ in refs})
        out[hid] = Evidence(hpo_id=hid, label=onto.label(hid) or hid, entry_ids=ids,
                            first_seen=dates[0], last_seen=dates[-1], count=len(ids))
    return out


def neutral_label(labels: list[str]) -> str:
    """Evidence-first title for a pattern card: the strongest matched features, no condition name."""
    feats = [l.strip() for l in labels if l.strip()][:3]
    return (", ".join(feats[:1]).capitalize() + "".join(", " + f.lower() for f in feats[1:])) if feats else "Recorded features"


def negated_ids(entries: list[Entry]) -> set[str]:
    """Confirmed HPO terms the patient said are absent and never reported present in another note."""
    conf = [ent for e in entries for ent in e.entities if ent.review in COUNTED and ent.hpo_id and not ent.family_history]
    return {x.hpo_id for x in conf if x.negated} - {x.hpo_id for x in conf if not x.negated}


def annotated_freq(onto: Ontology, disease, feature: str, floor: float = 0.02) -> float:
    """P(feature | disease): annotated frequency, counting a more specific annotated descendant, else a floor."""
    best = floor
    for q, w in disease.phenotypes.items():
        if w > best and (q == feature or feature in onto.ancestors(q)):
            best = w
    return min(best, 0.98)


def negation_factor(onto: Ontology, negated: set[str], disease) -> float:
    """Likelihood of the 'no' answers under a disease (softened so one answer never erases a pattern)."""
    f = 1.0
    for n in negated:
        f *= max(NO_FLOOR, 1.0 - 0.85 * annotated_freq(onto, disease, n))
    return f


def is_generic(onto: Ontology, hid: str) -> bool:
    return hid in GENERIC or bool(GENERIC & onto.ancestors(hid))


# Signal tiers, set from the calibration benchmark (eval/pattern_calibration.py -> eval/results/pattern_calibration.json).
# The benchmark showed the raw score barely separates right from wrong cards: precision sits at 45-55% across scores
# 0.3-0.65 and falls above 0.7 (short annotation lists score high by chance). What predicts a correct card is its LEAD,
# the score minus the best other condition's score: precision climbs from about 25% at no lead to about 90% at 0.15+.
# Each tier is a band of lead with a stated precision target (share of cards in that tier that are the simulated
# condition, held-out run; the cut-off is the lowest lead that reaches target + 3 points on the calibration run):
#   strong   = lead >= STRONG_LEAD    target >= 80% precision
#   moderate = lead >= MODERATE_LEAD  target >= 40% (a band: it cannot borrow precision from strong)
#   weak     = lead >= WEAK_LEAD      target >= 25%; a card with a lower lead is not shown
# and no card at all below MIN_SCORE. Rerun the script and update the three numbers when the scorer or knowledge
# changes; test_pattern_calibration pins them to the result file.
STRONG_LEAD: float | None = 0.10
MODERATE_LEAD: float | None = 0.03
WEAK_LEAD: float | None = 0.01
MIN_SCORE = 0.2  # the matched terms explain under a fifth of what the patient recorded: never a card


def signal_for(score: float, n_matched: int, n_specific: int | None = None, lead: float = 0.0) -> str | None:
    if (n_matched if n_specific is None else n_specific) < MIN_SPECIFIC or score < MIN_SCORE:
        return None
    if STRONG_LEAD is not None and lead >= STRONG_LEAD:
        return "strong"
    if MODERATE_LEAD is not None and lead >= MODERATE_LEAD:
        return "moderate"
    if WEAK_LEAD is not None and lead >= WEAK_LEAD:
        return "weak"
    return None


def template_rationale(name: str, matched: list[Evidence], lang: str = "en") -> str:
    """Clinic side only: names the condition."""
    feats = ", ".join(m.label.lower() for m in matched[:4])
    if lang == "it":
        return (f"Alcune cose che il paziente ha annotato ({feats}) coincidono con caratteristiche tipiche di {name}. "
                f"Potrebbe valere la pena parlarne con il medico, che può dire se è rilevante.")
    return (f"Some of what the patient recorded ({feats}) overlaps with features that are typical of {name}. "
            f"This may be worth discussing, and the clinician can tell whether it is relevant.")


def patient_rationale(labels: list[str], lang: str = "en") -> str:
    """Patient side: no condition name."""
    feats = ", ".join(l.lower() for l in labels[:4])
    if lang == "it":
        return (f"Alcune cose che hai annotato ({feats}) compaiono spesso insieme. "
                f"Potrebbe valere la pena parlarne con il medico, che può dire se è rilevante per te.")
    return (f"Some of what you recorded ({feats}) often shows up together. "
            f"This may be worth discussing with your doctor, who can tell whether it is relevant to you.")


def close(onto: Ontology, p: str, d: str) -> bool:
    """Disease term d really matches patient term p: same term, a descendant, or a specific ancestor."""
    if d == p or p in onto.ancestors(d):
        return True
    return d in onto.ancestors(p) and onto.ic(d) >= SPECIFIC * onto.ic(p)


_freq_cache: dict[str, bool] = {}


def has_frequency_info(disease: Disease) -> bool:
    """True when the disease's annotations carry real frequencies, not only the 0.5 default or lone 1/1 case reports."""
    ok = _freq_cache.get(disease.id)
    if ok is None:
        if disease.n_freq is not None:  # the build counted annotations with a real frequency behind them
            ok = disease.n_freq >= MIN_FREQ_ANNOT
        else:  # older knowledge file: guess from the weights
            ok = sum(1 for w in disease.phenotypes.values()
                     if abs(w - DEFAULT_FREQ) > 1e-6 and abs(w - SINGLE_CASE) > 1e-3) >= MIN_FREQ_ANNOT
        _freq_cache[disease.id] = ok
    return ok


def missing_terms(onto: Ontology, disease, patient: set[str], k: int = 5, lay: dict[str, list[str]] | None = None) -> list[Term]:
    """Common features of the condition, in body systems the patient already wrote about, not yet recorded.

    Only features a person can notice and answer about (plain words exist, no emergency, lab, structural or
    frightening term), only when the annotation says "more than half of cases" with a real frequency behind it.
    """
    if not has_frequency_info(disease):
        return []
    lay = default_lay_terms() if lay is None else lay
    systems = set().union(*(onto.systems(p) for p in patient)) if patient else set()
    cands = []
    for hid, w in disease.phenotypes.items():
        if w <= COMMON or not (onto.systems(hid) & systems) or is_generic(onto, hid):
            continue
        if any(close(onto, p, hid) or hid in onto.ancestors(p) for p in patient):
            continue
        if not patient_noticeable(onto, hid, lay):
            continue
        cands.append((-w, onto.ic(hid), hid))
    cands.sort()
    return [Term(hpo_id=h, label=onto.label(h) or h) for _, _, h in cands[:k]]


def display_name(name: str) -> str:
    """'Systemic lupus erythematosus 18' -> 'Systemic lupus erythematosus' (subtype numbers mean nothing to a clinician list)."""
    return re.sub(r"[\s,;-]*(type\s*)?\d+[a-z]?$", "", name, flags=re.I).strip() or name


# ---------------------------------------------------------------- scoring
@dataclass
class Scored:
    disease: Disease
    name: str
    score: float
    matched_ids: list[str]
    specific_ids: list[str]
    signal: str | None  # None: not enough specific evidence to show as a card
    lead: float = 0.0  # score minus the best other condition's score (negative for all but the top condition)

    @property
    def card_id(self) -> str:
        return card_id(self.disease.id)


_RANK = {"strong": 0, "moderate": 1, "weak": 2}


def scored_diseases(entries: list[Entry], onto: Ontology, ev: dict[str, Evidence] | None = None, k: int = 80) -> list[Scored]:
    """Every candidate condition, best score first, one per family. The score counts close matches only."""
    ev = evidence_from(entries, onto) if ev is None else ev
    patient = {p for p in ev if onto.label(p) is not None}
    denom = sum(onto.ic(p) for p in patient)
    if not patient or denom <= 0:
        return []
    negated = negated_ids(entries)
    out: list[Scored] = []
    for disease, _far, contrib in onto.top_diseases(patient, k=k):
        hits = [(p, c) for p, d, c in contrib if close(onto, p, d)]
        if not hits:
            continue
        score = min(1.0, sum(c for _, c in hits) / denom) * negation_factor(onto, negated, disease)
        ids = [p for p, _ in hits]
        spec = [p for p in ids if not is_generic(onto, p)]
        out.append(Scored(disease, display_name(disease.name), round(score, 4), ids, spec, None))
    out.sort(key=lambda s: -s.score)
    seen: set[str] = set()
    deduped = []
    for s in out:  # subtypes of one condition ("... 16", "... 18") are one family: keep the best
        if s.name.lower() not in seen:
            seen.add(s.name.lower())
            deduped.append(s)
    for i, s in enumerate(deduped):  # the signal needs the lead over the best other condition, known only now
        rival = deduped[1].score if i == 0 and len(deduped) > 1 else (deduped[0].score if i else 0.0)
        s.lead = round(s.score - rival, 4)
        s.signal = signal_for(s.score, len(s.matched_ids), len(s.specific_ids), s.lead)
    return deduped


def shown_cards(scored: list[Scored], limit: int) -> list[Scored]:
    """Cards worth showing: enough specific evidence, strongest signal first."""
    cards = sorted((s for s in scored if s.signal), key=lambda s: (_RANK[s.signal], -s.score))  # type: ignore[index]
    return cards[:limit]


def score_patterns(entries: list[Entry], onto: Ontology, limit: int = MAX_PATTERNS) -> list[Pattern]:
    """Clinic package: cards with condition names. Weak ones are included and marked weak."""
    ev = evidence_from(entries, onto)
    if len(ev) < MIN_TERMS:
        return []
    patient = set(ev)
    out = []
    for s in shown_cards(scored_diseases(entries, onto, ev), limit):
        matched = sorted((ev[p] for p in s.matched_ids if p in ev), key=lambda e: (-e.count, e.hpo_id))
        out.append(Pattern(disease_id=s.disease.id, disease_name=s.name, signal=s.signal,  # type: ignore[arg-type]
                           score=round(s.score, 3), matched=matched, missing=missing_terms(onto, s.disease, patient),
                           rationale=template_rationale(s.name, matched),
                           neutral_label=neutral_label([m.label for m in matched])))
    return out


# ---------------------------------------------------------------- patient copy
def patient_label(onto: Ontology, hid: str, lang: str, lay: dict[str, list[str]] | None = None) -> str:
    """Everyday name of a term: the Italian table in Italian, curated English or a plain synonym in English."""
    if lang == "it":
        return hpo_it().get(hid) or lay_it().get(hid) or (onto.label(hid) or hid)
    return en_label(onto, hid, lay)


def patient_pattern(onto: Ontology, scored: Scored, ev: dict[str, Evidence], patient: set[str], lang: str = "en",
                    lay: dict[str, list[str]] | None = None) -> PatientPattern:
    """The card as the patient sees it: opaque id, features in everyday words (clinical name as subtext), no condition."""
    def clinical(hid: str, label: str) -> str | None:
        name = onto.label(hid) or hid
        return name if name.strip().lower() != label.strip().lower() else None

    matched = []
    for p in sorted((p for p in scored.matched_ids if p in ev), key=lambda p: (-ev[p].count, p)):
        label = patient_label(onto, p, lang, lay)
        e = ev[p]
        matched.append(PatientEvidence(hpo_id=p, label=label, clinical=clinical(p, label), entry_ids=e.entry_ids,
                                       first_seen=e.first_seen, last_seen=e.last_seen, count=e.count))
    missing = []
    for t in missing_terms(onto, scored.disease, patient, lay=lay):
        if lang == "it" and t.hpo_id not in hpo_it() and t.hpo_id not in lay_it():
            continue  # never an English word in an Italian list
        label = patient_label(onto, t.hpo_id, lang, lay)
        missing.append(PatientTerm(hpo_id=t.hpo_id, label=label, clinical=clinical(t.hpo_id, label)))
    labels = [m.label for m in matched]
    return PatientPattern(card_id=scored.card_id, signal=scored.signal, matched=matched, missing=missing,  # type: ignore[arg-type]
                          neutral_label=neutral_label(labels), rationale=patient_rationale(labels, lang))


def patient_patterns(entries: list[Entry], onto: Ontology, lang: str = "en") -> list[PatientPattern]:
    ev = evidence_from(entries, onto)
    if len(ev) < MIN_TERMS:
        return []
    patient = set(ev)
    return [patient_pattern(onto, s, ev, patient, lang) for s in shown_cards(scored_diseases(entries, onto, ev), PATIENT_CARDS)]
