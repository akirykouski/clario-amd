import json

import pytest
from fastapi.testclient import TestClient

from conftest import PASS, settings, sse, wait_extracted
from clario import privacy
from clario.app import create_app
from clario.extract import extract, messages_for
from clario.knowledge import Ontology
from clario.llm import LLM, Stats
from clario.models import Entry
from clario.share import build_package, seal
from clario.vault import Vault

CASES = {
    "email": "giulia.rossi@example.com",
    "phone": "+39 345 678 9012",
    "codice_fiscale": "RSSGLI95M45F205X",
    "iban": "IT60 X054 2811 1010 0000 0123 456",
    "date": "12/03/2026",
    "address": "Via Garibaldi 12",
    "name": "Giulia",
}


@pytest.mark.parametrize("typ,value", CASES.items())
def test_every_pii_type_is_replaced(typ, value):
    text = f"Note: {value} was written down. Knees ache 6/10."
    red, reps = privacy.pseudonymize(text)
    assert value not in red
    assert privacy.PLACEHOLDER[typ] in red
    assert [r["type"] for r in reps] == [typ]
    assert value not in json.dumps(reps), "replacements must not carry the original value"
    r = reps[0]
    assert text[r["start"]:r["end"]] == value
    assert red[r["out_start"]:r["out_end"]] == privacy.PLACEHOLDER[typ]
    assert "Knees ache 6/10" in red


@pytest.mark.parametrize("phone", ["0039 02 1234567", "+44 20 7946 0958", "345 678 9012", "02 1234567", "(+1) 415-555-0132"])
def test_phone_formats(phone):
    red, _ = privacy.pseudonymize(f"call {phone} today")
    assert "[PHONE]" in red and not any(c.isdigit() for c in red)


@pytest.mark.parametrize("d", ["2026-03-12", "12-03-26", "12 March 2026", "March 12th", "3 marzo 2026", "12 Mar."])
def test_date_formats(d):
    red, reps = privacy.pseudonymize(f"seen on {d} at the clinic")
    assert red == "seen on [DATE] at the clinic" or red.startswith("seen on [DATE]"), red
    assert reps and reps[0]["type"] == "date"


def test_mixed_text_and_overlaps():
    text = ("Dr. Bianchi said call Marco on 345 678 9012 or mail marco@x.it. He lives in Viale Monza 5, "
            "bank IT60X0542811101000000123456, CF RSSMRA85T10A562S.")
    red, reps = privacy.pseudonymize(text)
    for leaked in ["Bianchi", "Marco", "345", "marco@x.it", "Monza", "IT60", "RSSMRA"]:
        assert leaked not in red, (leaked, red)
    assert {r["type"] for r in reps} == {"name", "phone", "email", "address", "iban", "codice_fiscale"}


@pytest.mark.parametrize("text", [
    "I have lupus and my TSH 4.8 is high",
    "Taking 200 mg hydroxychloroquine twice a day",
    "Knees ache 6/10, no fever, 37.9 in the evening",
    "Platelets 350, CRP 12.5 mg/L, ANA 1:320, white cells 3.1 x10^9/L",
    "Malar rash, Raynaud phenomenon, oral ulcer, proteinuria 0.5 g/day",
    "Sore in my mouth again. It is the third one this month. Arthralgia in 2 joints.",
    "Rheumatology appointment on Thursday, in March it got worse",
])
def test_medical_terms_untouched(text):
    red, reps = privacy.pseudonymize(text)
    assert red == text and reps == []


def test_names_file_size():
    names = privacy._NAMES_FILE.read_text().split()
    assert 250 <= len(names) <= 400


# ---------------------------------------------------------------- grounding survives redaction
class SeesRedacted(LLM):
    """Fake model: records the text it was sent and quotes spans copied from it, like a real model would."""

    backend, model = "fake-remote", "fake-1"

    def __init__(self, quotes):
        super().__init__()
        self.quotes, self.seen = quotes, []

    async def _complete(self, task, messages, json_mode, max_tokens, payload):
        self.seen.append(messages[-1]["content"])
        ents = [{"quote": q, "canonical": c, "hpo_id": h, "type": "symptom", "negated": False, "severity": None}
                for q, c, h in self.quotes]
        return json.dumps({"entities": ents}), Stats(self.backend, self.model)


async def test_extraction_grounds_on_a_redacted_entry(tmp_path):
    text = ("On 12/03/2026 Giulia called me from Via Garibaldi 12. Giulia's knees ache 6/10 "
            "and the rash on my cheeks is back. Write to giulia@example.com.")
    fake = SeesRedacted([("knees ache", "Arthralgia", "HP:0002829"),
                         ("rash on my cheeks", "Malar rash", "HP:0025300"),
                         ("[NAME]'s knees ache", "Arthralgia", "HP:0002829"),  # model copied a placeholder
                         ("[DATE] [NAME] called", "Fever", "HP:0001945")])  # spans two placeholders
    log = privacy.CallLog(privacy.FileStore(tmp_path / "log.jsonl"))
    llm = privacy.PrivacyLLM(fake, log, True)
    ents, _ = await extract(llm, "e1", text, Ontology.load())

    sent = fake.seen[0]
    for leaked in ["Giulia", "12/03/2026", "Garibaldi", "giulia@example.com"]:
        assert leaked not in sent
    assert "knees ache 6/10" in sent  # medical content went through
    assert ents, "entities must survive"
    for e in ents:
        assert e.quote in text, e.quote  # every quote is verbatim from the ORIGINAL text
        assert "[" not in e.quote
    quotes = {e.quote for e in ents}
    assert "rash on my cheeks" in quotes
    assert "Giulia's knees ache" in quotes  # placeholder quote restored from the in-memory map
    assert "12/03/2026 Giulia called" in quotes
    assert log.verify()["ok"] and all(c["purpose"] == "extract" and c["redacted"] is True for c in log.calls())


async def test_local_backend_is_not_redacted_but_still_logged(tmp_path):
    text = "Giulia: knees ache"
    fake = SeesRedacted([("knees ache", "Arthralgia", "HP:0002829")])
    log = privacy.CallLog(privacy.FileStore(tmp_path / "log.jsonl"))
    await extract(privacy.PrivacyLLM(fake, log, False), "e1", text, Ontology.load())
    assert fake.seen[0] == text
    rec = log.calls()[-1]  # oldest: the extraction call itself
    assert rec["redacted"] is False and "Giulia" not in rec["redacted_preview"]  # preview is always redacted
    assert rec["payload_sha256"] == privacy.sha256(json.dumps(
        [{"role": m["role"], "content": m["content"]} for m in
         messages_for(text)],ensure_ascii=False, sort_keys=True))


# ---------------------------------------------------------------- hash chain
def _fill(log, n=4):
    for i in range(n):
        log.append(backend="b", model="m", purpose="extract", preview=f"p{i}", sent_text=f"text {i}")


def test_chain_verifies_and_links(tmp_path):
    log = privacy.CallLog(privacy.FileStore(tmp_path / "l.jsonl"))
    assert log.verify() == {"ok": True, "broken_at": None, "count": 0}
    _fill(log)
    assert log.verify()["ok"]
    recs = log.store.records()
    assert recs[0]["prev_hash"] == privacy.GENESIS
    assert all(b["prev_hash"] == a["hash"] for a, b in zip(recs, recs[1:]))
    assert [c["id"] for c in log.calls(2)] == ["call_000004", "call_000003"]


@pytest.mark.parametrize("field,value", [("backend", "evil"), ("payload_sha256", "0" * 64), ("ts", "2020-01-01T00:00:00.000+00:00"),
                                         ("model", "other"), ("purpose", "brief")])
def test_tampering_a_file_record_breaks_verify(tmp_path, field, value):
    path = tmp_path / "l.jsonl"
    log = privacy.CallLog(privacy.FileStore(path))
    _fill(log)
    lines = path.read_text().splitlines()
    rec = json.loads(lines[1])
    rec[field] = value
    lines[1] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n")
    assert log.verify() == {"ok": False, "broken_at": "call_000002", "count": 4}


def test_removed_or_reordered_record_breaks_verify(tmp_path):
    path = tmp_path / "l.jsonl"
    log = privacy.CallLog(privacy.FileStore(path))
    _fill(log)
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:1] + lines[2:]) + "\n")
    assert log.verify()["broken_at"] == "call_000003"


def test_vault_store_tamper_detected(tmp_path):
    v = Vault(tmp_path)
    v.setup(PASS)
    log = privacy.CallLog(privacy.VaultStore(v))
    _fill(log)
    assert log.verify()["ok"]
    rec = v.get("call_000003")
    v.put("ai_call", "call_000003", rec | {"model": "swapped"})
    assert log.verify() == {"ok": False, "broken_at": "call_000003", "count": 4}


def test_calls_while_locked_are_chained_later(tmp_path):
    v = Vault(tmp_path)
    v.setup(PASS)
    log = privacy.CallLog(privacy.VaultStore(v))
    _fill(log, 1)
    v.lock()
    _fill(log, 1)  # vault locked: held in memory
    v.unlock(PASS)
    _fill(log, 1)
    assert [c["seq"] for c in log.calls()] == [3, 2, 1] and log.verify()["ok"]


# ---------------------------------------------------------------- app level
def test_settings_default(tmp_path):
    base = dict(offline=False, data_dir=tmp_path, frontend_dist=None)
    from clario.config import Settings

    assert privacy.should_pseudonymize(Settings.from_env(mode="patient", llm_base_url="https://amd.example/v1", **base))
    assert not privacy.should_pseudonymize(Settings.from_env(mode="patient", llm_base_url="http://localhost:11434/v1", **base))
    assert not privacy.should_pseudonymize(Settings.from_env(mode="clinic", llm_base_url="https://amd.example/v1", **base))
    assert privacy.should_pseudonymize(Settings.from_env(mode="patient", pseudonymize=True, llm_base_url="http://localhost:1/v1", **base))
    assert not privacy.should_pseudonymize(Settings.from_env(mode="patient", pseudonymize=False, llm_base_url="https://x/v1", **base))


@pytest.fixture
def remote_patient(tmp_path):
    with TestClient(create_app(settings(tmp_path, pseudonymize=True))) as c:
        assert c.post("/api/vault/setup", json={"passphrase": PASS}).status_code == 200
        yield c


def test_patient_flow_logs_redacts_and_previews(remote_patient):
    c = remote_patient
    assert c.get("/api/health").json()["llm"]["pseudonymize"] is True
    text = "Giulia here, 12/03/2026. My knees ache 6/10 and the rash on my cheeks came back. Mail giulia@example.com"
    eid = c.post("/api/entries", json={"text": text}).json()["entry"]["id"]
    e = wait_extracted(c)[0]
    assert e["extraction"] == "done" and e["entities"]
    assert all(x["quote"] in text for x in e["entities"])

    calls = c.get("/api/privacy/calls").json()
    first = calls[-1]  # extraction may add self-consistency and HPO-pick calls; all are logged
    assert all(x["purpose"] == "extract" and x["redacted"] is True for x in calls)
    assert first["replacements"] == 3 and first["backend"] == "offline-fixtures"
    assert "[NAME]" in first["redacted_preview"] and "Giulia" not in json.dumps(calls)
    assert c.get("/api/privacy/verify").json() == {"ok": True, "broken_at": None, "count": len(calls)}

    p = c.get("/api/privacy/preview", params={"entry_id": eid}).json()
    assert p["original"] == text and p["applied"] is True
    assert "Giulia" not in p["redacted"] and "knees ache 6/10" in p["redacted"]
    assert {r["type"] for r in p["replacements"]} == {"name", "date", "email"}
    assert c.get("/api/privacy/preview", params={"entry_id": "nope"}).status_code == 404

    # re-run adds a second link; the log never stores the raw text
    assert c.post(f"/api/entries/{eid}/extract").status_code == 200
    assert c.get("/api/privacy/verify").json()["count"] > len(calls)
    raw = json.dumps(c.get("/api/privacy/calls?limit=1").json())
    assert "giulia@example.com" not in raw


def test_log_is_vault_encrypted_and_locked_returns_423(remote_patient):
    c = remote_patient
    c.post("/api/entries", json={"text": "Giulia knees ache"})
    wait_extracted(c)
    c.post("/api/vault/lock")
    assert c.get("/api/privacy/calls").status_code == 423
    assert c.get("/api/privacy/verify").status_code == 423


def test_local_default_leaves_text_alone_but_logs(unlocked):
    # offline fixtures count as local: no redaction, still one logged call per extraction
    unlocked.post("/api/entries", json={"text": "Giulia knees ache"})
    wait_extracted(unlocked)
    calls = unlocked.get("/api/privacy/calls").json()
    assert calls and all(x["redacted"] is False for x in calls) and calls[-1]["redacted_preview"].startswith("[NAME]")


def test_clinic_keeps_its_own_log(tmp_path):
    from clario.models import Entry as E

    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        assert clinic.get("/api/privacy/verify").json()["ok"] is True
        assert clinic.get("/api/privacy/preview", params={"entry_id": "x"}).status_code in (404, 405)
        key = clinic.get("/api/clinic/key").json()["public_key"]
        entry = E(id="e_1", created_at="2026-03-01T00:00:00+00:00", occurred_on="2026-03-01", text="Knees ache, tired")
        pkg = build_package([entry], "2026-01-01", "2026-12-31", "Ash-001", None, [], 24)
        assert clinic.post("/api/inbox", json={"package_id": pkg.package_id, "sealed": seal(pkg, key)}).status_code == 200
        rid = clinic.post(f"/api/inbox/{pkg.package_id}/brief").json()["run_id"]
        assert sse(clinic, rid)[-1]["stage"] == "done"
        calls = clinic.get("/api/privacy/calls").json()
        assert [c["purpose"] for c in calls] == ["brief"] and calls[0]["redacted"] is False
        assert clinic.get("/api/privacy/verify").json()["ok"] is True
    assert (tmp_path / "clinic" / "ai_calls.jsonl").exists()
