"""Seams between the lanes: labs in the shared review queue, one extraction prompt, dosing interceptor,
encryption at rest in clinic mode, privacy wrapper coverage."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clario import extract
from clario.app import create_app
from clario.models import Entity, Entry
from clario.safety import check_entry
from clario.share import ClinicKeys, build_package, seal
from conftest import PASS, settings, sse, wait_extracted

ROOT = Path(__file__).resolve().parents[2]
DEMO = Path(__file__).resolve().parents[1] / "clario" / "data" / "demo"


# ------------------------------------------------------------ labs in the review queue
def import_demo_pdfs(client):
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in sorted(DEMO.glob("*.pdf"))]
    r = client.post("/api/documents/batch", files=files)
    assert r.status_code == 200, r.text
    bid = r.json()["batch_id"]
    with client.stream("GET", f"/api/documents/batch/{bid}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and '"done": true' in line:
                break


def test_lab_rows_wait_in_the_shared_queue_and_are_logged(unlocked):
    import_demo_pdfs(unlocked)
    labs = unlocked.get("/api/labs").json()
    q = unlocked.get("/api/review").json()
    items = [i for i in q["items"] if i["kind"] == "lab"]
    assert items and len(items) == labs["needs_review"] and q["count"] == len(q["items"])
    first = items[0]
    assert first["display"] and first["page"] >= 1 and first["confidence"] < 0.7
    n = q["count"]
    r = unlocked.post(f"/api/review/lab/{first['id']}", json={"action": "confirm"})
    assert r.json() == {"ok": True, "count": n - 1}
    # correct one with an Italian decimal, reject another
    second = items[1]
    r = unlocked.post(f"/api/review/lab/{second['id']}", json={"action": "correct", "value": "5,5"})
    assert r.status_code == 200
    row = next(v for t in unlocked.get("/api/labs").json()["tests"] for v in t["values"] if v["id"] == second["id"])
    assert row["review"] == "corrected" and row["value_numeric"] == 5.5
    assert unlocked.post(f"/api/review/lab/{second['id']}", json={"action": "correct"}).status_code == 422
    if len(items) > 2:
        assert unlocked.post(f"/api/review/lab/{items[2]['id']}", json={"action": "reject"}).status_code == 200
    assert unlocked.post("/api/review/lab/nope", json={"action": "confirm"}).status_code == 404
    log = unlocked.app.state.vault.all("correction_log")
    lab_log = [x for x in log if x["kind"] == "lab"]
    assert {x["action"] for x in lab_log} >= {"confirm", "correct"}
    corrected = next(x for x in lab_log if x["action"] == "correct")
    assert corrected["before"]["review"] == "needs_review" and corrected["after"]["value_numeric"] == 5.5


def test_queue_mixes_entities_and_labs(unlocked):
    unlocked.post("/api/entries", json={"text": "Maybe my knees ache a bit. Tired."})
    wait_extracted(unlocked)
    import_demo_pdfs(unlocked)
    kinds = {i["kind"] for i in unlocked.get("/api/review").json()["items"]}
    assert kinds == {"entity", "lab"}


def test_vault_survives_concurrent_threads(tmp_path):
    """The API serves sync routes from a thread pool over one sqlite connection (extraction writes while the UI reads)."""
    import threading

    from clario.vault import Vault

    v = Vault(tmp_path / "v")
    v.setup(PASS)
    errors: list[Exception] = []

    def work(n: int) -> None:
        try:
            for i in range(150):
                v.put("entry", f"e{n}_{i}", {"n": n, "i": i})
                assert len(v.all("entry")) >= 1
                assert v.get(f"e{n}_{i}")["i"] == i
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == [] and len(v.all("entry")) == 8 * 150


# ------------------------------------------------------------ one prompt for app and training
def test_app_prompt_is_the_training_prompt():
    sys.path.insert(0, str(ROOT / "train"))
    import importlib

    train_prompt = importlib.import_module("prompt")
    assert (ROOT / "train" / "prompt.py").read_bytes() == (ROOT / "backend" / "clario" / "prompt.py").read_bytes(), \
        "clario/prompt.py must be a verbatim copy of train/prompt.py: cp train/prompt.py backend/clario/prompt.py"
    for text in ("Knees ache 6/10. Niente febbre.", "  padded diary  ", "Mia madre ha il lupus."):
        assert extract.messages_for(text) == train_prompt.build_messages(text)
        assert extract.messages_for(text, True) == train_prompt.build_messages(text, confidence=True)
    msgs = extract.messages_for("x")
    assert [m["role"] for m in msgs] == ["system", "user"]  # no few-shot: training had none


# ------------------------------------------------------------ dosing / medication interceptor
DOSING_EN = ["Can I take more ibuprofen today?", "should I stop my pills", "Is it safe to take paracetamol with this?",
             "How much ibuprofen should I take?", "I am pregnant, is it ok to take ibuprofen?", "Can I double my dose",
             "Could I skip my steroid tomorrow?"]
DOSING_IT = ["Posso aumentare la dose?", "smetto di prendere le pastiglie?", "E se smetto il cortisone",
             "Sono incinta, posso prendere il paracetamolo?", "Devo smettere di prendere l'ibuprofene",
             "Dovrei ridurre la dose di cortisone?"]
MENTIONS = ["I took ibuprofen for my knees, it helped", "Pregnant 10 weeks, very tired", "Can I take the tram without pain?",
            "Took paracetamol 500 mg at night, slept badly", "Taking my pills every morning. Knees ache.",
            "ho preso l'ibuprofene e il mal di testa è passato", "Ho smesso di prendere il cortisone mesi fa.",
            "Sono incinta di dieci settimane, molto stanca."]


@pytest.mark.parametrize("text", DOSING_EN)
def test_dosing_questions_en(text):
    n = check_entry(text, "en")
    assert n and n.level == "advice" and "pharmacist" in n.message


@pytest.mark.parametrize("text", DOSING_IT)
def test_dosing_questions_it(text):
    n = check_entry(text, "it")
    assert n and n.level == "advice" and "farmacista" in n.message


@pytest.mark.parametrize("text", MENTIONS)
def test_notes_that_mention_a_medicine_are_not_blocked(text):
    assert check_entry(text, "en") is None and check_entry(text, "it") is None


def test_dosing_entry_is_saved_but_never_reaches_a_model(unlocked):
    r = unlocked.post("/api/entries", json={"text": "Can I take more ibuprofen? Knees ache.", "lang": "en"}).json()
    assert r["safety"]["level"] == "advice" and r["entry"]["extraction"] == "done" and r["entry"]["entities"] == []
    assert unlocked.get("/api/privacy/calls").json() == []  # no model call was logged
    r = unlocked.post("/api/entries", json={"text": "Posso aumentare la dose?", "lang": "it"}).json()
    assert "farmacista" in r["safety"]["message"]
    ok = unlocked.post("/api/entries", json={"text": "Took ibuprofen, knees ache.", "lang": "en"}).json()
    assert ok["safety"] is None and ok["entry"]["extraction"] == "pending"


def test_emergency_notice_in_italian():
    n = check_entry("Ho dolore al petto e sudo, mi manca il respiro", "it")
    assert n and n.level == "emergency" and "112" in n.message and "emergenza" in n.message


# ------------------------------------------------------------ clinic data at rest
PHRASE = "Unmistakable zebra phrase: my knees ache"


def test_clinic_files_hold_no_diary_text(tmp_path):
    s = settings(tmp_path, "clinic")
    with TestClient(create_app(s)) as clinic:
        key = clinic.get("/api/clinic/key").json()["public_key"]
        e = Entry(id="e_1", created_at="2026-10-01T00:00:00+00:00", occurred_on="2026-10-01", text=PHRASE, extraction="done",
                  entities=[Entity(id="x1", entry_id="e_1", type="symptom", quote="knees ache", canonical="Arthralgia",
                                   hpo_id="HP:0002829", review="confirmed")])
        pkg = build_package([e], "2026-09-01", "2026-10-31", "Ash-001", None, [], 24)
        assert clinic.post("/api/inbox", json={"package_id": pkg.package_id, "sealed": seal(pkg, key)}).status_code == 200
        rid = clinic.post(f"/api/inbox/{pkg.package_id}/brief").json()["run_id"]
        assert sse(clinic, rid)[-1]["stage"] == "done"
        assert clinic.get(f"/api/inbox/{pkg.package_id}/brief").json()["items"]  # still readable through the API
        assert clinic.get("/api/privacy/calls").json()[0]["redacted_preview"]  # decrypted for the clinic
    files = [p for p in s.data_dir.rglob("*") if p.is_file()]
    assert any(p.parent.name == "briefs" for p in files) and any(p.name == "ai_calls.jsonl" for p in files)
    for p in files:
        raw = p.read_bytes()
        assert b"zebra" not in raw and b"Arthralgia" not in raw, p.name
    # a second process with the same key still opens the brief
    with TestClient(create_app(s)) as again:
        assert again.get(f"/api/inbox/{pkg.package_id}/brief").status_code == 200


def test_clinic_data_key_is_stable_and_private(tmp_path):
    a, b = ClinicKeys(tmp_path / "a"), ClinicKeys(tmp_path / "a")
    blob = a.seal_data(b"hello")
    assert b.open_data(blob) == b"hello" and b"hello" not in blob
    with pytest.raises(Exception):
        ClinicKeys(tmp_path / "other").open_data(blob)


# ------------------------------------------------------------ privacy wrapper on every path
def test_every_llm_path_is_logged_and_semaphore_reaches_the_client(unlocked):
    unlocked.post("/api/demo", json={"persona": "giulia"})
    wait_extracted(unlocked)
    for e in unlocked.get("/api/entries").json():
        for x in e["entities"]:
            unlocked.patch(f"/api/entities/{x['id']}", json={"review": "confirmed"})
    assert unlocked.get("/api/patterns").status_code == 200
    q = unlocked.get("/api/patterns/next-question").json()
    assert q is not None
    import_demo_pdfs(unlocked)
    purposes = {c["purpose"] for c in unlocked.get("/api/privacy/calls", params={"limit": 500}).json()}
    assert {"extract", "next_question", "document"} <= purposes
    assert "rationale" not in purposes  # no condition name is ever sent to a model for the patient
    assert unlocked.get("/api/privacy/verify").json()["ok"]
