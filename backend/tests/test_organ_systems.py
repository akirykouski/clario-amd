"""Organ-system row above the conditions to consider (#16): computed in code from the evidence the ranking counts."""

from fastapi.testclient import TestClient

from clario.app import create_app
from clario.clinic_ddx import organ_systems, with_labs
from clario.knowledge import Ontology
from clario.models import Entity, Entry, PastRef
from conftest import settings
from test_clinic_ddx_labs import lab, shared_giulia_with_labs

MALAR, ARTHRALGIA, FATIGUE, ALOPECIA = "HP:0025300", "HP:0002829", "HP:0012378", "HP:0001596"


def ent(eid, hpo_id, **kw):
    return Entity(id=f"x_{eid}_{hpo_id}", entry_id=eid, type="symptom", quote="q", canonical="c", hpo_id=hpo_id, **kw)


def entry(eid, *ents, date="2026-01-05"):
    return Entry(id=eid, created_at="", occurred_on=date, text="", extraction="done", entities=list(ents))


def keys(systems):
    return {s.key: {f.hpo_id for f in s.findings} for s in systems}


def test_negated_family_and_past_terms_stay_out_and_general_is_not_an_organ():
    onto = Ontology.load()
    entries = [entry("e1", ent("e1", MALAR), ent("e1", ARTHRALGIA), ent("e1", FATIGUE)),
               entry("e2", ent("e2", MALAR), ent("e2", ALOPECIA, negated=True)),
               entry("e3", ent("e3", "HP:0000093", family_history=True),  # a relative's proteinuria
                     ent("e3", "HP:0001903", past=PastRef(kind="childhood", cue="as a child")))]  # anaemia as a child
    got = organ_systems(onto, entries)
    assert keys(got) == {"skin": {MALAR}, "joints": {ARTHRALGIA}}
    skin = next(s for s in got if s.key == "skin")
    assert skin.count == 1 and skin.findings[0].count == 2 and skin.findings[0].labs == 0


def test_labs_count_only_when_verified_and_are_placed_by_test():
    onto = Ontology.load()
    labs = [lab("Creatinina", 1.9, lo=0.5, hi=1.1, id_="cr"),  # HPO files it under metabolism; the row says kidney
            lab("Emoglobina", 1.1, lo=12, hi=16, id_="hb", needs_review=True)]  # possible misread, not checked yet
    got = keys(organ_systems(onto, with_labs(onto, [], labs)))
    assert got == {"kidney": {"HP:0003259"}}
    got = keys(organ_systems(onto, with_labs(onto, [], labs, {"hb": "confirmed"})))
    assert got == {"kidney": {"HP:0003259"}, "blood": {"HP:0001903"}}
    assert keys(organ_systems(onto, with_labs(onto, [], labs, {"cr": "rejected"}))) == {}


def test_giulia_with_referti_spans_skin_joints_kidney_blood(unlocked, clinic_server, tmp_path):
    pid = shared_giulia_with_labs(unlocked, clinic_server)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        d = clinic.get(f"/api/inbox/{pid}/ddx").json()
        systems = {s["key"]: s for s in d["systems"]}
        assert {"skin", "joints", "kidney", "blood"} <= set(systems)
        assert not {"general", "other"} & set(systems)
        assert all(s["count"] == len(s["findings"]) for s in d["systems"])
        counts = [s["count"] for s in d["systems"]]
        assert counts == sorted(counts, reverse=True)
        blood = {f["hpo_id"]: f for f in systems["blood"]["findings"]}
        assert blood["HP:0001903"]["labs"] == 1  # one haemoglobin counts; the stored misread waits for the clinician
        assert "HP:0003493" in {f["hpo_id"] for f in systems["immune"]["findings"]}  # ANA, from the referti
        it = clinic.get(f"/api/inbox/{pid}/ddx?lang=it").json()
        assert [s["key"] for s in it["systems"]] == [s["key"] for s in d["systems"]]
