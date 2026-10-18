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
    # the PDF's own text layer (a born-digital report), else None (photo, scan): a second source for every reading
    text: str | None = None
    lines: list[dict] | None = None  # text-layer lines [{"text", "box": [x0, y0, x1, y1]}], box as a share of the page


def text_layer(pg) -> tuple[str | None, list[dict]]:
    """Text and line boxes of one PDF page from its text layer. Boxes are fractions of the page width and height,
    origin top left, so they apply to the rendered JPEG at any size. A page without text (a scan) gives (None, [])."""
    tp = pg.get_textpage()
    try:
        n = tp.count_chars()
        text = tp.get_text_range() if n else ""
        if not text.strip():
            return None, []
        w, h = pg.get_size()
        lines: list[dict] = []
        cur: dict | None = None
        for i in range(n):
            ch = tp.get_text_range(i, 1)
            if ch in ("\r", "\n"):
                cur = None
                continue
            if not ch.strip():
                if cur is not None:
                    cur["text"] += " "
                continue
            left, bottom, right, top = tp.get_charbox(i)
            # same line while the glyph overlaps the line vertically (a comma or a caret sits lower or higher)
            if cur is None or min(top, cur["top"]) - max(bottom, cur["bottom"]) <= 0:
                cur = {"text": "", "x0": left, "x1": right, "top": top, "bottom": bottom}
                lines.append(cur)
            cur["text"] += ch
            cur["x0"], cur["x1"] = min(cur["x0"], left), max(cur["x1"], right)
            cur["top"], cur["bottom"] = max(cur["top"], top), min(cur["bottom"], bottom)
        return text, [{"text": ln["text"].strip(), "box": [round(ln["x0"] / w, 4), round(1 - ln["top"] / h, 4),
                                                           round(ln["x1"] / w, 4), round(1 - ln["bottom"] / h, 4)]}
                      for ln in lines]
    finally:
        tp.close()


def locate_row(lines: list[dict] | None, test_name: str, value: float | None = None,
               value_text: str | None = None) -> list[float] | None:
    """Box of the printed line that starts with the test name (the row on the page), or None. When the name starts
    several lines, the one that also prints the value wins."""
    key = test_key(test_name)
    if not lines or not key:
        return None
    hits = [ln for ln in lines if test_key(ln["text"]).startswith(key)]
    if not hits:
        return None
    if len(hits) > 1:
        want = test_key(value_text) if value_text else (f"{value:g}".replace(".", "") if value is not None else "")
        hits = [ln for ln in hits if want and want in test_key(ln["text"])] or hits
    return list(hits[0]["box"])


CROP_WIDTH = 900  # px: a row crop is scaled down to this width at most
CROP_QUALITY = 70


def crop_row(jpeg: bytes, box: list[float], max_width: int = CROP_WIDTH) -> bytes:
    """The printed row (box from `locate_row`) cut out of the page JPEG with a little margin: the line itself, never
    the page header with the patient's name."""
    from PIL import Image

    img = Image.open(io.BytesIO(jpeg))
    W, H = img.size
    x0, y0, x1, y1 = box
    rh = max(1.0, (y1 - y0) * H)
    pad_y, pad_x = rh * 0.45 + 2, 10
    a = (max(0, int(x0 * W - pad_x)), max(0, int(y0 * H - pad_y)), min(W, int(x1 * W + pad_x)), min(H, int(y1 * H + pad_y)))
    part = img.crop(a).convert("RGB")
    if part.width > max_width:
        part = part.resize((max_width, max(1, round(part.height * max_width / part.width))), Image.LANCZOS)
    buf = io.BytesIO()
    part.save(buf, "JPEG", quality=CROP_QUALITY)
    return buf.getvalue()


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
    from .brief_pdf import PDFIUM_LOCK

    with PDFIUM_LOCK:
        return _pdf_pages(data, source, max_dim)


def _pdf_pages(data: bytes, source: str, max_dim: int) -> list[Page]:
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
            text, lines = text_layer(pg)
            out.append(Page(_fit_jpeg(img, max_dim), i + 1, source, off, text, lines or None))
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


# Qualitative results (no number, no range): a positive / present / reactive reading is out of range at any titre.
_QUAL_NEG = re.compile(r"^\s*(negativ|assente|absent|non\s*-?\s*(reattiv|reactive|rilevat|present)|not\s+(detected|present)|"
                       r"nonreactive)", re.I)
_QUAL_POS = re.compile(r"^\s*(positiv|presente|present|reattiv|reactive|rilevat|detected)", re.I)
OFF_FLAGS = ("low", "high", "positive")


def qualitative_flag(text: str | None) -> str | None:
    """"Positivo 1:80", "Presente", "Reattivo" -> positive; "Negativo", "Assente" -> normal; any other text -> None."""
    if not text:
        return None
    if _QUAL_NEG.match(text):
        return "normal"
    if _QUAL_POS.match(text):
        return "positive"
    return None


def compute_flag(num: float | None, lo: float | None, hi: float | None, given: str | None = None,
                 text: str | None = None) -> str | None:
    """The one place a lab flag is decided. `given` (what the model or the page said) is never trusted."""
    if num is not None and (lo is not None or hi is not None):
        if hi is not None and num > hi:
            return "high"
        if lo is not None and num < lo:
            return "low"
        return "normal"
    if num is None:
        return qualitative_flag(text)
    return None  # no printed range to compare with: never claim "normal"


def lab_flag(lab: Any) -> str | None:
    """Flag of a stored or shared lab row, recomputed, so rows stored before a rule change (an ANA "Positivo 1:80"
    saved with no flag) read the same as new ones. The stored flag stays when the rule has nothing to say."""
    return compute_flag(lab.value_numeric, lab.ref_low, lab.ref_high, text=lab.value_text) or lab.flag


def is_off(flag: str | None) -> bool:
    return flag in OFF_FLAGS


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


# ------------------------------------------------------------------ code checks every reading must pass
# Values a living person can have, per test (documents.test_key) and printed unit (folded the same way). Far wider
# than any reference range: outside them a reading is almost surely misread (a lost decimal comma, a digit read twice).
# A unit not listed for a known test is unexpected (mg/L where the test is printed in mg/dL). Unknown tests pass.
LAB_LIMITS: dict[str, dict[str, tuple[float, float]]] = {
    "emoglobina": {"gdl": (2.0, 25.0), "gl": (20.0, 250.0), "mmoll": (1.2, 15.5)},
    "globulirossi": {"106ul": (0.5, 10.0), "1012l": (0.5, 10.0)},
    "ematocrito": {"": (5.0, 75.0), "ll": (0.05, 0.75)},
    "mcv": {"fl": (40.0, 150.0)},
    "globulibianchi": {"103ul": (0.1, 500.0), "109l": (0.1, 500.0)},
    "neutrofili": {"103ul": (0.0, 300.0), "109l": (0.0, 300.0), "": (0.0, 100.0)},
    "linfociti": {"103ul": (0.0, 400.0), "109l": (0.0, 400.0), "": (0.0, 100.0)},
    "piastrine": {"103ul": (1.0, 3000.0), "109l": (1.0, 3000.0)},
    "ves": {"mmh": (0.0, 160.0), "mm1h": (0.0, 160.0), "mm1ora": (0.0, 160.0)},
    "pcr": {"mgl": (0.0, 700.0), "mgdl": (0.0, 70.0)},
    "tsh": {"miul": (0.0, 500.0), "uiml": (0.0, 500.0), "muil": (0.0, 500.0)},
    "ft4": {"ngdl": (0.05, 10.0), "pmoll": (0.5, 130.0)},
    "ft3": {"pgml": (0.3, 40.0), "pmoll": (0.5, 60.0)},
    "antidsdna": {"uiml": (0.0, 10000.0), "iuml": (0.0, 10000.0), "uml": (0.0, 10000.0)},
    "c3": {"mgdl": (5.0, 400.0), "gl": (0.05, 4.0)},
    "c4": {"mgdl": (1.0, 150.0), "gl": (0.01, 1.5)},
    "ferritina": {"ngml": (0.5, 100000.0), "ugl": (0.5, 100000.0)},
    "sideremia": {"ugdl": (5.0, 1000.0), "umoll": (1.0, 180.0)},
    "creatinina": {"mgdl": (0.1, 25.0), "umoll": (9.0, 2200.0)},
    "azotemia": {"mgdl": (1.0, 400.0), "mmoll": (0.3, 140.0)},
    "glicemia": {"mgdl": (10.0, 1500.0), "mmoll": (0.5, 85.0)},
    "colesterolototale": {"mgdl": (40.0, 1500.0), "mmoll": (1.0, 40.0)},
    "ast": {"ul": (0.0, 20000.0)},
    "alt": {"ul": (0.0, 20000.0)},
    "vitaminad": {"ngml": (1.0, 300.0), "nmoll": (2.5, 750.0)},
    "sodio": {"mmoll": (100.0, 190.0), "meql": (100.0, 190.0)},
    "potassio": {"mmoll": (1.0, 10.0), "meql": (1.0, 10.0)},
    "proteineurinarie": {"mgdl": (0.0, 3000.0), "gl": (0.0, 30.0), "mg24h": (0.0, 30000.0)},
}
for _it, _en in (("emoglobina", ("hemoglobin", "haemoglobin")), ("sodio", ("sodium",)), ("potassio", ("potassium",)),
                 ("creatinina", ("creatinine",)), ("glicemia", ("glucose",)), ("piastrine", ("platelets",)),
                 ("globulibianchi", ("whitebloodcells", "wbc")), ("pcr", ("crp",)), ("ves", ("esr",))):
    for _k in _en:
        LAB_LIMITS[_k] = LAB_LIMITS[_it]

# Why a reading waits for a person, in the order the clinic screen explains them.
CHECKS = ("not_on_page", "not_in_ocr", "implausible", "unit_unexpected", "range_inverted", "flag_disagrees",
          "low_confidence")


def code_checks(row: dict, *, page_text: str | None = None, ocr_text: str | None = None,
                confidence: float | None = None, threshold: float | None = None, given_flag: str | None = None) -> list[str]:
    """Rules in code that send a reading to the clinician's check, besides the reader's own confidence:
    - not_on_page: the PDF has a text layer and the name or a number of the row is not printed there (the strongest
      check: a second source, independent of the OCR)
    - not_in_ocr: the name or a number is not in the OCR text the row was read from
    - implausible: the value is outside what a living person can have for this test and unit (`LAB_LIMITS`)
    - unit_unexpected: a known test with a unit it is never printed in
    - range_inverted: the printed range has its low end above its high end
    - flag_disagrees: the page (or the reader) gave a flag that the value and range do not support
    - low_confidence: the reader's confidence is below the review threshold, or nothing was measured"""
    raw = RawLab.model_validate({k: row.get(k) for k in ("test_name", "value_numeric", "value_text", "unit",
                                                         "ref_low", "ref_high")})
    out: list[str] = []
    if page_text is not None and not grounded(raw, page_text):
        out.append("not_on_page")
    if ocr_text is not None and not grounded(raw, ocr_text):
        out.append("not_in_ocr")
    limits = LAB_LIMITS.get(test_key(raw.test_name))
    if limits is not None and raw.value_numeric is not None:
        span = limits.get(test_key(raw.unit))
        if span is None:
            out.append("unit_unexpected")
        elif not span[0] <= raw.value_numeric <= span[1]:
            out.append("implausible")
    if raw.ref_low is not None and raw.ref_high is not None and raw.ref_low > raw.ref_high:
        out.append("range_inverted")
    if given_flag in ("low", "high", "normal"):
        mine = compute_flag(raw.value_numeric, raw.ref_low, raw.ref_high, text=raw.value_text)
        if mine in ("low", "high", "normal") and mine != given_flag:
            out.append("flag_disagrees")
    if threshold is not None and (confidence is None or confidence < threshold):
        out.append("low_confidence")
    return out


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
        cell = _cell(r, col, "result")
        mk = _MARKER.search(cell)
        printed = {"H": "high", "↑": "high", "L": "low", "↓": "low"}.get(mk.group(1)) if mk else None
        name, shown = _cell(r, col, "name"), _MARKER.sub("", cell)
        if not name or not shown:
            continue
        num = _num(shown)
        clean = num is not None or not re.fullmatch(r"[\d\s.,]+", shown)  # digits that are not a number are odd
        lo, hi, ref_ok = _ref(_cell(r, col, "ref"))
        out.append(RawLab.model_validate({
            "test_name": name, "value_numeric": num, "value_text": None if num is not None else shown,
            "unit": _cell(r, col, "unit"), "ref_low": lo, "ref_high": hi, "flag": printed,
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
              markdown: str | None, page: "Page | None" = None) -> list[dict]:
    rows = []
    for r, c in zip(doc.rows, confs):
        if not r.test_name or (r.value_numeric is None and not r.value_text):
            continue
        row = {"test_name": r.test_name, "value_numeric": r.value_numeric, "value_text": r.value_text,
               "unit": r.unit, "ref_low": r.ref_low, "ref_high": r.ref_high}
        checks = code_checks(row, page_text=page.text if page else None, ocr_text=markdown, confidence=c,
                             threshold=threshold, given_flag=r.flag)
        review = route_review(c, threshold, none_means="needs_review")
        if any(k != "low_confidence" for k in checks):  # a failed rule caps the confidence, as an unfound row did
            c, review = (None if c is None else min(c, UNGROUNDED_CAP)), "needs_review"
        rows.append({**row, "flag": compute_flag(r.value_numeric, r.ref_low, r.ref_high, r.flag, r.value_text),
                     "date": r.date or page_date, "page": page_no, "confidence": c, "review": review, "checks": checks,
                     "box": locate_row(page.lines if page else None, r.test_name, r.value_numeric, r.value_text)})
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
            rows = _rows_out(table, [r.confidence for r in table.rows], page_no, table.date, threshold, markdown, page)
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
    rows = _rows_out(doc, confs, page_no, page_date, threshold, markdown, page)
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
    return new.model_copy(update={"flag": compute_flag(new.value_numeric, new.ref_low, new.ref_high, text=new.value_text)})


def parse_lab_value(value: str) -> dict:
    """Free text from the review queue ('5,5' or 'Positivo 1:160') -> a correction for apply_lab_action."""
    v = (value or "").strip()
    n = _num(v)
    return {"value_numeric": n} if n is not None else {"value_text": v}


def today_iso() -> str:
    return date.today().isoformat()
