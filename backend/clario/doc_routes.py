"""Patient-mode routes for batch document import and the lab history."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import time
import uuid
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import documents as docs
from .config import Settings
from .review import LabReview
from .share import now_iso
from .models import Entry, LabResult, LabsResponse, LabTest, LabValue
from .vault import Locked, Vault

log = logging.getLogger("clario")

MAX_PAGES = 400
MAX_FILE_BYTES = 60 * 1024 * 1024
GPU_ROUTE = "/api/system/gpu"


class LabPatch(BaseModel):
    action: Literal["confirm", "correct", "reject"]
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str | None = None
    ref_low: float | None = None
    ref_high: float | None = None


def register(app: FastAPI, s: Settings, vault: Vault, llm: Any, spawn) -> None:
    batches: dict[str, dict] = {}

    def widen_llm() -> None:
        """The client's own semaphore would cap the pool below CLARIO_DOC_CONCURRENCY and starve vLLM batching."""
        inner = getattr(llm, "_inner", llm)  # PrivacyLLM forwards reads only: assigning on the wrapper would not reach the client
        if getattr(inner, "_sem", None) is not None and s.doc_workers > s.llm_concurrency:
            inner._sem = asyncio.Semaphore(s.doc_workers)

    def labs() -> list[LabResult]:
        return [LabResult.model_validate(d) for d in vault.all("lab")]

    def save_lab(lab: LabResult) -> None:
        vault.put("lab", lab.id, lab.model_dump(mode="json"))

    # labs wait in the same review queue as entities (GET /api/review, nav badge, correction_log)
    app.state.review_kinds["lab"] = LabReview(labs, save_lab)

    async def gpu_info() -> dict | None:
        """GET /api/system/gpu if another module registered it, else None. amd-smi is not called here."""
        for r in app.routes:
            if getattr(r, "path", None) == GPU_ROUTE and hasattr(r, "endpoint"):
                try:
                    out = r.endpoint()
                    out = await out if inspect.isawaitable(out) else out
                    return json.loads(out.body) if isinstance(out, Response) else out  # route may return JSONResponse
                except Exception:  # noqa: BLE001 - telemetry must never break the import
                    return None
        return None

    async def run_batch(bid: str, pages: list[docs.Page]) -> None:
        b = batches[bid]
        sem = asyncio.Semaphore(s.doc_workers)
        fallback_date = b["occurred_on"]

        async def one(i: int, page: docs.Page) -> None:
            async with sem:
                try:
                    res = await docs.extract_page(llm, page, i + 1, vision_model=s.llm_vision_model,
                                                  threshold=s.review_threshold, n_samples=s.doc_samples)
                    for r in res.rows:
                        lab = LabResult(id=f"l_{uuid.uuid4().hex[:10]}", batch_id=bid, test_key=docs.test_key(r["test_name"]),
                                        model=res.model, **{**r, "date": r["date"] or fallback_date})
                        vault.put("lab", lab.id, lab.model_dump(mode="json"))
                        b["labs"] += 1
                        b["needs_review"] += lab.review == "needs_review"
                except Locked:
                    b["errors"] += 1
                except Exception as err:  # noqa: BLE001 - one bad page must not sink the batch
                    log.warning("page %s of batch %s failed: %s", i + 1, bid, err)
                    b["errors"] += 1
                b["done"] += 1

        await asyncio.gather(*(one(i, p) for i, p in enumerate(pages)))
        b["finished"] = time.monotonic()

    @app.post("/api/documents/batch")
    async def batch_upload(files: list[UploadFile] = File(...)):
        if vault.locked:
            raise Locked()
        pages: list[docs.Page] = []
        for f in files:
            data = await f.read()
            if not data:
                continue
            if len(data) > MAX_FILE_BYTES:
                raise HTTPException(413, f"{f.filename} is larger than {MAX_FILE_BYTES // 2**20} MB")
            try:
                pages += await asyncio.to_thread(docs.file_pages, f.filename or "document", data)
            except ValueError as e:
                raise HTTPException(422, str(e))
            if len(pages) > MAX_PAGES:
                raise HTTPException(413, f"A batch is limited to {MAX_PAGES} pages")
        if not pages:
            raise HTTPException(422, "Add at least one PDF or image")
        return start_batch(pages)

    def start_batch(pages: list[docs.Page]) -> dict:
        """Store the pages encrypted, add the diary entry, start reading in the background."""
        bid = f"b_{uuid.uuid4().hex[:10]}"
        now = now_iso()
        occurred = docs.today_iso()
        for i, p in enumerate(pages):
            vault.put("docpage", f"{bid}_p{i + 1}", {"batch_id": bid, "page": i + 1, "source": p.source,
                                                      "jpeg_b64": base64.b64encode(p.jpeg).decode()})
        entry = Entry(id=f"e_{uuid.uuid4().hex[:10]}", created_at=now, occurred_on=occurred,
                      text=f"Imported documents ({len(pages)} pages)", extraction="done")
        vault.put("entry", entry.id, entry.model_dump(mode="json"))
        batches[bid] = {"total": len(pages), "done": 0, "errors": 0, "labs": 0, "needs_review": 0,
                        "started": time.monotonic(), "finished": None, "entry_id": entry.id, "occurred_on": occurred}
        widen_llm()
        spawn(run_batch(bid, pages))
        return {"batch_id": bid, "pages": len(pages), "entry_id": entry.id}

    app.state.start_batch = start_batch

    def snapshot(bid: str, gpu: dict | None) -> dict:
        b = batches[bid]
        end = b["finished"] or time.monotonic()
        el = max(end - b["started"], 1e-3)
        return {"batch_id": bid, "pages_done": b["done"], "pages_total": b["total"],
                "pages_per_sec": round(b["done"] / el, 2), "gpu": gpu, "errors": b["errors"], "labs": b["labs"],
                "needs_review": b["needs_review"], "done": b["done"] >= b["total"]}

    @app.get("/api/documents/batch/{bid}/events")
    async def batch_events(bid: str):
        if bid not in batches:
            raise HTTPException(404, "batch not found")

        async def stream():
            while True:
                ev = snapshot(bid, await gpu_info())
                yield {"data": json.dumps(ev)}
                if ev["done"]:
                    return
                await asyncio.sleep(1.0)

        return EventSourceResponse(stream(), ping=10)

    @app.get("/api/labs")
    def list_labs(include_rejected: bool = False) -> LabsResponse:
        rows = [r for r in labs() if include_rejected or r.review != "rejected"]
        groups: dict[str, list[LabResult]] = {}
        for r in rows:
            groups.setdefault(r.test_key, []).append(r)
        tests = []
        for key, grp in groups.items():
            grp.sort(key=lambda r: (r.date, r.page, r.id))
            vals = [LabValue(id=r.id, date=r.date, value_numeric=r.value_numeric, value_text=r.value_text, flag=r.flag,
                             review=r.review, confidence=r.confidence, page=r.page, batch_id=r.batch_id) for r in grp]
            last = grp[-1]
            unit = next((r.unit for r in reversed(grp) if r.unit), "")
            tests.append(LabTest(test_key=key, test_name=last.test_name, unit=unit, ref_low=last.ref_low,
                                 ref_high=last.ref_high, latest=vals[-1], values=vals,
                                 out_of_range=vals[-1].flag in ("low", "high") and vals[-1].review != "rejected"))
        tests.sort(key=lambda t: (not t.out_of_range, t.test_name.lower()))
        return LabsResponse(tests=tests, n_results=len(rows), out_of_range=sum(t.out_of_range for t in tests),
                            needs_review=sum(r.review == "needs_review" for r in rows))

    @app.patch("/api/labs/{lab_id}")
    def patch_lab(lab_id: str, body: LabPatch) -> LabResult:
        doc = vault.get(lab_id)
        if not doc or "test_key" not in doc:
            raise HTTPException(404, "lab result not found")
        lab = LabResult.model_validate(doc)
        try:
            new = docs.apply_lab_action(lab, body.action, body.model_dump(exclude={"action"}, exclude_none=True))
        except ValueError as e:
            raise HTTPException(422, str(e))
        vault.put("lab", new.id, new.model_dump(mode="json"))
        return new
