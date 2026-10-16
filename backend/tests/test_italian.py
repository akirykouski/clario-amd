"""Italian persona, server-side wording in Italian, and the brief for two audiences."""

import json
import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from clario.app import create_app
from clario.demo import GIULIA, GIULIA_IT, persona_entries
from clario.i18n import hpo_it, lay_it
from clario.knowledge import Ontology
from clario.safety import hedge_problems
from conftest import confirm_all, settings, sse, wait_extracted
from test_integration import import_demo_pdfs


def entities(client):
    return [x for e in client.get("/api/entries").json() for x in e["entities"]]


def load_it(client):
    assert client.post("/api/demo", json={"persona": "giulia_it"}).json()["lang"] == "it"
    wait_extracted(client)


def test_persona_has_the_required_texture():
    assert len(GIULIA_IT) == len(GIULIA)
    text = " ".join(t for _, t, _ in GIULIA_IT).lower()
    for needle in ("niente febbre", "mia madre ha il lupus", "6/10", "da lunedì"):
        assert needle in text
    assert persona_entries("giulia_it")[0][0] == (date.today() - timedelta(days=70)).isoformat()
    assert not re.search(r"[—!]", text)


def test_italian_persona_negation_family_onset_severity(unlocked):
    load_it(unlocked)
    xs = entities(unlocked)
    fever_no = [x for x in xs if x["hpo_id"] == "HP:0001945" and x["negated"]]
    assert fever_no and fever_no[0]["quote"].lower() == "febbre"
    fam = [x for x in xs if x["family_history"]]
    assert fam and "lupus" in fam[0]["quote"].lower()
    assert any(x["severity"] == 6 for x in xs) and any(x["onset_hint"] == "da lunedì" for x in xs)
    # hedged sentences ("Forse", "Mi sembra") wait in the queue
    q = unlocked.get("/api/review").json()
    assert q["count"] >= 2 and {i["kind"] for i in q["items"]} == {"entity"}


def test_family_history_and_negation_never_count_toward_patterns(unlocked):
    load_it(unlocked)
    confirm_all(unlocked)
    tl = unlocked.get("/api/timeline").json()
    ids = {t["hpo_id"] for t in tl["terms"]}
    assert "HP:0001945" in ids  # one present fever note ("un po' di febbre") counts, the negated one does not
    fever = next(t for t in tl["terms"] if t["hpo_id"] == "HP:0001945")
    assert fever["count"] == 1
    assert not any("lupus" in t["label"].lower() for t in tl["terms"])
    pats = unlocked.get("/api/patterns", params={"lang": "it"}).json()
    assert pats["patterns"] and "Non è una diagnosi" in pats["note"]
    top = pats["patterns"][0]
    assert "lupus" not in json.dumps(pats, ensure_ascii=False).lower()  # condition names are clinician-only
    assert re.search(r"[a-z]", top["neutral_label"]) and "rash" not in top["neutral_label"].lower()
    assert any("farfalla" in p["neutral_label"].lower() for p in pats["patterns"])
    malar = next(m for m in top["matched"] if m["hpo_id"] == "HP:0025300")  # which term sorts first depends on note counts
    assert malar["label"] == "Arrossamento a farfalla sul viso" and malar["clinical"] == "Malar rash"
    en = unlocked.get("/api/patterns").json()
    assert "red rash" in en["patterns"][0]["neutral_label"].lower() and en["note"].startswith("Patterns worth")
    assert "lupus" not in json.dumps(en).lower()


def test_next_question_and_answer_entry_in_italian(unlocked):
    load_it(unlocked)
    confirm_all(unlocked)
    for it in unlocked.get("/api/review").json()["items"]:
        unlocked.post(f"/api/review/{it['kind']}/{it['id']}", json={"action": "confirm"})
    q = unlocked.get("/api/patterns/next-question", params={"lang": "it"}).json()
    assert q and q["question"].startswith("Ti capita di avere") and q["feature_id"] in lay_it()
    assert "pattern" not in q["why"].lower() and "potrebbe" in q["why"].lower()
    r = unlocked.post("/api/patterns/answer", json={"feature_id": q["feature_id"], "answer": "no",
                                                    "question": q["question"], "lang": "it"}).json()
    e = unlocked.get(f"/api/entries/{r['entry_id']}").json()
    assert e["text"] == f"Risposta a una domanda: {q['question']} No"
    assert e["entities"][0]["review"] == "confirmed" and e["entities"][0]["negated"] is True
    r = unlocked.post("/api/patterns/answer", json={"feature_id": q["feature_id"], "answer": "yes", "lang": "it"}).json()
    assert unlocked.get(f"/api/entries/{r['entry_id']}").json()["text"].endswith(" Sì")


def test_entry_safety_message_follows_the_language(unlocked):
    r = unlocked.post("/api/entries", json={"text": "Non riesco a respirare", "lang": "it"}).json()
    assert r["safety"]["level"] == "emergency" and "emergenza" in r["safety"]["message"]
    r = unlocked.post("/api/entries", json={"text": "Can't breathe", "lang": "en"}).json()
    assert "emergency" in r["safety"]["message"]


def test_demo_referti_are_one_tap(unlocked):
    r = unlocked.post("/api/demo/documents")
    assert r.status_code == 200 and r.json()["pages"] == 3
    bid = r.json()["batch_id"]
    with unlocked.stream("GET", f"/api/documents/batch/{bid}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and '"done": true' in line:
                break
    assert unlocked.get("/api/labs").json()["n_results"] > 20


def test_translation_tables_point_at_real_terms():
    onto = Ontology.load()
    assert len(hpo_it()) >= 50
    for hid, label in {**hpo_it(), **lay_it()}.items():
        assert onto.exists(hid) and label.strip() and label == label.strip(), hid
    for label in list(hpo_it().values()) + list(lay_it().values()):
        assert "—" not in label and "!" not in label
    assert set(lay_it()) <= set(hpo_it())


def test_italian_hedge_validator():
    assert hedge_problems("Quello che hai annotato somiglia ad alcune caratteristiche tipiche. Potrebbe valere la pena parlarne.") == []
    assert hedge_problems("Soffre di lupus. Iniziare 200 mg di idrossiclorochina.")
    assert hedge_problems("La diagnosi è confermata.")
    assert "no hedging language" in hedge_problems("Il tuo medico ti vedrà giovedì.")


# ------------------------------------------------------------ brief audiences
def share_it(unlocked, clinic_server):
    load_it(unlocked)
    confirm_all(unlocked)
    for it in unlocked.get("/api/review").json()["items"]:
        unlocked.post(f"/api/review/{it['kind']}/{it['id']}", json={"action": "confirm"})
    today = date.today()
    body = {"clinic_url": clinic_server, "since": (today - timedelta(days=90)).isoformat(), "until": today.isoformat(),
            "note": "Il dolore alle articolazioni e l'eruzione sono collegati?"}
    r = unlocked.post("/api/share", json=body)
    assert r.status_code == 200, r.text
    return r.json()["package_id"]


def test_brief_for_two_audiences_and_two_languages(unlocked, clinic_server, tmp_path):
    pid = share_it(unlocked, clinic_server)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        ev = sse(clinic, clinic.post(f"/api/inbox/{pid}/brief", params={"lang": "it"}).json()["run_id"])
        assert ev[-1]["stage"] == "done", ev[-1]
        b = clinic.get(f"/api/inbox/{pid}/brief").json()
        assert b["lang"] == "it" and b["audience"] == "clinician"
        texts = " ".join(i["text"] for i in b["items"])
        assert "Soffre di lupus" not in texts and "200 mg" not in texts and "senza fonte" not in texts  # guardrails, Italian
        ai = [i for i in b["items"] if i["origin"] == "ai"]
        assert any(i["section"] == "patterns" for i in ai), "Italian hedged pattern note must survive the validator"
        # clinician copy: clinical terms and HPO ids, severity and onset, family history marked
        assert "HP:0002829" in texts and "gravità fino a 6/10" in texts and "esordio: da lunedì" in texts
        assert any(i["text"].startswith("Storia familiare:") for i in b["items"])
        assert any("registrato" in i["text"] for i in b["items"])
        # clinician copy in English from the same package
        en = clinic.get(f"/api/inbox/{pid}/brief", params={"audience": "clinician", "lang": "en"}).json()
        assert en["lang"] == "en" and any("recorded" in i["text"] and "HP:0002829" in i["text"] for i in en["items"])
        assert any(i["text"].startswith("Family history:") for i in en["items"])
        # patient copy only after the clinician finalized
        assert clinic.get(f"/api/inbox/{pid}/brief", params={"audience": "patient"}).status_code == 409
        assert clinic.get(f"/api/inbox/{pid}/brief", params={"audience": "nobody"}).status_code == 422
        for i in ai:
            assert clinic.patch(f"/api/brief-items/{pid}/{i['id']}", json={"review": "accepted"}).status_code == 200
        assert clinic.post(f"/api/inbox/{pid}/brief/finalize").json()["finalized"] is True
        p = clinic.get(f"/api/inbox/{pid}/brief", params={"audience": "patient", "lang": "it"}).json()
        ptext = " ".join(i["text"] for i in p["items"])
        assert p["audience"] == "patient" and p["lang"] == "it" and p["items"]
        assert "HP:" not in ptext and "lupus" not in ptext.lower() and "Systemic" not in ptext
        assert "hai scritto" in ptext and any(i["kind"] == "patient_note" for i in p["items"])
        assert "Hai scritto di una condizione che ha un tuo parente" in ptext
        assert "Stanchezza" in ptext and "Arrossamento a farfalla" in ptext
        assert not any(i["origin"] == "ai" and i["section"] == "patterns" for i in p["items"])
        assert all(i["review"] in ("accepted", "edited") for i in p["items"])
        # wrong language for the AI items: they are left out of the patient copy, never shown untranslated
        pe = clinic.get(f"/api/inbox/{pid}/brief", params={"audience": "patient", "lang": "en"}).json()
        assert not any(i["origin"] == "ai" for i in pe["items"]) and "HP:" not in " ".join(i["text"] for i in pe["items"])
        md = clinic.get(f"/api/inbox/{pid}/brief.md", params={"audience": "patient", "lang": "it"}).text
        assert md.startswith("# Il tuo riepilogo") and "Non è una diagnosi" in md and "HP:" not in md
        mdc = clinic.get(f"/api/inbox/{pid}/brief.md").text
        assert mdc.startswith("# Riepilogo clinico") and "HP:0002829" in mdc and "bozza IA, rivista" in mdc
