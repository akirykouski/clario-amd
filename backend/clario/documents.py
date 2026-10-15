"""Paper documents -> lab rows.

PDF pages and photos are normalised to JPEG (long side capped), sent to the vision model through the
same OpenAI-compatible client as everything else, and parsed into lab rows. The model only reads what
is printed. Flags are recomputed in code from value and range, and every row gets a confidence that
decides whether a person must look at it (CLARIO_REVIEW_THRESHOLD).
"""

from __future__ import annotations

import base64
import io
import json
import re
import unicodedata
import zlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from .llm import LLM, LLMError, extract_json

TRUTH_PREFIX = "clario-truth:"
MAX_DIM = 1600
JPEG_QUALITY = 82

SYSTEM = """You read one page of a laboratory report (Italian or English) and copy the result table into JSON. \
Return JSON only:
{"date": "<YYYY-MM-DD collection date printed on the page, else null>", "rows": [{"test_name": "<as printed>", \
"value_numeric": <number or null>, "value_text": "<printed result when it is not a plain number, else null>", \
"unit": "<as printed or empty>", "ref_low": <number or null>, "ref_high": <number or null>, \
"flag": "low|high|normal|null", "confidence": <0 to 1, how sure you are this row is read correctly>}]}
Rules: copy exactly what is printed. Italian decimals use a comma: 4,52 means 4.52. A range like "< 5,0" has \
ref_low null and ref_high 5.0. Never guess a value you cannot read: lower the confidence instead. Skip headers, \
names, addresses and footers. Do not interpret results."""


# ------------------------------------------------------------------ truth sidecar (offline fixture + eval)
def encode_truth(doc: dict) -> str:
    raw = zlib.compress(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode())
    return TRUTH_PREFIX + base64.b64encode(raw).decode()


def decode_truth(s: str | None) -> dict | None:
    if not s or TRUTH_PREFIX not in s:
        return None
    try:
        tok = s.split(TRUTH_PREFIX, 1)[1].split()[0]
        return json.loads(zlib.decompress(base64.b64decode(tok)))
    except Exception:  # noqa: BLE001 - foreign keywords are simply not ours
        return None


# ------------------------------------------------------------------ rendering
@dataclass
class Page:
    jpeg: bytes
    index: int  # 1-based within its file
    source: str
    offline: dict | None = None  # {"rows": [...], "date": "..."} only when the PDF carries a truth sidecar


def _fit_jpeg(img, max_dim: int) -> bytes:
    from PIL import Image

    img = img.convert("RGB")
    long_side = max(img.size)
    if long_side > max_dim:
        k = max_dim / long_side
        img = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def pdf_pages(data: bytes, source: str = "document.pdf", max_dim: int = MAX_DIM) -> list[Page]:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"{source} is not a readable PDF") from e
    try:
        truth = decode_truth(pdf.get_metadata_dict().get("Keywords"))
        by_page = {p["page"]: p["tests"] for p in (truth or {}).get("pages", [])}
        out = []
        for i in range(len(pdf)):
            pg = pdf[i]
            w, h = pg.get_size()
            scale = min(3.0, max_dim / max(w, h))
            img = pg.render(scale=scale).to_pil()
            off = {"rows": by_page[i + 1], "date": truth["date"]} if truth and (i + 1) in by_page else None
            out.append(Page(_fit_jpeg(img, max_dim), i + 1, source, off))
        return out
    finally:
        pdf.close()


def image_page(data: bytes, source: str = "image", max_dim: int = MAX_DIM) -> Page:
    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"{source} is not a readable image") from e
    return Page(_fit_jpeg(img, max_dim), 1, source)


def file_pages(name: str, data: bytes, max_dim: int = MAX_DIM) -> list[Page]:
    return pdf_pages(data, name, max_dim) if is_pdf(data) else [image_page(data, name, max_dim)]


# ------------------------------------------------------------------ model output
def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", "."))
        except ValueError:
            return None
    return None


def parse_date(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    return None


class RawLab(BaseModel):
    test_name: str
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str = ""
    ref_low: float | None = None
    ref_high: float | None = None
    flag: str | None = None
    date: str | None = None
    confidence: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, d: Any) -> Any:
        if not isinstance(d, dict):
            return d
        d = dict(d)
        raw_val = d.get("value_numeric")
        d["value_numeric"] = _num(raw_val)
        if d["value_numeric"] is None and raw_val not in (None, "") and not d.get("value_text"):
            d["value_text"] = str(raw_val)
        if d.get("value_text") is not None:
            d["value_text"] = str(d["value_text"]).strip() or None
        for k in ("ref_low", "ref_high", "confidence"):
            d[k] = _num(d.get(k))
        d["unit"] = str(d.get("unit") or "").strip()
        if d.get("flag") not in ("low", "high", "normal"):
            d["flag"] = None
        d["date"] = parse_date(d.get("date"))
        d["test_name"] = str(d.get("test_name") or "").strip()
        return d

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float | None) -> float | None:
        return None if v is None else max(0.0, min(1.0, v))


class RawDoc(BaseModel):
    date: str | None = None
    rows: list[RawLab] = Field(default_factory=list)

    @field_validator("date", mode="before")
    @classmethod
    def _d(cls, v: Any) -> str | None:
        return parse_date(v)


def messages_for(jpeg: bytes, page_no: int) -> list[dict]:
    url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": f"Page {page_no}. Copy the results table."},
                                         {"type": "image_url", "image_url": {"url": url}}]}]


# ------------------------------------------------------------------ rules in code
def test_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def compute_flag(num: float | None, lo: float | None, hi: float | None, given: str | None = None) -> str | None:
    if num is not None and (lo is not None or hi is not None):
        if hi is not None and num > hi:
            return "high"
        if lo is not None and num < lo:
            return "low"
        return "normal"
    return given


def review_state(confidence: float | None, threshold: float) -> str:
    return "needs_review" if confidence is None or confidence < threshold else "auto"


def _vkey(r: RawLab) -> str:
    return f"n{r.value_numeric:.6g}" if r.value_numeric is not None else f"t{(r.value_text or '').lower()}"


def consistency(samples: list[RawDoc]) -> list[float]:
    """Per row of the first sample: share of samples that read the same value AND unit (min of the two)."""
    base, n = samples[0].rows, len(samples)
    idx = [{test_key(r.test_name): r for r in s.rows} for s in samples]
    out = []
    for r in base:
        k = test_key(r.test_name)
        same_v = sum(1 for m in idx if k in m and _vkey(m[k]) == _vkey(r))
        same_u = sum(1 for m in idx if k in m and test_key(m[k].unit) == test_key(r.unit))
        out.append(min(same_v, same_u) / n)
    return out


# ------------------------------------------------------------------ extraction
@dataclass
class PageResult:
    rows: list[dict]
    date: str | None
    model: str
    backend: str


def _parse_samples(raw: list) -> list[RawDoc]:
    docs = []
    for item in raw:
        text = item[0] if isinstance(item, (tuple, list)) else item
        try:
            docs.append(RawDoc.model_validate(extract_json(text)))
        except Exception:  # noqa: BLE001 - a bad sample is just a missing vote
            continue
    return docs


async def extract_page(llm: LLM, page: Page, page_no: int, *, vision_model: str | None = None,
                       threshold: float = 0.7, n_samples: int = 3) -> PageResult:
    """One page -> rows with confidence and review state. `page_no` is the number within the batch."""
    payload: dict[str, Any] = {"page": page.index}
    if vision_model:
        payload["_model"] = vision_model
    if page.offline:
        payload["offline"] = page.offline
    msgs = messages_for(page.jpeg, page.index)
    use_samples = n_samples > 1 and hasattr(llm, "samples") and llm.backend != "offline-fixtures"
    samples: list[RawDoc] = []
    if use_samples:
        try:
            samples = _parse_samples(await llm.samples("document", msgs, n_samples, payload=payload))  # type: ignore[attr-defined]
        except (TypeError, LLMError):
            samples = []
    if not samples:
        doc, _st = await llm.json("document", msgs, RawDoc, payload=payload)
        samples, use_samples = [doc], False
    doc = samples[0]
    confs = consistency(samples) if use_samples and len(samples) > 1 else [r.confidence for r in doc.rows]
    rows = []
    for r, c in zip(doc.rows, confs):
        if not r.test_name or (r.value_numeric is None and not r.value_text):
            continue
        rows.append({"test_name": r.test_name, "value_numeric": r.value_numeric, "value_text": r.value_text,
                     "unit": r.unit, "ref_low": r.ref_low, "ref_high": r.ref_high,
                     "flag": compute_flag(r.value_numeric, r.ref_low, r.ref_high, r.flag),
                     "date": r.date or doc.date, "page": page_no, "confidence": c,
                     "review": review_state(c, threshold)})
    return PageResult(rows, doc.date, vision_model or llm.model, llm.backend)


def today_iso() -> str:
    return date.today().isoformat()
