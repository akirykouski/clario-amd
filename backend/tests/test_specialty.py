"""Specialty tags on brief lines (issue #21): code only, from HPO organ systems and lab tests."""

from fastapi.testclient import TestClient

from clario.brief_pdf import page_count
from conftest import settings, sign_brief, sse, wait_extracted
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
        # the tags survive signing (lab lines are rebuilt then); the selected specialty filters what goes into the PDF
        for l in clinic.get(f"/api/inbox/{pid}").json()["labs"]:
            if l.get("needs_review"):
                clinic.patch(f"/api/inbox/{pid}/labs/{l['id']}", json={"decision": "confirmed"})
        general = clinic.get(f"/api/inbox/{pid}/brief/text").json()["text"]
        rheum = clinic.get(f"/api/inbox/{pid}/brief/text", params={"specialty": "rheumatology"}).json()["text"]
        neph_only = [i["text"] for i in items if i["section"] == "labs" and i["specialties"] == ["nephrology"]]
        assert neph_only and all(t.split(":")[0] in general for t in neph_only)
        assert not any(t.split(":")[0] in rheum for t in neph_only)
        assert rheum.index("## Recorded symptoms") < rheum.index("## Timeline")  # rheumatology reads symptoms first
        assert page_count(clinic.get(f"/api/inbox/{pid}/brief.pdf", params={"specialty": "rheumatology"}).content) == 1
        fin = sign_brief(clinic, pid, specialty="rheumatology").json()
        assert fin["finalized"] and fin["specialty"] == "rheumatology"
        assert {i["id"]: i["specialties"] for i in fin["items"]}.get("bi_lab_c3") == ["rheumatology", "nephrology"]
        assert not any(i["section"] == "labs" and i["specialties"] == ["nephrology"] for i in fin["items"])
