import time

import pytest

from clario.knowledge import Ontology


@pytest.fixture(scope="module")
def onto():
    return Ontology.load()


def test_fever(onto):
    assert onto.label("HP:0001945") == "Fever"
    assert onto.exists("HP:0001945") and not onto.exists("HP:9999999")
    assert onto.n_terms > 10000 and onto.n_diseases > 5000


def test_search_malar(onto):
    for q in ("butterfly rash", "malar rash"):
        ids = [t.hpo_id for t in onto.search(q, 10)]
        assert "HP:0025300" in ids[:3], (q, ids)


def test_search_fast_and_accent_insensitive(onto):
    t = time.perf_counter()
    onto.search("swollen glands")
    assert time.perf_counter() - t < 0.02
    assert onto.search("FEVER")[0].hpo_id == "HP:0001945"


def test_ancestors_and_ic(onto):
    anc = onto.ancestors("HP:0025300")
    assert "HP:0000118" in anc and "HP:0025300" not in anc
    assert onto.ic("HP:0025300") > onto.ic("HP:0000118")
    assert onto.ic("HP:0025300") > onto.ic("HP:0000951")  # rash > skin abnormality


def test_top_diseases_lupus(onto):
    pts = {"HP:0025300", "HP:0002829", "HP:0000992", "HP:0000155", "HP:0012378"}
    t = time.perf_counter()
    res = onto.top_diseases(pts, 10)
    dt = time.perf_counter() - t
    print([(d.id, d.name, round(s, 3)) for d, s, _ in res], f"{dt:.3f}s")
    assert dt < 1.5
    assert len(res) == 10
    assert any("lupus" in d.name.lower() for d, _, _ in res), [d.name for d, _, _ in res]
    d, s, m = res[0]
    assert 0 < s <= 1 and m
    s2, m2 = onto.similarity(pts, d)
    assert 0 < s2 <= 1 and m2


def test_best_match_lymph(onto):
    r = onto.best_match("swollen neck lymph nodes")
    assert r is not None
    term, score = r
    assert "lymph" in term.label.lower() and 0 < score <= 1, (term, score)
