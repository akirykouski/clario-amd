import asyncio

from fastapi.testclient import TestClient

from clario import doc_routes
from clario.app import Runs, create_app
from clario.demo import demo_referti
from conftest import PASS, settings
from test_documents import events, upload


def test_finished_runs_are_dropped_after_the_ttl_and_running_ones_are_kept():
    async def go():
        runs = Runs(ttl=0.0)
        finished, running = runs.new(), runs.new()
        await runs.emit(finished, "done", "ok", 1.0)
        await runs.emit(running, "draft", "working", 0.5)
        await asyncio.sleep(0.01)
        fresh = runs.new()  # a new run sweeps
        assert finished not in runs.runs and {running, fresh} <= set(runs.runs)

    asyncio.run(go())


def test_finished_batches_are_dropped_after_the_ttl(tmp_path, monkeypatch):
    pdf = demo_referti()[:1]
    monkeypatch.setattr(doc_routes, "FINISHED_TTL", 0.0)
    with TestClient(create_app(settings(tmp_path))) as c:
        c.post("/api/vault/setup", json={"passphrase": PASS})
        first = upload(c, pdf).json()["batch_id"]
        assert events(c, first)[-1]["done"]
        second = upload(c, pdf).json()["batch_id"]  # starting a batch sweeps the finished one
        assert c.get(f"/api/documents/batch/{first}/events").status_code == 404
        assert events(c, second)[-1]["done"]
