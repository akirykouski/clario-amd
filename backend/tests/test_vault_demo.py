"""Demo server: "Skip for the demo" opens the vault with a passphrase the server keeps (CLARIO_DEMO_PASSPHRASE)."""
from fastapi.testclient import TestClient

from clario.app import create_app

from conftest import PASS, settings

DEMO = "demo vault passphrase 42"


def client(tmp_path, **kw):
    return TestClient(create_app(settings(tmp_path, **kw)))


def test_off_unless_demo_server_with_a_passphrase(tmp_path):
    for kw in ({}, {"demo_instance": True}, {"demo_passphrase": DEMO}):
        with client(tmp_path / str(len(kw)), **kw) as c:
            assert c.get("/api/vault").json()["demo_open"] is False
            assert c.post("/api/vault/demo").status_code == 404


def test_sets_up_then_unlocks_and_never_reveals_the_passphrase(tmp_path):
    with client(tmp_path, demo_instance=True, demo_passphrase=DEMO) as c:
        state = c.get("/api/vault").json()
        assert state == {"initialized": False, "locked": True, "demo_open": True}
        assert DEMO not in c.get("/api/vault").text and DEMO not in c.get("/api/health").text
        assert c.post("/api/vault/demo").json() == {"ok": True}
        assert c.get("/api/entries").status_code == 200
        c.post("/api/vault/lock")
        assert c.get("/api/entries").status_code == 423
        assert c.post("/api/vault/demo").json() == {"ok": True}
        assert c.get("/api/entries").status_code == 200
        c.post("/api/vault/lock")
        assert c.post("/api/vault/unlock", json={"passphrase": DEMO}).status_code == 200  # the same vault, typed


def test_a_diary_made_with_another_passphrase_stays_shut(tmp_path):
    with client(tmp_path, demo_instance=True, demo_passphrase=DEMO) as c:
        assert c.post("/api/vault/setup", json={"passphrase": PASS}).status_code == 200
        c.post("/api/vault/lock")
        assert c.post("/api/vault/demo").status_code == 409
        assert c.get("/api/entries").status_code == 423
