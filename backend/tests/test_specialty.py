"""Specialty tags on brief lines (issue #21): code only, from HPO organ systems and lab tests."""

from fastapi.testclient import TestClient

from conftest import settings, sse, wait_extracted
from test_share_clinic import share_body
from clario.app import create_app
from clario.knowledge import Ontology
from clario.specialty import lab_specialties, term_specialties


def test_terms_map_through_organ_system_and_label():
    onto = Ontology.load()
    assert term_specialties(onto, "HP:0002829") == {"rheumatology"}  # Arthralgia
    assert term_specialties(onto, "HP:0025300") == {"rheumatology"}  # Malar rash
    assert term_specialties(onto, "HP:0030880") == {"rheumatology"}  # Raynaud, filed under cardiovascular
    assert term_specialties(onto, "HP:0000155") == {"rheumatology"}  # Oral ulcer, filed under head and neck
    assert term_specialties(onto, "HP:0000093") == {"nephrology"}  # Proteinuria
    assert term_specialties(onto, "HP:0012378") == {"rheumatology", "nephrology"}  # Fatigue: both
    assert term_specialties(onto, "HP:0002315") == set()  # Headache: general practice only
    assert term_specialties(onto, None) == set()


def test_labs_map_by_folded_name_in_both_languages():
    assert lab_specialties("Anti-dsDNA") == lab_specialties("anti dsDNA") == {"rheumatology"}
    assert lab_specialties("Creatinina") == lab_specialties("Creatinine") == {"nephrology"}
    assert lab_specialties("Proteine urinarie") == {"nephrology"}
    assert lab_specialties("C3") == {"rheumatology", "nephrology"}
    assert lab_specialties("TSH") == set() and lab_specialties("") == set()


def test_giulia_brief_lines_carry_specialties(unlocked, clinic_server, tmp_path):
    unlocked.post("/api/demo", json={"persona": "giulia"})
    unlocked.post("/api/demo/documents")
    wait_extracted(unlocked)
    pid = unlocked.post("/api/share", json=share_body(clinic_server)).json()["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        events = sse(clinic, clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"])
        assert events[-1]["stage"] == "done", events[-1]
        for brief in (events[-1]["payload"], clinic.get(f"/api/inbox/{pid}/brief").json()):
            items = brief["items"]
            assert all(set(i["specialties"]) <= {"rheumatology", "nephrology"} for i in items)
            joint = [i for i in items if i["origin"] == "patient" and "(HP:0002829)" in i["text"]]
            assert joint and all(i["specialties"] == ["rheumatology"] for i in joint)
            labs = {i["id"]: i["specialties"] for i in items if i["section"] == "labs"}
            assert labs.get("bi_lab_antidsdna") == ["rheumatology"]
            assert labs.get("bi_lab_c3") == ["rheumatology", "nephrology"]
            assert any(sp == ["nephrology"] for sp in labs.values())  # sodium or creatinine
            note = next(i for i in items if i.get("kind") == "patient_note")
            assert note["specialties"] == []  # the summary is shown for every specialty
        # the tags survive review and finalize (lab lines are rebuilt then)
        pending = [i for i in items if i["review"] == "pending" and i["origin"] == "ai"]
        for i in pending:
            clinic.patch(f"/api/brief-items/{pid}/{i['id']}", json={"review": "accepted"})
        for l in clinic.get(f"/api/inbox/{pid}").json()["labs"]:
            if l.get("needs_review"):
                clinic.patch(f"/api/inbox/{pid}/labs/{l['id']}", json={"decision": "confirmed"})
        fin = clinic.post(f"/api/inbox/{pid}/brief/finalize").json()
        assert fin["finalized"] and {i["id"]: i["specialties"] for i in fin["items"]}.get("bi_lab_c3") == ["rheumatology", "nephrology"]
