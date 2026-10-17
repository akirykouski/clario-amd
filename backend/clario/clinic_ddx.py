"""Clinician-side differential: named conditions worth considering, and the one finding that would best separate them.

Clinic mode only; nothing here is sent to the patient. Scores come from the pattern engine (close HPO matches against
`phenotype.hpoa`, never a model). The question is the feature with the highest expected information gain over the
top conditions, worded clinically, with the annotated frequency in each condition on screen so the clinician sees why
it was picked. Answers are applied as present or absent terms and the list is scored again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from .documents import compute_flag, is_off, test_key
from .i18n import disease_name, term_label
from .knowledge import Ontology
from .models import (ClinicQuestion, Condition, ConditionFeature, Entity, Entry, OrganSystem, SharedEntity, SharedLab,
                     SharePackage, SystemFinding, Term)
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


# ---------------------------------------------------------------- labs -> HPO features
@dataclass(frozen=True)
class LabRule:
    hpo_id: str
    direction: str  # "low", "high", or "positive" (a positive qualitative result, a titre, or a value above range)
    names: tuple[str, ...]  # folded test names (documents.test_key), Italian and English
    skip_units: tuple[str, ...] = ()  # e.g. a lymphocyte percentage is not a count


# Abnormal lab results that are phenotype features in HPO. Every id and label is checked against the shipped ontology
# by tests/test_clinic_ddx_labs.py. Only these tests turn into features; everything else stays in the lab table.
LAB_RULES: tuple[LabRule, ...] = (
    LabRule("HP:0001903", "low", ("emoglobina", "hemoglobin", "haemoglobin", "hb", "hgb")),  # Anemia
    LabRule("HP:0005421", "low", ("c3", "complementoc3", "complementc3", "c3complement", "c3complemento")),  # Decreased circulating complement C3 concentration
    LabRule("HP:0045042", "low", ("c4", "complementoc4", "complementc4", "c4complement", "c4complemento")),  # Decreased circulating complement C4 concentration
    LabRule("HP:0004431", "low", ("complemento", "complement", "ch50", "complementototale", "totalcomplement")),  # Reduced circulating complement concentration
    LabRule("HP:0003493", "positive", ("ana", "anticorpiantinucleo", "anticorpiantinucleari", "antinuclearantibodies",
                                       "antinuclearantibody", "anaifi", "anaifa")),  # Antinuclear antibody positivity
    LabRule("HP:0020151", "positive", ("antidsdna", "anticorpiantidsdna", "dsdna", "antidnanativo", "antidna",
                                       "antidoublestrandeddna")),  # Anti-dsDNA antibody positivity
    LabRule("HP:0001882", "low", ("globulibianchi", "leucociti", "wbc", "whitebloodcells", "whitecells", "leukocytes"),
            ("%",)),  # Decreased total leukocyte count (leukopenia)
    LabRule("HP:0001888", "low", ("linfociti", "lymphocytes", "linfocitiassoluti", "lymphocytecount"),
            ("%",)),  # Decreased total lymphocyte count (lymphopenia)
    LabRule("HP:0001873", "low", ("piastrine", "platelets", "plt", "plateletcount", "conteggiopiastrinico")),  # Thrombocytopenia
    LabRule("HP:0003259", "high", ("creatinina", "creatinine", "creatininaserica", "serumcreatinine")),  # Elevated circulating creatinine concentration
    LabRule("HP:0000093", "positive", ("proteineurinarie", "proteinuria", "urineprotein", "proteineurine", "protidurinarie",
                                       "proteinurine")),  # Proteinuria
    LabRule("HP:0003565", "high", ("ves", "esr", "velocitadieritrosedimentazione", "erythrocytesedimentationrate")),  # Elevated erythrocyte sedimentation rate
    LabRule("HP:0011227", "high", ("pcr", "crp", "proteinacreattiva", "creactiveprotein")),  # Elevated circulating C-reactive protein concentration
)
_BY_NAME = {n: r for r in LAB_RULES for n in r.names}
# The organ system each lab-derived feature belongs to, by the test behind it (the specialty.py lab table splits the same
# tests into blood counts, immunology and kidney function). HPO files some of these where a reader would not look:
# elevated creatinine under metabolism, the complement and antibody results under blood.
LAB_SYSTEMS: dict[str, str] = {
    "HP:0001903": "blood", "HP:0001882": "blood", "HP:0001888": "blood", "HP:0001873": "blood",  # Hb, WBC, lymphocytes, PLT
    "HP:0003565": "blood", "HP:0011227": "blood",  # ESR, CRP: blood markers of inflammation
    "HP:0005421": "immune", "HP:0045042": "immune", "HP:0004431": "immune",  # complement C3, C4, total
    "HP:0003493": "immune", "HP:0020151": "immune",  # ANA, anti-dsDNA
    "HP:0003259": "kidney", "HP:0000093": "kidney",  # creatinine, proteinuria
}
LAB_ENTRY = "clinic_labs"  # prefix of the entries that carry lab-derived features
_NEGATIVE = re.compile(r"\b(negativ|non\s*reattiv|non\s*rilevat|not\s*detected|non[- ]?reactive|assent|absent)", re.I)
_POSITIVE = re.compile(r"\b(positiv|reattiv|reactive|detected|rilevat|presen)|^\s*\+{1,4}\s*$", re.I)
_TITRE = re.compile(r"\b1\s*:\s*\d{2,5}\b")


def lab_rule(l: SharedLab) -> LabRule | None:
    for name in (l.test_key, test_key(l.test_name), test_key(l.name_en or "")):
        if name and name in _BY_NAME:
            return _BY_NAME[name]
    return None


def lab_reading(l: SharedLab) -> set[str]:
    """What one result says, read from the value itself (never only from the flag): {"low"}, {"high", "positive"},
    {"positive"} or nothing. A text result reads positive on a positive word or a titre, and a negative word wins."""
    text = (l.value_text or "").strip()
    if text and _NEGATIVE.search(text):
        return set()
    if text and (_POSITIVE.search(text) or _TITRE.search(text)):
        return {"positive"}
    num = l.value_numeric
    if num is not None and (l.ref_low is not None or l.ref_high is not None):
        if l.ref_high is not None and num > l.ref_high:
            return {"high", "positive"}
        if l.ref_low is not None and num < l.ref_low:
            return {"low"}
        return set()
    if l.flag == "high":
        return {"high", "positive"}
    if l.flag == "low":
        return {"low"}
    return set()


def lab_counts(l: SharedLab, decision: str | None) -> bool:
    """Whether a reading feeds the ranking. A row that passed the code checks counts unless a person rejected it. A row
    the checks sent to the clinician (a possible OCR error) counts only once the clinician confirmed it or corrected it
    against the printed row, and then with the corrected value: an unchecked misread never moves the differential."""
    if decision == "rejected":
        return False
    if l.needs_review:
        return decision in ("confirmed", "corrected")
    return True


def lab_findings(labs: list[SharedLab], decisions: dict[str, str] | None = None) -> dict[str, list[SharedLab]]:
    """HPO feature -> the abnormal results behind it, from the rows the clinician has not rejected."""
    decisions = decisions or {}
    out: dict[str, list[SharedLab]] = {}
    for l in labs:
        if not lab_counts(l, decisions.get(l.id or "")):
            continue
        rule = lab_rule(l)
        if rule is None or (l.unit or "").strip() in rule.skip_units:
            continue
        if rule.direction in lab_reading(l):
            out.setdefault(rule.hpo_id, []).append(l)
    return out


def lab_normal(labs: list[SharedLab], decisions: dict[str, str] | None = None) -> set[str]:
    """Features a counted lab result already answers as absent: the test was measured and never read abnormal in the
    rule's direction (CRP within range three times is not "elevated CRP, not recorded"). Kept out of the next question
    and the "typical, not recorded" list; the score is not changed by it."""
    decisions = decisions or {}
    measured: set[str] = set()
    for l in labs:
        rule = lab_rule(l)
        if rule is None or not lab_counts(l, decisions.get(l.id or "")) or (l.unit or "").strip() in rule.skip_units:
            continue
        if l.value_numeric is not None or (l.value_text or "").strip():
            measured.add(rule.hpo_id)
    return measured - set(lab_findings(labs, decisions))


def with_labs(onto: Ontology, entries: list[Entry], labs: list[SharedLab], decisions: dict[str, str] | None = None) -> list[Entry]:
    """The entries plus one entry per lab date carrying the lab-derived features. A feature also in the notes is the
    same HPO term, so it is one feature (its note count is unchanged) and scores once."""
    decisions = decisions or {}
    by_date: dict[str, list[Entity]] = {}
    for hid, rows in lab_findings(labs, decisions).items():
        label = onto.label(hid) or hid
        for i, l in enumerate(rows):
            shown = l.value_text or (f"{l.value_numeric:g} {l.unit}".strip() if l.value_numeric is not None else l.flag or "")
            confirmed = decisions.get(l.id or "") in ("confirmed", "corrected")
            by_date.setdefault(l.date, []).append(Entity(
                id=f"lab_{l.id or i}_{hid}", entry_id=f"{LAB_ENTRY}_{l.date}", type="lab", quote=f"{l.test_name}: {shown}",
                canonical=label, hpo_id=hid, hpo_label=label, flags=["from_labs"], model="lab",
                review="confirmed" if confirmed else "needs_review" if l.needs_review else "auto"))
    extra = [Entry(id=f"{LAB_ENTRY}_{d}", created_at="", occurred_on=d, text="", extraction="done", entities=ents)
             for d, ents in sorted(by_date.items())]
    return entries + extra


def with_lab_fixes(pkg: SharePackage, fixes: dict[str, dict]) -> SharePackage:
    """Lab readings the clinician corrected after comparing them with the printed row: `fixes[lab_id] = {"from": {value_numeric,
    value_text, unit}, "to": {...}}`. The row carries the clinician's value and unit, its flag is recomputed in code, and
    `corrected_from` keeps what was read, so the glance, the lab tables, the differential and the brief use the right value."""
    if not fixes:
        return pkg
    labs = []
    for l in pkg.labs:
        f = fixes.get(l.id or "")
        if not f:
            labs.append(l)
            continue
        new = l.model_copy(update={**f["to"], "corrected_from": f["from"], "reviewed": True})
        flag = compute_flag(new.value_numeric, new.ref_low, new.ref_high, text=new.value_text)
        labs.append(new.model_copy(update={"flag": flag, "abnormal": is_off(flag)}))
    return pkg.model_copy(update={"labs": labs})


# Not organ systems: general symptoms (fatigue, fever) and terms HPO does not place. Left out of the row.
NOT_ORGANS = ("general", "other")


def organ_systems(onto: Ontology, entries: list[Entry], lang: str = "en") -> list[OrganSystem]:
    """Which organ systems the patient's current findings span (skin, joints, kidney, blood ...), each with the findings
    behind it. The same evidence the ranking scores: negated, family-history, past-history and rejected terms are out,
    and a lab result counts only once it passed the code checks or the clinician confirmed it (`with_labs`). A feature
    that came from a lab is placed by its test (`LAB_SYSTEMS`), a note term by its HPO branch (`system_key`)."""
    by_sys: dict[str, list[SystemFinding]] = {}
    for hid, ev in evidence_from(entries, onto).items():
        labs = _lab_count(ev.entry_ids)
        key = LAB_SYSTEMS.get(hid) if labs and hid in LAB_SYSTEMS else system_key(onto, hid)
        if key in NOT_ORGANS:
            continue
        by_sys.setdefault(key, []).append(SystemFinding(hpo_id=hid, label=term_label(hid, onto.label(hid) or hid, lang),
                                                        count=_note_count(ev.entry_ids), labs=labs))
    order = {k: i for i, k in enumerate(dict.fromkeys(SYSTEM_ORDER))}
    out = [OrganSystem(key=k, count=len(f), findings=sorted(f, key=lambda x: (-(x.count + x.labs), x.label)))
           for k, f in by_sys.items()]
    return sorted(out, key=lambda o: (-o.count, order.get(o.key, 99)))


def _note_count(entry_ids: list[str]) -> int:
    return sum(1 for i in entry_ids if not i.startswith(LAB_ENTRY))


def _lab_count(entry_ids: list[str]) -> int:
    return sum(1 for i in entry_ids if i.startswith(LAB_ENTRY))


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


CANDIDATES = 6  # replacement terms offered for one unsure term


def _as_finding(t: str) -> str:
    return "finding" if t in ("trigger", "medication") else t


def with_corrections(pkg: SharePackage, corrections: dict[str, dict], lab_fixes: dict[str, dict] | None = None) -> SharePackage:
    """The package with the clinician's replaced terms applied: `corrections[ent_id] = {"from", "to", "label"}`.
    The term keeps its quote and date and now carries the clinician's HPO id; it counts as reviewed. A trigger or
    medication the clinician maps to a phenotype term becomes a finding, so the overview lists it like any other.
    `lab_fixes[lab_id] = {"from", "to"}` are lab readings the clinician corrected (see `with_lab_fixes`)."""
    if lab_fixes:
        pkg = with_lab_fixes(pkg, lab_fixes)
    if not corrections:
        return pkg

    def fix_shared(x: SharedEntity) -> SharedEntity:
        c = corrections.get(x.id or "")
        if not c:
            return x
        return x.model_copy(update={"hpo_id": c["to"], "canonical": c["label"], "needs_review": False, "reviewed": True,
                                    "type": _as_finding(x.type)})

    def fix_entity(x: Entity) -> Entity:
        c = corrections.get(x.id)
        if not c:
            return x
        flags = [f for f in x.flags if not f.startswith(("hpo_", "no_hpo"))] + ["fixed_by_clinician"]
        return x.model_copy(update={"hpo_id": c["to"], "hpo_label": c["label"], "canonical": c["label"],
                                    "review": "corrected", "flags": flags, "type": _as_finding(x.type)})

    entries = [e.model_copy(update={"entities": [fix_entity(x) for x in e.entities]}) for e in pkg.entries]
    return pkg.model_copy(update={"entries": entries, "entities": [fix_shared(x) for x in pkg.entities]})


def replacement_candidates(onto: Ontology, quote: str, canonical: str, current: str | None, lang: str = "en",
                           limit: int = CANDIDATES) -> list[Term]:
    """Ontology terms that could stand for the quote instead of the current one: the same lookup the extractor's HPO
    pick uses (label and synonym match on the clinical name plus the patient's words), current term left out."""
    seen = {current} if current else set()
    out = []
    for phrase in (f"{canonical} {quote}", quote, canonical):
        for t in onto.search(phrase, 20):
            if t.hpo_id in seen:
                continue
            seen.add(t.hpo_id)
            out.append(Term(hpo_id=t.hpo_id, label=term_label(t.hpo_id, t.label, lang)))
            if len(out) == limit:
                return out
    return out


def shortlist(onto: Ontology, entries: list[Entry], ev=None, limit: int = MAX_CONDITIONS) -> list:
    """Signalled conditions first, then the best-scoring others above ALSO_MIN, up to `limit`. One entry per condition
    family, shown as its general entry (Orphanet, else OMIM), never a numbered subtype."""
    scored = scored_diseases(entries, onto, ev, general=True)
    top = [s for s in scored if s.signal][:limit]
    top += [s for s in scored if not s.signal and s.score >= ALSO_MIN][:max(0, limit - len(top))]
    return top


def conditions(onto: Ontology, entries: list[Entry], lang: str = "en", limit: int = MAX_CONDITIONS,
               measured_normal: set[str] | frozenset[str] = frozenset()) -> list[Condition]:
    ev = evidence_from(entries, onto)
    if len(ev) < MIN_TERMS:
        return []
    patient = set(ev)
    out = []
    for s in shortlist(onto, entries, ev, limit):
        matched = [ConditionFeature(hpo_id=p, label=term_label(p, onto.label(p) or p, lang),
                                    count=_note_count(ev[p].entry_ids), labs=_lab_count(ev[p].entry_ids))
                   for p in sorted((p for p in s.matched_ids if p in ev), key=lambda p: (-_note_count(ev[p].entry_ids), -ev[p].count, p))]
        out.append(Condition(disease_id=s.disease.id, name=disease_name(s.name, lang), full_name=s.disease.name, signal=s.signal,  # type: ignore[arg-type]
                             score=round(s.score, 3), rank=len(out) + 1, url=disease_url(s.disease.id), matched=matched,
                             missing=missing_features(onto, s.disease, patient, lang, normal=measured_normal)))
    return out


def feature_prob(onto: Ontology, disease, feature: str) -> tuple[float, float | None]:
    """(likelihood used for scoring, frequency to show). Annotations without real frequencies count as LISTED and show none."""
    w = annotated_freq(onto, disease, feature, FLOOR)
    if w <= FLOOR:
        return FLOOR, 0.0
    if has_frequency_info(disease) and real_freq(w) is not None:
        return w, real_freq(w)
    return LISTED, None


def missing_features(onto: Ontology, disease, patient: set[str], lang: str = "en", k: int = 6,
                     normal: set[str] | frozenset[str] = frozenset()) -> list[ConditionFeature]:
    """Features of the condition the patient has not recorded. With real frequencies: the most common first. Without:
    the broadest recognisable features first, never two from the same branch. Labs and exam findings included, except
    those a lab result already answers as normal (`normal`, from `lab_normal`)."""
    covered = set(patient)
    for p in patient:
        covered |= onto.ancestors(p)
    for n in normal:
        covered |= {n} | onto.descendants(n)
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


def question(onto: Ontology, entries: list[Entry], answered: set[str], lang: str = "en", k: int = 15,
             measured_normal: set[str] | frozenset[str] = frozenset()) -> ClinicQuestion | None:
    """The finding with the highest expected information gain over the top conditions. Never one the record already
    answers: a recorded or answered feature, or one a lab result measured as normal."""
    ev = evidence_from(entries, onto)
    if len(ev) < MIN_TERMS:
        return None
    scored = scored_diseases(entries, onto, ev, general=True)[:k]
    focus_ids = {s.disease.id for s in shortlist(onto, entries, ev)[:FOCUS]}
    focus = [s for s in scored if s.disease.id in focus_ids]
    if len(scored) < 2 or not focus:
        return None
    blocked: set[str] = set(answered)
    for h in set(ev) | answered:
        blocked |= {h} | onto.ancestors(h)
    for h in negated_ids(entries) | answered | set(measured_normal):
        blocked |= {h} | onto.descendants(h)
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
