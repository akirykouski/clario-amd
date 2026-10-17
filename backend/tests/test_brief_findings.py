"""Brief sections built in code: review of systems, pertinent negatives, findings of this visit."""

from fastapi.testclient import TestClient

from conftest import settings, sse
from test_clinic_ddx import shared_giulia
from clario import brief as briefing
from clario.app import create_app
from clario.knowledge import Ontology
from clario.models import Entry, SharedEntity, SharedLab
from clario.share import build_package


def _pkg(ents, labs=None):
    entries = [Entry(id="e_1", created_at="2026-03-01T00:00:00+00:00", occurred_on="2026-03-01", text="rash, no fever"),
               Entry(id="e_2", created_at="2026-03-12T00:00:00+00:00", occurred_on="2026-03-12", text="knees hurt, no fever")]
    pkg = build_package(entries, "2026-03-01", "2026-03-31", "Ash-001", None, [], 24)
    return pkg.model_copy(update={"entities": ents, "labs": labs or []})


def _ent(i, entry, canonical, hpo, **kw):
    return SharedEntity(id=i, entry_id=entry, occurred_on={"e_1": "2026-03-01", "e_2": "2026-03-12"}[entry], type="symptom",
                        quote=canonical.lower(), canonical=canonical, hpo_id=hpo, **kw)


ONTO = Ontology.load()


def test_symptoms_grouped_by_organ_system_and_negatives_listed():
    pkg = _pkg([_ent("x1", "e_1", "Malar rash", "HP:0025300"), _ent("x2", "e_2", "Arthralgia", "HP:0002829"),
                _ent("x3", "e_1", "Fever", "HP:0001945", negated=True), _ent("x4", "e_2", "Fever", "HP:0001945", negated=True),
                _ent("x5", "e_2", "Oral ulcer", "HP:0000155", negated=True), _ent("x6", "e_2", "Oral ulcer", "HP:0000155"),
                _ent("x7", "e_1", "Lupus", None, negated=True, family_history=True)])
    items = briefing.patient_items(pkg, "en", ONTO)
    sym = [i.text for i in items if i.section == "symptoms"]
    assert sym[0].startswith("Skin · Malar rash (HP:0025300)") and any(t.startswith("Musculoskeletal · Arthralgia") for t in sym)
    neg = [i for i in items if i.section == "negatives"]
    # recorded present elsewhere (oral ulcer) and a relative's condition are not the patient's negatives
    assert [i.text for i in neg] == ["General · Fever (HP:0001945): reported absent twice, 1 Mar to 12 Mar"]
    assert neg[0].origin == "patient" and neg[0].cites == ["e_1", "e_2"]
    it = briefing.patient_items(pkg, "it", ONTO)
    assert next(i.text for i in it if i.section == "negatives").endswith("riferito assente 2 volte, dal 1 mar al 12 mar")
    assert not any(i.text.startswith("Skin") for i in briefing.patient_items(pkg, "en"))  # no ontology: no grouping
    text = briefing.brief_text(pkg, briefing.shown_items(pkg, briefing.Brief(package_id=pkg.package_id, items=items), None), "en")
    assert "## Pertinent negatives (patient reported absent)\n- General · Fever" in text
    assert briefing.parse_text(text)[1] == []  # the new headings parse back


def test_findings_from_the_clinicians_decisions():
    pkg = _pkg([_ent("x1", "e_1", "Malar rash", "HP:0025300"), _ent("x2", "e_2", "Arthralgia", "HP:0002829")],
               labs=[SharedLab(id="l1", entry_id="e_2", date="2026-03-12", page=2, test_name="Creatinina", name_en="Creatinine",
                            value_numeric=9.0, unit="mg/dL")])
    d = {"answers": [{"feature_id": "HP:0030880", "label": "Raynaud phenomenon", "answer": "yes"},
                     {"feature_id": "HP:0000155", "label": "Oral ulcer", "answer": "no"}],
         "corrections": {"x2": {"from": "HP:0002829", "from_label": "Arthralgia", "to": "HP:0001369", "label": "Arthritis"}},
         "terms": {"x1": "rejected", "x2": "corrected"}, "labs": {"l1": "rejected"}}
    f = briefing.finding_items(pkg, d, "en", ONTO)
    assert [i.text for i in f] == [
        "Checked at this visit: Raynaud phenomenon (HP:0030880), present",
        "Checked at this visit: Oral ulcer (HP:0000155), absent",
        "Revised on review: Arthralgia (HP:0002829) read as Arthritis (HP:0001369)",
        "Not counted after review: Malar rash (HP:0025300), note of 1 Mar",
        "Lab reading set aside on review: Creatinine, 12 Mar, page 2"]
    assert all(i.origin == "clinician" and i.section == "findings" and i.id.startswith("bi_find_") for i in f)
    assert f[2].cites == ["e_2"]
    # nothing in them trips the code checks meant for the model's lines
    assert all(not briefing.hedge_problems(i.text) or briefing.hedge_problems(i.text) == ["no hedging language"] for i in f)
    b = briefing.Brief(package_id=pkg.package_id, items=f)
    again = briefing.with_findings(b, f[:1])
    assert [i.id for i in again.items] == [f[0].id]  # rebuilt, not appended
    assert briefing.with_findings(b.model_copy(update={"finalized": True}), []).items == f  # a signed brief keeps its own


def test_findings_reach_the_editor_and_the_signed_brief_but_not_the_patient(unlocked, clinic_server, tmp_path):
    pid = shared_giulia(unlocked, clinic_server)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        sse(clinic, clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"])
        q = clinic.get(f"/api/inbox/{pid}/ddx").json()["question"]
        clinic.post(f"/api/inbox/{pid}/ddx/answer", json={"feature_id": q["feature_id"], "answer": "no"})
        t = clinic.get(f"/api/inbox/{pid}/brief/text").json()
        found = [i for i in t["items"] if i["section"] == "findings"]
        assert len(found) == 1 and found[0]["origin"] == "clinician" and found[0]["text"].endswith(", absent")
        assert "## Findings this visit (clinician)" in t["text"]
        assert not any(w.get("item") == t["items"].index(found[0]) for w in t["warnings"])
        assert any(i["section"] == "symptoms" and " · " in i["text"] for i in t["items"])  # review of systems
        lines = [{"id": i["id"], "section": i["section"], "text": i["text"], "cites": i["cites"]} for i in t["items"]]
        fin = clinic.post(f"/api/inbox/{pid}/brief/sign", json={"items": lines, "clinician": "Dr Rossi"}).json()
        assert any(i["id"] == found[0]["id"] and i["origin"] == "clinician" for i in fin["items"])
        assert "Findings this visit (clinician)" in fin["text"]
        # answers changed after signing do not rewrite the signed brief
        clinic.delete(f"/api/inbox/{pid}/ddx/answers")
        assert any(i["section"] == "findings" for i in clinic.get(f"/api/inbox/{pid}/brief").json()["items"])
        pat = clinic.get(f"/api/inbox/{pid}/brief", params={"audience": "patient"}).json()
        assert not any(i["section"] in ("findings", "negatives") for i in pat["items"])

