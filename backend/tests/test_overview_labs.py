"""Clinic glance "Labs out of range": English names in an English clinic, qualitative results flagged in one place,
and the glance lists the same tests the header counts and the lab table marks (Giulia demo)."""

import json

import pytest
from fastapi.testclient import TestClient

from clario import documents as docs
from clario.app import create_app
from clario.demo import DEMO_DIR
from clario.models import LabResult, SharedLab
from clario.overview import labs_out_of_range
from clario.share import LAB_NAMES_EN, lab_abnormal, shared_labs
from conftest import sse, settings
from test_judge_share import share_body


@pytest.mark.parametrize("text,flag", [
    ("Positivo 1:80", "positive"), ("Positive 1:160", "positive"), ("positivo", "positive"), ("Presente", "positive"),
    ("present", "positive"), ("Reattivo", "positive"), ("Reactive", "positive"), ("Rilevato", "positive"),
    ("Negativo", "normal"), ("negative", "normal"), ("Assente", "normal"), ("Absent", "normal"),
    ("Non reattivo", "normal"), ("Non-reactive", "normal"), ("Not detected", "normal"), ("Non rilevato", "normal"),
    ("Tracce", None), ("vedi nota", None), ("", None), (None, None)])
def test_qualitative_results_are_flagged_in_code(text, flag):
    assert docs.compute_flag(None, None, None, "high", text) == flag  # what the page or model said is never trusted


def test_numeric_flag_wins_and_a_number_without_range_stays_unflagged():
    assert docs.compute_flag(12.0, 0.0, 10.0, None, "Positivo") == "high"
    assert docs.compute_flag(12.0, None, None, None, "Positivo") is None


def lab(i, key, text=None, value=None, day="2026-10-01", lo=None, hi=None, flag=None):
    return LabResult(id=f"l{i}", batch_id="b1", test_name=key.upper(), test_key=key, value_numeric=value, value_text=text,
                     unit="", ref_low=lo, ref_high=hi, flag=flag, date=day, page=1, review="confirmed")


def test_a_row_stored_before_the_rule_reads_positive_everywhere():
    old = lab(1, "ana", "Positivo 1:80")  # stored with flag None by the old rule
    assert lab_abnormal(old)
    shared, = shared_labs([old], "2026-09-01", "2026-10-31")
    assert shared.flag == "positive" and shared.abnormal


def test_correcting_a_qualitative_value_recomputes_the_flag():
    row = lab(1, "ana", "Negativo", flag="normal")
    assert docs.apply_lab_action(row, "correct", {"value_text": "Positivo 1:160"}).flag == "positive"
    assert docs.apply_lab_action(row, "correct", {"value_text": "Assente"}).flag == "normal"


def shared(i, key, value=None, text=None, day="2026-01-01", lo=None, hi=None, **kw):
    return SharedLab(id=f"s{i}", test_name=key.upper(), test_key=key, value_numeric=value, value_text=text, unit="",
                     ref_low=lo, ref_high=hi, flag=docs.compute_flag(value, lo, hi, text=text), date=day, page=1,
                     name_en=LAB_NAMES_EN.get(key), **kw)


def test_glance_lists_every_test_once_and_says_when_it_is_back_in_range():
    labs = [shared(1, "c4", 48, day="2025-09-15", lo=10, hi=40), shared(2, "c4", 36, day="2026-02-21", lo=10, hi=40),
            shared(3, "sodio", 149, day="2025-04-07", lo=136, hi=145), shared(4, "sodio", 147, day="2026-02-21", lo=136, hi=145),
            shared(5, "ana", text="Positivo 1:80", day="2025-04-07"), shared(6, "ana", text="Positivo 1:160", day="2025-09-15"),
            shared(7, "ana", text="Negativo", day="2026-02-21"), shared(8, "pcr", 1.0, day="2026-02-21", lo=0, hi=5),
            shared(9, "c3", 63, day="2025-04-07", lo=90, hi=180, decision="rejected")]
    got = labs_out_of_range(labs, "en")
    assert [(r["name"], r["flag"], r["value"], r["latest_in_range"]) for r in got] == [
        ("Sodium", "high", "147", False), ("ANA", "positive", "Positivo 1:160", True), ("C4", "high", "48", True)]
    it = labs_out_of_range(labs, "it")
    assert [r["name"] for r in it] == ["SODIO", "ANA", "C4"]  # Italian clinic: the name as printed


def test_every_test_on_the_demo_referti_has_an_english_name():
    for f in sorted(DEMO_DIR.glob("ref_*.truth.json")):
        for p in json.loads(f.read_text())["pages"]:
            for t in p["tests"]:
                assert LAB_NAMES_EN.get(docs.test_key(t["test_name"])), t["test_name"]


def test_giulia_glance_matches_header_count_and_lab_table(unlocked, clinic_server, tmp_path):
    unlocked.post("/api/demo", json={"persona": "giulia"})
    bid = unlocked.post("/api/demo/documents").json()["batch_id"]
    with unlocked.stream("GET", f"/api/documents/batch/{bid}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and '"done": true' in line:
                break
    mine = unlocked.get("/api/labs").json()  # the patient Labs page: the latest ANA is negative, so not out of range
    ana = next(t for t in mine["tests"] if t["test_key"] == "ana")
    assert [v["flag"] for v in ana["values"]] == ["positive", "positive", "normal"] and not ana["out_of_range"]
    assert mine["out_of_range"] == sum(t["out_of_range"] for t in mine["tests"])

    sh = unlocked.post("/api/share", json=share_body(clinic_server)).json()
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pid = sh["package_id"]
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        off_tests = {l["test_key"] for l in pkg["labs"] if l["abnormal"]}  # what the header counts, what the table marks
        assert all(l["abnormal"] == (l["flag"] in ("low", "high", "positive")) for l in pkg["labs"])
        assert "ana" in off_tests and {"c4", "creatinina", "globulirossi"} <= off_tests
        en = clinic.get(f"/api/inbox/{pid}/overview?lang=en").json()["labs_off"]
        assert {r["test_key"] for r in en} == off_tests and len(en) == len(off_tests) == 14
        names = [r["name"] for r in en]
        assert {"Total cholesterol", "Hemoglobin", "Glucose", "Neutrophils", "Serum iron", "Sodium", "Vitamin D",
                "Hematocrit", "ANA", "C4", "Creatinine", "Red blood cells"} <= set(names)
        assert not {"Colesterolo totale", "Emoglobina", "Glicemia", "Sodio"} & set(names)
        assert next(r for r in en if r["name"] == "ANA")["flag"] == "positive"
        assert [r["latest_in_range"] for r in en] == sorted(r["latest_in_range"] for r in en)  # still off first
        it = clinic.get(f"/api/inbox/{pid}/overview?lang=it").json()["labs_off"]
        assert {"Colesterolo totale", "Emoglobina", "Sodio"} <= {r["name"] for r in it}
        assert any("," in r["value"] for r in it if r["name"] == "Neutrofili")  # decimal comma in Italian

        events = sse(clinic, clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"])
        ana_line = next(i["text"] for i in events[-1]["payload"]["items"] if i["id"] == "bi_lab_ana")
        assert "Positivo 1:160" in ana_line and "positive (" not in ana_line  # the value says it, no extra flag word

        ana_ids = [l["id"] for l in pkg["labs"] if l["test_key"] == "ana" and l["flag"] == "positive"]
        for lid in ana_ids:  # a clinician rejects both positive readings: they leave the glance like they leave the table
            clinic.patch(f"/api/inbox/{pid}/labs/{lid}", json={"decision": "rejected"})
        after = clinic.get(f"/api/inbox/{pid}/overview?lang=en").json()["labs_off"]
        assert "ana" not in {r["test_key"] for r in after} and len(after) == 13
