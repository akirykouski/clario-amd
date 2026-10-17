"""Second opinion (#20): facts travel, the previous doctor's conclusions stay hidden until the new doctor signs."""

import json
from datetime import date, timedelta

from fastapi.testclient import TestClient

from conftest import settings, sse, wait_extracted
from clario import brief as briefing
from clario.app import create_app
from clario.demo import DEMO_DIR, persona_care
from clario.models import Brief, BriefItem, Condition, PriorOpinion, SharePackage
from clario.second_opinion import compare, facts_only

PREVIOUS_WORDS = ("fibromyalg", "fibromialg", "stress-related", "rheumatoid", "autoimmune tests not needed")


def share_body(url, **kw):
    today = date.today()
    return {"clinic_url": url, "since": (today - timedelta(days=84)).isoformat(), "until": today.isoformat(), **kw}


def giulia(unlocked, persona="giulia", referti=True):
    unlocked.post("/api/demo", json={"persona": persona})
    if referti:
        unlocked.post("/api/demo/documents")
    wait_extracted(unlocked)


def hidden(blob) -> bool:
    text = json.dumps(blob, ensure_ascii=False).lower()
    return not any(w in text for w in PREVIOUS_WORDS)


def finalize(clinic, pid):
    clinic.post(f"/api/inbox/{pid}/labs/decide", json={"decision": "confirmed"})
    events = sse(clinic, clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"])
    assert events[-1]["stage"] == "done", events[-1]
    ai = [i for i in events[-1]["payload"]["items"] if i["origin"] == "ai"]
    for k, it in enumerate(ai):
        clinic.patch(f"/api/brief-items/{pid}/{it['id']}", json={"review": "rejected" if k == 0 else "accepted"})
    r = clinic.post(f"/api/inbox/{pid}/brief/finalize")
    assert r.status_code == 200, r.text
    return ai


def test_demo_care_is_dated_like_the_diary_and_the_patient_never_sees_the_conclusions(unlocked):
    giulia(unlocked, referti=False)
    care = unlocked.get("/api/care").json()
    today = date.today()
    nsaid = care["tried"][0]
    assert "NSAID" in nsaid["treatment"] and nsaid["effect"] == "none" and nsaid["duration"] == "2 weeks"
    assert nsaid["started"] == (today - timedelta(days=47)).isoformat()
    assert any(t["abnormal"] for t in care["tested"]) and all("date" in t for t in care["tested"])
    assert care["previous"] == {"clinician": "GP", "date": (today - timedelta(days=47)).isoformat()}
    assert hidden(care)  # the patient screens never show a condition name


def test_english_and_italian_care_say_the_same_thing():
    en, it = (json.loads((DEMO_DIR / f"giulia_care_{l}.json").read_text()) for l in ("en", "it"))
    for k in ("tried", "tested"):
        assert [{f: x[f] for f in x if f in ("days_ago", "effect", "abnormal")} for x in en[k]] == \
               [{f: x[f] for f in x if f in ("days_ago", "effect", "abnormal")} for x in it[k]]
    for k in ("diagnosis", "conditions"):
        assert [c["disease_id"] for c in en["previous"][k]] == [c["disease_id"] for c in it["previous"][k]]
    assert len(en["previous"]["accepted"]) == len(it["previous"]["accepted"])
    assert len(en["previous"]["rejected"]) == len(it["previous"]["rejected"])
    assert persona_care("giulia_it")["tried"][0]["treatment"].startswith("Ibuprofene")


def test_a_normal_share_carries_the_facts_but_never_the_previous_opinion(unlocked, clinic_server, tmp_path):
    giulia(unlocked, referti=False)
    r = unlocked.post("/api/share", json=share_body(clinic_server))
    assert r.status_code == 200, r.text
    assert r.json()["second_opinion"] is False and r.json()["tried"] == 2 and r.json()["tested"] == 5
    pid = r.json()["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        assert pkg["second_opinion"] is False and pkg["previous"] is None
        assert [t["effect"] for t in pkg["tried"]] == ["none", "none"]
        assert clinic.get(f"/api/inbox/{pid}/compare").status_code == 404


def test_second_opinion_hides_the_conclusions_until_signed_then_compares(unlocked, clinic_server, tmp_path):
    giulia(unlocked)
    plain = unlocked.post("/api/share", json=share_body(clinic_server)).json()["package_id"]
    r = unlocked.post("/api/share", json=share_body(clinic_server, second_opinion=True))
    assert r.status_code == 200, r.text
    pid = r.json()["package_id"]
    assert r.json()["second_opinion"] is True
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        row = next(x for x in clinic.get("/api/inbox").json() if x["package_id"] == pid)
        assert row["second_opinion"] is True
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        assert pkg["second_opinion"] is True and pkg["previous"] is None
        # facts: what was tried and with what effect, what was tested
        assert any("NSAID" in t["treatment"] and t["effect"] == "none" for t in pkg["tried"])
        assert any(t["test"] == "Urine test" and t["abnormal"] for t in pkg["tested"])
        # conclusions: nowhere in what the new doctor or the brief model sees
        assert hidden(pkg)
        assert hidden(clinic.get(f"/api/inbox/{pid}/overview").json())
        ddx = clinic.get(f"/api/inbox/{pid}/ddx").json()
        assert hidden(ddx)
        assert hidden(briefing.model_input(SharePackage.model_validate(pkg)))
        assert "Ibuprofen" in briefing.model_input(SharePackage.model_validate(pkg))  # the facts do reach the brief model
        # the ranking is computed in code from the facts: SLE on top, the same as without a previous opinion
        assert ddx["conditions"][0]["disease_id"] == "ORPHA:536"
        assert [c["disease_id"] for c in ddx["conditions"]] == \
               [c["disease_id"] for c in clinic.get(f"/api/inbox/{plain}/ddx").json()["conditions"]]

        r = clinic.get(f"/api/inbox/{pid}/compare")
        assert r.status_code == 409  # not before this doctor has signed
        finalize(clinic, pid)
        cmp = clinic.get(f"/api/inbox/{pid}/compare").json()
        assert [c["name"] for c in cmp["previous"]["diagnosis"]] == ["Fibromyalgia", "Stress-related fatigue"]
        assert cmp["previous"]["notes"].startswith("Most likely stress")
        rows = {r["name"]: r for r in cmp["rows"]}
        assert rows["Fibromyalgia"] == {"name": "Fibromyalgia", "disease_id": None, "previous": "diagnosis",
                                        "current_rank": None, "agree": False}
        assert rows["Rheumatoid arthritis"]["previous"] == "considered" and not rows["Rheumatoid arthritis"]["agree"]
        sle = rows["Systemic lupus erythematosus"]
        assert sle["previous"] is None and sle["current_rank"] == 1 and not sle["agree"]
        assert cmp["disagreements"] == len(cmp["rows"])  # the two opinions share no condition
        assert cmp["current"]["conditions"][0]["disease_id"] == "ORPHA:536"
        assert len(cmp["current"]["rejected"]) == 1 and cmp["current"]["accepted"]
        # what the previous doctor could not have seen: terms first noted after the visit, abnormal tests after it
        assert "Fever" in cmp["since_previous"] and "Urine test: Protein present" in cmp["since_previous"]
        assert "Fatigue" not in cmp["since_previous"]  # noted before the visit
        # the package page itself still carries facts only
        assert clinic.get(f"/api/inbox/{pid}").json()["previous"] is None


def test_second_opinion_in_italian(unlocked, clinic_server, tmp_path):
    giulia(unlocked, "giulia_it")
    pid = unlocked.post("/api/share", json=share_body(clinic_server, second_opinion=True)).json()["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        assert pkg["tried"][0]["treatment"].startswith("Ibuprofene") and hidden(pkg)
        finalize(clinic, pid)
        cmp = clinic.get(f"/api/inbox/{pid}/compare", params={"lang": "it"}).json()
        assert cmp["previous"]["clinician"] == "Medico di base"
        assert cmp["rows"][0]["name"] == "Fibromialgia" and cmp["current"]["conditions"][0]["disease_id"] == "ORPHA:536"


def test_second_opinion_without_a_previous_opinion_on_file(unlocked, clinic_server, tmp_path):
    giulia(unlocked, referti=False)
    unlocked.app.state.vault.delete("care")
    pid = unlocked.post("/api/share", json=share_body(clinic_server, second_opinion=True)).json()["package_id"]
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        assert pkg["second_opinion"] is True and pkg["tried"] == [] and pkg["previous"] is None
        finalize(clinic, pid)
        assert clinic.get(f"/api/inbox/{pid}/compare").json()["previous"] is None


def cond(did, name, rank):
    return Condition(disease_id=did, name=name, signal=None, score=0.3, rank=rank, matched=[])


def test_compare_matches_by_id_then_by_name_and_counts_disagreements():
    prev = PriorOpinion(clinician="GP", date="2026-01-01",
                        diagnosis=[{"name": "Systemic lupus erythematosus 18"}],
                        conditions=[{"name": "Rheumatoid arthritis", "disease_id": "OMIM:180300"},
                                    {"name": "Systemic lupus erythematosus"}])
    b = Brief(package_id="pkg_x", items=[BriefItem(id="a", section="summary", text="ok", review="accepted"),
                                         BriefItem(id="b", section="summary", text="no", review="rejected"),
                                         BriefItem(id="c", section="summary", text="fact", origin="patient", review="accepted")])
    out = compare(prev, [cond("ORPHA:536", "Systemic lupus erythematosus", 1), cond("OMIM:180300", "RA", 2),
                         cond("ORPHA:809", "Mixed connective tissue disease", 3)], b, [])
    rows = {r["name"]: r for r in out["rows"]}
    assert rows["Systemic lupus erythematosus 18"]["agree"] and rows["Systemic lupus erythematosus 18"]["current_rank"] == 1
    assert rows["Rheumatoid arthritis"]["agree"] and rows["Rheumatoid arthritis"]["current_rank"] == 2
    assert len(out["rows"]) == 3  # the diagnosis is not listed again as "considered"
    assert rows["Mixed connective tissue disease"] == {"name": "Mixed connective tissue disease", "disease_id": "ORPHA:809",
                                                       "previous": None, "current_rank": 3, "agree": False}
    assert out["disagreements"] == 1
    assert out["current"]["accepted"] == ["ok"] and out["current"]["rejected"] == ["no"]


def test_facts_only_drops_just_the_conclusions():
    pkg = SharePackage(package_id="pkg_x", patient_alias="A", created_at="x", expires_at="x", period=("a", "b"),
                       entries=[], entities=[], second_opinion=True, tried=[{"treatment": "Ibuprofen", "effect": "none"}],
                       previous=PriorOpinion(clinician="GP", diagnosis=[{"name": "Fibromyalgia"}]))
    out = facts_only(pkg)
    assert out.previous is None and out.tried == pkg.tried and out.second_opinion and pkg.previous is not None
