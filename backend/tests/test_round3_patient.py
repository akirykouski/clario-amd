"""Round 3, lane P: demo diary arrives reviewed, "all correct", clinic and patient cards agree, deterministic scoring."""
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import settings, wait_extracted
from clario.app import create_app
from clario.knowledge import Ontology
from clario.patterns import patient_patterns, score_patterns
from clario.models import Entry

BACKEND = Path(__file__).resolve().parents[1]


def entries_of(client):
    return [Entry.model_validate(e) for e in client.get("/api/entries").json()]


@pytest.mark.parametrize("persona,lang", [("giulia", "en"), ("giulia_it", "it")])
def test_demo_arrives_reviewed_and_keeps_hedged_items_queued(unlocked, persona, lang):
    assert unlocked.post("/api/demo", json={"persona": persona}).json()["entries"] == 19
    wait_extracted(unlocked)
    ents = [x for e in entries_of(unlocked) for x in e.entities]
    assert not any(x.review == "auto" for x in ents)
    assert any(x.review == "confirmed" for x in ents)
    body = unlocked.get("/api/patterns", params={"lang": lang}).json()
    assert body["confirmed_terms"] >= 8 and body["patterns"] and body["to_check"] == 0
    log = unlocked.app.state.vault.all("correction_log")
    assert log and all(r["actor"] == "demo_seed" and r["action"] == "confirm" for r in log)
    if persona == "giulia_it":
        assert any(x.review == "needs_review" for x in ents)  # the hedged sentences still have work for the review step
        assert unlocked.get("/api/review").json()["count"] >= 1


def test_demo_unreviewed_keeps_auto_and_counts_them(unlocked):
    unlocked.post("/api/demo", json={"persona": "giulia", "reviewed": False})
    wait_extracted(unlocked)
    body = unlocked.get("/api/patterns").json()
    assert body["confirmed_terms"] == 0 and body["to_check"] >= 5
    assert unlocked.get("/api/review").json()["auto"] == body["to_check"]


def test_all_correct_confirms_auto_terms_of_one_entry_and_logs_it(unlocked):
    unlocked.post("/api/entries", json={"text": "Knees ache in the morning. Mouth sore again. So tired."})
    e = wait_extracted(unlocked)[0]
    assert any(x["review"] == "auto" for x in e["entities"])
    r = unlocked.post(f"/api/entries/{e['id']}/confirm-all").json()
    assert r["confirmed"] >= 1
    assert not any(x["review"] == "auto" for x in unlocked.get(f"/api/entries/{e['id']}").json()["entities"])
    assert any(rec["actor"] == "patient" for rec in unlocked.app.state.vault.all("correction_log"))
    assert unlocked.post(f"/api/entries/{e['id']}/confirm-all").json()["confirmed"] == 0
    unlocked.post("/api/entries", json={"text": "Red rash on my cheeks after the sun. Wrists swollen, knees ache."})
    wait_extracted(unlocked)
    assert unlocked.post("/api/confirm-auto").json()["confirmed"] >= 1
    assert unlocked.get("/api/patterns").json()["to_check"] == 0


def test_shared_card_signal_equals_the_patient_signal(unlocked, clinic_server, tmp_path):
    unlocked.post("/api/demo", json={"persona": "giulia"})
    wait_extracted(unlocked)
    mine = {p["card_id"]: p["signal"] for p in unlocked.get("/api/patterns").json()["patterns"]}
    assert mine
    today = date.today()
    for weeks in (4, 12):  # the window changes what is shared, never the card
        r = unlocked.post("/api/share", json={"clinic_url": clinic_server, "since": (today - timedelta(days=7 * weeks)).isoformat(),
                                              "until": today.isoformat(), "include_patterns": True})
        assert r.status_code == 200, r.text
        pid = r.json()["package_id"]
        with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
            shared = clinic.get(f"/api/inbox/{pid}").json()["patterns"]
        assert shared and all(p["card_id"] in mine and p["signal"] == mine[p["card_id"]] for p in shared)
        inside = {e["id"] for e in clinic_entries(tmp_path, pid)}
        assert all(set(m["entry_ids"]) <= inside for p in shared for m in p["matched"])


def clinic_entries(tmp_path, pid):
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        return clinic.get(f"/api/inbox/{pid}").json()["entries"]


def test_share_scores_the_whole_diary_like_the_patient_screen():
    onto = Ontology.load()
    from clario.models import Entity

    # a diary built from the ontology: the same entries through both entry points give the same card and signal
    es = []
    for i, hids in enumerate((["HP:0002829", "HP:0025300"], ["HP:0000155", "HP:0030880"], ["HP:0001945", "HP:0002829"])):
        es.append(Entry(id=f"e{i}", created_at="2026-01-01T00:00:00Z", occurred_on=f"2026-01-0{i + 1}", text="x", entities=[
            Entity(id=f"x{i}{h}", entry_id=f"e{i}", type="symptom", quote=h, canonical=onto.label(h), hpo_id=h, review="confirmed")
            for h in hids]))
    mine = {p.card_id: p.signal for p in patient_patterns(es, onto)}
    theirs = {p.card_id: p.signal for p in score_patterns(es, onto, within={"e0"})}
    assert mine == theirs


def test_italian_term_search_ranks_italian_labels_and_never_returns_english_noise(unlocked):
    r = unlocked.get("/api/terms/search", params={"q": "mal di testa", "lang": "it"}).json()
    assert r and r[0]["hpo_id"] == "HP:0002315" and r[0]["label"] == "Mal di testa" and len(r) <= 3
    assert not any("seizure" in x["label"].lower() or "epilep" in x["label"].lower() for x in r)
    assert len(unlocked.get("/api/terms/search", params={"q": "dolore", "lang": "it"}).json()) <= 3


SCRIPT = """
import json, sys
sys.path.insert(0, {backend!r})
from clario.knowledge import Ontology
from clario.models import Entity, Entry
from clario.patterns import scored_diseases
onto = Ontology.load()
hs = ["HP:0002829", "HP:0025300", "HP:0000155", "HP:0030880", "HP:0001945", "HP:0001369", "HP:0002315"]
es = [Entry(id="e", created_at="2026-01-01T00:00:00Z", occurred_on="2026-01-01", text="x", entities=[
    Entity(id=f"x{{h}}", entry_id="e", type="symptom", quote=h, canonical=onto.label(h), hpo_id=h, review="confirmed") for h in hs])]
print(json.dumps([[s.disease.id, s.score, s.lead, s.signal] for s in scored_diseases(es, onto)[:6]]))
"""


def test_scores_and_leads_do_not_depend_on_the_hash_seed():
    outs = []
    for seed in ("0", "1", "7"):
        r = subprocess.run([sys.executable, "-c", SCRIPT.format(backend=str(BACKEND))], capture_output=True, text=True,
                           env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"}, timeout=300)
        assert r.returncode == 0, r.stderr
        outs.append(r.stdout)
    assert outs[0] == outs[1] == outs[2] and json.loads(outs[0])
