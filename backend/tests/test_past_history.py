"""Past history end to end (issue #17): a note about the past ("knee surgery 5 years ago", "as a child I had asthma")
keeps the term, marked past and dated from the words, and the term is never a current finding: not in the patient's
timeline terms, not in the clinic glance's frequent/recent/new lists, not in the differential, listed under past
history in the overview and the brief."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from conftest import settings, sse, wait_extracted
from clario.app import create_app
from clario.brief import patient_view_items
from clario.models import SharePackage
from clario.extract import RawOut, ground
from clario.knowledge import Ontology

ONTO = Ontology.load()
ASTHMA = "HP:0002099"


def _day(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


NOTES_EN = [
    (3, "I remembered I had knee surgery 5 years ago. My knees ache today."),
    (2, "As a child I had asthma. Today I feel tired and my knees ache."),
    (1, "Two years ago my thyroid was removed. I am exhausted and my knees ache."),
]
NOTES_IT = [
    (3, "Mi sono ricordata che ho avuto un'operazione al ginocchio cinque anni fa. Oggi sono stanca."),
    (2, "Da bambina avevo l'asma. Oggi ho mal di testa."),
]


def _share(unlocked, clinic_server, notes):
    unlocked.post("/api/demo", json={"persona": "giulia"})  # enough current terms for a differential
    for days, text in notes:
        assert unlocked.post("/api/entries", json={"text": text, "occurred_on": _day(days)}).status_code == 200
    wait_extracted(unlocked)
    unlocked.get("/api/clinic/key", params={"url": clinic_server})
    r = unlocked.post("/api/share", json={"clinic_url": clinic_server, "since": _day(56), "until": _day(0)})
    assert r.status_code == 200, r.text
    return r.json()["package_id"]


def test_patient_side_keeps_past_terms_marked_and_out_of_the_timeline(unlocked):
    for days, text in NOTES_EN:
        unlocked.post("/api/entries", json={"text": text, "occurred_on": _day(days)})
    entries = wait_extracted(unlocked)
    ents = {x["quote"].lower(): x for e in entries for x in e["entities"]}
    surgery, asthma, thyroid = ents["knee surgery"], ents["asthma"], ents["thyroid was removed"]
    assert surgery["past"]["kind"] == "ago" and surgery["past"]["n"] == 5 and surgery["past"]["unit"] == "year"
    assert surgery["past"]["approx_date"] == f"{date.fromisoformat(_day(3)).year - 5}-01-01"
    assert surgery["onset_hint"] is None and "past_from_text" in surgery["flags"]  # "5 years ago" is not "since"
    assert asthma["past"]["kind"] == "childhood" and asthma["past"]["approx_date"] is None and asthma["onset_hint"] is None
    assert thyroid["past"]["n"] == 2
    assert ents["knees ache"]["past"] is None  # the next sentence is today
    tl = unlocked.get("/api/timeline").json()
    assert ASTHMA not in {t["hpo_id"] for t in tl["terms"]}
    assert all(ASTHMA not in {t["hpo_id"] for t in d["terms"]} for d in tl["days"])
    assert "HP:0002829" in {t["hpo_id"] for t in tl["terms"]}  # the current joint pain still counts


def test_clinic_glance_ddx_and_brief_treat_past_as_history(unlocked, clinic_server, tmp_path):
    pid = _share(unlocked, clinic_server, NOTES_EN)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        pkg = clinic.get(f"/api/inbox/{pid}").json()
        shared = {x["quote"].lower(): x for x in pkg["entities"]}
        assert shared["knee surgery"]["past"]["n"] == 5 and shared["asthma"]["past"]["kind"] == "childhood"

        ov = clinic.get(f"/api/inbox/{pid}/overview").json()
        current = {r["label"] for k in ("frequent", "recent") for r in ov[k]} | set(ov["new"]) | {ov["first"]["label"]}
        assert not current & {"knee surgery", "asthma", "thyroidectomy"}
        past = [(p["label"], p["when"]) for p in ov["past"]]
        assert past == [("asthma", "in childhood"),
                        ("knee surgery", f"about 5 years ago (around {date.fromisoformat(_day(3)).year - 5})"),
                        ("thyroidectomy", f"about 2 years ago (around {date.fromisoformat(_day(1)).year - 2})")]

        ddx = clinic.get(f"/api/inbox/{pid}/ddx").json()
        assert ddx["conditions"], ddx["note"]
        assert all(ASTHMA not in {m["hpo_id"] for m in c["matched"]} for c in ddx["conditions"])

        rid = clinic.post(f"/api/inbox/{pid}/brief").json()["run_id"]
        assert sse(clinic, rid)[-1]["stage"] == "done"
        brief = clinic.get(f"/api/inbox/{pid}/brief").json()
        lines = [i["text"] for i in brief["items"] if i["origin"] == "patient"]
        assert any(t.startswith("Past history: Asthma (HP:0002099): mentioned") and "in childhood" in t for t in lines), lines
        assert any(t.startswith("Past history: Knee surgery: mentioned") and "about 5 years ago" in t for t in lines), lines
        assert not any(t.startswith("Asthma") for t in lines)

        mine = [i.text for i in patient_view_items(SharePackage.model_validate(pkg), "en", ONTO)]
        assert any(t.startswith("Past: knee surgery (about 5 years ago, ") for t in mine), mine
        assert any(t.startswith("Past: asthma (in childhood, ") for t in mine), mine


def test_italian_notes(unlocked, clinic_server, tmp_path):
    pid = _share(unlocked, clinic_server, NOTES_IT)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        ov = clinic.get(f"/api/inbox/{pid}/overview", params={"lang": "it"}).json()
        whens = {p["quote"]: p["when"] for p in ov["past"]}
        assert whens["l'asma"] == "nell'infanzia"
        assert whens["operazione al ginocchio"].startswith("circa 5 anni fa")
        ddx = clinic.get(f"/api/inbox/{pid}/ddx").json()
        assert all(ASTHMA not in {m["hpo_id"] for m in c["matched"]} for c in ddx["conditions"])


def test_onset_since_two_years_is_a_current_term_not_history():
    text = "I have had asthma since two years. As a child I had asthma too."
    raw = RawOut.model_validate({"entities": [{"quote": "asthma since two years", "canonical": "Asthma", "hpo_id": ASTHMA,
                                               "onset_hint": "since two years"}]})
    e = ground("e1", text, raw, ONTO, "m", note_date="2026-10-12")[0]
    assert e.past is None and e.onset_hint == "since two years"
    raw = RawOut.model_validate({"entities": [{"quote": "Da due anni", "canonical": "Asthma", "hpo_id": ASTHMA}]})
    assert ground("e1", "Da due anni ho l'asma.", raw, ONTO, "m", note_date="2026-10-12")[0].past is None


def test_negated_or_relative_is_never_past():
    raw = RawOut.model_validate({"entities": [{"quote": "asthma", "canonical": "Asthma", "hpo_id": ASTHMA}]})
    e = ground("e1", "My mother had asthma as a child.", raw, ONTO, "m", note_date="2026-10-12")[0]
    assert e.family_history and e.past is None
