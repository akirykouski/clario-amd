"""The clinician replaces an unsure term with another ontology term (issue #15): it flows to the package, the overview,
the conditions to consider and the brief, is stored with the other decisions and logged with ids only."""

import json

from fastapi.testclient import TestClient

from conftest import settings, sse
from test_clinic_ddx import shared_giulia
from clario.app import create_app
from clario.clinic_ddx import replacement_candidates, with_corrections
from clario.knowledge import Ontology
from clario.models import Entity, Entry, SharedEntity, SharePackage
from clario.overview import overview
from clario.patterns import patient_label

PHOTO = "HP:0000992"  # cutaneous photosensitivity


def unsure_sun(pkg: dict) -> dict:
    return next(x for x in pkg["entities"] if x["needs_review"] and x["canonical"] == "Sun exposure")


def test_replace_flows_to_overview_conditions_and_brief(unlocked, clinic_server, tmp_path):
    pid = shared_giulia(unlocked, clinic_server)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        sun = unsure_sun(clinic.get(f"/api/inbox/{pid}").json())
        cands = clinic.get(f"/api/inbox/{pid}/terms/{sun['id']}/candidates").json()
        assert PHOTO in [c["hpo_id"] for c in cands] and len(cands) <= 6
        assert clinic.get(f"/api/terms/search", params={"q": "photosensitivity"}).json()  # free search works in clinic mode
        before = clinic.get(f"/api/inbox/{pid}/ddx").json()
        rid = clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"]
        assert sse(clinic, rid)[-1]["stage"] == "done"

        d = clinic.patch(f"/api/inbox/{pid}/terms/{sun['id']}", json={"decision": "replaced", "hpo_id": PHOTO.lower()}).json()
        assert d["terms"][sun["id"]] == "corrected"
        c = d["corrections"][sun["id"]]
        assert c["from"] is None and c["from_label"] == "Sun exposure" and c["to"] == PHOTO and c["label"] == "Cutaneous photosensitivity"
        assert clinic.get(f"/api/inbox/{pid}/decisions").json()["corrections"][sun["id"]]["to"] == PHOTO

        pkg = clinic.get(f"/api/inbox/{pid}").json()
        now = next(x for x in pkg["entities"] if x["id"] == sun["id"])
        assert now["hpo_id"] == PHOTO and now["quote"] == sun["quote"] and not now["needs_review"] and now["reviewed"]
        after = clinic.get(f"/api/inbox/{pid}/ddx").json()
        assert after["n_terms"] == before["n_terms"] + 1
        assert any(m["hpo_id"] == PHOTO for x in after["conditions"] for m in x["matched"])
        assert all(m["hpo_id"] != PHOTO for x in after["conditions"] for m in x["missing"])
        brief = clinic.get(f"/api/inbox/{pid}/brief").json()
        assert any(PHOTO in i["text"] and i["origin"] == "patient" for i in brief["items"])  # draft brief lines rebuilt
        assert all(i["review"] == "pending" for i in brief["items"] if i["origin"] == "ai")  # AI lines untouched

        log = [json.loads(line) for line in (tmp_path / "clinic" / "term_decisions.jsonl").read_text().splitlines()]
        assert log[-1] == log[-1] | {"package_id": pid, "term_id": sun["id"], "decision": "corrected", "from": None, "to": PHOTO}
        assert sun["quote"] not in json.dumps(log)  # ids only, no diary text
        stored = (tmp_path / "clinic" / "decisions" / f"{pid}.json").read_bytes()
        assert PHOTO.encode() not in stored  # decisions stay encrypted at rest

        # undo puts the original term back everywhere
        undo = clinic.patch(f"/api/inbox/{pid}/terms/{sun['id']}", json={"decision": "pending"}).json()
        assert sun["id"] not in undo["terms"] and sun["id"] not in undo["corrections"]
        assert clinic.get(f"/api/inbox/{pid}/ddx").json()["n_terms"] == before["n_terms"]
        assert not any(PHOTO in i["text"] for i in clinic.get(f"/api/inbox/{pid}/brief").json()["items"])


def test_replace_validates_the_term(unlocked, clinic_server, tmp_path):
    pid = shared_giulia(unlocked, clinic_server)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        ulcer = next(x for x in pkg["entities"] if x["needs_review"] and x["hpo_id"] == "HP:0000155")
        url = f"/api/inbox/{pid}/terms/{ulcer['id']}"
        assert clinic.patch(url, json={"decision": "corrected"}).status_code == 422
        assert clinic.patch(url, json={"decision": "corrected", "hpo_id": "HP:9999999"}).status_code == 422
        assert clinic.patch(url, json={"decision": "corrected", "hpo_id": "HP:0000155"}).status_code == 422  # same term
        assert clinic.patch(f"/api/inbox/{pid}/terms/nope", json={"decision": "corrected", "hpo_id": PHOTO}).status_code == 404
        assert clinic.get(f"/api/inbox/{pid}/terms/nope/candidates").status_code == 404
        fam = next(x for x in pkg["entities"] if x["family_history"])
        assert clinic.patch(f"/api/inbox/{pid}/terms/{fam['id']}", json={"decision": "corrected", "hpo_id": PHOTO}).status_code == 422
        # the overview counts the replaced term: the mouth sore read as joint pain makes joint pain a third note
        joints = next(r for r in clinic.get(f"/api/inbox/{pid}/overview").json()["frequent"] if r["label"] == "joint pain")
        assert clinic.patch(url, json={"decision": "corrected", "hpo_id": "HP:0002829"}).status_code == 200
        now = next(r for r in clinic.get(f"/api/inbox/{pid}/overview").json()["frequent"] if r["label"] == "joint pain")
        assert now["count"] == joints["count"] + 1
        # confirm and reject still work as before and clear a replacement
        assert clinic.patch(url, json={"decision": "corrected", "hpo_id": "HP:0200042"}).status_code == 200
        d = clinic.patch(url, json={"decision": "rejected"}).json()
        assert d["terms"][ulcer["id"]] == "rejected" and ulcer["id"] not in d["corrections"]


def test_with_corrections_rewrites_both_views_of_the_term():
    ent = Entity(id="x1", entry_id="e1", type="trigger", quote="after the sun", canonical="Sun exposure", review="needs_review",
                 confidence=0.6, flags=["no_hpo"])
    pkg = SharePackage(package_id="pkg_1", patient_alias="a", created_at="x", expires_at="y", period=("a", "b"),
                       entries=[Entry(id="e1", created_at="x", occurred_on="2026-09-01", text="Rash after the sun.", entities=[ent])],
                       entities=[SharedEntity(id="x1", entry_id="e1", occurred_on="2026-09-01", type="trigger", quote="after the sun",
                                              canonical="Sun exposure", reviewed=False, needs_review=True, confidence=0.6)])
    out = with_corrections(pkg, {"x1": {"from": None, "to": PHOTO, "label": "Cutaneous photosensitivity"}})
    e = out.entries[0].entities[0]
    assert (e.hpo_id, e.review, e.type, e.quote) == (PHOTO, "corrected", "finding", "after the sun")
    assert "fixed_by_clinician" in e.flags and "no_hpo" not in e.flags
    s = out.entities[0]
    assert (s.hpo_id, s.canonical, s.needs_review, s.reviewed, s.type) == (PHOTO, "Cutaneous photosensitivity", False, True, "finding")
    assert with_corrections(pkg, {}) is pkg
    assert "sun" not in str(overview(pkg, Ontology.load())["frequent"]).lower()  # a trigger is not a symptom row
    rows = overview(out, Ontology.load())["frequent"]
    assert [(r["label"], r["count"]) for r in rows] == [(patient_label(Ontology.load(), PHOTO, "en"), 1)]


def test_candidates_leave_out_the_current_term_and_speak_italian():
    onto = Ontology.load()
    en = replacement_candidates(onto, "sore in my mouth", "Oral ulcer", "HP:0000155")
    assert en and "HP:0000155" not in [c.hpo_id for c in en] and len({c.hpo_id for c in en}) == len(en)
    it = replacement_candidates(onto, "after a sunny afternoon", "Sun exposure", None, "it")
    assert any(c.hpo_id == PHOTO for c in it)
