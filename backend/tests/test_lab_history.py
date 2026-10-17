"""Lab history reaches the clinic, low-confidence rows need a clinician decision, empty-state note follows the term count."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from clario.app import create_app
from clario.models import LabResult
from clario.share import shared_labs
from conftest import confirm_all, demo_referti_with_unsure, settings, sse, wait_extracted
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
        ("ana", "Positivo 1:160"), ("antidsdna", 90.0), ("ana", "Negativo"), ("ana", "Positivo")]
    assert got[0].abnormal and got[1].abnormal and not got[2].abnormal
    assert [l.needs_review for l in got] == [False, False, False, True]  # a low-confidence row travels, marked for the clinician
    assert got[2].name_en == "ANA" and got[1].name_en == "Anti-dsDNA"


def test_clinic_decides_unchecked_labs_before_finalize(unlocked, clinic_server, tmp_path):
    unlocked.post("/api/entries", json={"text": "Knees ache. Tired. Rash on my cheeks."})
    wait_extracted(unlocked)
    confirm_all(unlocked)
    bid = demo_referti_with_unsure(unlocked)
    with unlocked.stream("GET", f"/api/documents/batch/{bid}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and '"done": true' in line:
                break
    sh = unlocked.post("/api/share", json=share_body(clinic_server)).json()
    pid = sh["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        unchecked = [l for l in pkg["labs"] if l["needs_review"]]
        assert unchecked and all(l["decision"] is None for l in unchecked)
        assert {"ana", "antidsdna"} <= {l["test_key"] for l in pkg["labs"]}
        ana = [l["value_text"] for l in pkg["labs"] if l["test_key"] == "ana"]
        assert len(ana) >= 2  # the history, not one latest value
        events = sse(clinic, clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"])
        texts = [i["text"] for i in events[-1]["payload"]["items"] if i["section"] == "labs"]
        assert any("low-confidence reading, please check" in t for t in texts)
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
        assert r.json()["labs"][rejected["id"]] == "rejected" and r.json()["labs"][unchecked[-1]["id"]] == "confirmed"
        got = {l["id"]: l for l in clinic.get(f"/api/inbox/{pid}").json()["labs"]}
        assert got[rejected["id"]]["decision"] == "rejected" and got[unchecked[-1]["id"]]["decision"] == "confirmed"
        assert clinic.patch(f"/api/inbox/{pid}/labs/{unchecked[0]['id']}", json={"decision": "confirmed"}).status_code == 200  # theirs: PATCH, same handler
        fin = clinic.post(f"/api/inbox/{pid}/brief/finalize")
        assert fin.status_code == 200, fin.text
        md = clinic.get(f"/api/inbox/{pid}/brief.md").text
        assert "please check" not in md
        assert clinic.put(f"/api/inbox/{pid}/labs/{rejected['id']}", json={"decision": "pending"}).status_code == 409


def test_clinic_bulk_lab_decisions_one_log_row_per_lab(unlocked, clinic_server, tmp_path):
    import json

    unlocked.post("/api/entries", json={"text": "Knees ache. Tired. Rash on my cheeks."})
    wait_extracted(unlocked)
    confirm_all(unlocked)
    bid = demo_referti_with_unsure(unlocked)
    with unlocked.stream("GET", f"/api/documents/batch/{bid}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and '"done": true' in line:
                break
    pid = unlocked.post("/api/share", json=share_body(clinic_server)).json()["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        unchecked = [l for l in pkg["labs"] if l["needs_review"]]
        key = unchecked[0]["test_key"]
        n_key = sum(1 for l in unchecked if l["test_key"] == key)
        r = clinic.post(f"/api/inbox/{pid}/labs/decide", json={"decision": "accepted", "test_key": key})
        assert r.status_code == 200 and sum(1 for l in r.json()["labs"] if l["test_key"] == key and l["decision"] == "confirmed") == n_key
        page = next(l for l in unchecked if l["test_key"] != key)
        r = clinic.post(f"/api/inbox/{pid}/labs/decide", json={"decision": "accepted", "page": page["page"], "entry_id": page["entry_id"]})
        assert all(l["decision"] == "confirmed" for l in r.json()["labs"] if l["needs_review"] and (l["page"] == page["page"] or l["test_key"] == key))
        assert clinic.post(f"/api/inbox/{pid}/labs/decide", json={"decision": "maybe"}).status_code == 422
        r = clinic.post(f"/api/inbox/{pid}/labs/decide", json={"decision": "accepted"})
        assert all(l["decision"] == "confirmed" for l in r.json()["labs"] if l["needs_review"])
        log = [json.loads(x) for x in (tmp_path / "clinic" / "lab_decisions.jsonl").read_text().splitlines()]
        assert len(log) >= len(unchecked) and {"lab_id", "decision", "scope", "at"} <= set(log[0]) and "value" not in log[0]
        assert {x["scope"] for x in log} >= {"test", "page"}
        sse(clinic, clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"])
        labs = [i for i in clinic.get(f"/api/inbox/{pid}/brief").json()["items"] if i["origin"] == "document"]
        assert labs and all(i["review"] == "accepted" for i in labs)  # every row decided: no lab line waits any more


def test_brief_text_is_localized_and_does_not_double_the_label():
    from clario.brief import _times, fdate, lab_items, _note_text, _range_text, elide_it
    from datetime import date as _d
    y = _d.today().year
    assert fdate(f"{y}-08-22", "en") == "22 Aug" and fdate(f"{y}-08-22", "it") == "22 ago"
    assert fdate(f"{y - 1}-11-02", "en") == f"2 Nov {y - 1}" and fdate(f"{y - 1}-11-02", "it") == f"2 nov {y - 1}"  # another year shows it
    assert elide_it("dal 8 ago al 11 set") == "dall'8 ago all'11 set"
    assert [_times(n, "en") for n in (1, 2, 3)] == ["once", "twice", "3 times"] and _times(2, "it") == "2 volte"
    assert _note_text("Domanda per la visita: è collegato?") == "è collegato?"
    assert _note_text("Question for this visit: is it linked?") == "is it linked?"
    assert _range_text(None, 200, "en") == "printed range up to 200" and _range_text(None, 200, "it") == "valori di riferimento fino a 200"
    assert _range_text(5, None, "en") == "printed range from 5" and _range_text(5, 9, "it") == "valori di riferimento da 5 a 9"
    from clario.models import SharedLab, SharePackage

    def row(i, name, v, lo, hi, flag, needs_review=False):
        return SharedLab(id=f"l{i}", test_key=name.lower(), test_name=name, value_numeric=v, unit="mg/dL", ref_low=lo, ref_high=hi,
                         flag=flag, date="2026-09-15", page=i, needs_review=needs_review, abnormal=flag in ("low", "high"))

    pkg = SharePackage(package_id="pkg_x", patient_alias="A", created_at="x", expires_at="x", period=("2026-09-01", "2026-09-30"),
                       entries=[], entities=[], labs=[row(1, "Sodium", 140, 135, 145, "normal"), row(2, "Potassium", 4, 3.5, 5, "normal", True),
                                                      row(3, "Cholesterol", 264, None, 200, "high")])
    out = {i.id: i for i in lab_items(pkg, "en")}
    assert out["bi_lab_in_range"].text == "2 tests in range" and out["bi_lab_in_range"].review == "pending"  # one reading needs a check
    assert "printed range up to 200" in out["bi_lab_cholesterol"].text and out["bi_lab_cholesterol"].pages == [3]
    assert lab_items(pkg, "it")[-1].text == "2 esami nella norma"


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
