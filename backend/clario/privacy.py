"""Pseudonymization before text leaves the device, and a tamper-evident log of every model call.

Three parts:
  * `pseudonymize(text)`: rule-based removal of direct identifiers. Returns the redacted text and a list of
    replacements (type and positions only, never the original value).
  * `PrivacyLLM`: wraps any LLM. In patient mode with a remote backend it redacts user messages before the call,
    then maps returned quotes back to the ORIGINAL text so grounding still works. Every call is logged.
  * `CallLog`: hash chain of calls. hash = sha256(prev_hash + payload_sha256 + ts + backend + model + purpose),
    so changing, removing or reordering a record is detectable with `verify()`.

Medical content (terms, doses, lab values, scores) is deliberately left alone: the cloud model needs it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .llm import extract_json
from .vault import Locked, Vault

GENESIS = "0" * 64
PURPOSES = ("extract", "rationale", "brief", "next_question", "document", "other")
PLACEHOLDER = {"email": "[EMAIL]", "iban": "[IBAN]", "codice_fiscale": "[CODICE_FISCALE]", "address": "[ADDRESS]",
               "date": "[DATE]", "phone": "[PHONE]", "name": "[NAME]"}
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")


# ====================================================================== pseudonymize
def _ci(word: str) -> str:
    return "".join(f"[{c.upper()}{c.lower()}]" if c.isalpha() else re.escape(c) for c in word)


_MONTHS_FULL = ["january", "february", "march", "april", "june", "july", "august", "september", "october",
                "november", "december", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
                "agosto", "settembre", "ottobre", "novembre", "dicembre"]
_MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec",
                "Gen", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Dic"]
_MONTH = "(?:" + "|".join([_ci(m) for m in _MONTHS_FULL] + ["May"] + [m + r"\.?" for m in _MONTHS_ABBR]) + ")"
_DAY = r"\d{1,2}(?:st|nd|rd|th|°)?"

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_IBAN = re.compile(r"\b[A-Za-z]{2}\d{2}(?:\s?[A-Za-z0-9]{4}){3,7}(?:\s?[A-Za-z0-9]{1,4})?\b")
_CF = re.compile(r"\b[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z]\b")
_NAME_WORD = r"[A-ZÀ-Ý][\w'’]+"
_ADDRESS = [
    re.compile(rf"\b(?i:via|viale|piazza|piazzale|corso|vicolo|largo)\s+(?:(?i:di|del|della|dei|degli|delle|dell['’])\s*)?"
               rf"{_NAME_WORD}(?:\s+{_NAME_WORD}){{0,2}}(?:,?\s*(?:(?i:n\.?|civico)\s*)?\d{{1,4}}[A-Za-z]?)?"),
    re.compile(rf"\b\d{{1,4}}\s+{_NAME_WORD}(?:\s+{_NAME_WORD}){{0,2}}\s+(?i:street|st|road|rd|avenue|ave|lane|drive)\b\.?"),
    re.compile(rf"\b{_NAME_WORD}(?:\s+{_NAME_WORD}){{0,2}}\s+(?:Street|Road|Avenue|Lane|Drive)\b(?:,?\s*\d{{1,4}})?"),
]
_DATE = [
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"),
    re.compile(r"\b\d{1,2}([/.-])\d{1,2}\1(?:\d{4}|\d{2})\b"),
    re.compile(rf"\b{_DAY}\s+(?:(?i:of)\s+)?{_MONTH}(?:,?\s+\d{{4}})?\b"),
    re.compile(rf"\b{_MONTH}\s+{_DAY}\b(?:,?\s+\d{{4}})?"),
]
_PHONE = [
    re.compile(r"(?<![\w+])\(?(?:\+|00)\d{1,3}\)?[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?!\d)"),
    re.compile(r"(?<![\d.])3\d{2}[\s.-]?\d{3}[\s.-]?\d{3,4}(?!\d)"),
    re.compile(r"(?<![\d.])0\d{1,3}[\s.-]\d{5,8}(?!\d)"),
    re.compile(r"(?<![\d.])\d{3}[\s.-]\d{3}[\s.-]\d{4}(?!\d)"),
]
_TITLE_NAME = re.compile(r"\b(?:Dr|Dott|Prof|Mr|Mrs|Ms|Sig)(?:\.|\.ssa|\.ra)?(?:ssa)?\s+" + _NAME_WORD)

_NAMES_FILE = Path(__file__).parent / "data" / "first_names.txt"
_name_re: re.Pattern | None = None


def _names() -> re.Pattern:
    global _name_re
    if _name_re is None:
        names = [n.strip() for n in _NAMES_FILE.read_text(encoding="utf-8").splitlines() if n.strip()]
        alts = "|".join(sorted({a for n in names for a in (n, n.upper())}, key=len, reverse=True))
        _name_re = re.compile(rf"\b(?:{alts})\b")
    return _name_re


def _candidates(text: str) -> list[tuple[int, int, str]]:
    """(start, end, type) in priority order (earlier = wins an overlap)."""
    out: list[tuple[int, int, str]] = []

    def add(rx: re.Pattern, typ: str) -> None:
        out.extend((m.start(), m.end(), typ) for m in rx.finditer(text))

    add(_EMAIL, "email")
    add(_IBAN, "iban")
    add(_CF, "codice_fiscale")
    for rx in _ADDRESS:
        add(rx, "address")
    for rx in _DATE:
        add(rx, "date")
    for rx in _PHONE:
        add(rx, "phone")
    add(_TITLE_NAME, "name")
    add(_names(), "name")
    return out


def pseudonymize(text: str) -> tuple[str, list[dict]]:
    """Replace direct identifiers with placeholders.

    Returns (redacted, replacements). Each replacement is {type, start, end, out_start, out_end}: `start/end` index
    the original text, `out_start/out_end` the redacted text. The original values are not stored anywhere.
    """
    taken: list[tuple[int, int, str]] = []
    for s, e, typ in _candidates(text):
        if e > s and all(e <= ts or s >= te for ts, te, _ in taken):
            taken.append((s, e, typ))
    taken.sort()
    parts: list[str] = []
    reps: list[dict] = []
    pos = 0
    out_len = 0
    for s, e, typ in taken:
        chunk = text[pos:s]
        parts.append(chunk)
        out_len += len(chunk)
        ph = PLACEHOLDER[typ]
        parts.append(ph)
        reps.append({"type": typ, "start": s, "end": e, "out_start": out_len, "out_end": out_len + len(ph)})
        out_len += len(ph)
        pos = e
    parts.append(text[pos:])
    return "".join(parts), reps


# ---------------------------------------------------------------------- mapping quotes back
def _to_original(pos: int, reps: list[dict], *, end: bool) -> int:
    """Index in the redacted text -> index in the original. Inside a placeholder, snap to the whole value."""
    delta = 0
    for r in reps:
        if pos <= r["out_start"]:
            break
        if pos < r["out_end"]:
            return r["end"] if end else r["start"]
        delta = r["end"] - r["out_end"]
    return pos + delta


def restore_quote(quote: str, redacted: str, original: str, reps: list[dict]) -> str | None:
    """Map a quote the model copied from the redacted text onto the original text. None if it is not in it."""
    q = re.sub(r"\s+", " ", (quote or "").strip(" .,;:\"'"))
    if len(q) < 2:
        return None
    m = re.search(re.escape(q).replace(r"\ ", r"\s+"), redacted, flags=re.I)
    if not m:
        return None
    s, e = _to_original(m.start(), reps, end=False), _to_original(m.end(), reps, end=True)
    return original[s:e] if e > s else None


class Redaction:
    """What was redacted in one call. Lives only in memory for the duration of the call."""

    def __init__(self) -> None:
        self.pairs: list[tuple[str, str, list[dict]]] = []

    def add(self, original: str, redacted: str, reps: list[dict]) -> None:
        if reps:
            self.pairs.append((original, redacted, reps))

    @property
    def count(self) -> int:
        return sum(len(r) for _, _, r in self.pairs)

    def restore(self, quote: str) -> str:
        for original, redacted, reps in self.pairs:
            got = restore_quote(quote, redacted, original, reps)
            if got:
                return got
        return quote

    def restore_in(self, obj: Any) -> Any:
        """Walk a model output and restore every field called `quote`."""
        if isinstance(obj, BaseModel):
            for name in type(obj).model_fields:
                v = getattr(obj, name)
                if name == "quote" and isinstance(v, str):
                    setattr(obj, name, self.restore(v))
                else:
                    self.restore_in(v)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if k == "quote" and isinstance(v, str):
                    obj[k] = self.restore(v)
                else:
                    self.restore_in(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                self.restore_in(v)
        return obj


# ====================================================================== call log
def now_iso_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def chain_hash(prev_hash: str, payload_sha256: str, ts: str, backend: str, model: str, purpose: str) -> str:
    return sha256(prev_hash + payload_sha256 + ts + backend + model + purpose)


def call_id(seq: int) -> str:
    return f"call_{seq:06d}"


class VaultStore:
    """Calls live in the encrypted vault as kind 'ai_call'."""

    def __init__(self, vault: Vault):
        self.v = vault

    def records(self) -> list[dict]:
        return sorted(self.v.all("ai_call"), key=lambda r: r.get("seq", 0))

    def add(self, rec: dict) -> None:
        self.v.put("ai_call", rec["id"], rec)


class FileStore:
    """Clinic mode: its own append-only JSONL file next to the clinic keys. Holds redacted previews only."""

    def __init__(self, path: Path, keys=None):
        self.path = path
        self.keys = keys  # ClinicKeys: the diary preview text is encrypted at rest when given
        path.parent.mkdir(parents=True, exist_ok=True)

    def _enc(self, rec: dict) -> dict:
        if self.keys and rec.get("redacted_preview"):
            rec = {**rec, "redacted_preview": "enc:" + base64.b64encode(self.keys.seal_data(rec["redacted_preview"].encode())).decode()}
        return rec

    def _dec(self, rec: dict) -> dict:
        pv = rec.get("redacted_preview")
        if self.keys and isinstance(pv, str) and pv.startswith("enc:"):
            try:
                rec = {**rec, "redacted_preview": self.keys.open_data(base64.b64decode(pv[4:])).decode()}
            except Exception:  # noqa: BLE001 - wrong key or damaged: show nothing rather than the cipher text
                rec = {**rec, "redacted_preview": ""}
        return rec

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        recs = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    recs.append(self._dec(json.loads(line)))
                except json.JSONDecodeError:
                    recs.append({"id": "corrupt", "seq": 10 ** 9})
        return sorted(recs, key=lambda r: r.get("seq", 0))

    def add(self, rec: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(self._enc(rec), ensure_ascii=False) + "\n")


class CallLog:
    def __init__(self, store: VaultStore | FileStore):
        self.store = store
        self._lock = threading.Lock()
        self._head: tuple[int, str] | None = None  # (seq, hash) of the last record
        self._pending: list[dict] = []  # calls made while the vault was locked, chained on the next write

    @classmethod
    def for_settings(cls, s, vault: Vault | None, keys=None) -> "CallLog":
        return cls(VaultStore(vault) if vault is not None else FileStore(s.data_dir / "ai_calls.jsonl", keys))

    def _load_head(self) -> tuple[int, str]:
        recs = self.store.records()
        return (recs[-1].get("seq", len(recs)), recs[-1].get("hash", GENESIS)) if recs else (0, GENESIS)

    def append(self, *, backend: str, model: str, purpose: str, preview: str, sent_text: str,
               redacted: bool = False, replacements: int = 0, images: int = 0) -> dict | None:
        purpose = purpose if purpose in PURPOSES else "other"
        entry = {"ts": now_iso_ms(), "backend": backend, "model": model, "purpose": purpose,
                 "redacted_preview": preview[:200], "payload_sha256": sha256(sent_text),
                 "redacted": redacted, "replacements": replacements, "images": images}
        with self._lock:
            self._pending.append(entry)
            try:
                if self._head is None:
                    self._head = self._load_head()
                last = None
                while self._pending:
                    p = self._pending[0]
                    seq, prev = self._head
                    rec = {"id": call_id(seq + 1), "seq": seq + 1, **p, "prev_hash": prev,
                           "hash": chain_hash(prev, p["payload_sha256"], p["ts"], p["backend"], p["model"], p["purpose"])}
                    self.store.add(rec)
                    self._head = (rec["seq"], rec["hash"])
                    self._pending.pop(0)
                    last = rec
                return last
            except Locked:
                self._head = None
                return None

    def calls(self, limit: int = 50) -> list[dict]:
        recs = self.store.records()
        return list(reversed(recs))[: max(1, min(limit, 500))]

    def verify(self) -> dict:
        prev, expect = GENESIS, 1
        recs = self.store.records()
        for r in recs:
            try:
                ok = (r.get("seq") == expect and r.get("id") == call_id(expect) and r.get("prev_hash") == prev
                      and r.get("hash") == chain_hash(prev, r["payload_sha256"], r["ts"], r["backend"], r["model"], r["purpose"]))
            except (KeyError, TypeError):
                ok = False
            if not ok:
                return {"ok": False, "broken_at": r.get("id") or call_id(expect), "count": len(recs)}
            prev, expect = r["hash"], expect + 1
        return {"ok": True, "broken_at": None, "count": len(recs)}


# ====================================================================== LLM wrapper
def should_pseudonymize(s) -> bool:
    """CLARIO_PSEUDONYMIZE=1|0 wins. Default: on for patient mode when the model is remote."""
    if s.pseudonymize is not None:
        return s.pseudonymize
    if s.mode != "patient" or s.offline:
        return False
    return (s.llm_host or "") not in LOCAL_HOSTS


class PrivacyLLM:
    """Delegates to the inner LLM. Redacts user messages when `pseudonymize` is on. Logs every call."""

    def __init__(self, inner, log: CallLog, pseudonymize: bool):
        self._inner, self.log, self.pseudonymize = inner, log, pseudonymize

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    # -- internals
    def _prepare(self, task: str, messages: list[dict], payload: dict | None, purpose: str | None):
        red = Redaction()
        out: list[dict] = []
        last_user = ""
        for m in messages:
            c = m.get("content")
            if m.get("role") == "user" and isinstance(c, str):
                r, reps = pseudonymize(c)
                last_user = r  # the preview always shows redacted text, even when the backend is local
                if self.pseudonymize:
                    red.add(c, r, reps)
                    m = {**m, "content": r}
            elif isinstance(c, list):  # multimodal parts: text is redacted, images pass through
                parts = []
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                        r, reps = pseudonymize(p["text"])
                        last_user = r
                        if self.pseudonymize:
                            red.add(p["text"], r, reps)
                            p = {**p, "text": r}
                    parts.append(p)
                m = {**m, "content": parts}
            out.append(m)
        pl = payload
        if self.pseudonymize and payload and isinstance(payload.get("text"), str):
            pl = {**payload, "text": pseudonymize(payload["text"])[0]}  # the local hint must match what is sent
        self._log(task, out, last_user, purpose, red)
        return out, pl, red

    def _log(self, task: str, sent: list[dict], preview: str, purpose: str | None, red: Redaction) -> None:
        images = sum(1 for m in sent if isinstance(m.get("content"), list)
                     for p in m["content"] if isinstance(p, dict) and p.get("type") != "text")
        task = "extract" if task == "hpo_pick" else task  # the HPO pick is part of extraction
        p = purpose or (task if task in PURPOSES else "other")
        self.log.append(backend=self._inner.backend, model=self._inner.model, purpose=p, preview=preview,
                        sent_text=json.dumps(sent, ensure_ascii=False, sort_keys=True), redacted=self.pseudonymize,
                        replacements=red.count, images=images)

    # -- LLM surface
    async def complete(self, task, messages, *, purpose=None, payload=None, **kw):
        msgs, pl, _red = self._prepare(task, messages, payload, purpose)
        return await self._inner.complete(task, msgs, payload=pl, **kw)

    async def stream(self, task, messages, *, purpose=None, payload=None, **kw):
        msgs, pl, _red = self._prepare(task, messages, payload, purpose)
        async for item in self._inner.stream(task, msgs, payload=pl, **kw):
            yield item

    async def json(self, task, messages, cls, *, purpose=None, payload=None, **kw):
        msgs, pl, red = self._prepare(task, messages, payload, purpose)
        res, st = await self._inner.json(task, msgs, cls, payload=pl, **kw)
        return red.restore_in(res), st

    async def samples(self, task, messages, *args, purpose=None, payload=None, **kw):
        msgs, pl, red = self._prepare(task, messages, payload, purpose)
        texts, st = await self._inner.samples(task, msgs, *args, payload=pl, **kw)
        return [self._restore_text(t, red) for t in texts], st

    @staticmethod
    def _restore_text(text: str, red: Redaction) -> str:
        """Raw JSON text from samples(): restore placeholders inside `quote` fields, leave the rest as sent."""
        if not red.count:
            return text
        try:
            obj = extract_json(text)
        except ValueError:
            return text
        return json.dumps(red.restore_in(obj), ensure_ascii=False)


def wrap(inner, s, log: CallLog) -> PrivacyLLM:
    return PrivacyLLM(inner, log, should_pseudonymize(s))


# ====================================================================== HTTP routes
def routes(app: FastAPI, s, log: CallLog, get_entry: Callable[[str], Any] | None = None) -> None:
    @app.get("/api/privacy/calls")
    def privacy_calls(limit: int = 50) -> list[dict]:
        return log.calls(limit)

    @app.get("/api/privacy/verify")
    def privacy_verify() -> dict:
        return log.verify()

    if get_entry is not None:
        @app.get("/api/privacy/preview")
        def privacy_preview(entry_id: str) -> dict:
            e = get_entry(entry_id)
            if e is None:
                raise HTTPException(404, "entry not found")
            redacted, reps = pseudonymize(e.text)
            return {"original": e.text, "redacted": redacted, "replacements": reps,
                    "applied": should_pseudonymize(s), "backend": s.llm_backend}
