"""The demo persona's brief draft: precomputed (generated live once, data/demo/LABELS.md) for the unchanged package,
live for anything else and for "Regenerate live"."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import settings, sse, wait_extracted
from clario.app import create_app
from clario.demo_brief import BRIEFS_FILE

pytestmark = pytest.mark.skipif(not BRIEFS_FILE.exists(), reason="no precomputed demo briefs shipped")


def share(client, url, **kw):
    today = date.today()
    body = {"clinic_url": url, "since": (today - timedelta(days=84)).isoformat(), "until": today.isoformat(), "note": None,
            "include_patterns": True, "include_profile": True, **kw}
    r = client.post("/api/share", json=body)
    assert r.status_code == 200, r.text
    return r.json()["package_id"]


def draft(clinic, pid, **params):
    r = clinic.post(f"/api/inbox/{pid}/brief", params=params).json()
    return r, sse(clinic, r["run_id"])[-1]


def load(client, persona):
    client.post("/api/demo", json={"persona": persona})
    wait_extracted(client)
    assert client.post("/api/demo/documents").status_code == 200


@pytest.mark.parametrize("persona,lang,second_opinion", [("giulia", "en", False), ("giulia_it", "it", False), ("giulia", "en", True)])
def test_demo_package_gets_the_precomputed_draft(unlocked, clinic_server, tmp_path, persona, lang, second_opinion):
    load(unlocked, persona)
    pid = share(unlocked, clinic_server, second_opinion=second_opinion)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        r, done = draft(clinic, pid, lang=lang)
        assert r["precomputed"] is True and done["stage"] == "done"
        b = done["payload"]
        assert b["precomputed"] and b["model"] == "Gemma-4-31B-IT" and b["backend"] == "amd-token-factory"
        assert b["pseudonymized"] is True and b["stats"]["tokens_per_s"] > 0 and b["stats"]["latency_ms"] > 0
        assert done["tokens_per_s"] == b["stats"]["tokens_per_s"] and done["precomputed"] == b["precomputed"]
        ai = [i for i in b["items"] if i["origin"] == "ai"]
        entries = {e["id"] for e in clinic.get(f"/api/inbox/{pid}").json()["entries"]}
        assert ai and all(i["review"] == "pending" for i in ai)
        assert all(set(i["cites"]) <= entries for i in ai)  # positions mapped to this package's entry ids
        assert not any("day " in i["text"] or "giorno " in i["text"] for i in ai)  # day numbers back to dates
        assert clinic.get(f"/api/inbox/{pid}/brief").json()["precomputed"] == b["precomputed"]

        # "Regenerate live" calls the model (offline fixtures here), and the brief no longer says precomputed
        r, done = draft(clinic, pid, lang=lang, live="true")
        assert r["precomputed"] is False and done["stage"] == "done"
        assert done["payload"]["precomputed"] is None and done["payload"]["backend"] == "offline-fixtures"


def test_changed_demo_package_goes_live(unlocked, clinic_server, tmp_path):
    load(unlocked, "giulia")
    other_question = share(unlocked, clinic_server, note="Is the joint pain and rash connected?")
    r = unlocked.post("/api/entries", json={"text": "Fever again today and a new mouth ulcer.", "lang": "en"})
    assert r.status_code == 200
    wait_extracted(unlocked)
    own_note = share(unlocked, clinic_server)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as clinic:
        for pid in (other_question, own_note):
            r, done = draft(clinic, pid)
            assert r["precomputed"] is False and done["payload"]["precomputed"] is None
            assert done["payload"]["backend"] == "offline-fixtures"
