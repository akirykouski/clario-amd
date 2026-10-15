"""Calibration benchmark for the Patterns engine: simulated patients, the real scorer, honest tier cut-offs.

Method (the standard simulation of the phenotype-ranking literature, Phenomizer / LIRICAL / Exomiser style):
  1. Draw a disease from a stratified subset of the shipped HPO/Orphanet annotations (annotation count x whether
     the annotations carry real frequencies).
  2. Sample k = 3..8 of its HPO terms, weighted by annotated frequency, without replacement.
  3. Imprecision: each term moves to a random ancestor (never the root) with probability 0.3.
  4. Noise: 1-2 terms taken from random other diseases (frequency weighted).
  5. Optional negated term (probability 0.3): a feature of another disease that the true disease does not list.
  6. Run `clario.patterns.scored_diseases` and `shown_cards`, the code the app runs, on confirmed entries.

Two independent simulations (different seeds, disjoint draws): the CALIBRATION run picks the tier cut-offs, the
VALIDATION run reports every number in the result file with those cut-offs applied, so no number is in-sample.

Pure CPU, deterministic for a seed, no model, no network. Run (about a minute on a laptop):
  python eval/pattern_calibration.py --n 1200 --out eval/results/pattern_calibration.json
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import random
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from clario import patterns as P  # noqa: E402
from clario.knowledge import Ontology  # noqa: E402
from clario.models import Entity, Entry  # noqa: E402

P_IMPRECISE = 0.3
P_NEGATED = 0.3
MIN_ANNOT = 5  # a disease needs this many annotations to be a candidate patient
# Precision targets per tier: of the cards the patient sees in that tier, at least this share is the simulated disease.
TARGETS = {"strong": 0.80, "moderate": 0.40, "weak": 0.25}
SLACK = 0.03  # cut-offs are derived against target + SLACK so the held-out run does not dip under the target by chance
MIN_SUPPORT = 40  # a band needs this many cards in the calibration run before its cut-off is trusted
LEAD_GRID = [round(x * 0.01, 2) for x in range(1, 61)]
WEAK_GRID = [round(x * 0.01, 2) for x in range(-10, 61)]
PROVISIONAL_FLOOR = P.MIN_SCORE  # a card whose conditions explain less of the patient's information is never offered


# ---------------------------------------------------------------- simulation
def _wsample(rng: random.Random, items: dict[str, float], k: int) -> list[str]:
    """k keys without replacement, weighted (Efraimidis-Spirakis), deterministic for a seeded rng."""
    keyed = sorted(((rng.random() ** (1.0 / max(w, 0.05)), t) for t, w in sorted(items.items())), reverse=True)
    return [t for _, t in keyed[:k]]


def strata(onto: Ontology) -> dict[str, list[str]]:
    elig = sorted((d for d in onto.diseases() if len(d.phenotypes) >= MIN_ANNOT), key=lambda d: d.id)
    sizes = sorted(len(d.phenotypes) for d in elig)
    lo, hi = sizes[len(sizes) // 3], sizes[2 * len(sizes) // 3]
    out: dict[str, list[str]] = {}
    for d in elig:
        n = len(d.phenotypes)
        size = "small" if n < lo else ("medium" if n < hi else "large")
        freq = "freq" if P.has_frequency_info(d) else "nofreq"
        out.setdefault(f"{size}/{freq}", []).append(d.id)
    return out


def simulate(onto: Ontology, disease_id: str, rng: random.Random, pool: list[str]) -> tuple[Entry, dict]:
    d = onto.disease(disease_id)
    k = min(rng.randint(3, 8), len(d.phenotypes))
    picked = _wsample(rng, d.phenotypes, k)
    moved = 0
    terms: list[str] = []
    for t in picked:
        anc = sorted(onto.ancestors(t) - {"HP:0000118"})
        if anc and rng.random() < P_IMPRECISE:
            t, moved = rng.choice(anc), moved + 1
        terms.append(t)
    noise = []
    for _ in range(rng.randint(1, 2)):
        o = onto.disease(rng.choice(pool))
        noise.append(_wsample(rng, o.phenotypes, 1)[0])
    negated: list[str] = []
    if rng.random() < P_NEGATED:
        own = set(d.phenotypes) | {a for q in d.phenotypes for a in onto.ancestors(q)}
        for _ in range(10):
            o = onto.disease(rng.choice(pool))
            cand = {t: w for t, w in o.phenotypes.items() if w >= 0.5 and t not in own and not (onto.ancestors(t) & set(d.phenotypes))}
            if cand:
                negated = _wsample(rng, cand, 1)
                break
    present = list(dict.fromkeys(terms + noise))
    ents = [Entity(id=f"s{i}", entry_id="sim", type="symptom", quote=onto.label(t) or t, canonical=onto.label(t) or t,
                   hpo_id=t, review="confirmed") for i, t in enumerate(present)]
    ents += [Entity(id=f"n{i}", entry_id="sim", type="symptom", quote=onto.label(t) or t, canonical=onto.label(t) or t,
                    hpo_id=t, negated=True, review="confirmed") for i, t in enumerate(negated) if t not in present]
    return (Entry(id="sim", created_at="2026-01-01T00:00:00Z", occurred_on="2026-01-01", text="simulated", entities=ents),
            {"k": k, "imprecise": moved, "noise": len(noise), "negated": len(negated)})


_CTX: dict = {}


def _one(i: int) -> dict:
    """Patient i: seeded by (seed, i) alone, so the result does not depend on how work is split across processes."""
    onto, st, names, pool, seed = (_CTX[k] for k in ("onto", "st", "names", "pool", "seed"))
    rng = random.Random(seed * 1_000_003 + i)
    key = names[i % len(names)]  # equal share per stratum
    did = rng.choice(st[key])
    entry, meta = simulate(onto, did, rng, pool)
    true_name = P.display_name(onto.disease(did).name).lower()
    scored = P.scored_diseases([entry], onto)
    rank = next((j + 1 for j, s in enumerate(scored) if s.disease.id == did or s.name.lower() == true_name), 0)
    cands = [(s.score, len(s.specific_ids), j + 1 == rank, s.lead) for j, s in enumerate(scored[:6])]
    return {"disease": did, "stratum": key, "rank": rank, "cands": cands, **meta}


def run_sim(onto: Ontology, n: int, seed: int, workers: int = 0) -> list[dict]:
    """One record per simulated patient: the rank of the true disease and its top candidates (score, n_specific, hit)."""
    st = strata(onto)
    _CTX.update(onto=onto, st=st, names=sorted(st), pool=sorted(d for v in st.values() for d in v), seed=seed)
    workers = workers or min(8, os.cpu_count() or 1)
    if workers <= 1 or n < 50:
        return [_one(i) for i in range(n)]
    with multiprocessing.get_context("fork").Pool(workers) as pool:  # fork: workers share the loaded ontology
        return pool.map(_one, range(n), chunksize=16)


# ---------------------------------------------------------------- metrics
def recall_metrics(recs: list[dict]) -> dict:
    n = len(recs)
    ranks = [r["rank"] for r in recs]

    def at(k: int) -> float:
        return round(sum(1 for x in ranks if 0 < x <= k) / n, 4)

    found = [x for x in ranks if x]
    buckets = {"1": 0, "2": 0, "3": 0, "4-5": 0, "6-10": 0, "11-20": 0, ">20": 0, "not_scored": 0}
    for x in ranks:
        key = ("not_scored" if x == 0 else "1" if x == 1 else "2" if x == 2 else "3" if x == 3 else "4-5" if x <= 5
               else "6-10" if x <= 10 else "11-20" if x <= 20 else ">20")
        buckets[key] += 1
    by = {}
    for s in sorted({r["stratum"] for r in recs}):
        sub = [r["rank"] for r in recs if r["stratum"] == s]
        by[s] = {"n": len(sub), "top1": round(sum(1 for x in sub if x == 1) / len(sub), 4),
                 "top10": round(sum(1 for x in sub if 0 < x <= 10) / len(sub), 4)}
    return {"top1": at(1), "top3": at(3), "top10": at(10),
            "mrr": round(sum(1 / x for x in found) / n, 4), "median_rank_when_scored": statistics.median(found) if found else None,
            "rank_distribution": buckets, "by_stratum": by}


def shown(rec: dict, cuts: dict[str, float | None]) -> list[tuple[str, bool]]:
    """(tier, is_true) of the up to PATIENT_CARDS cards the patient would see under these cut-offs."""
    out = []
    for score, n_spec, hit, lead in rec["cands"]:
        tier = tier_for(score, n_spec, lead, cuts)
        if tier:
            out.append((tier, hit))
    out.sort(key=lambda x: {"strong": 0, "moderate": 1, "weak": 2}[x[0]])  # stable: score order kept inside a tier
    return out[: P.PATIENT_CARDS]


def tier_for(score: float, n_specific: int, lead: float, cuts: dict[str, float | None]) -> str | None:
    """Same rule as clario.patterns.signal_for, with the cut-offs passed in."""
    weak, strong, moderate = cuts.get("weak"), cuts.get("strong"), cuts.get("moderate")
    if n_specific < P.MIN_SPECIFIC or score < PROVISIONAL_FLOOR:
        return None
    if strong is not None and lead >= strong:
        return "strong"
    if moderate is not None and lead >= moderate:
        return "moderate"
    if weak is not None and lead >= weak:
        return "weak"
    return None


def wilson(h: int, n: int) -> list[float] | None:
    """95% Wilson interval for h hits in n cards. Cards of one patient are not independent, so read it as optimistic."""
    if not n:
        return None
    z, p = 1.96, h / n
    d = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(mid - half, 4), round(mid + half, 4)]


def tier_metrics(recs: list[dict], cuts: dict[str, float | None]) -> dict:
    cards = {t: [0, 0] for t in ("strong", "moderate", "weak")}  # tier -> [cards, true]
    top_tier = {"strong": 0, "moderate": 0, "weak": 0, "none": 0}
    any_true = 0
    for r in recs:
        s = shown(r, cuts)
        top_tier[s[0][0] if s else "none"] += 1
        any_true += any(h for _, h in s)
        for tier, hit in s:
            cards[tier][0] += 1
            cards[tier][1] += hit
    return {"cards_shown": {t: c for t, (c, _) in cards.items()},
            "precision": {t: (round(h / c, 4) if c else None) for t, (c, h) in cards.items()},
            "precision_ci95": {t: wilson(h, c) for t, (c, h) in cards.items()},
            "true_in_card": {t: h for t, (_, h) in cards.items()},
            "patients_by_top_tier": top_tier,
            "true_disease_on_screen": round(any_true / len(recs), 4)}


def lead_table(recs: list[dict]) -> list[dict]:
    """Precision of the up to two highest-scoring cards by lead band: the curve the cut-offs are read from."""
    bands = [(-1.0, -0.05), (-0.05, 0.0), (0.0, 0.03), (0.03, 0.07), (0.07, 0.10), (0.10, 0.15), (0.15, 0.25), (0.25, 2.0)]
    rows = []
    for lo, hi in bands:
        c = h = 0
        for r in recs:
            for score, n_spec, hit, lead in [x for x in r["cands"] if x[1] >= P.MIN_SPECIFIC][: P.PATIENT_CARDS]:
                if lo <= lead < hi and score >= PROVISIONAL_FLOOR:
                    c += 1
                    h += hit
        rows.append({"lead_from": lo, "lead_to": hi, "cards": c, "precision": round(h / c, 4) if c else None})
    return rows


def score_table(recs: list[dict]) -> list[dict]:
    """Precision of the same cards by raw score band: shows why the tiers are not cut on the score."""
    rows = []
    for lo in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        hi = lo + 0.1 if lo < 0.8 else 2.0
        c = h = 0
        for r in recs:
            for score, n_spec, hit, lead in [x for x in r["cands"] if x[1] >= P.MIN_SPECIFIC][: P.PATIENT_CARDS]:
                if lo <= score < hi:
                    c += 1
                    h += hit
        rows.append({"score_from": lo, "score_to": round(hi, 1), "cards": c, "precision": round(h / c, 4) if c else None})
    return rows


def rationale(cuts: dict, tiers: dict, scores: list[dict]) -> str:
    flat = [r["precision"] for r in scores if r["precision"] is not None and r["cards"] >= MIN_SUPPORT] or [0.0]
    prec = tiers["precision"]
    parts = [
        f"The raw score is a weak tier signal: held-out precision per 0.1 score band peaks at {max(flat):.2f} and falls again "
        f"at the top bands, so no score cut-off reaches the strong target (score_table_validation). The lead (the card's "
        f"score minus the best other condition's score) does separate (lead_table_validation), so tiers are bands of lead.",
        "Targets (share of cards in the tier that are the simulated condition): " +
        ", ".join(f"{t} >= {int(TARGETS[t]*100)}%" for t in ("strong", "moderate", "weak")) +
        f". Each cut-off is the lowest lead that reaches its target plus {int(SLACK*100)} points on the calibration run (twice the "
        f"size of the held-out run), so the held-out numbers are not tuned.",
        f"Cut-offs: strong lead >= {cuts['strong']}, moderate lead >= {cuts['moderate']}, weak lead >= {cuts['weak']}; "
        f"a lower lead is not shown. No card below score {P.MIN_SCORE} or with fewer than {P.MIN_SPECIFIC} specific terms.",
        "Held-out precision: " + ", ".join(f"{t} {prec[t]:.2f}" if prec[t] is not None else f"{t} n/a" for t in ("strong", "moderate", "weak")) +
        ". " + ("Every tier has a cut-off that meets its target, so the strength word stays in the patient UI."
                if all(v is not None for v in cuts.values()) else
                "At least one tier has no defensible cut-off: hide the strength word in the patient UI."),
    ]
    return " ".join(parts)


def derive_cuts(recs: list[dict], targets: dict[str, float] = TARGETS, min_support: int = MIN_SUPPORT) -> dict:
    """Cut-offs so every tier meets its precision target on the calibration run; None when no cut-off does.

    Population: the up to two highest-scoring candidates per patient with enough specific terms (the cards a patient
    would see). strong = lowest lead whose cards reach the strong target; moderate = lowest lead below it whose band
    reaches the moderate target; weak = lowest lead (it may be negative: a near-tie for the top) whose cards reach
    the weak target; a card below it is not shown. Moderate and weak are measured as bands (each excludes the tier
    above), so a tier cannot borrow precision from the tier above it.
    """
    cards = [x for r in recs for x in [y for y in r["cands"] if y[1] >= P.MIN_SPECIFIC][: P.PATIENT_CARDS]
             if x[0] >= PROVISIONAL_FLOOR]

    def prec(sel) -> tuple[int, float]:
        c = [x for x in cards if sel(x)]
        return len(c), (sum(x[2] for x in c) / len(c) if c else 0.0)

    cuts: dict[str, float | None] = {"strong": None, "moderate": None, "weak": None}
    for lead in LEAD_GRID:
        n, p = prec(lambda x: x[3] >= lead)
        if n >= min_support and p >= targets["strong"] + SLACK:
            cuts["strong"] = lead
            break
    top = cuts["strong"] if cuts["strong"] is not None else 99.0
    for lead in LEAD_GRID:
        if lead >= top:
            break
        n, p = prec(lambda x: lead <= x[3] < top)
        if n >= min_support and p >= targets["moderate"] + SLACK:
            cuts["moderate"] = lead
            break
    below = cuts["moderate"] if cuts["moderate"] is not None else top
    for lead in WEAK_GRID:
        if lead >= below:
            break
        n, p = prec(lambda x: lead <= x[3] < below)
        if n >= min_support and p >= targets["weak"] + SLACK:
            cuts["weak"] = lead
            break
    return cuts


def git_sha() -> str:
    try:
        return subprocess.run(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1200, help="simulated patients in the validation run (calibration uses 2x)")
    ap.add_argument("--seed", type=int, default=20261016)
    ap.add_argument("--out", default=str(ROOT / "eval" / "results" / "pattern_calibration.json"))
    a = ap.parse_args(argv)
    t0 = time.time()
    onto = Ontology.load()
    cal = run_sim(onto, 2 * a.n, a.seed)  # twice the validation size: the cut-offs are the noisy part
    val = run_sim(onto, a.n, a.seed + 1)
    cuts = derive_cuts(cal)
    shipped = {"strong": P.STRONG_LEAD, "moderate": P.MODERATE_LEAD, "weak": P.WEAK_LEAD}
    res = {
        "n": len(val),
        "dataset": f"simulated patients from the shipped HPO/Orphanet annotations (knowledge.json.gz, {onto.n_diseases} diseases), "
                   f"k=3..8 terms frequency weighted, {int(P_IMPRECISE*100)}% moved to an ancestor, 1-2 noise terms, "
                   f"{int(P_NEGATED*100)}% with one negated term; synthetic, no real patients",
        "model": f"clario-patterns {git_sha()}",
        "backend": "cpu",
        "date": date.today().isoformat(),
        "seed": a.seed,
        "report": "validation run (seed+1): an independent draw from the one that chose the cut-offs, so no number here is in-sample",
        "recall": recall_metrics(val),
        "tiers": tier_metrics(val, cuts),
        "tiers_as_shipped": tier_metrics(val, shipped),
        "lead_table_validation": lead_table(val),
        "score_table_validation": score_table(val),
        "calibration_run": {"n": len(cal), "seed": a.seed, "recall": recall_metrics(cal), "tiers": tier_metrics(cal, cuts)},
        "thresholds": {"derived": cuts, "shipped": shipped, "match": cuts == shipped,
                       "rationale": rationale(cuts, tier_metrics(val, cuts), score_table(val)),
                       "strength_word_shown": all(v is not None for v in cuts.values())},
        "targets": TARGETS,
        "slack": SLACK,
        "min_support": MIN_SUPPORT,
        "seconds": round(time.time() - t0, 1),
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps({k: res[k] for k in ("n", "recall", "tiers", "thresholds", "seconds")}, indent=1)[:4000])
    return res


if __name__ == "__main__":
    main()
