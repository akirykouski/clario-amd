"""Frequency defaults in the knowledge build, and the pattern calibration benchmark (small n)."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from clario import patterns
from clario.knowledge import Ontology
from scripts import build_knowledge as bk

EVAL = Path(__file__).resolve().parents[2] / "eval"


@pytest.fixture(scope="module")
def onto():
    return Ontology.load()


@pytest.fixture(scope="module")
def cal():
    spec = importlib.util.spec_from_file_location("pattern_calibration", EVAL / "pattern_calibration.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pattern_calibration"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- frequency default
def test_only_an_explicit_obligate_or_100_percent_is_one():
    assert bk.freq_weight("HP:0040280") == 1.0 and bk.freq_weight("100%") == 1.0
    assert bk.freq_weight("") == bk.DEFAULT_FREQ == patterns.DEFAULT_FREQ  # no info: the documented prior, not certainty
    assert bk.freq_weight("HP:0040285") is None  # excluded feature
    one_case = bk.freq_weight("1/1")
    assert 0.5 < one_case < 0.7 and abs(one_case - patterns.SINGLE_CASE) < 1e-3  # a lone case report is not "always"
    assert bk.freq_weight("4/4") < bk.freq_weight("20/20") < 1.0  # more patients, more confidence, never certainty
    assert 0 < bk.freq_weight("0/3") < 0.5  # an absent feature in 3 patients is not "never"
    assert not bk.freq_informative("1/1") and not bk.freq_informative("") and bk.freq_informative("HP:0040282")
    assert bk.freq_informative("12/30") and bk.freq_informative("40%")


def test_shipped_knowledge_no_longer_reads_case_reports_as_always(onto):
    d = onto.disease("OMIM:621369")  # 51 of 58 weights used to be 1.0 although every one was a 1/1 case report
    assert d is not None and max(d.phenotypes.values()) < 1.0
    assert not patterns.has_frequency_info(d)  # so its "typical features" list is not trusted either
    ones = sum(1 for x in onto.diseases() for w in x.phenotypes.values() if w == 1.0)
    total = sum(len(x.phenotypes) for x in onto.diseases())
    assert ones / total < 0.02, ones / total  # was 41,331 of ~275,000 (15%)


def test_cohort_frequencies_still_count_as_information(onto):
    informative = [d for d in onto.diseases() if patterns.has_frequency_info(d)]
    assert len(informative) > 500 and all(d.n_freq >= patterns.MIN_FREQ_ANNOT for d in informative)


# ---------------------------------------------------------------- calibration script
def test_simulation_is_deterministic_and_well_formed(onto, cal):
    a = cal.run_sim(onto, 18, seed=5, workers=1)
    b = cal.run_sim(onto, 18, seed=5, workers=1)
    assert a == b and len(a) == 18
    assert a != cal.run_sim(onto, 18, seed=6, workers=1)
    for r in a:
        assert 3 <= r["k"] <= 8 and r["rank"] >= 0 and len(r["cands"]) <= 6
        assert all(len(c) == 4 for c in r["cands"])
    m = cal.recall_metrics(a)
    assert 0 <= m["top1"] <= m["top3"] <= m["top10"] <= 1
    assert sum(m["rank_distribution"].values()) == 18


def test_simulated_patient_follows_the_recipe(onto, cal):
    import random

    st = cal.strata(onto)
    pool = sorted(d for v in st.values() for d in v)
    d = onto.disease(pool[0])
    entry, meta = cal.simulate(onto, d.id, random.Random(1), pool)
    present = [e for e in entry.entities if not e.negated]
    assert present and all(e.review == "confirmed" and onto.exists(e.hpo_id) for e in entry.entities)
    assert meta["noise"] in (1, 2) and 3 <= meta["k"] <= 8
    assert "HP:0000118" not in {e.hpo_id for e in entry.entities}  # imprecision never climbs to the root


def test_derive_cuts_meets_targets_and_tier_for_uses_them(cal):
    # 100 patients per lead value: the top card is right with probability rising in its lead.
    import random

    rng = random.Random(0)
    recs = []
    for _ in range(600):
        lead = rng.choice([0.0, 0.02, 0.05, 0.12, 0.2])
        p = {0.0: 0.1, 0.02: 0.3, 0.05: 0.5, 0.12: 0.9, 0.2: 0.95}[lead]
        recs.append({"cands": [(0.5, 4, rng.random() < p, lead), (0.5 - lead, 4, False, -lead)]})
    cuts = cal.derive_cuts(recs, min_support=30)
    assert cuts["strong"] is not None and cuts["strong"] > cuts["moderate"] >= cuts["weak"]
    got = cal.tier_metrics(recs, cuts)["precision"]
    assert got["strong"] >= cal.TARGETS["strong"] and got["moderate"] >= cal.TARGETS["moderate"]
    assert cal.tier_for(0.5, 4, cuts["strong"], cuts) == "strong"
    assert cal.tier_for(0.5, 2, 1.0, cuts) is None  # too few specific terms
    assert cal.tier_for(0.1, 4, 1.0, cuts) is None  # score under MIN_SCORE
    assert cal.tier_for(0.5, 4, -0.5, cuts) is None  # far behind the leader: not shown
    # no cut-off reaches the target -> None, and the tier is simply not offered
    hopeless = [{"cands": [(0.5, 4, False, 0.3)]} for _ in range(100)]
    assert cal.derive_cuts(hopeless)["strong"] is None


def test_main_writes_a_result_file_with_the_required_fields(cal, tmp_path):
    out = tmp_path / "r.json"
    r = cal.main(["--n", "10", "--out", str(out)])  # tiny: the real run is n=1200 (result file in eval/results)
    on_disk = json.loads(out.read_text())
    for key in ("n", "dataset", "model", "backend", "date"):
        assert on_disk[key] == r[key] and on_disk[key]
    assert on_disk["backend"] == "cpu" and on_disk["model"].startswith("clario-patterns ")
    assert set(on_disk["recall"]) >= {"top1", "top3", "top10", "rank_distribution"}
    assert set(on_disk["tiers"]["precision"]) == {"strong", "moderate", "weak"}


# ---------------------------------------------------------------- the shipped result and the shipped cut-offs
def test_shipped_cutoffs_equal_the_calibrated_ones():
    f = EVAL / "results" / "pattern_calibration.json"
    if not f.exists():
        pytest.skip("run eval/pattern_calibration.py first")
    r = json.loads(f.read_text())
    assert r["n"] >= 1000 and r["backend"] == "cpu" and r["model"].startswith("clario-patterns ")
    shipped = {"strong": patterns.STRONG_LEAD, "moderate": patterns.MODERATE_LEAD, "weak": patterns.WEAK_LEAD}
    assert r["thresholds"]["derived"] == shipped == r["thresholds"]["shipped"] and r["thresholds"]["match"]
    prec = r["tiers"]["precision"]  # held-out run, tiers in order
    assert prec["strong"] > prec["moderate"] > prec["weak"] > 0.2
    assert r["thresholds"]["rationale"]
