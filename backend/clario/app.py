"""FastAPI app. CLARIO_MODE=patient (on the patient's device) or clinic (on the clinic's AMD server)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import brief as briefing
from . import gpu as gpumetrics
from . import share as sharing
from .config import Settings
from .demo import giulia_entries
from .extract import extract
from .knowledge import Ontology
from .llm import extract_json, make_llm
from .models import Brief, Entity, Entry, ShareRequest, SharePackage
from .patterns import evidence_from, explain, score_patterns
from .safety import check_entry
from .vault import BadPassphrase, Locked, Vault

log = logging.getLogger("clario")
BENCH_DIR = Path(__file__).resolve().parents[2] / "bench" / "results"


class Passphrase(BaseModel):
    passphrase: str


class EntryIn(BaseModel):
    text: str
    occurred_on: str | None = None
    mood: int | None = None


class EntityPatch(BaseModel):
    status: str | None = None
    canonical: str | None = None
    hpo_id: str | None = None
    severity: int | None = None
    negated: bool | None = None


class DemoIn(BaseModel):
    persona: str = "giulia"


class InboxIn(BaseModel):
    package_id: str
    sealed: str


class ReviewIn(BaseModel):
    review: str
    text: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- run bus (SSE)
class Runs:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}

    def new(self) -> str:
        rid = f"run_{uuid.uuid4().hex[:10]}"
        self.runs[rid] = {"events": [], "cond": asyncio.Condition(), "done": False}
        return rid

    async def emit(self, rid: str, stage: str, message: str, progress: float = 0.0, **kw: Any) -> None:
        r = self.runs[rid]
        async with r["cond"]:
            r["events"].append({"stage": stage, "message": message, "progress": round(progress, 3), **kw})
            r["done"] = r["done"] or stage in ("done", "error")
            r["cond"].notify_all()

    async def stream(self, rid: str):
        r, i = self.runs[rid], 0
        while True:
            async with r["cond"]:
                while i >= len(r["events"]) and not r["done"]:
                    await r["cond"].wait()
                batch, done = r["events"][i:], r["done"]
            for ev in batch:
                yield {"data": json.dumps(ev)}
            i += len(batch)
            if done and i >= len(r["events"]):
                return


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    onto = Ontology.load()
    llm = make_llm(s)
    runs = Runs()
    tasks: set[asyncio.Task] = set()
    app = FastAPI(title=f"Clario ({s.mode})")
    app.state.settings = s

    def spawn(coro) -> None:
        t = asyncio.create_task(coro)
        tasks.add(t)
        t.add_done_callback(tasks.discard)

    @app.get("/api/health")
    def health() -> dict:
        out = {"ok": True, "mode": s.mode, "ontology": {"terms": onto.n_terms, "diseases": onto.n_diseases},
               "llm": {"backend": llm.backend, "model": llm.model, "base_url_host": s.llm_host, "is_amd": llm.is_amd},
               "demo_instance": s.demo_instance}
        if s.mode == "patient":
            out["locked"] = vault.locked
        return out

    @app.get("/api/system/gpu")
    async def system_gpu():
        """GPU summary {gpu_name, util_pct, vram_used_gb, vram_total_gb}, or null when there is no telemetry."""
        if s.gpu_metrics_url:
            try:
                async with httpx.AsyncClient(timeout=4) as c:
                    r = await c.get(s.gpu_metrics_url)
                    r.raise_for_status()
                    return JSONResponse(r.json())
            except (httpx.HTTPError, ValueError):
                return JSONResponse(None)
        return JSONResponse(await asyncio.to_thread(gpumetrics.read_cached))

    @app.get("/api/runs/{rid}/events")
    async def run_events(rid: str):
        if rid not in runs.runs:
            raise HTTPException(404, "run not found")
        return EventSourceResponse(runs.stream(rid), ping=10)

    @app.exception_handler(Locked)
    async def locked_handler(_r: Request, _e: Locked):
        return JSONResponse({"detail": "Diary is locked"}, status_code=423)

    if s.mode == "patient":
        vault = Vault(s.data_dir, s.auto_lock_minutes)
        _patient_routes(app, s, vault, onto, llm, spawn)
    else:
        keys = sharing.ClinicKeys(s.data_dir)
        _clinic_routes(app, s, keys, llm, runs, spawn)

    @app.get("/api/bench")
    def bench() -> list[dict]:
        out = []
        for f in sorted(BENCH_DIR.glob("*.json")) if BENCH_DIR.exists() else []:
            with contextlib.suppress(Exception):
                out.append(json.loads(f.read_text()) | {"file": f.name})
        return out

    dist = s.frontend_dist
    if dist and (dist / "index.html").exists():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


# ====================================================================== patient
def _patient_routes(app: FastAPI, s: Settings, vault: Vault, onto: Ontology, llm, spawn) -> None:
    pattern_cache: dict[str, Any] = {}

    def load(eid: str) -> Entry:
        doc = vault.get(eid)
        if not doc:
            raise HTTPException(404, "entry not found")
        return Entry.model_validate(doc)

    def save(e: Entry) -> Entry:
        vault.put("entry", e.id, e.model_dump(mode="json"))
        return e

    def all_entries() -> list[Entry]:
        return sorted((Entry.model_validate(d) for d in vault.all("entry")),
                      key=lambda e: (e.occurred_on, e.created_at), reverse=True)

    async def run_extraction(eid: str) -> Entry | None:
        try:
            e = load(eid)
        except Locked:
            return None
        try:
            ents, _st = await extract(llm, e.id, e.text, onto)
        except Exception as err:  # noqa: BLE001 - recorded as failed, retried on demand
            log.warning("extraction failed for %s: %s", eid, err)
            ents, status = [], "failed"
        else:
            status = "done"
        with contextlib.suppress(Locked):
            cur = load(eid)  # entities confirmed meanwhile are kept
            keep = [x for x in cur.entities if x.status != "suggested"]
            cur.entities = keep + [x for x in ents if (x.hpo_id, x.quote.lower()) not in
                                   {(k.hpo_id, k.quote.lower()) for k in keep}]
            cur.extraction = status
            return save(cur)
        return None

    @app.get("/api/vault")
    def vault_state():
        return {"initialized": vault.initialized, "locked": vault.locked}

    @app.post("/api/vault/setup")
    def vault_setup(body: Passphrase):
        try:
            vault.setup(body.passphrase)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"ok": True}

    @app.post("/api/vault/unlock")
    def vault_unlock(body: Passphrase):
        try:
            vault.unlock(body.passphrase)
        except BadPassphrase:
            raise HTTPException(401, "That passphrase does not open this diary")
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"ok": True}

    @app.post("/api/vault/lock")
    def vault_lock():
        vault.lock()
        return {"ok": True}

    @app.get("/api/entries")
    def list_entries(since: str | None = None, until: str | None = None) -> list[Entry]:
        return [e for e in all_entries() if (not since or e.occurred_on >= since) and (not until or e.occurred_on <= until)]

    @app.post("/api/entries")
    async def add_entry(body: EntryIn):
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "Write something first")
        if len(text) > 5000:
            raise HTTPException(422, "Entries are limited to 5,000 characters")
        notice = check_entry(text)
        e = save(Entry(id=f"e_{uuid.uuid4().hex[:10]}", created_at=now_iso(),
                       occurred_on=body.occurred_on or date.today().isoformat(), text=text,
                       mood=body.mood if body.mood is None or 0 <= body.mood <= 10 else None))
        spawn(run_extraction(e.id))
        return {"entry": e, "safety": notice.as_dict() if notice else None}

    @app.get("/api/entries/{eid}")
    def get_entry(eid: str) -> Entry:
        return load(eid)

    @app.delete("/api/entries/{eid}")
    def delete_entry(eid: str):
        load(eid)
        vault.delete(eid)
        return {"ok": True}

    @app.post("/api/entries/{eid}/extract")
    async def re_extract(eid: str) -> Entry:
        load(eid)
        e = await run_extraction(eid)
        if e is None:
            raise Locked()
        return e

    @app.patch("/api/entities/{ent_id}")
    def patch_entity(ent_id: str, body: EntityPatch) -> Entity:
        for e in all_entries():
            for i, x in enumerate(e.entities):
                if x.id != ent_id:
                    continue
                upd = body.model_dump(exclude_none=True)
                if "status" in upd and upd["status"] not in ("suggested", "confirmed", "rejected"):
                    raise HTTPException(422, "status must be suggested, confirmed or rejected")
                if "hpo_id" in upd:
                    if not onto.exists(upd["hpo_id"]):
                        raise HTTPException(422, "Unknown HPO term")
                    upd["hpo_label"] = onto.label(upd["hpo_id"])
                    upd.setdefault("canonical", upd["hpo_label"])
                    upd["flags"] = [f for f in x.flags if not f.startswith(("hpo_", "no_hpo"))] + ["fixed_by_patient"]
                new = x.model_copy(update=upd)
                e.entities[i] = Entity.model_validate(new.model_dump())
                save(e)
                return e.entities[i]
        raise HTTPException(404, "entity not found")

    @app.get("/api/terms/search")
    def term_search(q: str = ""):
        return onto.search(q, 10) if q.strip() else []

    @app.get("/api/timeline")
    def timeline():
        entries = all_entries()
        days: dict[str, dict] = {}
        for e in entries:
            d = days.setdefault(e.occurred_on, {"date": e.occurred_on, "entries": [], "terms": []})
            d["entries"].append(e.id)
            for x in e.entities:
                if x.status == "confirmed" and x.hpo_id and not x.negated:
                    d["terms"].append({"hpo_id": x.hpo_id, "label": x.hpo_label or x.canonical})
        terms = sorted(evidence_from(entries, onto).values(), key=lambda v: -v.count)
        return {"days": sorted(days.values(), key=lambda d: d["date"]), "terms": terms}

    @app.get("/api/patterns")
    async def patterns():
        entries = all_entries()
        ev = evidence_from(entries, onto)
        key = json.dumps(sorted((k, v.count) for k, v in ev.items()))
        if key not in pattern_cache:
            pattern_cache.clear()
            pattern_cache[key] = await explain(llm, score_patterns(entries, onto))
        pats = pattern_cache[key]
        note = ("Patterns worth discussing with your doctor. Not a diagnosis."
                if pats else "Confirm at least 3 terms in your entries to look for patterns.")
        return {"patterns": pats, "confirmed_terms": len(ev), "note": note}

    @app.post("/api/demo")
    async def demo(body: DemoIn):
        if body.persona != "giulia":
            raise HTTPException(404, "unknown persona")
        n = 0
        for day, text, mood in giulia_entries():
            e = save(Entry(id=f"e_{uuid.uuid4().hex[:10]}", created_at=now_iso(), occurred_on=day, text=text, mood=mood))
            spawn(run_extraction(e.id))
            n += 1
        return {"ok": True, "entries": n}

    async def clinic_key(url: str) -> dict:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.netloc:
            raise HTTPException(422, "Clinic address must start with http:// or https://")
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(url.rstrip("/") + "/api/clinic/key")
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Could not reach the clinic: {e}")

    @app.get("/api/clinic/key")
    async def proxy_clinic_key(url: str):
        return await clinic_key(url)

    @app.post("/api/share")
    async def share(body: ShareRequest):
        if body.since > body.until:
            raise HTTPException(422, "The start date is after the end date")
        key = await clinic_key(body.clinic_url)
        entries = all_entries()
        pats = []
        if body.include_patterns:
            chosen = [e for e in entries if body.since <= e.occurred_on <= body.until]
            pats = score_patterns(chosen, onto)
        pkg = sharing.build_package(entries, body.since, body.until, sharing.alias(str(s.data_dir.resolve())),
                                    body.note, pats, body.expires_hours)
        if not pkg.entries:
            raise HTTPException(422, "No entries in that period")
        sealed = sharing.seal(pkg, key["public_key"])
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(body.clinic_url.rstrip("/") + "/api/inbox",
                                 json={"package_id": pkg.package_id, "sealed": sealed})
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(502, f"The clinic did not accept the package: {e}")
        qr_payload = json.dumps({"clinic": body.clinic_url, "package": pkg.package_id})
        return {"package_id": pkg.package_id, "clinic_url": body.clinic_url, "expires_at": pkg.expires_at,
                "clinic_name": key.get("clinic_name"), "fingerprint": key.get("fingerprint"),
                "entries": len(pkg.entries), "entities": len(pkg.entities), "patterns": len(pkg.patterns),
                "qr_payload": qr_payload, "qr_svg": sharing.qr_svg(qr_payload)}


# ======================================================================= clinic
def _clinic_routes(app: FastAPI, s: Settings, keys: sharing.ClinicKeys, llm, runs: Runs, spawn) -> None:
    inbox_dir = s.data_dir / "inbox"
    briefs_dir = s.data_dir / "briefs"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    briefs_dir.mkdir(parents=True, exist_ok=True)

    def safe_id(pid: str) -> str:
        if not pid.startswith("pkg_") or not pid[4:].isalnum():
            raise HTTPException(404, "package not found")
        return pid

    def open_pkg(pid: str) -> SharePackage:
        f = inbox_dir / f"{safe_id(pid)}.json"
        if not f.exists():
            raise HTTPException(404, "package not found")
        rec = json.loads(f.read_text())
        pkg = keys.open(rec["sealed"])
        if sharing.is_expired(pkg):
            purge(pid)
            raise HTTPException(410, "This package has expired and was deleted")
        return pkg

    def purge(pid: str) -> None:
        for d in (inbox_dir, briefs_dir):
            with contextlib.suppress(FileNotFoundError):
                (d / f"{pid}.json").unlink()

    def load_brief(pid: str) -> Brief | None:
        f = briefs_dir / f"{safe_id(pid)}.json"
        return Brief.model_validate_json(f.read_text()) if f.exists() else None

    def save_brief(b: Brief) -> Brief:
        (briefs_dir / f"{b.package_id}.json").write_text(b.model_dump_json())
        return b

    @app.get("/api/clinic/key")
    def clinic_key():
        return {"public_key": keys.public_b64, "fingerprint": keys.fingerprint, "clinic_name": s.clinic_name}

    @app.post("/api/inbox")
    def receive(body: InboxIn):
        try:
            pkg = keys.open(body.sealed)
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Package could not be opened with this clinic's key")
        if pkg.package_id != body.package_id:
            raise HTTPException(400, "Package id mismatch")
        if sharing.is_expired(pkg):
            raise HTTPException(410, "Package already expired")
        (inbox_dir / f"{safe_id(pkg.package_id)}.json").write_text(
            json.dumps({"sealed": body.sealed, "received_at": now_iso()}))
        return {"ok": True, "package_id": pkg.package_id}

    @app.get("/api/inbox")
    def inbox():
        out = []
        for f in sorted(inbox_dir.glob("pkg_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            rec = json.loads(f.read_text())
            try:
                pkg = keys.open(rec["sealed"])
            except Exception:  # noqa: BLE001
                continue
            if sharing.is_expired(pkg):
                purge(pkg.package_id)
                continue
            b = load_brief(pkg.package_id)
            state = "none" if not b else ("final" if b.finalized else "draft")
            out.append({"package_id": pkg.package_id, "patient_alias": pkg.patient_alias, "period": pkg.period,
                        "received_at": rec["received_at"], "expires_at": pkg.expires_at,
                        "entities": len(pkg.entities), "entries": len(pkg.entries), "brief_state": state})
        return out

    @app.get("/api/inbox/{pid}")
    def get_pkg(pid: str) -> SharePackage:
        return open_pkg(pid)

    async def draft(rid: str, pkg: SharePackage) -> None:
        try:
            await runs.emit(rid, "draft", "Reading the shared diary", 0.05, backend=llm.backend, model=llm.model)
            msgs = [{"role": "system", "content": briefing.SYSTEM}, {"role": "user", "content": briefing.model_input(pkg)}]
            text, stats, n, last = "", None, 0, time.perf_counter()
            t0 = time.perf_counter()
            async for delta, st in llm.stream("brief", msgs, max_tokens=1500,
                                              payload={"entries": [{"id": e.id, "date": e.occurred_on} for e in pkg.entries]}):
                if st:
                    stats = st
                    continue
                text += delta
                n += 1
                if time.perf_counter() - last > 0.4:
                    last = time.perf_counter()
                    el = last - t0
                    await runs.emit(rid, "draft", "Drafting brief", min(0.9, 0.1 + n / 600), backend=llm.backend,
                                    model=llm.model, tokens=n, tokens_per_s=round(n / el, 1) if el else None)
            parsed = briefing.DraftOut.model_validate(extract_json(text))
            items = briefing.patient_items(pkg) + briefing.check_ai_items(pkg, parsed)
            b = save_brief(Brief(package_id=pkg.package_id, items=items, model=llm.model, backend=llm.backend,
                                 stats=stats.as_dict() if stats else {}))
            await runs.emit(rid, "done", "Brief drafted. Review each AI item.", 1.0, backend=llm.backend,
                            model=llm.model, **({k: v for k, v in stats.as_dict().items()
                                                 if k in ("tokens", "tokens_per_s", "latency_ms")} if stats else {}),
                            payload=b.model_dump(mode="json"))
        except Exception as e:  # noqa: BLE001
            await runs.emit(rid, "error", f"Could not draft the brief: {e}")

    @app.post("/api/inbox/{pid}/brief")
    async def start_brief(pid: str):
        pkg = open_pkg(pid)
        rid = runs.new()
        spawn(draft(rid, pkg))
        return {"run_id": rid}

    @app.get("/api/inbox/{pid}/brief")
    def get_brief(pid: str) -> Brief:
        open_pkg(pid)
        b = load_brief(pid)
        if not b:
            raise HTTPException(404, "No brief yet")
        return b

    @app.patch("/api/brief-items/{pid}/{item_id}")
    def review(pid: str, item_id: str, body: ReviewIn):
        open_pkg(pid)
        b = load_brief(pid)
        if not b:
            raise HTTPException(404, "No brief yet")
        if b.finalized:
            raise HTTPException(409, "Brief is final")
        if body.review not in ("pending", "accepted", "rejected", "edited"):
            raise HTTPException(422, "review must be pending, accepted, rejected or edited")
        for i, it in enumerate(b.items):
            if it.id == item_id:
                upd: dict[str, Any] = {"review": body.review}
                if body.review == "edited":
                    if not (body.text or "").strip():
                        raise HTTPException(422, "Edited items need text")
                    upd["text"] = body.text.strip()
                b.items[i] = it.model_copy(update=upd)
                save_brief(b)
                return b.items[i]
        raise HTTPException(404, "item not found")

    @app.post("/api/inbox/{pid}/brief/finalize")
    def finalize(pid: str) -> Brief:
        open_pkg(pid)
        b = load_brief(pid)
        if not b:
            raise HTTPException(404, "No brief yet")
        pending = [i for i in b.items if i.review == "pending"]
        if pending:
            raise HTTPException(409, f"{len(pending)} AI item(s) still need review")
        b.finalized = True
        return save_brief(b)

    @app.get("/api/inbox/{pid}/brief.md", response_class=PlainTextResponse)
    def brief_md(pid: str):
        pkg = open_pkg(pid)
        b = load_brief(pid)
        if not b or not b.finalized:
            raise HTTPException(409, "Finalize the brief first")
        return briefing.to_markdown(pkg, b)


def main() -> None:
    import uvicorn

    s = Settings.from_env()
    port = int(os.environ.get("CLARIO_PORT") or (8765 if s.mode == "patient" else 8800))
    uvicorn.run(create_app(s), host=os.environ.get("CLARIO_HOST", "127.0.0.1"), port=port)


if __name__ == "__main__":
    main()
