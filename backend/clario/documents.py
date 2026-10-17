"""Paper documents -> lab rows.

PDF pages and photos are normalised to JPEG (long side capped). Two ways to read a page, both through the same
client as everything else (so every call is in the hash-chained log):
- OCR first (LLM_OCR_MODEL, default MinerU2.5-Pro on AMD Token Factory): the OCR model turns the page into
  markdown. A recognised result table is read in code (CLARIO_DOC_STRUCTURE=table, the default: one request per
  page); otherwise, or with CLARIO_DOC_STRUCTURE=model, the text model (Gemma 4 31B) copies the table into JSON.
  A row whose name or numbers are not in the OCR text, or whose cells do not parse, waits for a person.
- Vision (LLM_VISION_MODEL or the chat model): the page image goes to a chat model. Used when no OCR model is set,
  and as the fallback when the OCR call fails.
The model only reads what is printed. Flags are recomputed in code from value and range, and every row gets a
confidence that decides whether a person must look at it (CLARIO_REVIEW_THRESHOLD).
"""

from __future__ import annotations

import base64
import html
import io
import json
import logging
import math
import re
import zlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import ExtractOpts
from .knowledge import fold
from .llm import LLM, LLMError, extract_json
from .models import LabResult, route_review

log = logging.getLogger("clario")

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

TEXT_SYSTEM = """You get the text of one page of a laboratory report (Italian or English) as read by OCR: markdown, \
tables may be HTML. Copy the result table into JSON. Return JSON only:
{"date": "<YYYY-MM-DD collection date printed on the page, else null>", "rows": [{"test_name": "<as printed>", \
"value_numeric": <number or null>, "value_text": "<printed result when it is not a plain number, else null>", \
"unit": "<as printed or empty>", "ref_low": <number or null>, "ref_high": <number or null>, \
"flag": "low|high|normal|null", "confidence": <0 to 1, how sure you are this row is read correctly>}]}
Rules: copy exactly what is in the text, one row per test. Italian decimals use a comma: 4,52 means 4.52. A range \
like "< 5,0" has ref_low null and ref_high 5.0. Placeholders such as [NAME] or [DATE] hide personal details: never \
copy them; if the collection date is a placeholder, return null. If a cell is garbled, lower the confidence instead \
of guessing. Skip headers, names, addresses and footers. Do not interpret results."""

UNGROUNDED_CAP = 0.5  # confidence of a row whose name or numbers the OCR text does not contain


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


def data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def text_messages_for(markdown: str, page_no: int) -> list[dict]:
    return [{"role": "system", "content": TEXT_SYSTEM},
            {"role": "user", "content": f"Page {page_no}, OCR text:\n\n{markdown}\n\nCopy the results table."}]


def messages_for(jpeg: bytes, page_no: int) -> list[dict]:
    url = data_url(jpeg)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": f"Page {page_no}. Copy the results table."},
                                         {"type": "image_url", "image_url": {"url": url}}]}]


# ------------------------------------------------------------------ rules in code
def test_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", fold(name))


def compute_flag(num: float | None, lo: float | None, hi: float | None, given: str | None = None) -> str | None:
    if num is not None and (lo is not None or hi is not None):
        if hi is not None and num > hi:
            return "high"
        if lo is not None and num < lo:
            return "low"
        return "normal"
    return None  # no printed range to compare with: never claim "normal"


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


# ------------------------------------------------------------------ checks against the OCR text
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_DATE_IN_TEXT = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
_BIRTH_CUE = re.compile(r"(nat[oa]|nascita|born|birth|dob)\W*(il|on)?\W*$", re.I)
_COLLECTION_CUE = re.compile(r"(prelievo|prelevat[oa]|accettazione|raccolta|collect\w*|sampl\w*)\W*(il|on|del)?\W*$", re.I)


def plain_text(markdown: str) -> str:
    """OCR markdown without HTML tags and entities, so names and numbers can be looked up."""
    return html.unescape(re.sub(r"<[^>]+>", " ", markdown or ""))


def date_from_text(text: str) -> str | None:
    """Collection date printed on the page: a date after "prelievo" / "collected" first, else the first date that is
    not a birth date. Read in code because the pseudonymiser hides dates from the model."""
    plain, other = plain_text(text), None
    for m in _DATE_IN_TEXT.finditer(plain):
        try:
            if m.group(1):
                d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            else:
                d = date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        except ValueError:
            continue
        before = plain[max(0, m.start() - 40):m.start()]
        if _COLLECTION_CUE.search(before):
            return d.isoformat()
        if other is None and not _BIRTH_CUE.search(before):
            other = d.isoformat()
    return other


def grounded(row: "RawLab", text: str) -> bool:
    """The test name and every number of the row appear in the OCR text (text results: the words appear)."""
    plain = plain_text(text)
    if test_key(row.test_name) not in test_key(plain):
        return False
    nums = [float(n.replace(",", ".")) for n in _NUM.findall(plain)]
    for v in (row.value_numeric, row.ref_low, row.ref_high):
        if v is not None and not any(math.isclose(v, n, rel_tol=1e-9, abs_tol=1e-9) for n in nums):
            return False
    return row.value_text is None or test_key(row.value_text) in test_key(plain)


# ------------------------------------------------------------------ result table read in code
_NAME_COL = re.compile(r"esame|analisi|parametro|test|exam|prova", re.I)
_RESULT_COL = re.compile(r"risultat|result|valore|value", re.I)
_UNIT_COL = re.compile(r"unit|u\.?\s?m\.?$|misura", re.I)
_REF_COL = re.compile(r"riferiment|referen|range|intervall|normal", re.I)
_RANGE = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*(?:-|–|÷|to|a)\s*(-?\d+(?:[.,]\d+)?)\s*$")
_BOUND = re.compile(r"^\s*(<=?|≤|>=?|≥)\s*(-?\d+(?:[.,]\d+)?)\s*$")
_MARKER = re.compile(r"\s*(\*+|\bH\b|\bL\b|↑|↓)\s*$")
TABLE_CONFIDENCE = 0.95  # a clean cell copied by code; an odd cell gets UNGROUNDED_CAP and waits for a person


def _table_rows(markdown: str) -> list[list[str]]:
    """Cells of the HTML tables (MinerU) or pipe tables in the OCR text, one list per row."""
    rows: list[list[str]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", markdown or "", flags=re.S | re.I):
        rows.append([html.unescape(re.sub(r"<[^>]+>", " ", c)).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)])
    if not rows:
        for line in (markdown or "").splitlines():
            if line.strip().startswith("|") and not re.fullmatch(r"[\s|:\-]+", line):
                rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def _ref(cell: str) -> tuple[float | None, float | None, bool]:
    """Printed reference -> (low, high, clean). Words only ("Negativo") are clean with no numbers."""
    if not cell or not re.search(r"\d", cell):
        return None, None, True
    m = _RANGE.match(cell)
    if m:
        return _num(m.group(1)), _num(m.group(2)), True
    m = _BOUND.match(cell)
    if m:
        v = _num(m.group(2))
        return (None, v, True) if m.group(1) in ("<", "<=", "≤") else (v, None, True)
    return None, None, False


def _cell(row: list[str], col: dict[str, int], key: str) -> str:
    i = col.get(key)
    return row[i] if i is not None and i < len(row) else ""


def parse_table(markdown: str) -> RawDoc | None:
    """The result table of an OCR page read in code, or None when no table has a name and a result column.
    Exact copy, no model call. A cell that does not parse cleanly gets a low confidence."""
    rows = _table_rows(markdown)
    for h, header in enumerate(rows):
        col = {}
        for i, c in enumerate(header):
            # reference first: "Valori di riferimento" also contains "valor"
            for key, rx in (("ref", _REF_COL), ("unit", _UNIT_COL), ("result", _RESULT_COL), ("name", _NAME_COL)):
                if key not in col and rx.search(c):
                    col[key] = i
                    break
        if "name" in col and "result" in col:
            break
    else:
        return None
    out = []
    for r in rows[h + 1:]:
        name, shown = _cell(r, col, "name"), _MARKER.sub("", _cell(r, col, "result"))
        if not name or not shown:
            continue
        num = _num(shown)
        clean = num is not None or not re.fullmatch(r"[\d\s.,]+", shown)  # digits that are not a number are odd
        lo, hi, ref_ok = _ref(_cell(r, col, "ref"))
        out.append(RawLab.model_validate({
            "test_name": name, "value_numeric": num, "value_text": None if num is not None else shown,
            "unit": _cell(r, col, "unit"), "ref_low": lo, "ref_high": hi,
            "confidence": TABLE_CONFIDENCE if clean and ref_ok else UNGROUNDED_CAP}))
    return RawDoc(date=date_from_text(markdown), rows=out) if out else None


# ------------------------------------------------------------------ extraction
@dataclass
class PageResult:
    rows: list[dict]
    date: str | None
    model: str
    backend: str
    # "ocr-table" (OCR, table read in code), "ocr" (OCR, then the text model) or "vision" (page image to a chat model)
    reader: str = "vision"


def _parse_samples(raw: list) -> list[RawDoc]:
    docs = []
    for item in raw:
        text = item[0] if isinstance(item, (tuple, list)) else item
        try:
            docs.append(RawDoc.model_validate(extract_json(text)))
        except Exception:  # noqa: BLE001 - a bad sample is just a missing vote
            continue
    return docs


async def read_ocr(llm: LLM, page: Page, ocr_model: str) -> str | None:
    """The page as markdown from the OCR model, or None (no OCR on this client, call failed, empty page)."""
    if not hasattr(llm, "ocr"):
        return None
    payload: dict[str, Any] = {"page": page.index, **({"offline": page.offline} if page.offline else {})}
    try:
        text, _st = await llm.ocr("document", data_url(page.jpeg), model=ocr_model, payload=payload)
    except LLMError as e:
        log.warning("OCR of %s page %s failed, reading the image instead: %s", page.source, page.index, e)
        return None
    return text if text and text.strip() else None


def _rows_out(doc: RawDoc, confs: list, page_no: int, page_date: str | None, threshold: float,
              markdown: str | None) -> list[dict]:
    rows = []
    for r, c in zip(doc.rows, confs):
        if not r.test_name or (r.value_numeric is None and not r.value_text):
            continue
        review = route_review(c, threshold, none_means="needs_review")
        if markdown is not None and not grounded(r, markdown):
            c, review = (None if c is None else min(c, UNGROUNDED_CAP)), "needs_review"
        rows.append({"test_name": r.test_name, "value_numeric": r.value_numeric, "value_text": r.value_text,
                     "unit": r.unit, "ref_low": r.ref_low, "ref_high": r.ref_high,
                     "flag": compute_flag(r.value_numeric, r.ref_low, r.ref_high, r.flag),
                     "date": r.date or page_date, "page": page_no, "confidence": c, "review": review})
    return rows


async def extract_page(llm: LLM, page: Page, page_no: int, *, vision_model: str | None = None,
                       ocr_model: str | None = None, structure: str = "table",
                       threshold: float = ExtractOpts.review_threshold, n_samples: int = 3) -> PageResult:
    """One page -> rows with confidence and review state. `page_no` is the number within the batch.
    With `ocr_model`: OCR first. `structure="table"` reads a recognised result table in code (no second call); any
    other page, or `structure="model"`, goes to the text model. The image path is the fallback when OCR fails."""
    markdown = await read_ocr(llm, page, ocr_model) if ocr_model else None
    if markdown is not None and structure == "table":
        table = parse_table(markdown)
        if table is not None:
            rows = _rows_out(table, [r.confidence for r in table.rows], page_no, table.date, threshold, markdown)
            return PageResult(rows, table.date, str(ocr_model), llm.backend, "ocr-table")
    payload: dict[str, Any] = {"page": page.index}
    if markdown is None and vision_model:
        payload["_model"] = vision_model
    if page.offline:
        payload["offline"] = page.offline
    msgs = text_messages_for(markdown, page.index) if markdown is not None else messages_for(page.jpeg, page.index)
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
    page_date = doc.date
    if markdown is not None:  # the printed date read in code wins: the model may only have seen [DATE]
        page_date = date_from_text(markdown) or doc.date
    rows = _rows_out(doc, confs, page_no, page_date, threshold, markdown)
    if markdown is not None:
        return PageResult(rows, page_date, f"{ocr_model} + {llm.model}", llm.backend, "ocr")
    return PageResult(rows, page_date, vision_model or llm.model, llm.backend)


def apply_lab_action(lab: LabResult, action: str, given: dict | None = None) -> LabResult:
    """confirm / reject / correct a lab row. `given` holds the corrected value_numeric, value_text, unit, ref_low, ref_high.
    Raises ValueError (HTTP 422) on an unusable correction. The flag is always recomputed in code."""
    if action == "confirm":
        upd: dict[str, Any] = {"review": "confirmed"}
    elif action == "reject":
        upd = {"review": "rejected"}
    elif action == "correct":
        given = dict(given or {})
        if not given:
            raise ValueError("Give the corrected value, unit or range")
        if "value_numeric" in given and "value_text" not in given:
            given["value_text"] = None
        if "value_text" in given and given["value_text"] is not None and "value_numeric" not in given:
            given["value_numeric"] = None
        upd = {**given, "review": "corrected"}
        if upd.get("value_numeric", lab.value_numeric) is None and not (upd.get("value_text") or lab.value_text):
            raise ValueError("A result needs a number or text")
    else:
        raise ValueError("action must be confirm, correct or reject")
    new = lab.model_copy(update=upd)
    return new.model_copy(update={"flag": compute_flag(new.value_numeric, new.ref_low, new.ref_high, new.flag)})


def parse_lab_value(value: str) -> dict:
    """Free text from the review queue ('5,5' or 'Positivo 1:160') -> a correction for apply_lab_action."""
    v = (value or "").strip()
    n = _num(v)
    return {"value_numeric": n} if n is not None else {"value_text": v}


def today_iso() -> str:
    return date.today().isoformat()
