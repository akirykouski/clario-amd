"""The demo persona and the demo referti load from reviewed, precomputed results (data/demo/LABELS.md): no model call."""

import json
import re

import pytest

from clario.demo import DEMO_DIR, PERSONAS, persona_labels
from clario.fixtures import OfflineLLM
from clario.knowledge import Ontology
from clario.models import Entity

from conftest import wait_extracted

PRECOMPUTED = "precomputed:"


@pytest.fixture
def no_model(monkeypatch):
    """Every model entry point of the offline client counts its calls."""
    calls: list[str] = []

    def spy(name):
        orig = getattr(OfflineLLM, name)

        async def wrapped(self, *a, **kw):
            calls.append(name)
            return await orig(self, *a, **kw)
        return wrapped

    for name in ("_complete", "samples", "ocr", "stream"):
        monkeypatch.setattr(OfflineLLM, name, spy(name))
    return calls


def by_text(client) -> dict[str, dict]:
    return {e["text"]: e for e in client.get("/api/entries").json()}


def terms(entry: dict) -> set[tuple]:
    return {(x["hpo_id"] or x["canonical"], x["negated"], x["family_history"], x["review"]) for x in entry["entities"]}


# ------------------------------------------------------------------ the label files themselves
@pytest.mark.parametrize("persona", list(PERSONAS))
def test_label_files_match_the_ontology_and_the_text(persona):
    onto = Ontology.load()
    labels = persona_labels(persona)
    assert set(labels) == {t for _d, t, _m in PERSONAS[persona]}  # one record per entry, same text
    for text, ents in labels.items():
        for x in ents:
            Entity(id="x", entry_id="e", **x)  # valid against the contract
            assert x["quote"] in text, (x["quote"], text)  # verbatim substring, same case
            assert x["model"].startswith(PRECOMPUTED)  # says how it was made, never a live call
            if x["hpo_id"]:
                assert onto.exists(x["hpo_id"]) and onto.label(x["hpo_id"]) == x["hpo_label"]
            else:
                assert x["hpo_label"] is None
            if x["onset_hint"]:  # real onsets only: no time of day, no trigger
                assert not re.search(r"morning|evening|afternoon|sun|mattin|sera|pomeriggio|sole", x["onset_hint"], re.I)
            assert x["review"] in ("auto", "needs_review")
            assert (x["review"] == "needs_review") == (x["confidence"] is not None and x["confidence"] < 0.7)


def test_files_carry_provenance():
    for lang in ("en", "it"):
        d = json.loads((DEMO_DIR / f"giulia_labels_{lang}.json").read_text())
        assert d["lang"] == lang and d["made"] and d["reviewed"]
    assert (DEMO_DIR / "LABELS.md").exists()


# ------------------------------------------------------------------ demo referti
def test_demo_referti_load_without_ocr(unlocked, no_model):
    r = unlocked.post("/api/demo/documents").json()
    assert r["pages"] == 3
    labs = unlocked.get("/api/labs").json()
    # the live MinerU table read gave 48 of 48 right; two rows are stored as deliberate misreads (LABELS.md) and the
    # code checks against the page's text layer send exactly those two to the clinician
    assert labs["n_results"] == 48 and labs["needs_review"] == 2
    unsure = sorted((d["test_name"], d["value_numeric"], tuple(d["checks"])) for d in unlocked.app.state.vault.all("lab")
                    if d["review"] == "needs_review")
    assert unsure == [("Emoglobina", 1.1, ("not_on_page", "implausible")), ("Sodio", 141.0, ("not_on_page",))]
    assert all(d["model"].startswith(PRECOMPUTED) and d["box"] for d in unlocked.app.state.vault.all("lab"))
    assert no_model == []
    with unlocked.stream("GET", f"/api/documents/batch/{r['batch_id']}/events") as s:
        ev = next(json.loads(line[5:]) for line in s.iter_lines() if line.startswith("data:"))
    assert ev["done"] and ev["precomputed"] and ev["labs"] == 48 and ev["pages_per_sec"] == 0 and ev["model"] is None


# ------------------------------------------------------------------ loading the personas
EN_UNSURE = {("Maybe the redness on my cheeks is back after a sunny afternoon at the market.", "HP:0025300"),
             ("Maybe the redness on my cheeks is back after a sunny afternoon at the market.", "Sun exposure"),
             ("I think there is a sore in my mouth again. Tired. Ankles a little puffy at the end of the day.", "HP:0000155")}


def test_demo_en_loads_reviewed_terms_without_a_model_call(unlocked, no_model):
    assert unlocked.post("/api/demo", json={"persona": "giulia"}).json()["entries"] == 19
    assert no_model == []  # nothing waits for a model: every entry is done at once
    es = by_text(unlocked)
    assert len(es) == 19 and all(e["extraction"] == "done" for e in es.values())
    ents = [(t, x) for t, e in es.items() for x in e["entities"]]
    assert all(x["model"].startswith(PRECOMPUTED) for _t, x in ents)
    assert not any("Arthralgia of the knee" in x["canonical"] for _t, x in ents)
    knees = terms(es["Knees ache 6/10 today. No fever. Work was stressful but I don't think that's it."])
    assert knees == {("HP:0030839", False, False, "auto"), ("HP:0001945", True, False, "auto")}
    fam = es["Feeling a bit better this week, more energy. Went for a short walk. My mother has lupus, she only told me now, "
             "and I keep thinking about it."]["entities"]
    assert [(x["quote"], x["family_history"]) for x in fam] == [("lupus", True)]
    unsure = {(t, x["hpo_id"] or x["canonical"]) for t, x in ents if x["review"] == "needs_review"}
    assert unsure == EN_UNSURE
    sun = next(x for t, x in ents if x["canonical"] == "Sun exposure" and x["review"] == "needs_review")
    assert sun["hpo_id"] is None and sun["type"] == "trigger"  # the clinician replaces it (Cutaneous photosensitivity)
    assert all(x["confidence"] is None or x["confidence"] >= 0.7 for _t, x in ents if x["review"] == "auto")
    onsets = {x["onset_hint"] for _t, x in ents} - {None}
    assert onsets == {"all week", "Lasted two days"}
    body = unlocked.get("/api/patterns").json()
    assert body["patterns"] and body["confirmed_terms"] >= 8


def test_demo_it_carries_the_same_picture(tmp_path, no_model):
    from fastapi.testclient import TestClient

    from clario.app import create_app
    from conftest import PASS, settings

    def counted(persona, sub):
        with TestClient(create_app(settings(tmp_path / sub))) as c:
            c.post("/api/vault/setup", json={"passphrase": PASS})
            assert c.post("/api/demo", json={"persona": persona}).json()["entries"] == 19
            es = sorted(c.get("/api/entries").json(), key=lambda e: e["occurred_on"])
            return [sorted((x["hpo_id"], x["negated"], x["family_history"], x["review"]) for x in e["entities"]
                           if x["hpo_id"] and not x["negated"]) for e in es]

    en, it = counted("giulia", "en"), counted("giulia_it", "it")
    assert no_model == []
    assert en == it  # day by day, the same counted terms and the same review states


def test_typed_entry_still_goes_to_the_model(unlocked, no_model):
    unlocked.post("/api/demo", json={"persona": "giulia_it"})
    assert no_model == []
    r = unlocked.post("/api/entries", json={"text": "Oggi la febbre è tornata e ho di nuovo una piaga in bocca.", "lang": "it"})
    assert r.status_code == 200
    wait_extracted(unlocked)
    assert no_model  # the new note was read by the (offline) model
    new = next(e for e in unlocked.get("/api/entries").json() if e["text"].startswith("Oggi la febbre"))
    assert new["extraction"] == "done" and new["entities"]
    assert not any((x["model"] or "").startswith(PRECOMPUTED) for x in new["entities"])


def test_italian_screens_have_an_italian_name_for_every_demo_term():
    from clario.i18n import hpo_it

    for persona in PERSONAS:
        for ents in persona_labels(persona).values():
            for x in ents:
                if x["hpo_id"]:
                    assert x["hpo_id"] in hpo_it(), x["hpo_id"]
                if x["family_history"]:
                    assert x["hpo_id"] is None  # a relative's condition is never a code or a condition name for her


# ------------------------------------------------------------------ loading twice (#12)
def counts(client) -> dict[str, int]:
    v = client.app.state.vault
    return {k: len(v.all(k)) for k in ("entry", "lab", "docpage", "docbatch", "care", "profile")}


def test_loading_the_demo_twice_replaces_it(unlocked, no_model):
    unlocked.post("/api/entries", json={"text": "My own note, not part of the demo."})
    unlocked.post("/api/demo", json={"persona": "giulia"})
    unlocked.post("/api/demo/documents")
    first = counts(unlocked)
    first_labs = unlocked.get("/api/labs").json()
    assert first["entry"] == len(PERSONAS["giulia"]) + 2 and first["lab"] == 48  # persona + own note + import entry

    unlocked.post("/api/demo", json={"persona": "giulia"})
    unlocked.post("/api/demo/documents")
    assert counts(unlocked) == first
    again = unlocked.get("/api/labs").json()
    assert (again["n_results"], again["needs_review"]) == (first_labs["n_results"], first_labs["needs_review"])
    texts = [e["text"] for e in unlocked.get("/api/entries").json()]
    assert len(texts) == len(set(texts)) and "My own note, not part of the demo." in texts

    # switching persona replaces too: the Italian diary instead of the English one, not on top of it
    unlocked.post("/api/demo", json={"persona": "giulia_it"})
    assert counts(unlocked) == first
    texts = {e["text"] for e in unlocked.get("/api/entries").json()}
    assert {t for _d, t, _m in PERSONAS["giulia_it"]} <= texts and not {t for _d, t, _m in PERSONAS["giulia"]} & texts
