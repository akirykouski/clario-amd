"""FastAPI app. CLARIO_MODE=patient (on the patient's device) or clinic (on the clinic's AMD server)."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import math
import os
import re
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
from . import clinic_ddx
from . import overview as overview_mod
from . import privacy
from . import doc_routes
from . import gpu as gpumetrics
from . import second_opinion as second
from . import share as sharing
from . import specialty
from .config import Settings
from .share import lab_needs_check, now_iso
from . import documents as docs
from .demo import (DEMO_ENTRY_PREFIX, DEMO_REFERTI_AGE, PERSONA_LANG, PERSONAS, REFERTI_LATEST, demo_referti, persona_care, persona_entries,
                   persona_labels, truth_rows)
from .i18n import ANSWER_ENTRY, PATTERNS_NOTE, hpo_it, norm_lang, term_label
from .extract import ExtractOpts, extract
from .knowledge import Ontology, fold
from .llm import extract_json, make_llm
from .models import (AnswerResult, Brief, BriefDecisions, ClinicMetrics, DecisionCounts, Differential, Entity, Entry, LabResult,
                     NextQuestion, ShareRequest, SharePackage, Term, Timeline, TimelineDay, TimelineTerm)
from .next_question import as_ranked_patterns, next_question, template_question
from .patterns import counts_as_evidence, evidence_from, patient_label, patient_patterns, score_patterns
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


class ProfileIn(BaseModel):
    age: int | None = None
    sex: str | None = None  # female | male | other


class InboxIn(BaseModel):
    package_id: str
    sealed: str


class LabDecisionIn(BaseModel):
    """`corrected` takes the value as printed (`value`, free text such as "11,0" or "Positivo 1:160", or `value_numeric` /
    `value_text`) and optionally the `unit`; what is not given stays as read."""

    decision: str
    value: str | None = None
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str | None = None


class LabBulkIn(BaseModel):
    """Decide many readings that still need a check in one call. No filter means every such reading; `test_key` narrows to one test,
    `page` (with `entry_id`, the import) to one page of one report."""

    decision: str
    test_key: str | None = None
    page: int | None = None
    entry_id: str | None = None


class ReviewIn(BaseModel):
    review: str
    text: str | None = None


class FinalizeIn(BaseModel):
    seconds: float | None = None  # opening the package to finalize, measured in the clinic UI


class TermDecisionIn(BaseModel):
    decision: str  # confirmed | rejected | corrected | pending
    hpo_id: str | None = None  # corrected: the term the clinician picked instead


class ClinicAnswerIn(BaseModel):
    feature_id: str
    answer: str  # yes | no | unsure
    lang: str = "en"


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
               "clinic_url": s.clinic_url,
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

    @app.get("/api/terms/systems")
    def term_systems(ids: str = "") -> dict[str, str]:
        """Organ-system key per HPO id ("skin", "joints", ...), for grouping heat map rows. Ontology only, no patient data."""
        return {h: clinic_ddx.system_key(onto, h) for h in ids.split(",")[:200] if h.strip()}

    @app.get("/api/terms/search")
    def term_search(q: str = "", lang: str = "en"):
        """Ontology lookup, in both modes (no patient data): the patient fixes a term, the clinician replaces one.
        In Italian the plain Italian names we ship come first (best match first, at most 3); English ontology hits
        only fill the list when they are a close match, so an Italian phrase never returns unrelated English terms."""
        if not q.strip():
            return []
        if norm_lang(lang) != "it":
            return onto.search(q, 10)
        low = fold(q.strip())
        words = [w for w in re.split(r"\W+", low) if w]
        mine: list[tuple[float, int, Term]] = []
        for h, lab in hpo_it().items():
            fl = fold(lab)
            if not onto.exists(h):
                continue
            if fl == low:
                sc = 1.0
            elif fl.startswith(low):
                sc = 0.9
            elif low in fl:
                sc = 0.8
            elif words and all(any(lw.startswith(w) for lw in re.split(r"\W+", fl)) for w in words):
                sc = 0.7
            else:
                continue
            mine.append((sc, len(lab), Term(hpo_id=h, label=lab)))
        mine.sort(key=lambda r: (-r[0], r[1], r[2].hpo_id))
        out = [m[2] for m in mine][:3]
        if len(out) < 3:
            have = {x.hpo_id for x in out}
            for x, sc in onto.search_scored(q, 6):
                if sc >= 0.8 and x.hpo_id not in have and len(out) < 3:
                    out.append(Term(hpo_id=x.hpo_id, label=term_label(x.hpo_id, x.label, "it")))
        return out

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
            ents, _st = await extract(llm, e.id, e.text, onto, opts, note_date=e.occurred_on)
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

    @app.get("/api/privacy/counts")
    def privacy_counts() -> dict[str, int]:
        """Personal details found per entry (only entries with at least one). Positions and values stay on the device."""
        out = {}
        for e in all_entries():
            n = len(privacy.pseudonymize(e.text)[1])
            if n:
                out[e.id] = n
        return out

    @app.get("/api/timeline")
    def timeline(lang: str = "en") -> Timeline:
        """Days with their notes, and the patient's terms in everyday words (clinical name kept in `clinical`)."""
        lang = norm_lang(lang)
        entries = all_entries()
        days: dict[str, TimelineDay] = {}
        for e in entries:
            d = days.setdefault(e.occurred_on, TimelineDay(date=e.occurred_on, entries=[], terms=[]))
            d.entries.append(e)
            for x in e.entities:
                if counts_as_evidence(x):
                    d.terms.append(Term(hpo_id=x.hpo_id, label=x.hpo_label or x.canonical))
        terms = [TimelineTerm(**t.model_dump() | {"label": patient_label(onto, t.hpo_id, lang).capitalize(), "clinical": t.label})
                 for t in sorted(evidence_from(entries, onto).values(), key=lambda v: -v.count)]
        systems = {t.hpo_id: clinic_ddx.system_key(onto, t.hpo_id) for t in terms}
        return Timeline(days=sorted(days.values(), key=lambda d: d.date), terms=terms, systems=systems)

    @app.get("/api/patterns")
    async def patterns(lang: str = "en"):
        """Cards for the patient: at most one, titled by the features recorded, in everyday words. No condition names."""
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

    @app.get("/api/care")
    def get_care() -> dict:
        """Earlier care: what was already tried and tested (facts, shared with every clinic), and whether a previous
        doctor's opinion is on file. Its conclusions name conditions, so the patient screens only learn who and when."""
        d = vault.get("care") or {}
        prev = d.get("previous")
        return {"tried": d.get("tried") or [], "tested": d.get("tested") or [],
                "previous": {"clinician": prev.get("clinician"), "date": prev.get("date")} if prev else None}

    def load_profile() -> dict:
        d = vault.get("profile") or {}
        return {k: d[k] for k in ("age", "sex") if d.get(k) is not None}

    @app.get("/api/profile")
    def get_profile() -> dict:
        return load_profile()

    @app.put("/api/profile")
    def put_profile(body: ProfileIn) -> dict:
        """Age and sex, optional, kept in the vault. Sent to a clinic only when the patient leaves include_profile on."""
        if body.age is not None and not 0 <= body.age <= 120:
            raise HTTPException(422, "Age must be between 0 and 120")
        if body.sex not in (None, "", "female", "male", "other"):
            raise HTTPException(422, "sex must be female, male or other")
        vault.put("profile", "profile", {"age": body.age, "sex": body.sex or None})
        return load_profile()

    @app.post("/api/demo")
    async def demo(body: DemoIn):
        if body.persona not in PERSONAS:
            raise HTTPException(404, "unknown persona")
        vault.put("profile", "profile", {"age": 29, "sex": "female"})  # Giulia, 29 (synthetic)
        labels = persona_labels(body.persona)  # reviewed, precomputed (data/demo/LABELS.md): no model call, no call log
        # loading again replaces the earlier demo diary (either persona) instead of adding a second copy; notes the user
        # wrote keep their own ids and stay
        for d in vault.all("entry"):
            if d["id"].startswith(DEMO_ENTRY_PREFIX):
                vault.delete(d["id"])
        n = 0
        for day, text, mood in persona_entries(body.persona):
            eid = f"{DEMO_ENTRY_PREFIX}{uuid.uuid4().hex[:10]}"
            ents = [Entity(id=f"ent_{uuid.uuid4().hex[:10]}", entry_id=eid, **x) for x in labels[text]]
            save(Entry(id=eid, created_at=now_iso(), occurred_on=day, text=text, mood=mood, extraction="done",
                       entities=ents))
            n += 1
        vault.put("care", "care", persona_care(body.persona))  # earlier care, written by hand (LABELS.md): facts + the GP's view
        return {"ok": True, "entries": n, "persona": body.persona, "lang": PERSONA_LANG[body.persona]}

    @app.post("/api/demo/documents")
    async def demo_documents():
        """One tap: read the three synthetic referti that ship with the app, same path as an upload."""
        if vault.locked:
            raise Locked()
        pages: list = []
        rows: list = []
        for f in demo_referti():
            got = await asyncio.to_thread(docs.file_pages, f.name, f.read_bytes())
            truth = truth_rows(f)
            if len(truth) != len(got):
                raise HTTPException(500, f"{f.name}: truth file and PDF disagree on the page count")
            pages += got
            rows += truth
        # the rows a live read gives (eval/results/documents_tf-mineru-table.json), stored at once: no OCR call
        return app.state.start_batch(pages, (date.today() - timedelta(days=DEMO_REFERTI_AGE) - REFERTI_LATEST).days,
                                     precomputed=rows, demo=True)

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
            pats = score_patterns(entries, onto, within={e.id for e in entries if body.since <= e.occurred_on <= body.until})
        labs = [LabResult.model_validate(d) for d in vault.all("lab")]
        batch_entry = {d["batch_id"]: d["entry_id"] for d in vault.all("docbatch")}
        def page_jpeg(bid: str, page: int) -> bytes | None:  # the page image stored encrypted at import
            d = vault.get(f"{bid}_p{page}")
            return base64.b64decode(d["jpeg_b64"]) if d and d.get("jpeg_b64") else None

        pkg = sharing.build_package(entries, body.since, body.until, sharing.alias(str(s.data_dir.resolve())),
                                    body.note, pats, body.expires_hours, labs, batch_entry,
                                    load_profile() if body.include_profile else None, page_jpeg,
                                    care=vault.get("care"), second_opinion=body.second_opinion)
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
                "second_opinion": pkg.second_opinion, "tried": len(pkg.tried), "tested": len(pkg.tested),
                "qr_payload": qr_payload, "qr_svg": sharing.qr_svg(qr_payload)}


# ======================================================================= clinic
def _clinic_routes(app: FastAPI, s: Settings, keys: sharing.ClinicKeys, llm, runs: Runs, spawn, onto: Ontology) -> None:
    inbox_dir = s.data_dir / "inbox"
    briefs_dir = s.data_dir / "briefs"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    briefs_dir.mkdir(parents=True, exist_ok=True)
    decisions_file = s.data_dir / "decisions.jsonl"  # counts and timing only, no diary text
    labdec_log = s.data_dir / "lab_decisions.jsonl"  # one row per lab decision: ids and timing only
    termdec_log = s.data_dir / "term_decisions.jsonl"  # one row per term decision: ids, HPO ids and timing only

    def safe_id(pid: str) -> str:
        if not pid.startswith("pkg_") or not pid[4:].isalnum():
            raise HTTPException(404, "package not found")
        return pid

    def open_pkg(pid: str) -> SharePackage:
        """The package as every view, the brief model and the differential see it: facts only. The previous doctor's
        conclusions of a second opinion stay out until the brief is final (`/compare`)."""
        return second.facts_only(open_full(pid))

    def open_full(pid: str) -> SharePackage:
        f = inbox_dir / f"{safe_id(pid)}.json"
        if not f.exists():
            raise HTTPException(404, "package not found")
        rec = json.loads(f.read_text())
        pkg = keys.open(rec["sealed"])
        if sharing.is_expired(pkg):
            purge(pid)
            raise HTTPException(410, "This package has expired and was deleted")
        return pkg

    decisions_dir = s.data_dir / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)

    def load_decisions(pid: str) -> dict:
        """The clinician's decisions on one package: term checks and answers. Encrypted at rest like the briefs."""
        f = decisions_dir / f"{safe_id(pid)}.json"
        if not f.exists():
            return {"terms": {}, "labs": {}, "corrections": {}, "lab_fixes": {}, "answers": []}
        return {"labs": {}, "corrections": {}, "lab_fixes": {}} | json.loads(keys.open_data(f.read_bytes()))

    def save_decisions(pid: str, d: dict) -> None:
        (decisions_dir / f"{safe_id(pid)}.json").write_bytes(keys.seal_data(json.dumps(d).encode()))

    def differential(pkg: SharePackage, d: dict, lang: str) -> Differential:
        pkg = clinic_ddx.with_corrections(pkg, d["corrections"], d["lab_fixes"])
        rejected = {k for k, v in d["terms"].items() if v == "rejected"}
        entries = clinic_ddx.with_answers(pkg.entries, d["answers"], rejected)
        entries = clinic_ddx.with_labs(onto, entries, pkg.labs, d["labs"])  # abnormal labs as features, rejected rows left out
        normal = clinic_ddx.lab_normal(pkg.labs, d["labs"])  # measured and within range: never asked, never "missing"
        answered = {a["feature_id"] for a in d["answers"]}
        conds = clinic_ddx.conditions(onto, entries, lang, measured_normal=normal)
        q = clinic_ddx.question(onto, entries, answered, lang, measured_normal=normal) if conds else None
        n_terms = len(evidence_from(entries, onto))
        note = "" if conds else ("Not enough specific findings yet to suggest conditions." if lang != "it"
                                 else "Non ci sono ancora abbastanza elementi specifici per suggerire condizioni.")
        return Differential(conditions=conds, question=q, answers=d["answers"], n_terms=n_terms, note=note)

    def purge(pid: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            (decisions_dir / f"{pid}.json").unlink()
        for d in (inbox_dir, briefs_dir):
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

    def decided(pkg: SharePackage, drop_rejected: bool) -> SharePackage:
        """The package with the clinic's decisions applied. A row or term the clinician confirmed no longer asks for a check;
        a rejected one is dropped (`drop_rejected`) or kept marked, so the page can offer undo."""
        d = load_decisions(pkg.package_id)
        pkg = clinic_ddx.with_corrections(pkg, d["corrections"], d["lab_fixes"])
        labs = []
        for l in pkg.labs:
            v = d["labs"].get(l.id) if l.id else None
            if v == "rejected" and drop_rejected:
                continue
            labs.append(l.model_copy(update={"decision": v if v in ("confirmed", "rejected", "corrected") else None}))
        ents = []
        for x in pkg.entities:
            v = d["terms"].get(x.id) if x.id else None
            if v == "rejected" and drop_rejected:
                continue
            ents.append(x.model_copy(update={"needs_review": False, "reviewed": True}) if v == "confirmed" else x)
        return pkg.model_copy(update={"labs": labs, "entities": ents})

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
                        **sharing.counts(pkg), "entries": len(pkg.entries), "brief_state": state,
                        "second_opinion": pkg.second_opinion})
        return out

    @app.get("/api/inbox/{pid}")
    def get_pkg(pid: str) -> SharePackage:
        return decided(open_pkg(pid), drop_rejected=False)

    @app.api_route("/api/inbox/{pid}/labs/{lab_id}", methods=["PATCH", "PUT"])
    def decide_lab(pid: str, lab_id: str, body: LabDecisionIn) -> dict:
        """The clinician confirms, rejects or corrects one lab value (`accepted` is an alias of `confirmed`). `corrected`
        stores the value (and unit) the clinician read on the printed row; the reading then counts with that value.
        Returns the clinic's decisions, `labs` keyed by row id, `lab_fixes` the corrections."""
        pkg = open_pkg(pid)
        row = next((l for l in pkg.labs if l.id == lab_id), None)
        if row is None:
            raise HTTPException(404, "lab row not found")
        fix = lab_fix(row, body) if body.decision == "corrected" else None
        write_lab_decisions(pid, [row], body.decision, "row", {lab_id: fix} if fix else None)
        return load_decisions(pid)

    def lab_fix(row, body: LabDecisionIn) -> dict:
        """{"from", "to"} for a corrected reading, or 422 when nothing usable or nothing different was given."""
        was = {"value_numeric": row.value_numeric, "value_text": row.value_text, "unit": row.unit}
        to = dict(was)
        if (body.value or "").strip():
            to.update({"value_numeric": None, "value_text": None, **docs.parse_lab_value(body.value or "")})
        elif body.value_numeric is not None:
            to.update(value_numeric=body.value_numeric, value_text=None)
        elif (body.value_text or "").strip():
            to.update(value_numeric=None, value_text=(body.value_text or "").strip())
        if body.unit is not None:
            to["unit"] = body.unit.strip()
        if to["value_numeric"] is None and not to["value_text"]:
            raise HTTPException(422, "A corrected reading needs a number or a printed result")
        if to["value_numeric"] is not None and not math.isfinite(to["value_numeric"]):
            raise HTTPException(422, "The corrected value is not a number")
        if to == was:
            raise HTTPException(422, "The correction is the same as the reading: confirm it instead")
        return {"from": was, "to": to, "at": now_iso()}

    @app.post("/api/inbox/{pid}/labs/decide")
    def decide_labs(pid: str, body: LabBulkIn) -> SharePackage:
        """Confirm or reject many readings that still need a check at once: all of them, one test, or one page of one report."""
        pkg = decided(open_pkg(pid), drop_rejected=False)
        rows = [l for l in pkg.labs if lab_needs_check(l)
                and (body.test_key is None or (l.test_key or l.test_name) == body.test_key)
                and (body.page is None or (l.page == body.page and (body.entry_id is None or l.entry_id == body.entry_id)))]
        scope = "test" if body.test_key else "page" if body.page is not None else "all"
        write_lab_decisions(pid, rows, body.decision, scope)
        return decided(open_pkg(pid), drop_rejected=False)

    def write_lab_decisions(pid: str, rows: list, decision: str, scope: str, fixes: dict | None = None) -> None:
        b = load_brief(pid)
        if b and b.finalized:
            raise HTTPException(409, "Brief is final")
        decision = {"accepted": "confirmed"}.get(decision, decision)
        if decision not in ("pending", "confirmed", "rejected", "corrected"):
            raise HTTPException(422, "decision must be pending, confirmed, rejected or corrected")
        if decision == "corrected" and not fixes:
            raise HTTPException(422, "corrected needs the value read on the report")
        d = load_decisions(pid)
        at = now_iso()
        with labdec_log.open("a") as fh:  # one row per lab, ids and timing only: no values, no diary text
            for r in rows:
                d["lab_fixes"].pop(r.id, None)
                if decision == "pending":
                    d["labs"].pop(r.id, None)
                else:
                    d["labs"][r.id] = decision
                changed = None
                if decision == "corrected" and fixes and r.id in fixes:
                    was, to = fixes[r.id]["from"], fixes[r.id]["to"]
                    d["lab_fixes"][r.id] = fixes[r.id]
                    changed = []  # which fields, never the values
                    if (was["value_numeric"], was["value_text"]) != (to["value_numeric"], to["value_text"]):
                        changed.append("value")
                    if was["unit"] != to["unit"]:
                        changed.append("unit")
                fh.write(json.dumps({"package_id": pid, "lab_id": r.id, "decision": decision, "scope": scope, "at": at,
                                     **({"changed": changed} if changed is not None else {})}) + "\n")
        save_decisions(pid, d)

    @app.get("/api/inbox/{pid}/overview")
    def get_overview(pid: str, lang: str = "en") -> dict:
        """Plain-words summary of the package for the first look: no model call, no codes."""
        d = load_decisions(pid)
        pkg = clinic_ddx.with_corrections(open_pkg(pid), d["corrections"], d["lab_fixes"])
        rejected = {k for k, v in (d.get("labs") or {}).items() if v == "rejected"}  # as the lab table leaves them out
        pkg = pkg.model_copy(update={"labs": [l for l in pkg.labs if l.id not in rejected]})
        return overview_mod.overview(pkg, onto, norm_lang(lang))

    @app.get("/api/inbox/{pid}/decisions")
    def get_decisions(pid: str) -> dict:
        open_pkg(pid)
        return load_decisions(pid)

    @app.patch("/api/inbox/{pid}/terms/{ent_id}")
    def decide_term(pid: str, ent_id: str, body: TermDecisionIn) -> dict:
        """The clinician confirms, rejects or replaces a term the extractor was unsure about. Rejected terms leave the
        differential; a replaced term (`corrected` with `hpo_id`, alias `replaced`) counts as the clinician's term in the
        overview, the differential and the brief. `pending` undoes any of them."""
        pkg = open_pkg(pid)
        decision = {"replaced": "corrected"}.get(body.decision, body.decision)
        if decision not in ("confirmed", "rejected", "corrected", "pending"):
            raise HTTPException(422, "decision must be confirmed, rejected, corrected or pending")
        ent = next((x for x in pkg.entities if x.id == ent_id), None)
        if ent is None:
            raise HTTPException(404, "term not found")
        if decision == "corrected" and ent.family_history:
            raise HTTPException(422, "a relative's condition stays family history and cannot be replaced")
        d = load_decisions(pid)
        had = ent_id in d["corrections"]
        new_id = None
        if decision == "corrected":
            b = load_brief(pid)
            if b and b.finalized:
                raise HTTPException(409, "Brief is final")
            new_id = (body.hpo_id or "").strip().upper()
            if not re.fullmatch(r"HP:\d{7}", new_id) or not onto.exists(new_id):
                raise HTTPException(422, "corrected needs the id of a term from the term list")
            if new_id == ent.hpo_id:
                raise HTTPException(422, "pick a different term, or confirm this one")
            d["corrections"][ent_id] = {"from": ent.hpo_id, "from_label": ent.canonical, "to": new_id,
                                        "label": onto.label(new_id), "at": now_iso()}
        else:
            d["corrections"].pop(ent_id, None)
        if decision == "pending":
            d["terms"].pop(ent_id, None)
        else:
            d["terms"][ent_id] = decision
        save_decisions(pid, d)
        with termdec_log.open("a") as fh:  # ids and HPO ids only: no quote, no diary text
            fh.write(json.dumps({"package_id": pid, "term_id": ent_id, "decision": decision, "from": ent.hpo_id,
                                 "to": new_id, "at": now_iso()}) + "\n")
        if had or decision == "corrected":
            refresh_brief_terms(pid)
        return d

    def refresh_brief_terms(pid: str) -> None:
        """A draft brief lists the patient's terms as they were when it was drafted: rebuild those lines after a term was
        replaced (or a replacement undone). AI lines stay as they are, with their review state."""
        b = load_brief(pid)
        if not b or b.finalized:
            return
        pkg = decided(open_pkg(pid), drop_rejected=True)
        kept = [i for i in b.items if i.origin == "ai" or (i.origin == "document" and i.section != "labs")]
        save_brief(b.model_copy(update={"items": specialty.tag(pkg, briefing.patient_items(pkg, b.lang) + kept, onto)}))

    @app.get("/api/inbox/{pid}/terms/{ent_id}/candidates")
    def term_candidates(pid: str, ent_id: str, lang: str = "en") -> list[Term]:
        """Other ontology terms for the patient's words, for the clinician to pick a replacement. No model call."""
        pkg = open_pkg(pid)
        ent = next((x for x in pkg.entities if x.id == ent_id), None)
        if ent is None:
            raise HTTPException(404, "term not found")
        return clinic_ddx.replacement_candidates(onto, ent.quote, ent.canonical, ent.hpo_id, norm_lang(lang))

    @app.get("/api/inbox/{pid}/ddx")
    async def get_ddx(pid: str, lang: str = "en") -> Differential:
        pkg = open_pkg(pid)
        d = load_decisions(pid)
        return await asyncio.to_thread(differential, pkg, d, norm_lang(lang))

    @app.post("/api/inbox/{pid}/ddx/answer")
    async def ddx_answer(pid: str, body: ClinicAnswerIn) -> dict:
        """Record what the clinician found, score again, and return the ranking before and after plus the next question."""
        if body.answer not in ("yes", "no", "unsure"):
            raise HTTPException(422, "answer must be yes, no or unsure")
        label = onto.label(body.feature_id)
        if label is None:
            raise HTTPException(422, "Unknown feature")
        pkg = open_pkg(pid)
        lang = norm_lang(body.lang)
        d = load_decisions(pid)
        before = await asyncio.to_thread(differential, pkg, d, lang)
        d["answers"] = [a for a in d["answers"] if a["feature_id"] != body.feature_id]
        d["answers"].append({"feature_id": body.feature_id, "label": term_label(body.feature_id, label, lang),
                             "answer": body.answer, "at": now_iso()})
        save_decisions(pid, d)
        after = await asyncio.to_thread(differential, pkg, d, lang)
        return {"before": [c.model_dump() for c in before.conditions], "differential": after.model_dump()}

    @app.delete("/api/inbox/{pid}/ddx/answers")
    async def ddx_reset(pid: str, lang: str = "en") -> Differential:
        pkg = open_pkg(pid)
        d = load_decisions(pid)
        d["answers"] = []
        save_decisions(pid, d)
        return await asyncio.to_thread(differential, pkg, d, norm_lang(lang))

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
            items = specialty.tag(pkg, briefing.patient_items(pkg, lang) + briefing.check_ai_items(pkg, parsed, lang), onto)
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
        pkg = decided(open_pkg(pid), drop_rejected=True)
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
        out = briefing.render_brief(pkg, b, aud, lg, onto)
        return specialty.tag_brief(pkg, out, onto) if aud == "clinician" else out

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
        dpkg = decided(open_pkg(pid), drop_rejected=True)
        unchecked = [l for l in dpkg.labs if lab_needs_check(l)]
        if unchecked:
            raise HTTPException(409, f"{len(unchecked)} lab reading(s) still need a check")
        pending = [i for i in b.items if i.review == "pending" and i.section != "labs"]
        if pending:
            raise HTTPException(409, f"{len(pending)} AI item(s) still need review")
        b = specialty.tag_brief(dpkg, briefing.with_labs(b, dpkg, b.lang), onto)
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

    @app.get("/api/inbox/{pid}/compare")
    async def compare_opinions(pid: str, lang: str = "en") -> dict:
        """Second opinion only, after this doctor finalized the brief: the previous doctor's conclusions next to this
        doctor's (conditions computed in code from the facts, brief lines as decided), disagreements marked."""
        full = open_full(pid)
        if not full.second_opinion:
            raise HTTPException(404, "This package is not a second opinion")
        b = load_brief(pid)
        if not b or not b.finalized:
            raise HTTPException(409, "The previous opinion opens after you finalize your brief")
        lang = norm_lang(lang)
        pkg = second.facts_only(full)
        ddx = await asyncio.to_thread(differential, pkg, load_decisions(pid), lang)
        if full.previous is None:
            return {"previous": None, "current": None, "rows": [], "disagreements": 0, "since_previous": []}
        dpkg = decided(pkg, drop_rejected=True)
        return second.compare(full.previous, ddx.conditions, b,
                              second.since_previous(dpkg, full.previous.date, onto, lang))

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
