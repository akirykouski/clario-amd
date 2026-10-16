import json

from fastapi.testclient import TestClient

from conftest import settings, wait_extracted
from test_share_clinic import share_body
from clario.app import create_app


def test_overview_is_plain_words_with_profile_and_the_questions_from_the_notes(unlocked, clinic_server, tmp_path):
    unlocked.post("/api/demo", json={"persona": "giulia"})
    wait_extracted(unlocked)
    assert unlocked.get("/api/profile").json() == {"age": 29, "sex": "female"}
    r = unlocked.post("/api/share", json=share_body(clinic_server, note=None))
    pid = r.json()["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        o = clinic.get(f"/api/inbox/{pid}/overview").json()
        print(json.dumps(o, indent=1))
        assert o["profile"] == {"age": 29, "sex": "female"}
        assert o["notes"] > 5 and o["weeks"] >= 4
        assert o["frequent"] and all(not x["label"].startswith("HP:") for x in o["frequent"] + o["recent"])
        assert "HP:" not in json.dumps(o)  # no codes anywhere in the overview
        assert o["asks"] and "joint pain and the rash" in o["asks"][0]["text"]
        assert o["recent"] and o["first"]
        assert o["mood"]["avg"] > 0


def test_profile_is_optional_and_validated(unlocked, clinic_server, tmp_path):
    assert unlocked.get("/api/profile").json() == {}
    assert unlocked.put("/api/profile", json={"age": 200}).status_code == 422
    assert unlocked.put("/api/profile", json={"sex": "x"}).status_code == 422
    assert unlocked.put("/api/profile", json={"age": 41, "sex": "male"}).json() == {"age": 41, "sex": "male"}
    unlocked.post("/api/entries", json={"text": "Knees ache"})
    wait_extracted(unlocked)
    pid = unlocked.post("/api/share", json=share_body(clinic_server, include_profile=False)).json()["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        assert clinic.get(f"/api/inbox/{pid}").json()["profile"] is None  # the patient left it out
