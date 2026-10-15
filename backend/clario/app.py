"""FastAPI app. CLARIO_MODE=patient (on the patient's device) or clinic (on the clinic's AMD server)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import brief as briefing
from . import privacy
from . import doc_routes
from . import gpu as gpumetrics
from . import share as sharing
from .config import Settings
from .share import now_iso
from . import documents as docs
from .demo import DEMO_REFERTI_AGE, PERSONA_LANG, PERSONAS, REFERTI_LATEST, demo_referti, persona_entries
from .i18n import ANSWER_ENTRY, PATTERNS_NOTE, hpo_it, norm_lang, term_label
from .extract import ExtractOpts, extract
from .knowledge import Ontology
from .llm import extract_json, make_llm
from .models import AnswerResult, Brief, BriefDecisions, ClinicMetrics, DecisionCounts, Entity, Entry, LabResult, NextQuestion, ShareRequest, SharePackage, Term
from .next_question import as_ranked_patterns, next_question, template_question
from .patterns import counts_as_evidence, evidence_from, patient_patterns, score_patterns
from .review import ACTIONS, EntityReview, apply_entity_action, correction_record, register_review_kind
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
    lang: str = "en"


class EntityPatch(BaseModel):
    review: str | None = None
    canonical: str | None = None
    hpo_id: str | None = None
    severity: int | None = None
    negated: bool | None = None


class ReviewAction(BaseModel):
    action: str
    value: str | None = None


class AnswerIn(BaseModel):
    feature_id: str
    answer: str  # yes | no | unsure
    question: str | None = None
    lang: str = "en"


class DemoIn(BaseModel):
    persona: str = "giulia"


class InboxIn(BaseModel):
    package_id: str
    sealed: str


class LabDecisionIn(BaseModel):
    decision: str


class ReviewIn(BaseModel):
    review: str
    text: str | None = None


class FinalizeIn(BaseModel):
    seconds: float | None = None  # opening the package to finalize, measured in the clinic UI


# ---------------------------------------------------------------- run bus (SSE)
FINISHED_TTL = 15 * 60  # seconds a finished run is kept for late subscribers, then dropped


class Runs:
    def __init__(self, ttl: float = FINISHED_TTL) -> None:
        self.runs: dict[str, dict] = {}
        self.ttl = ttl

    def new(self) -> str:
        now = time.monotonic()
        for k in [k for k, r in self.runs.items() if r["finished"] is not None and now - r["finished"] > self.ttl]:
            del self.runs[k]
        rid = f"run_{uuid.uuid4().hex[:10]}"
        self.runs[rid] = {"events": [], "cond": asyncio.Condition(), "done": False, "finished": None}
        return rid

    async def emit(self, rid: str, stage: str, message: str, progress: float = 0.0, **kw: Any) -> None:
        r = self.runs[rid]
        async with r["cond"]:
            r["events"].append({"stage": stage, "message": message, "progress": round(progress, 3), **kw})
            r["done"] = r["done"] or stage in ("done", "error")
            if r["done"] and r["finished"] is None:
                r["finished"] = time.monotonic()
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


def create_app(settings: Settings | None = None, gpu_reader=None) -> FastAPI:
    s = settings or Settings.from_env()
    onto = Ontology.load()
    vault = Vault(s.data_dir, s.auto_lock_minutes) if s.mode == "patient" else None
    keys = sharing.ClinicKeys(s.data_dir) if s.mode == "clinic" else None
    call_log = privacy.CallLog.for_settings(s, vault, keys)
    llm = make_llm(s, call_log)
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
               "llm": {"backend": llm.backend, "model": llm.model, "base_url_host": s.llm_host, "is_amd": llm.is_amd,
                       "pseudonymize": privacy.should_pseudonymize(s)},
               "demo_instance": s.demo_instance,
               "review": {"threshold": s.review_threshold, "source": s.review_source, "alpha": s.review_alpha,
                          "delta": s.review_delta, "calibration_n": s.review_calibration_n,
                          "calibration_status": s.review_calibration_status}}
        if s.mode == "patient":
            out["locked"] = vault.locked
        return out

    @app.get("/api/system/gpu")
    async def system_gpu():
        """GPU summary {gpu_name, util_pct, vram_used_gb, vram_total_gb}, or null when there is no telemetry."""
        return JSONResponse(await gpumetrics.read_gpu(s))

    @app.get("/api/runs/{rid}/events")
    async def run_events(rid: str):
        if rid not in runs.runs:
            raise HTTPException(404, "run not found")
        return EventSourceResponse(runs.stream(rid), ping=10)

    @app.exception_handler(Locked)
    async def locked_handler(_r: Request, _e: Locked):
        return JSONResponse({"detail": "Diary is locked"}, status_code=423)

    if s.mode == "patient":
        _patient_routes(app, s, vault, onto, llm, spawn, gpu_reader)
        privacy.routes(app, s, call_log, lambda eid: Entry.model_validate(d) if (d := vault.get(eid)) else None)
    else:
        privacy.routes(app, s, call_log)
        _clinic_routes(app, s, keys, llm, runs, spawn, onto)

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
def _patient_routes(app: FastAPI, s: Settings, vault: Vault, onto: Ontology, llm, spawn, gpu_reader=None) -> None:
    opts = ExtractOpts.from_settings(s)

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
            ents, _st = await extract(llm, e.id, e.text, onto, opts)
        except Exception as err:  # noqa: BLE001 - recorded as failed, retried on demand
            log.warning("extraction failed for %s: %s", eid, err)
            ents, status = [], "failed"
        else:
            status = "done"
        with contextlib.suppress(Locked):
            cur = load(eid)  # entities confirmed meanwhile are kept
            keep = [x for x in cur.entities if x.review not in ("auto", "needs_review")]  # decided by a person
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
        notice = check_entry(text, body.lang)  # before any model call
        blocked = notice is not None and notice.level == "advice"  # a dosing question never reaches a model
        e = save(Entry(id=f"e_{uuid.uuid4().hex[:10]}", created_at=now_iso(),
                       occurred_on=body.occurred_on or date.today().isoformat(), text=text,
                       mood=body.mood if body.mood is None or 0 <= body.mood <= 10 else None,
                       extraction="done" if blocked else "pending"))
        if not blocked:
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
                if "review" in upd and upd["review"] not in ("auto", "confirmed", "rejected"):
                    raise HTTPException(422, "review must be auto, confirmed or rejected")
                base = x
                if "hpo_id" in upd:  # same correction as the review queue; fields sent in the same body win over it
                    try:
                        base = apply_entity_action(x, "correct", upd.pop("hpo_id"), onto)
                    except ValueError:
                        raise HTTPException(422, "Unknown HPO term")
                new = base.model_copy(update=upd)
                e.entities[i] = Entity.model_validate(new.model_dump())
                save(e)
                return e.entities[i]
        raise HTTPException(404, "entity not found")

    # ---- human review queue; other modules add kinds with review.register_review_kind
    app.state.vault = vault
    register_review_kind(app, "entity", EntityReview(all_entries, save, onto))

    @app.get("/api/review")
    def review_queue():
        items = [i for k in app.state.review_kinds.values() for i in k.items()]
        return {"items": items, "count": len(items)}

    @app.post("/api/review/{kind}/{item_id}")
    def review_act(kind: str, item_id: str, body: ReviewAction):
        handler = app.state.review_kinds.get(kind)
        if handler is None:
            raise HTTPException(404, "unknown review kind")
        if body.action not in ACTIONS:
            raise HTTPException(422, "action must be confirm, correct or reject")
        try:
            detail = handler.apply(item_id, body.action, body.value)
        except LookupError:
            raise HTTPException(404, "item not found")
        except ValueError as e:
            raise HTTPException(422, str(e))
        rid, rec = correction_record(kind, item_id, body.action, detail)
        vault.put("correction_log", rid, rec)
        return {"ok": True, "count": sum(len(k.items()) for k in app.state.review_kinds.values())}

    @app.get("/api/terms/search")
    def term_search(q: str = "", lang: str = "en"):
        """Ontology lookup. In Italian the plain Italian names we ship are searched first (labels in Italian)."""
        if not q.strip():
            return []
        out = onto.search(q, 10)
        if norm_lang(lang) == "it":
            low = q.strip().lower()
            mine = [Term(hpo_id=h, label=lab) for h, lab in hpo_it().items() if low in lab.lower() and onto.exists(h)]
            out = mine + [Term(hpo_id=x.hpo_id, label=term_label(x.hpo_id, x.label, "it")) for x in out
                          if x.hpo_id not in {m.hpo_id for m in mine}]
        return out[:10]

    @app.get("/api/timeline")
    def timeline():
        entries = all_entries()
        days: dict[str, dict] = {}
        for e in entries:
            d = days.setdefault(e.occurred_on, {"date": e.occurred_on, "entries": [], "terms": []})
            d["entries"].append(e.id)
            for x in e.entities:
                if counts_as_evidence(x):
                    d["terms"].append({"hpo_id": x.hpo_id, "label": x.hpo_label or x.canonical})
        terms = sorted(evidence_from(entries, onto).values(), key=lambda v: -v.count)
        return {"days": sorted(days.values(), key=lambda d: d["date"]), "terms": terms}

    @app.get("/api/patterns")
    async def patterns(lang: str = "en"):
        """Cards for the patient: at most two, titled by the features recorded, in everyday words. No condition names."""
        lang = norm_lang(lang)

        def compute():  # vault reads and scoring are CPU work: keep them off the event loop
            entries = all_entries()
            return len(evidence_from(entries, onto)), patient_patterns(entries, onto, lang)

        n_terms, pats = await asyncio.to_thread(compute)
        return {"patterns": pats, "confirmed_terms": n_terms, "note": PATTERNS_NOTE[lang][1 if n_terms < 3 else 0 if pats else 2]}

    doc_routes.register(app, s, vault, llm, spawn, gpu_reader)
    asked: dict[str, str] = {}  # feature_id -> question text last shown (so the diary entry quotes what was asked)

    def unsure_ids() -> set[str]:
        return {d["feature_id"] for d in vault.all("qa") if d.get("answer") == "unsure"}

    @app.get("/api/patterns/next-question")
    async def pattern_next_question(lang: str = "en") -> NextQuestion | None:
        entries, skip = await asyncio.to_thread(lambda: (all_entries(), unsure_ids()))
        q = await next_question(llm, onto, entries, lang, skip=skip)
        if q:
            asked[q.feature_id] = q.question
        return q

    @app.post("/api/patterns/answer")
    def pattern_answer(body: AnswerIn) -> AnswerResult:
        if body.answer not in ("yes", "no", "unsure"):
            raise HTTPException(422, "answer must be yes, no or unsure")
        label = onto.label(body.feature_id)
        if label is None:
            raise HTTPException(422, "Unknown feature")
        entries = all_entries()
        before = as_ranked_patterns(onto, entries, norm_lang(body.lang))
        vault.put("qa", f"qa_{uuid.uuid4().hex[:10]}", {"feature_id": body.feature_id, "answer": body.answer, "at": now_iso()})
        entry_id = None
        if body.answer != "unsure":
            q = (body.question or asked.get(body.feature_id) or template_question(label.lower(), body.lang)).strip()
            lead, yes, no = ANSWER_ENTRY[norm_lang(body.lang)]
            text = f"{lead} {q} {yes if body.answer == 'yes' else no}"
            eid = f"e_{uuid.uuid4().hex[:10]}"
            ent = Entity(id=f"x_{uuid.uuid4().hex[:10]}", entry_id=eid, type="symptom", quote=q, canonical=label,
                         hpo_id=body.feature_id, hpo_label=label, negated=body.answer == "no", review="confirmed",
                         flags=["from_question"], model="next-question")
            save(Entry(id=eid, created_at=now_iso(), occurred_on=date.today().isoformat(), text=text,
                       extraction="done", entities=[ent]))
            entry_id = eid
        after = as_ranked_patterns(onto, all_entries(), norm_lang(body.lang))
        return AnswerResult(before=before, after=after, entry_id=entry_id)

    @app.post("/api/demo")
    async def demo(body: DemoIn):
        if body.persona not in PERSONAS:
            raise HTTPException(404, "unknown persona")
        n = 0
        for day, text, mood in persona_entries(body.persona):
            e = save(Entry(id=f"e_{uuid.uuid4().hex[:10]}", created_at=now_iso(), occurred_on=day, text=text, mood=mood))
            spawn(run_extraction(e.id))
            n += 1
        return {"ok": True, "entries": n, "persona": body.persona, "lang": PERSONA_LANG[body.persona]}

    @app.post("/api/demo/documents")
    async def demo_documents():
        """One tap: read the three synthetic referti that ship with the app, same path as an upload."""
        if vault.locked:
            raise Locked()
        pages: list = []
        for f in demo_referti():
            pages += await asyncio.to_thread(docs.file_pages, f.name, f.read_bytes())
        return app.state.start_batch(pages, (date.today() - timedelta(days=DEMO_REFERTI_AGE) - REFERTI_LATEST).days)

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
        labs = [LabResult.model_validate(d) for d in vault.all("lab")]
        batch_entry = {d["batch_id"]: d["entry_id"] for d in vault.all("docbatch")}
        pkg = sharing.build_package(entries, body.since, body.until, sharing.alias(str(s.data_dir.resolve())),
                                    body.note, pats, body.expires_hours, labs, batch_entry)
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
                "entries": len(pkg.entries), **sharing.counts(pkg), "patterns": len(pkg.patterns),
                "qr_payload": qr_payload, "qr_svg": sharing.qr_svg(qr_payload)}


# ======================================================================= clinic
def _clinic_routes(app: FastAPI, s: Settings, keys: sharing.ClinicKeys, llm, runs: Runs, spawn, onto: Ontology) -> None:
    inbox_dir = s.data_dir / "inbox"
    briefs_dir = s.data_dir / "briefs"
    labdec_dir = s.data_dir / "labdec"
    labdec_dir.mkdir(parents=True, exist_ok=True)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    briefs_dir.mkdir(parents=True, exist_ok=True)
    decisions_file = s.data_dir / "decisions.jsonl"  # counts and timing only, no diary text

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
        for d in (inbox_dir, briefs_dir, labdec_dir):
            with contextlib.suppress(FileNotFoundError):
                (d / f"{pid}.json").unlink()

    def load_brief(pid: str) -> Brief | None:
        f = briefs_dir / f"{safe_id(pid)}.json"
        if not f.exists():
            return None
        raw = f.read_bytes()
        try:
            return Brief.model_validate_json(keys.open_data(raw))
        except Exception:  # noqa: BLE001 - a brief written before encryption at rest: read it once, store it sealed
            b = Brief.model_validate_json(raw)
            save_brief(b)
            return b

    def load_decisions(pid: str) -> dict[str, str]:
        f = labdec_dir / f"{safe_id(pid)}.json"
        if not f.exists():
            return {}
        try:
            return json.loads(keys.open_data(f.read_bytes()))
        except Exception:  # noqa: BLE001
            return {}

    def decided(pkg: SharePackage, drop_rejected: bool) -> SharePackage:
        """The package with the clinic's lab decisions applied. Unchecked rows the clinician accepted count as checked."""
        dec = load_decisions(pkg.package_id)
        labs = []
        for l in pkg.labs:
            d = dec.get(l.id) if not l.reviewed else None
            if d == "rejected" and drop_rejected:
                continue
            labs.append(l.model_copy(update={"decision": d, "reviewed": l.reviewed or d == "accepted"}))
        return pkg.model_copy(update={"labs": labs})

    def save_brief(b: Brief) -> Brief:
        """Briefs quote the diary, so they are encrypted at rest (key derived from the clinic key). The inbox is already sealed."""
        (briefs_dir / f"{b.package_id}.json").write_bytes(keys.seal_data(b.model_dump_json().encode()))
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
                        **sharing.counts(pkg), "entries": len(pkg.entries), "brief_state": state})
        return out

    @app.get("/api/inbox/{pid}")
    def get_pkg(pid: str) -> SharePackage:
        return decided(open_pkg(pid), drop_rejected=False)

    @app.put("/api/inbox/{pid}/labs/{lab_id}")
    def decide_lab(pid: str, lab_id: str, body: LabDecisionIn) -> SharePackage:
        """The clinician accepts or rejects a lab row read from a document and not checked by the patient."""
        pkg = open_pkg(pid)
        row = next((l for l in pkg.labs if l.id == lab_id), None)
        if row is None:
            raise HTTPException(404, "lab row not found")
        if row.reviewed:
            raise HTTPException(409, "The patient already checked this row")
        b = load_brief(pid)
        if b and b.finalized:
            raise HTTPException(409, "Brief is final")
        if body.decision not in ("pending", "accepted", "rejected"):
            raise HTTPException(422, "decision must be pending, accepted or rejected")
        dec = load_decisions(pid)
        if body.decision == "pending":
            dec.pop(lab_id, None)
        else:
            dec[lab_id] = body.decision
        (labdec_dir / f"{pid}.json").write_bytes(keys.seal_data(json.dumps(dec).encode()))
        return decided(pkg, drop_rejected=False)

    async def draft(rid: str, pkg: SharePackage, lang: str = "en") -> None:
        try:
            await runs.emit(rid, "draft", "Reading the shared diary", 0.05, backend=llm.backend, model=llm.model)
            msgs = [{"role": "system", "content": briefing.SYSTEM}, {"role": "user", "content": briefing.model_input(pkg, lang)}]
            text, stats, n, last = "", None, 0, time.perf_counter()
            t0 = time.perf_counter()
            async for delta, st in llm.stream("brief", msgs, max_tokens=1500,
                                              payload={"lang": lang,
                                                       "entries": [{"id": e.id, "date": e.occurred_on} for e in pkg.entries],
                                                       "entry_terms": {e.id: sorted({x.canonical for x in pkg.entities if x.entry_id == e.id
                                                                                    and not x.negated and not x.family_history})
                                                                       for e in pkg.entries}}):
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
            items = briefing.patient_items(pkg, lang) + briefing.check_ai_items(pkg, parsed)
            b = save_brief(Brief(package_id=pkg.package_id, items=items, model=llm.model, backend=llm.backend,
                                 stats=stats.as_dict() if stats else {}, lang=lang))  # type: ignore[arg-type]
            await runs.emit(rid, "done", "Brief drafted. Review each AI item.", 1.0, backend=llm.backend,
                            model=llm.model, **({k: v for k, v in stats.as_dict().items()
                                                 if k in ("tokens", "tokens_per_s", "latency_ms")} if stats else {}),
                            payload=b.model_dump(mode="json"))
        except Exception as e:  # noqa: BLE001
            await runs.emit(rid, "error", f"Could not draft the brief: {e}")

    @app.post("/api/inbox/{pid}/brief")
    async def start_brief(pid: str, lang: str = "en"):
        pkg = open_pkg(pid)
        rid = runs.new()
        spawn(draft(rid, pkg, norm_lang(lang)))
        return {"run_id": rid}

    def view(pid: str, audience: str | None, lang: str | None) -> tuple[SharePackage, Brief, str, str]:
        if audience not in (None, "clinician", "patient"):
            raise HTTPException(422, "audience must be clinician or patient")
        pkg = decided(open_pkg(pid), drop_rejected=True)
        b = load_brief(pid)
        if not b:
            raise HTTPException(404, "No brief yet")
        aud = audience or "clinician"
        if aud == "patient" and not b.finalized:
            raise HTTPException(409, "The patient copy is available after the clinician finalizes the brief")
        return pkg, b, aud, norm_lang(lang) if lang else b.lang

    @app.get("/api/inbox/{pid}/brief")
    def get_brief(pid: str, audience: str | None = None, lang: str | None = None) -> Brief:
        pkg, b, aud, lg = view(pid, audience, lang)
        return briefing.render_brief(pkg, b, aud, lg, onto)

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
    def finalize(pid: str, body: FinalizeIn | None = None) -> Brief:
        open_pkg(pid)
        b = load_brief(pid)
        if not b:
            raise HTTPException(404, "No brief yet")
        pending = [i for i in b.items if i.review == "pending"]
        if pending:
            raise HTTPException(409, f"{len(pending)} AI item(s) still need review")
        dpkg = decided(open_pkg(pid), drop_rejected=False)
        unchecked = [l for l in dpkg.labs if not l.reviewed and l.decision is None]
        if unchecked:
            raise HTTPException(409, f"{len(unchecked)} lab row(s) from documents still need a decision")
        b.items = [i for i in b.items if not (i.section == "labs" and i.origin == "patient")] + \
            briefing.lab_items(dpkg.model_copy(update={"labs": [l for l in dpkg.labs if l.decision != "rejected"]}), b.lang)
        b.finalized = True
        b.finalized_at = now_iso()
        secs = body.seconds if body else None
        b.review_seconds = round(secs, 1) if secs is not None and 0 <= secs < 86400 else None
        save_brief(b)
        tally = DecisionCounts()
        for i in b.items:
            if i.origin == "ai" and i.review in ("accepted", "edited", "rejected"):
                setattr(tally, i.review, getattr(tally, i.review) + 1)
        row = BriefDecisions(package_id=pid, finalized_at=b.finalized_at, review_seconds=b.review_seconds, **tally.model_dump())
        with decisions_file.open("a") as fh:
            fh.write(row.model_dump_json() + "\n")
        return b

    @app.get("/api/clinic/metrics")
    def clinic_metrics() -> ClinicMetrics:
        latest: dict[str, BriefDecisions] = {}
        if decisions_file.exists():
            for line in decisions_file.read_text().splitlines():
                with contextlib.suppress(ValueError):
                    r = BriefDecisions.model_validate_json(line)
                    latest[r.package_id] = r
        rows = sorted(latest.values(), key=lambda r: r.finalized_at, reverse=True)
        timed = [r.review_seconds for r in rows if r.review_seconds is not None]
        return ClinicMetrics(
            briefs=rows, finalized=len(rows), timed=len(timed),
            totals=DecisionCounts(accepted=sum(r.accepted for r in rows), edited=sum(r.edited for r in rows),
                                  rejected=sum(r.rejected for r in rows)),
            mean_review_seconds=round(sum(timed) / len(timed), 1) if timed else None)

    @app.get("/api/inbox/{pid}/brief.md", response_class=PlainTextResponse)
    def brief_md(pid: str, audience: str | None = None, lang: str | None = None):
        open_pkg(pid)
        b = load_brief(pid)
        if not b or not b.finalized:
            raise HTTPException(409, "Finalize the brief first")
        pkg, b, aud, lg = view(pid, audience, lang)
        return briefing.to_markdown(pkg, b, aud, lg, onto)


def main() -> None:
    import uvicorn

    s = Settings.from_env()
    port = int(os.environ.get("CLARIO_PORT") or (8765 if s.mode == "patient" else 8800))
    uvicorn.run(create_app(s), host=os.environ.get("CLARIO_HOST", "127.0.0.1"), port=port)


if __name__ == "__main__":
    main()
