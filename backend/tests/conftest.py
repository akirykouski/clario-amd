import json
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from clario.app import create_app
from clario.config import Settings

PASS = "correct horse battery staple"


def settings(tmp_path, mode="patient", **kw):
    return Settings.from_env(mode=mode, offline=True, data_dir=tmp_path / mode, frontend_dist=None, **kw)


@pytest.fixture
def patient(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as c:
        yield c


@pytest.fixture
def unlocked(patient):
    assert patient.post("/api/vault/setup", json={"passphrase": PASS}).status_code == 200
    return patient


def wait_extracted(client, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        es = client.get("/api/entries").json()
        if es and all(e["extraction"] != "pending" for e in es):
            return es
        time.sleep(0.05)
    raise AssertionError("extraction did not finish")


def demo_referti_with_unsure(client, every: int = 6) -> str:
    """Import the demo referti (precomputed rows, all confident, as the live read gave) and mark every `every`-th row as
    a low-confidence reading, the way an unsure OCR row arrives, so tests can exercise the clinician's lab check."""
    bid = client.post("/api/demo/documents").json()["batch_id"]
    vault = client.app.state.vault
    rows = sorted((d for d in vault.all("lab") if d["batch_id"] == bid), key=lambda d: (d["page"], d["test_name"]))
    for i, d in enumerate(rows):
        if i % every == every - 1:
            vault.put("lab", d["id"], {**d, "confidence": 0.55, "review": "needs_review"})
    return bid


def confirm_all(client):
    for e in client.get("/api/entries").json():
        for x in e["entities"]:
            client.patch(f"/api/entities/{x['id']}", json={"review": "confirmed"})


def sse(client, rid):
    out = []
    with client.stream("GET", f"/api/runs/{rid}/events") as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                ev = json.loads(line[5:].strip())
                out.append(ev)
                if ev["stage"] in ("done", "error"):
                    break
    return out


@pytest.fixture
def clinic_server(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(settings(tmp_path, "clinic"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def sign_brief(clinic, pid, clinician="Dr Test", **params):
    """Sign the brief as drafted: the draft text unchanged, so every AI line counts as accepted."""
    text = clinic.get(f"/api/inbox/{pid}/brief/text", params=params).json()["text"]
    return clinic.post(f"/api/inbox/{pid}/brief/sign", json={"text": text, "clinician": clinician, **params})
