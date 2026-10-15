import re

from conftest import PASS, confirm_all, wait_extracted
from clario.extract import RawEntity, RawOut, ground
from clario.knowledge import Ontology
from clario.safety import check_entry, hedge_problems, is_hedged


def test_vault_lifecycle_and_encryption_at_rest(patient):
    assert patient.get("/api/vault").json() == {"initialized": False, "locked": True}
    assert patient.post("/api/vault/setup", json={"passphrase": "short"}).status_code == 422
    assert patient.post("/api/vault/setup", json={"passphrase": PASS}).status_code == 200
    secret = "Fingers turned white in the cold at Porta Romana"
    patient.post("/api/entries", json={"text": secret, "occurred_on": "2026-09-01"})
    raw = patient.app.state  # noqa: F841 - settings live on app.state
    db = (patient.app.state.settings.data_dir / "clario.db").read_bytes()
    assert b"Porta Romana" not in db and b"2026-09-01" not in db and b"Fingers" not in db
    assert patient.post("/api/vault/lock").status_code == 200
    assert patient.get("/api/entries").status_code == 423
    assert patient.post("/api/vault/unlock", json={"passphrase": "wrong passphrase!!"}).status_code == 401
    assert patient.post("/api/vault/unlock", json={"passphrase": PASS}).status_code == 200
    assert patient.get("/api/entries").json()[0]["text"] == secret


def test_emergency_entry_returns_notice_and_still_saves(unlocked):
    r = unlocked.post("/api/entries", json={"text": "Chest pain and I can't catch my breath, pain going down my arm"}).json()
    assert r["safety"]["level"] == "emergency" and "112" in r["safety"]["message"]
    assert r["entry"]["id"]
    assert unlocked.post("/api/entries", json={"text": "Knees ache again"}).json()["safety"] is None


def test_self_harm_gets_support_message():
    n = check_entry("Some nights I just want to die")
    assert n and n.level == "emergency" and "Telefono Amico" in n.message
    assert check_entry("dolore al petto e sudorazione fredda").level == "emergency"


def test_hedge_validator():
    assert is_hedged("This may resemble a pattern worth discussing with your doctor.")
    assert not is_hedged("You have lupus.")
    assert not is_hedged("This pattern may suggest you should take 200 mg daily.")
    assert not is_hedged("This confirms the diagnosis.")
    assert "no hedging language" in hedge_problems("Joint pain was recorded.")


def test_grounding_drops_invented_quotes_and_wrong_codes():
    onto = Ontology.load()
    text = "Woke up with the butterfly rash on my cheeks. Non ho febbre. Knees ache 6/10."
    raw = RawOut(entities=[
        RawEntity(quote="butterfly rash on my cheeks", canonical="Malar rash", hpo_id="HP:0025300"),
        RawEntity(quote="seizures every night", canonical="Seizure", hpo_id="HP:0001250"),  # not in text
        RawEntity(quote="Knees ache", canonical="Knee pain", hpo_id="HP:0001250", severity=6),  # wrong code
        RawEntity(quote="febbre", canonical="Fever", hpo_id="HP:0001945"),  # negated in Italian, model missed it
    ])
    ents = {e.canonical: e for e in ground("e1", text, raw, onto, "m")}
    assert set(ents) == {"Malar rash", "Knee pain", "Fever"}
    assert ents["Malar rash"].hpo_id == "HP:0025300" and not ents["Malar rash"].flags
    assert ents["Knee pain"].hpo_id != "HP:0001250" and "hpo_dropped" in ents["Knee pain"].flags
    assert ents["Knee pain"].severity == 6
    assert ents["Fever"].negated and "negation_from_text" in ents["Fever"].flags


def test_demo_to_patterns(unlocked):
    assert unlocked.post("/api/demo", json={"persona": "giulia"}).json()["entries"] == 19
    entries = wait_extracted(unlocked)
    assert all(e["extraction"] == "done" for e in entries)
    assert unlocked.get("/api/patterns").json()["patterns"] == []  # nothing confirmed yet
    confirm_all(unlocked)
    body = unlocked.get("/api/patterns").json()
    pats = body["patterns"]
    assert pats and body["confirmed_terms"] >= 8
    assert "Not a diagnosis" in body["note"]
    for p in pats:
        assert p["signal"] in ("weak", "moderate", "strong")
        assert is_hedged(p["rationale"]) and not re.search(r"\d+\s?%", p["rationale"])
        assert all(m["entry_ids"] for m in p["matched"])
    assert any("lupus" in p["disease_name"].lower() for p in pats)
    tl = unlocked.get("/api/timeline").json()
    assert tl["terms"][0]["count"] >= tl["terms"][-1]["count"] and len(tl["days"]) == 19


def test_rejected_and_negated_terms_do_not_count(unlocked):
    unlocked.post("/api/entries", json={"text": "No fever. Knees ache. Mouth sore again. So tired."})
    e = wait_extracted(unlocked)[0]
    for x in e["entities"]:
        unlocked.patch(f"/api/entities/{x['id']}", json={"status": "confirmed" if x["canonical"] != "Oral ulcer" else "rejected"})
    terms = {t["label"] for t in unlocked.get("/api/timeline").json()["terms"]}
    assert "Fever" not in terms and "Oral ulcer" not in terms and "Arthralgia" in terms


def test_fix_term_validates_ontology(unlocked):
    unlocked.post("/api/entries", json={"text": "Knees ache"})
    x = wait_extracted(unlocked)[0]["entities"][0]
    assert unlocked.patch(f"/api/entities/{x['id']}", json={"hpo_id": "HP:9999999"}).status_code == 422
    r = unlocked.patch(f"/api/entities/{x['id']}", json={"hpo_id": "HP:0002829"}).json()
    assert r["hpo_label"] == "Arthralgia" and "fixed_by_patient" in r["flags"]
    assert any(t["hpo_id"] == "HP:0025300" for t in unlocked.get("/api/terms/search", params={"q": "malar rash"}).json())


def test_patterns_only_count_close_matches_and_list_common_missing_features(unlocked):
    from clario.knowledge import Ontology
    from clario.patterns import COMMON, close

    unlocked.post("/api/demo", json={"persona": "giulia"})
    wait_extracted(unlocked)
    confirm_all(unlocked)
    onto = Ontology.load()
    pats = unlocked.get("/api/patterns").json()["patterns"]
    assert 1 <= len(pats) <= 3
    assert pats[0]["disease_name"] == "Systemic lupus erythematosus"  # subtype number stripped, ranked first
    for p in pats:
        d = onto.disease(p["disease_id"])
        for m in p["matched"]:
            assert any(close(onto, m["hpo_id"], t) for t in d.phenotypes), m["label"]
        for t in p["missing"]:
            assert d.phenotypes[t["hpo_id"]] >= COMMON
