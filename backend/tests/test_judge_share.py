"""Family history and negated terms never leave as patient terms; lab rows reach the clinic; counts agree."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from clario.app import create_app
from clario.models import Entity, Entry, LabResult
from clario.share import build_package, counts, patient_mentions, shared_labs
from conftest import confirm_all, settings, sse, wait_extracted
from test_italian import load_it


def share_body(url, **kw):
    today = date.today()
    return {"clinic_url": url, "since": (today - timedelta(days=90)).isoformat(), "until": today.isoformat(),
            "note": "Domanda per la visita", **kw}


def ent(i, canonical, hpo, **kw):
    return Entity(id=f"x{i}", entry_id="e1", type="finding", quote=canonical, canonical=canonical, hpo_id=hpo,
                  review="confirmed", **kw)


def test_family_history_is_shared_only_as_family_history_and_never_counted():
    e = Entry(id="e1", created_at="2026-10-01T00:00:00Z", occurred_on="2026-10-01", text="Mia madre ha il lupus", entities=[
        ent(1, "Systemic lupus erythematosus", "HP:0002725", family_history=True),
        ent(2, "Fever", "HP:0001945", negated=True),
        ent(3, "Arthralgia", "HP:0002829"),
        Entity(id="x4", entry_id="e1", type="symptom", quote="q", canonical="Fatigue", hpo_id="HP:0012378", review="needs_review")])
    pkg = build_package([e], "2026-09-01", "2026-10-31", "Ash-001", None, [], 1)
    fam = [x for x in pkg.entities if x.family_history]
    assert len(fam) == 1 and fam[0].hpo_id is None  # no ontology id: a consumer cannot count it as the patient's term
    assert all(x.hpo_id is None for en in pkg.entries for x in en.entities if x.family_history)
    assert {x.canonical for x in patient_mentions(pkg.entities)} == {"Arthralgia", "Fatigue"}
    assert counts(pkg) == {"entities": 2, "mentions": 2, "terms": 2, "labs": 0}
    fat = next(x for x in pkg.entities if x.canonical == "Fatigue")  # unsure terms leave flagged for the clinician
    assert fat.needs_review and not fat.reviewed and fat.id == "x4"


def test_italian_persona_lupus_never_reaches_the_clinic_as_a_patient_term(unlocked, clinic_server, tmp_path):
    load_it(unlocked)
    confirm_all(unlocked)  # even a person confirming the relative's line does not make it a patient term
    r = unlocked.post("/api/share", json=share_body(clinic_server))
    assert r.status_code == 200, r.text
    sh = r.json()
    pid = sh["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        lupus = [x for x in pkg["entities"] if "lupus" in x["canonical"].lower()]
        assert lupus and all(x["family_history"] and x["hpo_id"] is None for x in lupus)
        present = [x for x in pkg["entities"] if not x["negated"] and not x["family_history"]]
        assert not any("lupus" in x["canonical"].lower() for x in present)
        row = clinic.get("/api/inbox").json()[0]
        assert row["entities"] == len(present) and row["terms"] == len({x["hpo_id"] or x["canonical"].lower() for x in present})
        assert (sh["entities"], sh["terms"]) == (row["entities"], row["terms"])  # patient share screen and clinic agree
        events = sse(clinic, clinic.post(f"/api/inbox/{pid}/brief", params={"lang": "it"}).json()["run_id"])
        texts = [i["text"] for i in events[-1]["payload"]["items"]]
        assert any(t.startswith("Storia familiare:") and "lupus" in t.lower() for t in texts)


def lab(i, name, value, review="confirmed", day="2026-10-01", page=1, **kw):
    return LabResult(id=f"l{i}", batch_id="b1", test_name=name, test_key=name.lower(), value_numeric=value, unit="mg/dL",
                     ref_low=0, ref_high=200, flag="high", date=day, page=page, review=review, **kw)


def test_shared_labs_are_confirmed_or_marked_and_in_the_period():
    rows = [lab(1, "Cholesterol", 264), lab(2, "Glucose", 90, review="auto"), lab(3, "Ferritin", 5, review="needs_review"),
            lab(4, "Sodium", 140, review="rejected"), lab(5, "Old", 1, day="2025-01-01"), lab(6, "Fixed", 2, review="corrected")]
    got = shared_labs(rows, "2026-09-01", "2026-10-31", {"b1": "e9"})
    by = {l.test_name: l for l in got}
    assert set(by) == {"Cholesterol", "Glucose", "Ferritin", "Fixed"}  # rejected and out-of-period rows never leave
    assert by["Cholesterol"].reviewed and by["Fixed"].reviewed and not by["Glucose"].reviewed
    assert by["Ferritin"].needs_review and not by["Glucose"].needs_review  # the clinician is asked to check unsure rows
    assert by["Cholesterol"].entry_id == "e9" and by["Cholesterol"].page == 1 and by["Cholesterol"].ref_high == 200


def test_labs_reach_the_clinic_and_the_brief_cites_them(unlocked, clinic_server, tmp_path):
    unlocked.post("/api/entries", json={"text": "Knees ache. Tired. Rash on my cheeks."})
    wait_extracted(unlocked)
    confirm_all(unlocked)
    bid = unlocked.post("/api/demo/documents").json()["batch_id"]  # one tap: dates land in the diary's weeks
    with unlocked.stream("GET", f"/api/documents/batch/{bid}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and '"done": true' in line:
                break
    for it in unlocked.get("/api/review").json()["items"]:
        if it["kind"] == "lab":
            unlocked.post(f"/api/review/lab/{it['id']}", json={"action": "confirm"})
    sh = unlocked.post("/api/share", json=share_body(clinic_server)).json()
    assert sh["labs"] >= 10
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{sh['package_id']}").json()
        assert len(pkg["labs"]) == sh["labs"]
        first = pkg["labs"][0]
        assert {"test_name", "unit", "ref_low", "ref_high", "flag", "date", "page", "reviewed"} <= set(first)
        entry_ids = {e["id"] for e in pkg["entries"]}
        assert all(l["entry_id"] in entry_ids for l in pkg["labs"])
        events = sse(clinic, clinic.post(f"/api/inbox/{sh['package_id']}/brief").json()["run_id"])
        labs = [i for i in events[-1]["payload"]["items"] if i["section"] == "labs" and i["origin"] == "document"]
        tests = [i for i in labs if i["id"] != "bi_lab_in_range"]
        assert len(tests) >= 3 and all(i["pages"] and i["review"] in ("accepted", "pending") for i in tests)  # from the report, cited by page
        assert any("page" in i["text"] and "printed range" in i["text"] for i in tests)
        assert not any(" to  " in i["text"] or i["text"].count("2026-") for i in labs)  # dates localized, no empty range end


def test_demo_referti_latest_date_is_pinned():
    from clario.demo import REFERTI_LATEST, demo_referti
    from clario.documents import file_pages
    from clario.fixtures import OfflineLLM
    import json as _json

    best = ''
    for f in demo_referti():
        for p in file_pages(f.name, f.read_bytes()):
            off = getattr(p, 'offline', None)
            if off:
                best = max(best, off['date'])
    assert best == REFERTI_LATEST.isoformat()


def test_citation_mismatch_flags_a_term_no_cited_entry_confirms():
    from clario.brief import DraftItem, DraftOut, check_ai_items

    e1 = Entry(id="e1", created_at="x", occurred_on="2026-10-01", text="Knees ache", entities=[ent(1, "Arthralgia", "HP:0002829")])
    e2 = Entry(id="e2", created_at="x", occurred_on="2026-10-02", text="Tired", entities=[
        Entity(id="x9", entry_id="e2", type="symptom", quote="Tired", canonical="Fatigue", hpo_id="HP:0012378", review="confirmed")])
    pkg = build_package([e1, e2], "2026-09-01", "2026-10-31", "Ash-001", None, [], 1)
    draft = DraftOut(items=[
        DraftItem(section="timeline", text="2026-10-01: fatigue first noted.", cites=["e1"]),  # e1 has no fatigue
        DraftItem(section="timeline", text="2026-10-02: fatigue noted.", cites=["e2"]),
        DraftItem(section="timeline", text="2026-10-01: arthralgia noted, fatigue later.", cites=["e1", "e2"])])
    out = check_ai_items(pkg, draft)
    assert [i.flag for i in out] == ["citation_mismatch", None, None]
    assert all(i.review == "pending" for i in out)  # flagged or not, a clinician decides


def test_demo_brief_wrong_line_is_flagged_and_stays_out_of_the_patient_copy(unlocked, clinic_server, tmp_path):
    unlocked.post("/api/demo", json={"persona": "giulia"})
    wait_extracted(unlocked)
    confirm_all(unlocked)
    today = date.today()
    body = {"clinic_url": clinic_server, "since": (today - timedelta(days=56)).isoformat(), "until": today.isoformat()}
    pid = unlocked.post("/api/share", json=body).json()["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        events = sse(clinic, clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"])
        items = events[-1]["payload"]["items"]
        bad = [i for i in items if i["flag"] == "citation_mismatch"]
        assert len(bad) == 1 and "fatigue first noted" in bad[0]["text"] and bad[0]["review"] == "pending"
        good = [i for i in items if i["origin"] == "ai" and not i["flag"]]
        assert any("fatigue noted" in i["text"] for i in good)  # the correct dated line passes the check
        for i in items:
            if i["origin"] == "ai":
                r = "rejected" if i["flag"] else "accepted"
                assert clinic.patch(f"/api/brief-items/{pid}/{i['id']}", json={"review": r}).status_code == 200
        assert clinic.post(f"/api/inbox/{pid}/brief/finalize").json()["finalized"] is True
        md = clinic.get(f"/api/inbox/{pid}/brief.md").text
        assert "fatigue first noted" not in md
