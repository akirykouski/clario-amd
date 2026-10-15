"""Generate synthetic Italian lab reports (referti) with exact ground truth.

Everything here is fictional: the laboratory, the patient, the values. Each PDF gets a sidecar
`<name>.truth.json` with the exact printed values. The truth is also embedded in the PDF
metadata so the offline fixture model can "read" a page without any OCR or model.

    uv run python scripts/make_referti.py --n-docs 3 --pages-per-doc 2 --seed 7 --out /tmp/referti
    uv run python scripts/make_referti.py --n-docs 20 --scan-noise --out /tmp/scans
"""

from __future__ import annotations

import argparse
import io
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clario.documents import encode_truth  # noqa: E402

LAB_NAMES = ["Laboratorio Analisi Colle Verde", "Centro Diagnostico Borgo Alto", "Laboratorio Clinico Riva Serena"]
STREETS = ["Via dei Tigli 14", "Corso Aurora 88", "Via Fontana Vecchia 3"]
CITIES = ["20100 Milano (MI)", "10100 Torino (TO)", "40100 Bologna (BO)"]
FIRST = ["Giulia", "Marta", "Elena", "Chiara", "Sofia", "Paola", "Irene", "Lucia"]
LAST = ["Verdi", "Ferrante", "Colombo", "Marini", "Gallo", "Costa", "Fontana", "Greco"]

# name, unit, ref_low, ref_high, decimals, typical (mean, sd) inside the range
# kind "num" values; kind "text" qualitative
CATALOG = [
    {"name": "Emoglobina", "unit": "g/dL", "lo": 12.0, "hi": 16.0, "dec": 1, "core": True},
    {"name": "Globuli rossi", "unit": "10^6/uL", "lo": 4.0, "hi": 5.2, "dec": 2},
    {"name": "Ematocrito", "unit": "%", "lo": 36.0, "hi": 46.0, "dec": 1},
    {"name": "MCV", "unit": "fL", "lo": 80.0, "hi": 98.0, "dec": 1},
    {"name": "Globuli bianchi", "unit": "10^3/uL", "lo": 4.0, "hi": 10.0, "dec": 2, "core": True},
    {"name": "Neutrofili", "unit": "10^3/uL", "lo": 1.8, "hi": 7.0, "dec": 2},
    {"name": "Linfociti", "unit": "10^3/uL", "lo": 1.0, "hi": 4.0, "dec": 2},
    {"name": "Piastrine", "unit": "10^3/uL", "lo": 150.0, "hi": 400.0, "dec": 0},
    {"name": "VES", "unit": "mm/h", "lo": 0.0, "hi": 20.0, "dec": 0, "core": True},
    {"name": "PCR", "unit": "mg/L", "lo": 0.0, "hi": 5.0, "dec": 1, "core": True},
    {"name": "TSH", "unit": "mIU/L", "lo": 0.4, "hi": 4.0, "dec": 2},
    {"name": "FT4", "unit": "ng/dL", "lo": 0.8, "hi": 1.8, "dec": 2},
    {"name": "FT3", "unit": "pg/mL", "lo": 2.0, "hi": 4.4, "dec": 2},
    {"name": "ANA", "unit": "", "kind": "text", "ref": "Negativo", "core": True,
     "choices": ["Negativo", "Negativo", "Positivo 1:80", "Positivo 1:160", "Positivo 1:320"]},
    {"name": "Anti-dsDNA", "unit": "UI/mL", "lo": 0.0, "hi": 100.0, "dec": 0},
    {"name": "C3", "unit": "mg/dL", "lo": 90.0, "hi": 180.0, "dec": 0, "core": True},
    {"name": "C4", "unit": "mg/dL", "lo": 10.0, "hi": 40.0, "dec": 0, "core": True},
    {"name": "Ferritina", "unit": "ng/mL", "lo": 13.0, "hi": 150.0, "dec": 0},
    {"name": "Sideremia", "unit": "ug/dL", "lo": 37.0, "hi": 145.0, "dec": 0},
    {"name": "Creatinina", "unit": "mg/dL", "lo": 0.5, "hi": 0.9, "dec": 2, "core": True},
    {"name": "Azotemia", "unit": "mg/dL", "lo": 15.0, "hi": 45.0, "dec": 0},
    {"name": "Glicemia", "unit": "mg/dL", "lo": 70.0, "hi": 100.0, "dec": 0},
    {"name": "Colesterolo totale", "unit": "mg/dL", "lo": 0.0, "hi": 200.0, "dec": 0, "upper_only": True},
    {"name": "AST", "unit": "U/L", "lo": 5.0, "hi": 34.0, "dec": 0},
    {"name": "ALT", "unit": "U/L", "lo": 0.0, "hi": 35.0, "dec": 0},
    {"name": "Vitamina D", "unit": "ng/mL", "lo": 30.0, "hi": 100.0, "dec": 1},
    {"name": "Sodio", "unit": "mmol/L", "lo": 136.0, "hi": 145.0, "dec": 0},
    {"name": "Potassio", "unit": "mmol/L", "lo": 3.5, "hi": 5.1, "dec": 1},
    {"name": "Proteine urinarie", "unit": "mg/dL", "lo": 0.0, "hi": 15.0, "dec": 0, "upper_only": True},
]


def it_num(v: float, dec: int) -> str:
    return f"{v:.{dec}f}".replace(".", ",")


def make_row(rng: random.Random, t: dict, out_p: float) -> dict:
    if t.get("kind") == "text":
        v = rng.choice(t["choices"])
        return {"test_name": t["name"], "value_numeric": None, "value_text": v, "value": v, "unit": "", "shown": v,
                "ref_low": None, "ref_high": None, "ref_text": t["ref"],
                "flag": "high" if v.startswith("Positivo") else "normal"}
    lo, hi, dec = t["lo"], t["hi"], t["dec"]
    span = hi - lo
    if rng.random() < out_p:
        if t.get("upper_only") or lo <= 0 or rng.random() < 0.5:
            v = hi + span * rng.uniform(0.08, 0.6)
        else:
            v = lo - span * rng.uniform(0.08, 0.4)
            if lo > 0:
                v = max(v, lo * 0.3)
    else:
        v = rng.uniform(lo + span * 0.1, hi - span * 0.1)
    v = round(v, dec)
    r_lo = None if t.get("upper_only") else lo
    flag = "high" if v > hi else ("low" if r_lo is not None and v < r_lo else "normal")
    ref_text = f"< {it_num(hi, dec)}" if t.get("upper_only") else f"{it_num(lo, dec)} - {it_num(hi, dec)}"
    return {"test_name": t["name"], "value_numeric": v, "value_text": None, "value": v, "unit": t["unit"],
            "shown": it_num(v, dec), "ref_low": r_lo, "ref_high": hi, "ref_text": ref_text, "flag": flag}


def pick_tests(rng: random.Random, n: int, out_p: float) -> list[dict]:
    core = [t for t in CATALOG if t.get("core")]
    rest = [t for t in CATALOG if not t.get("core")]
    chosen = core[: min(n, len(core))] + rng.sample(rest, max(0, min(n - len(core), len(rest))))
    rng.shuffle(chosen)
    return [make_row(rng, t, out_p) for t in chosen]


def build_pdf(doc: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_creation_date(datetime(2026, 1, 1, tzinfo=timezone.utc))
    pdf.set_title(f"Referto {doc['doc_id']}")
    pdf.set_keywords(encode_truth(doc))
    pdf.set_auto_page_break(False)
    cols = [(0, 62, "Esame"), (62, 32, "Risultato"), (94, 28, "Unita'"), (122, 58, "Valori di riferimento")]
    for pg in doc["pages"]:
        pdf.add_page()
        pdf.set_margins(15, 15, 15)
        pdf.set_xy(15, 15)
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 8, doc["lab"]["name"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, f"{doc['lab']['street']} - {doc['lab']['city']}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, "REFERTO DI ANALISI DI LABORATORIO", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 5, f"Paziente: {doc['patient']['name']}   Nata il: {doc['patient']['born']}",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, f"Data del prelievo: {doc['date_it']}   Pagina {pg['page']} di {len(doc['pages'])}",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        pdf.set_fill_color(225, 232, 232)
        pdf.set_font("Helvetica", "B", 10)
        x0 = pdf.get_x()
        for dx, w, label in cols:
            pdf.set_xy(x0 + dx, pdf.get_y())
            pdf.cell(w, 7, label, border=1, fill=True)
        pdf.ln(7)
        pdf.set_font("Helvetica", "", 10)
        for row in pg["tests"]:
            y = pdf.get_y()
            cells = [row["test_name"], row["shown"], row["unit"], row["ref_text"]]
            for (dx, w, _l), txt in zip(cols, cells):
                pdf.set_xy(x0 + dx, y)
                bold = dx == 62 and row["flag"] != "normal"
                pdf.set_font("Helvetica", "B" if bold else "", 10)
                pdf.cell(w, 7, txt, border=1)
            pdf.ln(7)
        pdf.set_xy(15, 280)
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 4, "Documento sintetico generato a scopo dimostrativo. Laboratorio e paziente sono fittizi.")
    return bytes(pdf.output())


def scan_noise(pdf_bytes: bytes, doc: dict, rng: random.Random) -> bytes:
    """Re-render as a photocopied image PDF: rotation +-2 deg, gaussian noise, JPEG artefacts."""
    import pypdfium2 as pdfium
    from fpdf import FPDF
    from PIL import Image, ImageChops, ImageFilter

    src = pdfium.PdfDocument(pdf_bytes)
    out = FPDF(format="A4")
    out.set_creation_date(datetime(2026, 1, 1, tzinfo=timezone.utc))
    out.set_keywords(encode_truth(doc))
    for i in range(len(src)):
        img = src[i].render(scale=2.0).to_pil().convert("L")
        img = img.rotate(rng.uniform(-2, 2), resample=Image.BICUBIC, expand=False, fillcolor=255)
        noise = Image.effect_noise(img.size, rng.uniform(10, 22))
        img = ImageChops.subtract(img, ImageChops.invert(noise).point(lambda p: max(0, p - 215)))
        img = ImageChops.add(img, noise.point(lambda p: max(0, p - 120) // 3))
        img = img.filter(ImageFilter.GaussianBlur(0.5))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=rng.randint(32, 55))
        out.add_page()
        out.image(buf, x=0, y=0, w=210, h=297)
    return bytes(out.output())


def make_docs(n_docs: int, pages_per_doc: int, seed: int, noise: bool = False, out_p: float = 0.3,
              tests_per_page: tuple[int, int] = (8, 25)) -> list[tuple[dict, bytes]]:
    rng = random.Random(seed)
    lab = {"name": rng.choice(LAB_NAMES), "street": rng.choice(STREETS), "city": rng.choice(CITIES)}
    patient = {"name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
               "born": date(rng.randint(1975, 1998), rng.randint(1, 12), rng.randint(1, 28)).strftime("%d/%m/%Y")}
    start = date(2025, 3, 1) + timedelta(days=rng.randint(0, 60))
    out = []
    for i in range(n_docs):
        d = start + timedelta(days=int(i * 480 / max(1, n_docs)) + rng.randint(0, 10))
        pages = [{"page": p + 1, "tests": pick_tests(rng, rng.randint(*tests_per_page), out_p)}
                 for p in range(pages_per_doc)]
        doc = {"doc_id": f"ref_{seed}_{i + 1:03d}", "lab": lab, "patient": patient, "date": d.isoformat(),
               "date_it": d.strftime("%d/%m/%Y"), "scan_noise": noise, "pages": pages}
        pdf = build_pdf(doc)
        out.append((doc, scan_noise(pdf, doc, rng) if noise else pdf))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-docs", type=int, default=3)
    ap.add_argument("--pages-per-doc", type=int, default=1)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scan-noise", action="store_true", help="photocopy look: rotation, noise, JPEG artefacts, image PDF")
    ap.add_argument("--min-tests", type=int, default=8)
    ap.add_argument("--max-tests", type=int, default=25)
    a = ap.parse_args()
    if not (1 <= a.min_tests <= a.max_tests <= len(CATALOG)):
        ap.error(f"tests per page must satisfy 1 <= min <= max <= {len(CATALOG)}")
    a.out.mkdir(parents=True, exist_ok=True)
    for doc, pdf in make_docs(a.n_docs, a.pages_per_doc, a.seed, a.scan_noise, tests_per_page=(a.min_tests, a.max_tests)):
        (a.out / f"{doc['doc_id']}.pdf").write_bytes(pdf)
        (a.out / f"{doc['doc_id']}.truth.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    print(f"wrote {a.n_docs} documents ({a.n_docs * a.pages_per_doc} pages) to {a.out}")


if __name__ == "__main__":
    main()
