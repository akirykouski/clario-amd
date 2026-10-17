"""Doctor verify (demo): the state machine, and that the patient side never gets the conclusions."""

import json

import pytest

from clario import doctor_verify as dv
from clario.demo import persona_care

DIAGNOSIS_WORDS = ("fibromyalg", "stress")
H = "X-Doctor-Token"


@pytest.fixture
def clock(unlocked):
    t = [1_000_000.0]
    unlocked.app.state.verifier.clock = lambda: t[0]
    return t


def start(c):
    r = c.post("/api/verify/start")
    assert r.status_code == 200, r.text
    return r.json()


def claim(c, code, name="Maria", surname="Rossi", province="Milano"):
    hits = c.post(f"/api/verify/{code}/lookup", json={"name": name, "surname": surname, "province": province}).json()["hits"]
    assert hits
    r = c.post(f"/api/verify/{code}/claim", json={"hit_id": hits[0]["id"]})
    assert r.status_code == 200, r.text
    return r.json()["doctor_token"]


def demo_care(c):
    c.post("/api/demo", json={"persona": "giulia"})


def test_start_shape_and_demo_label(unlocked):
    s = start(unlocked)
    assert s["doctor_path"] == f"/doctor/{s['code']}" and len(s["code"]) == 8
    assert s["register"] == "demo" and "Albo Unico" in s["register_note"]
    assert s["expires_at"]


def test_start_needs_open_vault(patient):
    assert patient.post("/api/verify/start").status_code == 423


def test_lookup_case_and_accent_insensitive(unlocked):
    code = start(unlocked)["code"]
    for body in ({"name": "maria", "surname": "ROSSI", "province": "milano"},
                 {"name": " Maria ", "surname": "Rossi", "province": "MI"}):
        r = unlocked.post(f"/api/verify/{code}/lookup", json=body).json()
        assert r["register"] == "demo"
        assert [h["display"] for h in r["hits"]] == ["Rossi Maria, Ordine di Milano, Albo medici chirurghi"]
    r = unlocked.post(f"/api/verify/{code}/lookup", json={"name": "NICCOLO", "surname": "esposito", "province": "napoli"}).json()
    assert r["hits"][0]["display"].startswith("Esposito Niccolò, Ordine di Napoli")
    r = unlocked.post(f"/api/verify/{code}/lookup", json={"name": "d'angelo", "surname": "d angelo", "province": "Milano"}).json()
    assert r["hits"] == []
    r = unlocked.post(f"/api/verify/{code}/lookup", json={"name": "Maria", "surname": "Rossi", "province": "Torino"}).json()
    assert r["hits"] == []
    r = unlocked.post(f"/api/verify/{code}/lookup", json={"name": "Maria", "surname": "Rossi", "province": ""}).json()
    assert r["hits"] == []


def test_same_name_other_province_is_a_different_hit(unlocked):
    code = start(unlocked)["code"]
    r = unlocked.post(f"/api/verify/{code}/lookup", json={"name": "Maria", "surname": "Rossi", "province": "Roma"}).json()
    assert [h["display"] for h in r["hits"]] == ["Rossi Maria, Ordine di Roma, Albo medici chirurghi"]


def test_full_flow_conclusions_released_only_after_confirm(unlocked):
    demo_care(unlocked)
    code = start(unlocked)["code"]
    assert unlocked.get(f"/api/verify/{code}/status").json()["state"] == "waiting"
    token = claim(unlocked, code)
    st = unlocked.get(f"/api/verify/{code}/status").json()
    assert st["state"] == "claimed" and st["hit_display"] == "Rossi Maria, Ordine di Milano, Albo medici chirurghi"

    assert unlocked.get(f"/api/verify/{code}/conclusions", headers={H: token}).status_code == 403
    assert unlocked.get(f"/api/verify/{code}/conclusions").status_code == 403
    assert unlocked.get(f"/api/verify/{code}/doctor-status", headers={H: token}).json()["state"] == "claimed"

    assert unlocked.post(f"/api/verify/{code}/confirm").json()["state"] == "confirmed"
    assert unlocked.get(f"/api/verify/{code}/conclusions").status_code == 403  # no token
    assert unlocked.get(f"/api/verify/{code}/conclusions", headers={H: "wrong"}).status_code == 403
    r = unlocked.get(f"/api/verify/{code}/conclusions", headers={H: token})
    assert r.status_code == 200
    body = r.json()
    assert body["register"] == "demo" and body["doctor"].startswith("Rossi Maria")
    prev = body["previous"][0]
    assert prev["diagnosis"] and prev["clinician"]
    want = persona_care("giulia")["previous"]
    assert [c["name"] for c in prev["diagnosis"]] == [c["name"] for c in want["diagnosis"]]

    audit = unlocked.get(f"/api/verify/{code}/status").json()["audit"]
    assert [a["event"] for a in audit] == ["started", "claimed", "confirmed", "opened"]
    assert audit[-1]["who"].startswith("Rossi Maria")


def test_patient_never_gets_conclusions(unlocked):
    demo_care(unlocked)
    code = start(unlocked)["code"]
    token = claim(unlocked, code)
    seen = [unlocked.get(f"/api/verify/{code}/status").text]
    seen.append(unlocked.post(f"/api/verify/{code}/confirm").text)
    unlocked.get(f"/api/verify/{code}/conclusions", headers={H: token})
    seen.append(unlocked.get(f"/api/verify/{code}/status").text)
    seen.append(unlocked.get("/api/care").text)
    seen.append(unlocked.post("/api/verify/start").text)
    seen.append(unlocked.get("/api/verify/register").text)
    blob = " ".join(seen).lower()
    for w in DIAGNOSIS_WORDS:
        assert w not in blob, w
    assert "diagnosis" not in json.loads(seen[2]) and "previous" not in json.loads(seen[2])


def test_no_previous_opinion_gives_empty_list_and_message(unlocked):
    code = start(unlocked)["code"]
    token = claim(unlocked, code)
    unlocked.post(f"/api/verify/{code}/confirm")
    r = unlocked.get(f"/api/verify/{code}/conclusions", headers={H: token}).json()
    assert r["previous"] == [] and "No previous opinion" in r["message"]


def test_reject_path(unlocked):
    demo_care(unlocked)
    code = start(unlocked)["code"]
    token = claim(unlocked, code)
    assert unlocked.post(f"/api/verify/{code}/reject").json()["state"] == "rejected"
    assert unlocked.get(f"/api/verify/{code}/conclusions", headers={H: token}).status_code == 403
    assert unlocked.post(f"/api/verify/{code}/confirm").status_code == 409
    assert unlocked.get(f"/api/verify/{code}/doctor-status", headers={H: token}).json()["state"] == "rejected"


def test_confirm_before_claim_is_refused(unlocked):
    code = start(unlocked)["code"]
    assert unlocked.post(f"/api/verify/{code}/confirm").status_code == 409


def test_claim_once_and_unknown_hit(unlocked):
    code = start(unlocked)["code"]
    assert unlocked.post(f"/api/verify/{code}/claim", json={"hit_id": "nope"}).status_code == 404
    claim(unlocked, code)
    assert unlocked.post(f"/api/verify/{code}/claim", json={"hit_id": "demo-001"}).status_code == 409
    assert unlocked.post(f"/api/verify/{code}/lookup", json={"name": "a", "surname": "b", "province": "c"}).status_code == 409


def test_unknown_code(unlocked):
    assert unlocked.get("/api/verify/ZZZZZZZZ/status").status_code == 404
    start(unlocked)
    assert unlocked.get("/api/verify/ZZZZZZZZ/status").status_code == 404


def test_expiry_before_and_after_confirm(unlocked, clock):
    demo_care(unlocked)
    code = start(unlocked)["code"]
    clock[0] += dv.PENDING_TTL + 1
    assert unlocked.get(f"/api/verify/{code}/status").json()["state"] == "expired"
    assert unlocked.post(f"/api/verify/{code}/claim", json={"hit_id": "demo-001"}).status_code == 409

    code = start(unlocked)["code"]
    token = claim(unlocked, code)
    unlocked.post(f"/api/verify/{code}/confirm")
    clock[0] += dv.PENDING_TTL + 1  # a confirmed session outlives the pending window
    assert unlocked.get(f"/api/verify/{code}/conclusions", headers={H: token}).status_code == 200
    clock[0] += dv.OPEN_TTL
    assert unlocked.get(f"/api/verify/{code}/conclusions", headers={H: token}).status_code == 403
    assert unlocked.get(f"/api/verify/{code}/status").json()["state"] == "expired"


def test_end_by_doctor_and_by_patient(unlocked):
    demo_care(unlocked)
    code = start(unlocked)["code"]
    token = claim(unlocked, code)
    unlocked.post(f"/api/verify/{code}/confirm")
    assert unlocked.post(f"/api/verify/{code}/end", headers={H: token}).json() == {"ok": True, "state": "ended"}
    assert unlocked.get(f"/api/verify/{code}/conclusions", headers={H: token}).status_code == 403

    code = start(unlocked)["code"]
    token = claim(unlocked, code)
    unlocked.post(f"/api/verify/{code}/confirm")
    assert unlocked.post(f"/api/verify/{code}/end").json()["state"] == "ended"  # patient, vault open
    assert unlocked.get(f"/api/verify/{code}/conclusions", headers={H: token}).status_code == 403


def test_doctor_end_works_with_locked_vault_patient_end_does_not(unlocked):
    code = start(unlocked)["code"]
    token = claim(unlocked, code)
    unlocked.post("/api/vault/lock")
    assert unlocked.post(f"/api/verify/{code}/end").status_code == 423
    assert unlocked.post(f"/api/verify/{code}/lookup", json={"name": "a", "surname": "b", "province": "c"}).status_code == 409  # doctor routes need no vault
    assert unlocked.post(f"/api/verify/{code}/end", headers={H: token}).json()["state"] == "ended"


def test_new_start_ends_the_previous_session(unlocked):
    a = start(unlocked)["code"]
    b = start(unlocked)["code"]
    assert a != b
    assert unlocked.get(f"/api/verify/{a}/status").status_code == 404
    assert unlocked.get(f"/api/verify/{b}/status").json()["state"] == "waiting"


def test_doctor_routes_work_while_vault_is_locked(unlocked):
    code = start(unlocked)["code"]
    unlocked.post("/api/vault/lock")
    r = unlocked.post(f"/api/verify/{code}/lookup", json={"name": "Luca", "surname": "Bianchi", "province": "Torino"})
    assert r.status_code == 200 and r.json()["hits"]
    assert unlocked.get(f"/api/verify/{code}/status").status_code == 423


def test_register_is_synthetic_fixture():
    assert 6 <= len(dv.REGISTER) <= 10
    assert set(dv.PROVINCES) >= {"Milano", "Roma", "Torino", "Napoli", "Bologna"}
