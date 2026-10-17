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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from nacl.public import PrivateKey, PublicKey, SealedBox

from typing import Callable

from .documents import crop_row, is_off, lab_flag
from .models import (COUNTED, REVIEWED, Entity, Entry, LabResult, Pattern, PriorOpinion, PriorTest, SharedEntity, SharedLab,
                     SharePackage, TriedTreatment)


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
    """What counts as the patient's own current terms: not negated, not about a relative, not past history. Every count
    uses this."""
    return [x for x in entities if not x.negated and not x.family_history and not x.past]


def past_mentions(entities: list[SharedEntity]) -> list[SharedEntity]:
    """The patient's past history ("knee surgery 5 years ago", clario/past.py): listed apart, never counted as current."""
    return [x for x in entities if x.past and not x.negated and not x.family_history]


def term_count(entities: list[SharedEntity]) -> int:
    return len({x.hpo_id or x.canonical.lower() for x in patient_mentions(entities) if x.type != "lab"})


def counts(pkg: SharePackage) -> dict[str, int]:
    """The numbers both screens show ("N mentions of M terms"), from one place."""
    ms = patient_mentions(pkg.entities)
    return {"entities": len(ms), "mentions": len(ms), "terms": term_count(pkg.entities), "labs": len(pkg.labs)}


def _clinic_copy(x: Entity) -> Entity:
    """A relative's condition leaves as family history only: no ontology id the clinic could count as the patient's."""
    return x.model_copy(update={"hpo_id": None, "hpo_label": None}) if x.family_history else x


# English names for the tests the shipped Italian referti print; test_name stays as printed.
LAB_NAMES_EN = {
    "proteineurinarie": "Urine protein", "sodio": "Sodium", "pcr": "CRP", "mcv": "MCV", "c3": "C3", "c4": "C4",
    "glicemia": "Glucose", "emoglobina": "Hemoglobin", "antidsdna": "Anti-dsDNA", "neutrofili": "Neutrophils",
    "ematocrito": "Hematocrit", "ft3": "FT3", "tsh": "TSH", "ves": "ESR", "potassio": "Potassium", "ana": "ANA",
    "alt": "ALT", "creatinina": "Creatinine", "piastrine": "Platelets", "vitamina d": "Vitamin D", "vitamind": "Vitamin D", "vitaminad": "Vitamin D",
    "colesterolototale": "Total cholesterol", "sideremia": "Serum iron", "globulibianchi": "White blood cells",
    "globulirossi": "Red blood cells", "azotemia": "Blood urea nitrogen", "linfociti": "Lymphocytes",
}
RECENT_DAYS = 365
# Row crops in a package: the printed line only (no header, so no name or date of birth). Rows that need a check go
# first, then out-of-range rows, then the rest, until the budget is spent. A crop above the cap is left out.
CROP_MAX_BYTES = 40_000
CROPS_MAX_BYTES = 1_500_000


def lab_abnormal(l: LabResult | SharedLab) -> bool:
    """Out of range: low, high, or a positive qualitative result (one rule, `documents.compute_flag`)."""
    return is_off(lab_flag(l))


def lab_needs_check(l: SharedLab) -> bool:
    """A reading the clinician still has to confirm or reject. Blocks finalizing the brief."""
    return l.needs_review and l.decision is None


def shared_labs(labs: list[LabResult], since: str, until: str, batch_entry: dict[str, str] | None = None,
                page_jpeg: Callable[[str, int], bytes | None] | None = None) -> list[SharedLab]:
    """Lab history a clinic needs: every result of each test that appears in the period (so an earlier positive stays
    visible next to a later negative), plus any out-of-range result from the 12 months before the end date.
    Every row except rejected ones; nobody-checked rows are marked and low-confidence rows ask the clinician.
    `page_jpeg(batch_id, page)` gives the stored page image: each row with a known position carries a crop of its printed
    line, so the clinician can compare the reading with the paper."""
    batch_entry = batch_entry or {}
    ok = [l for l in labs if l.date <= until and l.review in COUNTED]
    in_period = {l.test_key for l in ok if since <= l.date <= until}
    floor = (date.fromisoformat(until) - timedelta(days=RECENT_DAYS)).isoformat()
    rows = [l for l in ok if l.test_key in in_period or (l.date >= floor and lab_abnormal(l))]
    rows.sort(key=lambda l: (l.date, l.test_key, l.page))
    crops = row_crops(rows, page_jpeg) if page_jpeg else {}
    return [SharedLab(id=l.id, test_name=l.test_name, value_numeric=l.value_numeric, value_text=l.value_text, unit=l.unit,
                      ref_low=l.ref_low, ref_high=l.ref_high, flag=lab_flag(l), date=l.date, page=l.page,
                      entry_id=batch_entry.get(l.batch_id), reviewed=l.review in REVIEWED, confidence=l.confidence,
                      needs_review=l.review == "needs_review", test_key=l.test_key, name_en=LAB_NAMES_EN.get(l.test_key),
                      abnormal=lab_abnormal(l), checks=list(l.checks), crop=crops.get(l.id)) for l in rows]


def row_crops(rows: list[LabResult], page_jpeg: Callable[[str, int], bytes | None]) -> dict[str, str]:
    """Row id -> JPEG data URL of its printed line, within CROPS_MAX_BYTES (rows to check first)."""
    order = sorted((l for l in rows if l.box), key=lambda l: (l.review != "needs_review", not lab_abnormal(l), l.date))
    pages: dict[tuple[str, int], bytes | None] = {}
    out: dict[str, str] = {}
    spent = 0
    for l in order:
        k = (l.batch_id, l.page)
        if k not in pages:
            pages[k] = page_jpeg(*k)
        if not pages[k]:
            continue
        try:
            jpg = crop_row(pages[k], l.box)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - a bad page image only loses the picture, never the reading
            continue
        if len(jpg) > CROP_MAX_BYTES or spent + len(jpg) > CROPS_MAX_BYTES:
            continue
        spent += len(jpg)
        out[l.id] = "data:image/jpeg;base64," + base64.b64encode(jpg).decode()
    return out


def build_package(entries: list[Entry], since: str, until: str, patient_alias: str, note: str | None,
                  patterns: list[Pattern], expires_hours: int, labs: list[LabResult] | None = None,
                  batch_entry: dict[str, str] | None = None, profile: dict | None = None,
                  page_jpeg: Callable[[str, int], bytes | None] | None = None, care: dict | None = None,
                  second_opinion: bool = False) -> SharePackage:
    """`care` is what the vault keeps about earlier care (`{tried, tested, previous}`): the facts (`tried`, `tested`, up
    to the end date) go with every share; the previous doctor's conclusions (`previous`) only with a second opinion."""
    care = care or {}
    tried = [TriedTreatment.model_validate(t) for t in care.get("tried") or [] if (t.get("started") or "") <= until]
    tested = [PriorTest.model_validate(t) for t in care.get("tested") or [] if (t.get("date") or "") <= until]
    previous = PriorOpinion.model_validate(care["previous"]) if second_opinion and care.get("previous") else None
    chosen = sorted((e for e in entries if since <= e.occurred_on <= until), key=lambda e: e.occurred_on)
    shared_entities, slim = [], []
    for e in chosen:
        kept = [_clinic_copy(x) for x in e.entities if x.review in COUNTED]  # rejected never leaves
        shared_entities += [SharedEntity(id=x.id, entry_id=e.id, occurred_on=e.occurred_on, type=x.type, quote=x.quote,
                                         canonical=x.canonical, hpo_id=x.hpo_id, negated=x.negated,
                                         family_history=x.family_history, severity=x.severity, onset_hint=x.onset_hint,
                                         reviewed=x.review in REVIEWED, confidence=x.confidence,
                                         needs_review=x.review == "needs_review",
                                         from_question="from_question" in x.flags, past=x.past) for x in kept]
        slim.append(e.model_copy(update={"entities": kept}))
    created = datetime.now(timezone.utc)
    return SharePackage(package_id=f"pkg_{uuid.uuid4().hex[:12]}", patient_alias=patient_alias,
                        created_at=created.isoformat(timespec="seconds"),
                        expires_at=(created + timedelta(hours=expires_hours)).isoformat(timespec="seconds"),
                        period=(since, until), note=note, profile=profile or None, entries=slim, entities=shared_entities,
                        labs=shared_labs(labs or [], since, until, batch_entry, page_jpeg), patterns=patterns,
                        second_opinion=second_opinion, tried=tried, tested=tested, previous=previous)


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
