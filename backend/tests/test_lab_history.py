"""Lab history reaches the clinic, unchecked rows need a clinician decision, empty-state note follows the term count."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from clario.app import create_app
from clario.models import LabResult
from clario.share import shared_labs
from conftest import confirm_all, settings, sse, wait_extracted
from test_judge_share import share_body


def row(i, key, text=None, value=None, day="2026-10-01", review="confirmed", flag=None):
    return LabResult(id=f"l{i}", batch_id="b1", test_name=key.upper(), test_key=key, value_numeric=value, value_text=text,
                     unit="", ref_low=None, ref_high=None, flag=flag, date=day, page=1, review=review)


def test_history_keeps_earlier_positive_and_recent_out_of_range_tests():
    rows = [row(1, "ana", "Positivo 1:160", day="2026-02-01"), row(2, "ana", "Negativo", day="2026-10-01"),
            row(3, "antidsdna", value=90, day="2026-03-01", flag="high"),   # abnormal, last 12 months, test not in period
            row(4, "tsh", value=2, day="2026-03-01", flag="normal"),        # normal and not in period: stays home
            row(5, "psa", value=9, day="2024-01-01", flag="high"),          # abnormal but older than 12 months
            row(6, "ana", "Positivo", day="2026-10-02", review="needs_review")]
    got = shared_labs(rows, "2026-09-15", "2026-10-31")
    assert [(l.test_key, l.value_text or l.value_numeric) for l in got] == [
        ("ana", "Positivo 1:160"), ("antidsdna", 90.0), ("ana", "Negativo")]
    assert got[0].abnormal and got[1].abnormal and not got[2].abnormal
    assert got[2].name_en == "ANA" and got[1].name_en == "Anti-dsDNA"


def test_clinic_decides_unchecked_labs_before_finalize(unlocked, clinic_server, tmp_path):
    unlocked.post("/api/entries", json={"text": "Knees ache. Tired. Rash on my cheeks."})
    wait_extracted(unlocked)
    confirm_all(unlocked)
    bid = unlocked.post("/api/demo/documents").json()["batch_id"]
    with unlocked.stream("GET", f"/api/documents/batch/{bid}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and '"done": true' in line:
                break
    sh = unlocked.post("/api/share", json=share_body(clinic_server)).json()
    pid = sh["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        unchecked = [l for l in pkg["labs"] if not l["reviewed"]]
        assert unchecked and all(l["decision"] is None for l in unchecked)
        assert {"ana", "antidsdna"} <= {l["test_key"] for l in pkg["labs"]}
        ana = [l["value_text"] for l in pkg["labs"] if l["test_key"] == "ana"]
        assert len(ana) >= 2  # the history, not one latest value
        events = sse(clinic, clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"])
        texts = [i["text"] for i in events[-1]["payload"]["items"] if i["section"] == "labs"]
        assert any("from documents, pending check" in t for t in texts)
        for it in clinic.get(f"/api/inbox/{pid}/brief").json()["items"]:
            if it["review"] == "pending":
                clinic.patch(f"/api/brief-items/{pid}/{it['id']}", json={"review": "accepted"})
        assert clinic.post(f"/api/inbox/{pid}/brief/finalize").status_code == 409  # labs undecided
        assert clinic.put(f"/api/inbox/{pid}/labs/nope", json={"decision": "accepted"}).status_code == 404
        assert clinic.put(f"/api/inbox/{pid}/labs/{unchecked[0]['id']}", json={"decision": "maybe"}).status_code == 422
        rejected = unchecked[0]
        clinic.put(f"/api/inbox/{pid}/labs/{rejected['id']}", json={"decision": "rejected"})
        for l in unchecked[1:]:
            r = clinic.put(f"/api/inbox/{pid}/labs/{l['id']}", json={"decision": "accepted"})
            assert r.status_code == 200
        got = {l["id"]: l for l in r.json()["labs"]}
        assert got[rejected["id"]]["decision"] == "rejected" and got[unchecked[-1]["id"]]["decision"] == "accepted"
        fin = clinic.post(f"/api/inbox/{pid}/brief/finalize")
        assert fin.status_code == 200, fin.text
        md = clinic.get(f"/api/inbox/{pid}/brief.md").text
        assert "pending check" not in md
        assert clinic.put(f"/api/inbox/{pid}/labs/{rejected['id']}", json={"decision": "pending"}).status_code == 409


def test_patterns_note_follows_the_counted_terms(unlocked):
    r = unlocked.get("/api/patterns").json()
    assert r["confirmed_terms"] == 0 and "at least 3" in r["note"]
    unlocked.post("/api/entries", json={"text": "Knees ache. Tired. Rash on my cheeks."})
    wait_extracted(unlocked)
    confirm_all(unlocked)
    r = unlocked.get("/api/patterns").json()
    if r["confirmed_terms"] >= 3 and not r["patterns"]:
        assert "at least 3" not in r["note"]
    elif r["confirmed_terms"] < 3:
        assert "at least 3" in r["note"]
    else:
        assert "worth discussing" in r["note"]
