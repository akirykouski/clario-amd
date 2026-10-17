"""Doctor verify (demo): show the patient's conclusions to a doctor in the room, with the patient's tap as the check.

Two parts live in the vault: facts (diary, quotes, labs) belong to the patient always; conclusions (a previous doctor's
diagnosis and condition names, `care.previous`) are released to a doctor tab for one session, and only after the patient
has seen the register line the doctor claimed and tapped Confirm. The patient screens never receive the conclusions.

Flow: patient `start` -> doctor opens `/doctor/<code>`, `lookup` (name, surname, province), `claim` a hit and gets a
`doctor_token` once (held in the tab's memory only) -> patient `status` shows the hit, `confirm` or `reject` -> doctor
reads `conclusions` with `X-Doctor-Token` -> `end` from either side. Closing the doctor tab drops the token.

DEMO ONLY: the register below is a fixture of synthetic people. A real pilot has a person check the public Albo Unico
(albounico.fnomceo.it); a match proves a name is on the albo, not that the phone holder is that doctor. This module never
calls or scrapes any site. The state is in memory (one active session), so a server restart ends it.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException

from .knowledge import fold
from .models import (PriorOpinion, VerifyAuditRow, VerifyClaim, VerifyClaimIn, VerifyConclusions, VerifyDoctorStatus,
                     VerifyHit, VerifyLookup, VerifyLookupIn, VerifyStarted, VerifyStatus)
from .vault import Locked, Vault

REGISTER_NOTE = ("Demo register with synthetic doctors. In a pilot a person checks the public Albo Unico "
                 "(albounico.fnomceo.it); no site is called from this app.")
PENDING_TTL = 15 * 60  # a code works for 15 minutes until the patient decides
OPEN_TTL = 60 * 60  # a confirmed session lasts at most an hour, or until either side ends it
MAX_LOOKUPS = 20
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L

# (id, surname, name, province, sigla, albo). Synthetic people only; any resemblance to a real doctor is chance.
MEDICI = "Albo medici chirurghi"
ODONTO = "Albo odontoiatri"
RegEntry = tuple[str, str, str, str, str, str]
REGISTER: list[RegEntry] = [
    ("demo-001", "Rossi", "Maria", "Milano", "MI", MEDICI),
    ("demo-002", "Rossi", "Maria", "Roma", "RM", MEDICI),
    ("demo-003", "Bianchi", "Luca", "Torino", "TO", MEDICI),
    ("demo-004", "Esposito", "Niccolò", "Napoli", "NA", MEDICI),
    ("demo-005", "Ferrari", "Chiara", "Bologna", "BO", ODONTO),
    ("demo-006", "D'Angelo", "Giovanni", "Milano", "MI", MEDICI),
    ("demo-007", "Marino", "Elena", "Roma", "RM", ODONTO),
    ("demo-008", "Conti", "Andrea", "Torino", "TO", MEDICI),
    ("demo-009", "Greco", "Giulia", "Napoli", "NA", MEDICI),
]
PROVINCES = sorted({r[3] for r in REGISTER})


def display(r: RegEntry) -> str:
    return f"{r[1]} {r[2]}, Ordine di {r[3]}, {r[5]}"


def _norm(s: str) -> str:
    return " ".join(fold(s).replace("'", " ").replace("’", " ").split())


def search(name: str, surname: str, province: str) -> list[VerifyHit]:
    """Exact match on name, surname and province (or its two-letter sigla), ignoring case, accents and spacing."""
    n, s, p = _norm(name), _norm(surname), _norm(province)
    if not (n and s and p):
        return []
    return [VerifyHit(id=r[0], display=display(r)) for r in REGISTER
            if _norm(r[2]) == n and _norm(r[1]) == s and p in (_norm(r[3]), _norm(r[4]))]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


@dataclass
class Session:
    code: str
    expires: float
    state: str = "waiting"
    hit: RegEntry | None = None
    token: str | None = None
    lookups: int = 0
    conclusions: list[dict] | None = None  # snapshot taken at Confirm, held in memory only
    audit: list[VerifyAuditRow] = field(default_factory=list)

    @property
    def who(self) -> str | None:
        return display(self.hit) if self.hit else None


class Verifier:
    def __init__(self, vault: Vault, clock=time.time):
        self.vault, self.clock = vault, clock
        self._lock = threading.RLock()
        self._s: Session | None = None

    def _log(self, s: Session, event: str) -> None:
        s.audit.append(VerifyAuditRow(ts=_iso(self.clock()), event=event, who=s.who))  # type: ignore[arg-type]

    def _require_open(self) -> None:
        if self.vault.locked:
            raise Locked("Diary is locked")

    def _get(self, code: str) -> Session:
        s = self._s
        if s is None or not secrets.compare_digest(s.code, code.strip().upper()):
            raise HTTPException(404, "unknown code")
        if s.state in ("waiting", "claimed", "confirmed") and self.clock() >= s.expires:
            self._close(s, "expired", "expired")
        return s

    @staticmethod
    def _token_ok(s: Session, token: str | None) -> bool:
        return bool(token and s.token and secrets.compare_digest(s.token, token))

    def _close(self, s: Session, state: str, event: str) -> None:
        s.state, s.token, s.conclusions = state, None, None
        self._log(s, event)

    def _patient_view(self, s: Session) -> VerifyStatus:
        return VerifyStatus(state=s.state, hit_display=s.who, expires_at=_iso(s.expires), audit=list(s.audit))  # type: ignore[arg-type]

    # ---- patient (vault open)
    def start(self) -> VerifyStarted:
        self._require_open()
        with self._lock:
            if self._s and self._s.state in ("waiting", "claimed", "confirmed"):
                self._close(self._s, "ended", "ended")  # one active session at a time
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            s = self._s = Session(code=code, expires=self.clock() + PENDING_TTL)
            self._log(s, "started")
            return VerifyStarted(code=code, doctor_path=f"/doctor/{code}", expires_at=_iso(s.expires), register_note=REGISTER_NOTE)

    def status(self, code: str) -> VerifyStatus:
        self._require_open()
        with self._lock:
            return self._patient_view(self._get(code))

    def confirm(self, code: str) -> VerifyStatus:
        self._require_open()
        with self._lock:
            s = self._get(code)
            if s.state != "claimed":
                raise HTTPException(409, f"cannot confirm in state {s.state}")
            prev = (self.vault.get("care") or {}).get("previous")
            s.conclusions = [PriorOpinion.model_validate(prev).model_dump()] if prev else []
            s.state, s.expires = "confirmed", self.clock() + OPEN_TTL
            self._log(s, "confirmed")
            return self._patient_view(s)

    def reject(self, code: str) -> VerifyStatus:
        self._require_open()
        with self._lock:
            s = self._get(code)
            if s.state not in ("waiting", "claimed"):
                raise HTTPException(409, f"cannot reject in state {s.state}")
            self._close(s, "rejected", "rejected")
            return self._patient_view(s)

    def end(self, code: str, token: str | None) -> dict:
        """Either side: the doctor with the token, or the patient with the vault open."""
        with self._lock:
            s = self._get(code)
            if not self._token_ok(s, token):
                self._require_open()
            if s.state in ("waiting", "claimed", "confirmed"):
                self._close(s, "ended", "ended")
            return {"ok": True, "state": s.state}

    # ---- doctor (no vault)
    def lookup(self, code: str, body: VerifyLookupIn) -> VerifyLookup:
        with self._lock:
            s = self._get(code)
            if s.state != "waiting":
                raise HTTPException(409, f"session is {s.state}")
            s.lookups += 1
            if s.lookups > MAX_LOOKUPS:
                raise HTTPException(429, "too many lookups for this code")
            return VerifyLookup(register_note=REGISTER_NOTE, hits=search(body.name, body.surname, body.province))

    def claim(self, code: str, body: VerifyClaimIn) -> VerifyClaim:
        with self._lock:
            s = self._get(code)
            if s.state != "waiting":
                raise HTTPException(409, f"session is {s.state}")
            hit = next((r for r in REGISTER if r[0] == body.hit_id), None)
            if hit is None:
                raise HTTPException(404, "unknown register entry")
            s.hit, s.token, s.state = hit, secrets.token_urlsafe(24), "claimed"
            self._log(s, "claimed")
            return VerifyClaim(doctor_token=s.token, hit_display=display(hit))

    def doctor_status(self, code: str, token: str | None) -> VerifyDoctorStatus:
        with self._lock:
            s = self._get(code)
            if s.state == "waiting":
                return VerifyDoctorStatus(state="waiting")
            if s.state in ("claimed", "confirmed") and not self._token_ok(s, token):
                raise HTTPException(403, "invalid doctor token")
            return VerifyDoctorStatus(state=s.state, hit_display=s.who)  # type: ignore[arg-type]

    def conclusions(self, code: str, token: str | None) -> VerifyConclusions:
        with self._lock:
            s = self._get(code)
            if s.state != "confirmed" or not self._token_ok(s, token) or s.conclusions is None:
                raise HTTPException(403, "not released: the patient has not confirmed this doctor")
            self._log(s, "opened")
            prev = [PriorOpinion.model_validate(p) for p in s.conclusions]
            return VerifyConclusions(doctor=s.who or "", previous=prev,
                                     message=None if prev else "No previous opinion is on file for this patient.")


def routes(app: FastAPI, vault: Vault, clock=time.time) -> Verifier:
    v = Verifier(vault, clock)
    app.state.verifier = v

    @app.get("/api/verify/register")
    def verify_register() -> dict:
        return {"register": "demo", "register_note": REGISTER_NOTE, "provinces": PROVINCES}

    @app.post("/api/verify/start")
    def verify_start() -> VerifyStarted:
        return v.start()

    @app.post("/api/verify/{code}/lookup")
    def verify_lookup(code: str, body: VerifyLookupIn) -> VerifyLookup:
        return v.lookup(code, body)

    @app.post("/api/verify/{code}/claim")
    def verify_claim(code: str, body: VerifyClaimIn) -> VerifyClaim:
        return v.claim(code, body)

    @app.get("/api/verify/{code}/status")
    def verify_status(code: str) -> VerifyStatus:
        return v.status(code)

    @app.get("/api/verify/{code}/doctor-status")
    def verify_doctor_status(code: str, x_doctor_token: str | None = Header(None)) -> VerifyDoctorStatus:
        return v.doctor_status(code, x_doctor_token)

    @app.post("/api/verify/{code}/confirm")
    def verify_confirm(code: str) -> VerifyStatus:
        return v.confirm(code)

    @app.post("/api/verify/{code}/reject")
    def verify_reject(code: str) -> VerifyStatus:
        return v.reject(code)

    @app.get("/api/verify/{code}/conclusions")
    def verify_conclusions(code: str, x_doctor_token: str | None = Header(None)) -> VerifyConclusions:
        return v.conclusions(code, x_doctor_token)

    @app.post("/api/verify/{code}/end")
    def verify_end(code: str, x_doctor_token: str | None = Header(None)) -> dict:
        return v.end(code, x_doctor_token)

    return v
