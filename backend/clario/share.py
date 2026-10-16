"""Patient -> clinic sharing.

The patient picks a period. The entries in that period and their terms (never rejected ones) leave the device,
sealed with the clinic's X25519 public key (libsodium sealed box): only the clinic server can open it.
Packages carry an expiry; the clinic rejects expired ones and purges them.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from nacl.public import PrivateKey, PublicKey, SealedBox

from .models import COUNTED, REVIEWED, Entity, Entry, LabResult, Pattern, SharedEntity, SharedLab, SharePackage


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(public_key: bytes) -> str:
    h = hashlib.sha256(public_key).hexdigest()[:20].upper()
    return " ".join(h[i:i + 4] for i in range(0, 20, 4))


def alias(seed: str) -> str:
    """Stable, non-identifying alias for the patient (from the vault salt)."""
    words = ["Ash", "Birch", "Cedar", "Elm", "Fern", "Hazel", "Juniper", "Linden", "Maple", "Olive", "Rowan", "Willow"]
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return f"{words[h % len(words)]}-{h % 1000:03d}"


def patient_mentions(entities: list[SharedEntity]) -> list[SharedEntity]:
    """What counts as the patient's own terms: not negated, not about a relative. Every count uses this."""
    return [x for x in entities if not x.negated and not x.family_history]


def term_count(entities: list[SharedEntity]) -> int:
    return len({x.hpo_id or x.canonical.lower() for x in patient_mentions(entities) if x.type != "lab"})


def counts(pkg: SharePackage) -> dict[str, int]:
    """The numbers both screens show ("N mentions of M terms"), from one place."""
    ms = patient_mentions(pkg.entities)
    return {"entities": len(ms), "mentions": len(ms), "terms": term_count(pkg.entities), "labs": len(pkg.labs)}


def _clinic_copy(x: Entity) -> Entity:
    """A relative's condition leaves as family history only: no ontology id the clinic could count as the patient's."""
    return x.model_copy(update={"hpo_id": None, "hpo_label": None}) if x.family_history else x


def shared_labs(labs: list[LabResult], since: str, until: str, batch_entry: dict[str, str] | None = None) -> list[SharedLab]:
    """Lab rows in the period, except rejected ones. Rows nobody checked are marked; low-confidence rows ask the clinician."""
    batch_entry = batch_entry or {}
    rows = [l for l in labs if since <= l.date <= until and l.review in COUNTED]
    rows.sort(key=lambda l: (l.date, l.test_key, l.page))
    return [SharedLab(id=l.id, test_name=l.test_name, value_numeric=l.value_numeric, value_text=l.value_text, unit=l.unit,
                      ref_low=l.ref_low, ref_high=l.ref_high, flag=l.flag, date=l.date, page=l.page,
                      entry_id=batch_entry.get(l.batch_id), reviewed=l.review in REVIEWED, confidence=l.confidence,
                      needs_review=l.review == "needs_review") for l in rows]


def build_package(entries: list[Entry], since: str, until: str, patient_alias: str, note: str | None,
                  patterns: list[Pattern], expires_hours: int, labs: list[LabResult] | None = None,
                  batch_entry: dict[str, str] | None = None, profile: dict | None = None) -> SharePackage:
    chosen = sorted((e for e in entries if since <= e.occurred_on <= until), key=lambda e: e.occurred_on)
    shared_entities, slim = [], []
    for e in chosen:
        kept = [_clinic_copy(x) for x in e.entities if x.review in COUNTED]  # rejected never leaves
        shared_entities += [SharedEntity(id=x.id, entry_id=e.id, occurred_on=e.occurred_on, type=x.type, quote=x.quote,
                                         canonical=x.canonical, hpo_id=x.hpo_id, negated=x.negated,
                                         family_history=x.family_history, severity=x.severity, onset_hint=x.onset_hint,
                                         reviewed=x.review in REVIEWED, confidence=x.confidence,
                                         needs_review=x.review == "needs_review") for x in kept]
        slim.append(e.model_copy(update={"entities": kept}))
    created = datetime.now(timezone.utc)
    return SharePackage(package_id=f"pkg_{uuid.uuid4().hex[:12]}", patient_alias=patient_alias,
                        created_at=created.isoformat(timespec="seconds"),
                        expires_at=(created + timedelta(hours=expires_hours)).isoformat(timespec="seconds"),
                        period=(since, until), note=note, profile=profile or None, entries=slim, entities=shared_entities,
                        labs=shared_labs(labs or [], since, until, batch_entry), patterns=patterns)


def seal(package: SharePackage, clinic_public_key_b64: str) -> str:
    box = SealedBox(PublicKey(base64.b64decode(clinic_public_key_b64)))
    return base64.b64encode(box.encrypt(package.model_dump_json().encode())).decode()


class ClinicKeys:
    """The clinic server's long-lived keypair, stored with 0600 permissions."""

    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / "clinic.key"
        if not path.exists():
            path.write_bytes(bytes(PrivateKey.generate()))
            path.chmod(0o600)
        self._sk = PrivateKey(path.read_bytes())
        # data-at-rest key: HKDF of the clinic's private key (0600 file), same AES-256-GCM as the patient vault
        self._data = AESGCM(HKDF(hashes.SHA256(), 32, None, b"clario-clinic-data-v1").derive(bytes(self._sk)))

    def seal_data(self, data: bytes) -> bytes:
        """Encrypt something the clinic stores on disk (briefs, call previews). nonce || ciphertext."""
        from .vault import Vault

        return Vault._seal(self._data, data)

    def open_data(self, blob: bytes) -> bytes:
        from .vault import Vault

        return Vault._open(self._data, blob)

    @property
    def public_b64(self) -> str:
        return base64.b64encode(bytes(self._sk.public_key)).decode()

    @property
    def fingerprint(self) -> str:
        return fingerprint(bytes(self._sk.public_key))

    def open(self, sealed_b64: str) -> SharePackage:
        data = SealedBox(self._sk).decrypt(base64.b64decode(sealed_b64))
        return SharePackage.model_validate(json.loads(data))


def is_expired(pkg: SharePackage) -> bool:
    return datetime.fromisoformat(pkg.expires_at) <= datetime.now(timezone.utc)


def qr_svg(payload: str) -> str:
    import segno

    return segno.make(payload, error="m").svg_data_uri(scale=6, dark="#1C2321", light="#FFFFFF")
