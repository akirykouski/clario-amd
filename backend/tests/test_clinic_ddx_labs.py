"""Abnormal labs as HPO features in the clinic differential, and numbered OMIM subtypes shown as the general condition."""
from fastapi.testclient import TestClient

from conftest import demo_referti_with_unsure, settings, wait_extracted
from test_share_clinic import share_body
from clario.app import create_app
from clario.clinic_ddx import (LAB_ENTRY, LAB_RULES, conditions, lab_findings, lab_normal, lab_reading, lab_rule,
                               with_labs)
from clario.knowledge import Ontology
from clario.models import Entity, Entry, SharedLab
from clario.patterns import base_name, evidence_from, general_entry, scored_diseases

# The label each mapped id must carry in the shipped ontology: a wrong id from memory fails here.
EXPECTED = {
    "HP:0001903": "Anemia",
    "HP:0005421": "Decreased circulating complement C3 concentration",
    "HP:0045042": "Decreased circulating complement C4 concentration",
    "HP:0004431": "Reduced circulating complement concentration",
    "HP:0003493": "Antinuclear antibody positivity",
    "HP:0020151": "Anti-dsDNA antibody positivity",
    "HP:0001882": "Decreased total leukocyte count",  # leukopenia
    "HP:0001888": "Decreased total lymphocyte count",  # lymphopenia
    "HP:0001873": "Thrombocytopenia",
    "HP:0003259": "Elevated circulating creatinine concentration",
    "HP:0000093": "Proteinuria",
    "HP:0003565": "Elevated erythrocyte sedimentation rate",
    "HP:0011227": "Elevated circulating C-reactive protein concentration",
}


def lab(name, num=None, text=None, lo=None, hi=None, unit="", flag=None, id_="l1", date="2026-01-10", **kw):
    return SharedLab(id=id_, test_name=name, value_numeric=num, value_text=text, ref_low=lo, ref_high=hi, unit=unit,
                     flag=flag, date=date, page=1, **kw)


def note(eid, hpo_id, date="2026-01-05"):
    return Entry(id=eid, created_at="", occurred_on=date, text="", extraction="done",
                 entities=[Entity(id=f"x_{eid}_{hpo_id}", entry_id=eid, type="symptom", quote="q", canonical="c",
                                  hpo_id=hpo_id)])


def test_every_mapped_id_exists_with_the_expected_label():
    onto = Ontology.load()
    assert {r.hpo_id for r in LAB_RULES} == set(EXPECTED)
    for r in LAB_RULES:
        assert onto.label(r.hpo_id) == EXPECTED[r.hpo_id], r.hpo_id
        assert r.direction in ("low", "high", "positive") and r.names
    names = [n for r in LAB_RULES for n in r.names]
    assert len(names) == len(set(names))  # one rule per test name


def test_italian_and_english_names_map_to_the_same_rule():
    pairs = [("Emoglobina", "Hemoglobin"), ("Globuli bianchi", "White blood cells"), ("Linfociti", "Lymphocytes"),
             ("Piastrine", "Platelets"), ("Creatinina", "Creatinine"), ("Proteine urinarie", "Urine protein"),
             ("Anti-dsDNA", "anti-dsDNA"), ("ANA", "Antinuclear antibodies"), ("VES", "ESR"), ("PCR", "CRP")]
    for it, en in pairs:
        a, b = lab_rule(lab(it)), lab_rule(lab(en))
        assert a is not None and a == b, (it, en)
    assert lab_rule(lab("Sodio")) is None and lab_rule(lab("Colesterolo totale")) is None
    assert lab_rule(lab("Esame strano", name_en="Hemoglobin")).hpo_id == "HP:0001903"


def test_reading_comes_from_the_value_not_the_flag():
    assert lab_reading(lab("ANA", text="Positivo 1:160")) == {"positive"}
    assert lab_reading(lab("ANA", text="Positive 1:80")) == {"positive"}
    assert lab_reading(lab("ANA", text="1:320")) == {"positive"}  # a titre alone
    assert lab_reading(lab("ANA", text="Negativo")) == set()
    assert lab_reading(lab("ANA", text="Negativo (< 1:80)")) == set()  # a negative word wins over the titre
    # the other branch flags qualitative results "Positive": the value still decides
    assert lab_reading(SharedLab.model_construct(test_name="ANA", value_text="Positivo 1:160", flag="Positive",
                                                 value_numeric=None, ref_low=None, ref_high=None)) == {"positive"}
    assert lab_reading(lab("Emoglobina", 10.5, lo=12, hi=16, flag="normal")) == {"low"}  # wrong flag, value wins
    assert lab_reading(lab("Anti-dsDNA", 159, lo=0, hi=100)) == {"high", "positive"}
    assert lab_reading(lab("C3", 128, lo=90, hi=180)) == set()
    assert lab_reading(lab("Piastrine", 90, flag="low")) == {"low"}  # no range printed: the flag is all there is
    assert lab_reading(lab("Proteine urinarie", text="++")) == {"positive"}


def test_findings_follow_directions_and_units():
    labs = [lab("Emoglobina", 10.5, lo=12, hi=16, id_="a"), lab("C4", 48, lo=10, hi=40, id_="b"),
            lab("Linfociti", 15, lo=20, hi=45, unit="%", id_="c"), lab("Linfociti", 0.7, lo=1, hi=4, unit="10^3/uL", id_="d"),
            lab("Creatinina", 0.39, lo=0.5, hi=0.9, id_="e"), lab("ANA", text="Positivo 1:80", id_="f")]
    got = {h: [l.id for l in rows] for h, rows in lab_findings(labs).items()}
    assert got == {"HP:0001903": ["a"], "HP:0001888": ["d"], "HP:0003493": ["f"]}  # high C4 and low creatinine are not features
    assert lab_normal(labs) == {"HP:0045042", "HP:0003259"}  # measured, never abnormal in the rule's direction


def test_lab_decisions_are_respected_like_term_decisions():
    labs = [lab("ANA", text="Positivo 1:80", id_="ok"), lab("C3", 63, lo=90, hi=180, id_="unsure", needs_review=True),
            lab("Emoglobina", 10.5, lo=12, hi=16, id_="bad")]
    # a row the code checks sent to the clinician counts only once confirmed or corrected; a rejected row never does
    assert set(lab_findings(labs)) == {"HP:0003493", "HP:0001903"}
    assert set(lab_findings(labs, {"unsure": "confirmed"})) == {"HP:0003493", "HP:0005421", "HP:0001903"}
    assert set(lab_findings(labs, {"unsure": "corrected"})) == {"HP:0003493", "HP:0005421", "HP:0001903"}
    assert set(lab_findings(labs, {"unsure": "confirmed", "bad": "rejected"})) == {"HP:0003493", "HP:0005421"}
    assert set(lab_findings(labs, {"unsure": "rejected", "bad": "rejected"})) == {"HP:0003493"}
    assert "HP:0005421" not in lab_normal(labs)  # an unchecked reading says nothing either way
    onto = Ontology.load()
    ents = {x.hpo_id: x for e in with_labs(onto, [], labs, {"unsure": "confirmed"}) for x in e.entities}
    assert ents["HP:0005421"].review == "confirmed" and ents["HP:0003493"].review == "auto"
    assert all("from_labs" in x.flags and x.type == "lab" for x in ents.values())
    ents = {x.hpo_id: x for e in with_labs(onto, [], labs) for x in e.entities}
    assert "HP:0005421" not in ents  # unchecked: not a feature yet
    assert "HP:0001903" not in lab_normal(labs, {"bad": "rejected"})  # a rejected reading says nothing either way


def test_lab_and_note_features_merge_without_double_counting():
    onto = Ontology.load()
    notes = [note("e1", "HP:0000093"), note("e2", "HP:0000093", "2026-01-06"), note("e3", "HP:0025300"),
             note("e4", "HP:0002829")]
    labs = [lab("Proteine urinarie", text="Positivo", id_="p1", date="2026-01-10"),
            lab("Proteine urinarie", 40, hi=15, id_="p2", date="2026-02-10"), lab("ANA", text="Positivo 1:160", id_="a1")]
    entries = with_labs(onto, notes, labs)
    ev = evidence_from(entries, onto)
    assert set(ev) == {"HP:0000093", "HP:0025300", "HP:0002829", "HP:0003493"}  # one proteinuria, not two
    assert len(evidence_from(notes, onto)) == 3
    prot = ev["HP:0000093"].entry_ids
    assert sum(not i.startswith(LAB_ENTRY) for i in prot) == 2 and sum(i.startswith(LAB_ENTRY) for i in prot) == 2
    feats = {m.hpo_id: m for c in conditions(onto, entries) for m in c.matched}
    assert feats["HP:0000093"].count == 2 and feats["HP:0000093"].labs == 2  # two notes, two lab dates
    assert feats["HP:0003493"].count == 0 and feats["HP:0003493"].labs == 1
    assert all(e.id.startswith(LAB_ENTRY) for e in entries[len(notes):])


# ---------------------------------------------------------------- grouping of numbered subtypes
def test_base_name_strips_subtype_numbers_but_keeps_different_diseases_apart():
    assert base_name("Systemic lupus erythematosus 18") == "Systemic lupus erythematosus"
    assert base_name("Systemic lupus erythematosus, susceptibility to, 6") == "Systemic lupus erythematosus"
    assert base_name("Chilblain lupus 1") == "Chilblain lupus"
    assert base_name("Ehlers-Danlos syndrome, type 4") == "Ehlers-Danlos syndrome"
    assert base_name("Trisomy 18") == "Trisomy 18" != base_name("Trisomy 13")
    assert base_name("Chromosome 22q11.2 deletion syndrome") == "Chromosome 22q11.2 deletion syndrome"
    assert base_name("Pediatric systemic lupus erythematosus") != base_name("Systemic lupus erythematosus 18")
    assert base_name("Drug-induced lupus erythematosus") == "Drug-induced lupus erythematosus"


def test_general_entry_prefers_an_annotated_orphanet_entry():
    onto = Ontology.load()
    sle = general_entry(onto, "systemic lupus erythematosus")
    assert sle is not None and sle.id == "ORPHA:536" and sle.name == "Systemic lupus erythematosus"
    assert len(sle.phenotypes) >= 40  # annotated in phenotype.hpoa, with real frequencies
    assert onto.disease("OMIM:621369").name == "Systemic lupus erythematosus 18"
    assert general_entry(onto, "no such condition") is None


def test_grouped_scoring_shows_one_general_entry_per_family():
    onto = Ontology.load()
    terms = ["HP:0025300", "HP:0002829", "HP:0001596", "HP:0000093", "HP:0001882", "HP:0003493", "HP:0020151"]
    entries = [note(f"e{i}", h) for i, h in enumerate(terms)]
    grouped = scored_diseases(entries, onto, general=True)
    names = [base_name(s.disease.name).lower() for s in grouped]
    assert len(names) == len(set(names))
    sle = next(s for s in grouped if s.name == "Systemic lupus erythematosus")
    assert sle.disease.id == "ORPHA:536"
    assert not any(s.disease.id.startswith("OMIM:") and base_name(s.disease.name) == "Systemic lupus erythematosus"
                   for s in grouped)
    # distinct conditions that share words stay separate entries
    assert {"Drug-induced lupus erythematosus", "Pediatric systemic lupus erythematosus"} & {s.name for s in grouped}
    # the patient-side ranking is unchanged: best member of each display_name family
    assert scored_diseases(entries, onto)[0].disease.id == scored_diseases(entries, onto, general=False)[0].disease.id


# ---------------------------------------------------------------- Giulia, end to end
def shared_giulia_with_labs(unlocked, clinic_server, unsure_every=None):
    unlocked.post("/api/demo", json={"persona": "giulia"})
    if unsure_every:
        demo_referti_with_unsure(unlocked, unsure_every)
    else:
        unlocked.post("/api/demo/documents")
    wait_extracted(unlocked)
    r = unlocked.post("/api/share", json=share_body(clinic_server))
    assert r.status_code == 200, r.text
    return r.json()["package_id"]


def test_giulia_labs_reach_the_ranking_and_sle_is_the_general_entry(unlocked, clinic_server, tmp_path):
    pid = shared_giulia_with_labs(unlocked, clinic_server)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        d = clinic.get(f"/api/inbox/{pid}/ddx").json()
        top = d["conditions"][0]
        assert top["disease_id"] == "ORPHA:536" and top["name"] == "Systemic lupus erythematosus"
        assert top["full_name"] == "Systemic lupus erythematosus"  # no subtype number anywhere
        assert top["url"] == "https://www.orpha.net/en/disease/detail/536"
        assert top["signal"] == "moderate"  # measured: score 0.349, lead 0.061 over drug-induced lupus
        assert not any(c["full_name"].endswith(" 18") for c in d["conditions"])
        from_labs = {m["hpo_id"] for m in top["matched"] if m["labs"]}
        assert {"HP:0003493", "HP:0020151", "HP:0005421"} <= from_labs  # ANA, anti-dsDNA, low C3
        assert all(m["labs"] == 0 for m in top["matched"] if m["hpo_id"] == "HP:0025300")  # malar rash: notes only
        missing = {m["hpo_id"] for c in d["conditions"] for m in c["missing"]}
        assert "HP:0001903" not in missing  # her haemoglobin is low: anemia is recorded, not "typical, not recorded"
        # the demo stores one haemoglobin reading as a deliberate misread (1,1 for 11,0): unchecked, it does not count
        assert any(m["hpo_id"] == "HP:0001903" and m["labs"] == 1 for c in d["conditions"] for m in c["matched"])
        assert not {"HP:0011227", "HP:0003565", "HP:0045042"} & missing  # CRP, ESR and C4 were measured in range
        assert d["question"]["feature_id"] not in {"HP:0011227", "HP:0003565", "HP:0045042"}

        # the clinician rejects every ANA reading: the feature leaves the differential
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        for l in pkg["labs"]:
            if l["test_key"] == "ana":
                assert clinic.patch(f"/api/inbox/{pid}/labs/{l['id']}", json={"decision": "rejected"}).status_code == 200
        after = clinic.get(f"/api/inbox/{pid}/ddx").json()
        assert after["n_terms"] == d["n_terms"] - 1
        assert all(m["hpo_id"] != "HP:0003493" for c in after["conditions"] for m in c["matched"])

        # the clinician corrects the misread against the printed row: it now counts, with the printed value
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        hb = next(l for l in pkg["labs"] if l["test_key"] == "emoglobina" and l["needs_review"])
        assert hb["value_numeric"] == 1.1 and "implausible" in hb["checks"]
        r = clinic.patch(f"/api/inbox/{pid}/labs/{hb['id']}", json={"decision": "corrected", "value": "11,0"})
        assert r.status_code == 200, r.text
        assert r.json()["lab_fixes"][hb["id"]]["to"]["value_numeric"] == 11.0
        fixed = next(l for l in clinic.get(f"/api/inbox/{pid}").json()["labs"] if l["id"] == hb["id"])
        assert fixed["value_numeric"] == 11.0 and fixed["decision"] == "corrected" and fixed["flag"] == "low"
        assert fixed["corrected_from"]["value_numeric"] == 1.1
        corr = clinic.get(f"/api/inbox/{pid}/ddx").json()
        assert any(m["hpo_id"] == "HP:0001903" and m["labs"] == 2 for c in corr["conditions"] for m in c["matched"])

        it = clinic.get(f"/api/inbox/{pid}/ddx", params={"lang": "it"}).json()
        assert it["conditions"][0]["name"] == "Lupus eritematoso sistemico"
        labels = {m["label"] for m in it["conditions"][0]["matched"]}
        assert "C3 basso" in labels and "Anticorpi anti-DNA nativo positivi" in labels


def test_unsure_lab_rows_count_only_once_the_clinician_checked_them(unlocked, clinic_server, tmp_path):
    pid = shared_giulia_with_labs(unlocked, clinic_server, unsure_every=2)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        unsure = [l for l in pkg["labs"] if l["needs_review"] and l["test_key"] in ("ana", "antidsdna", "c3", "emoglobina")]
        assert unsure

        def lab_counts() -> dict:
            return {m["hpo_id"]: m["labs"] for c in clinic.get(f"/api/inbox/{pid}/ddx").json()["conditions"]
                    for m in c["matched"]}

        before = lab_counts()
        for l in unsure:  # an unchecked reading never feeds the ranking; confirming it does
            clinic.patch(f"/api/inbox/{pid}/labs/{l['id']}", json={"decision": "confirmed"})
        confirmed = lab_counts()
        assert sum(confirmed.values()) > sum(before.values())
        for l in unsure:
            clinic.patch(f"/api/inbox/{pid}/labs/{l['id']}", json={"decision": "rejected"})
        assert lab_counts() == before
        for l in unsure:  # undo: back to waiting, still out of the ranking
            clinic.patch(f"/api/inbox/{pid}/labs/{l['id']}", json={"decision": "pending"})
        assert lab_counts() == before


def test_lab_correction_is_validated(unlocked, clinic_server, tmp_path):
    pid = shared_giulia_with_labs(unlocked, clinic_server)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        na = next(l for l in pkg["labs"] if l["test_key"] == "sodio" and l["needs_review"])
        assert na["value_numeric"] == 141.0 and na["checks"] == ["not_on_page"]
        # the source: the printed row cut from the report page travels with the reading
        assert na["crop"] and na["crop"].startswith("data:image/jpeg;base64,")
        assert sum(len(l["crop"] or "") for l in pkg["labs"]) < 2_100_000
        url = f"/api/inbox/{pid}/labs/{na['id']}"
        assert clinic.patch(url, json={"decision": "corrected"}).status_code == 422  # nothing given
        assert clinic.patch(url, json={"decision": "corrected", "value": "141"}).status_code == 422  # same as read
        r = clinic.patch(url, json={"decision": "corrected", "value": "147", "unit": "mmol/L"})
        assert r.status_code == 200, r.text
        fixed = next(l for l in clinic.get(f"/api/inbox/{pid}").json()["labs"] if l["id"] == na["id"])
        assert fixed["value_numeric"] == 147.0 and fixed["flag"] == "high" and fixed["abnormal"]  # flag recomputed in code
        ov = clinic.get(f"/api/inbox/{pid}/overview").json()
        assert any(l["value"].startswith("147") for l in ov["labs_off"])
        assert clinic.patch(url, json={"decision": "pending"}).status_code == 200  # undo drops the fix
        back = next(l for l in clinic.get(f"/api/inbox/{pid}").json()["labs"] if l["id"] == na["id"])
        assert back["value_numeric"] == 141.0 and back["corrected_from"] is None
        assert clinic.get(f"/api/inbox/{pid}/decisions").json()["lab_fixes"] == {}
