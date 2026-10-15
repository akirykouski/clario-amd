"""Build a real-text eval set from PsyTAR: patient-written drug reviews with expert-marked symptom spans.

PsyTAR (Zolnoori et al. 2019, J Biomed Inform 90, doi:10.1016/j.jbi.2018.12.005) is released under
CC BY 4.0 from https://www.askapatient.com/research/pharmacovigilance/corpus-ades-psychiatric-medications.asp
(891 reviews of Zoloft, Lexapro, Cymbalta, Effexor XR). The data is a single workbook, PsyTAR_dataset.xlsx,
handed out through the site's store page; the site blocks scripted downloads (HTTP 403), so fetch it in a
browser once and put the file (or the zip) under train/data/psytar/. Layout, taken from the public
bigbio/psytar loader (workbook sheets, not verified against the file on this machine):

    Sentence_Labeling   drug_id, sentence_index, sentences, ADR, WD, SSI, DI, ...
    ADR_Mapped, WD-Mapped, SSI_Mapped, DI_Mapped
                        drug_id, sentence_index (WD: sentence_id), the span column (ADRs / WDs / SSI / DIs),
                        UMLS1, UMLS2, SNOMED-CT, SNOMED-CT.1, entity_type, type, class, ...

We keep ADR, WD and SSI spans (symptoms a patient notices; drug indications are conditions, dropped), map each
span to HPO with the shipped ontology's lexical matcher (Ontology.best_match) and keep it only when the match
score is at least --min-conf (default 0.95: exact label or synonym). Everything else counts as unmapped and
is reported, never guessed. The output rows are sentence-level, marked gold_complete=false (unmapped spans and
unannotated mentions exist, so precision is a lower bound) and partial=true (PsyTAR has no negation or family
labels, so those metrics are skipped).

    python psytar_hpo.py --xlsx data/psytar/PsyTAR_dataset.xlsx          # or the .zip
    python psytar_hpo.py --url <direct link to the zip>                  # only if you have one

Writes ../eval/data/psytar_hpo.jsonl and psytar_hpo.stats.json (coverage, honest). No model is involved.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
from prompt import normalise  # noqa: E402

CITATION = ("Zolnoori M, et al. A systematic approach for developing a corpus of patient reported adverse drug "
            "events: A case study for SSRI and SNRI medications. J Biomed Inform 90 (2019). "
            "doi:10.1016/j.jbi.2018.12.005. Licence CC BY 4.0.")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
SPAN_COL = {"ADR": "ADRs", "WD": "WDs", "SSI": "SSI"}  # DI (drug indication) is a condition, not used
DEFAULT_XLSX = HERE / "data" / "psytar" / "PsyTAR_dataset.xlsx"
DEFAULT_OUT = HERE.parent / "eval" / "data" / "psytar_hpo.jsonl"


# ---- minimal stdlib xlsx reader -------------------------------------------------------------
def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(data: bytes) -> dict[str, list[dict]]:
    """Workbook bytes -> {sheet name: [row dict keyed by the header row]}. Strings and numbers only."""
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall("p:Relationship", NS)}
    out = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS).findall("m:sheet", NS):
        target = rels[sh.get(f"{{{NS['r']}}}id")].lstrip("/")
        path = target if target.startswith("xl/") else "xl/" + target
        rows = []
        for row in ET.fromstring(z.read(path)).iter(f"{{{NS['m']}}}row"):
            cells = {}
            for c in row.findall("m:c", NS):
                t, v = c.get("t"), c.find("m:v", NS)
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                elif v is None or v.text is None:
                    continue
                elif t == "s":
                    val = shared[int(v.text)]
                else:
                    val = v.text
                cells[_col(c.get("r"))] = val
            rows.append(cells)
        if not rows:
            out[sh.get("name")] = []
            continue
        header = {i: str(h).strip() for i, h in rows[0].items() if str(h).strip()}
        out[sh.get("name")] = [{h: r[i] for i, h in header.items() if i in r} for r in rows[1:]]
    return out


def workbook_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if zipfile.is_zipfile(io.BytesIO(raw)) and "xl/workbook.xml" not in zipfile.ZipFile(io.BytesIO(raw)).namelist():
        z = zipfile.ZipFile(io.BytesIO(raw))  # a zip that holds the workbook: read the member in memory
        names = [n for n in z.namelist() if n.lower().endswith(".xlsx") and not n.startswith("__MACOSX")]
        if not names:
            raise SystemExit(f"no .xlsx inside {path}")
        return z.read(names[0])
    return raw


# ---- mapping --------------------------------------------------------------------------------
def _id(v) -> str:
    s = str(v).strip()
    return s[:-2] if re.fullmatch(r"\d+\.0", s) else s


def _sheet(sheets: dict, wanted: str):
    key = lambda s: s.strip().lower().replace("-", "_")
    for name, rows in sheets.items():
        if key(name) == key(wanted):
            return rows
    return None


def build(sheets: dict, onto, min_conf: float = 0.95):
    """-> (rows, stats). onto needs best_match(text) -> (Term, score) | None."""
    sents = _sheet(sheets, "Sentence_Labeling")
    if sents is None:
        raise SystemExit(f"no Sentence_Labeling sheet; sheets found: {list(sheets)}")
    text = {(_id(r.get("drug_id", "")), _id(r.get("sentence_index", ""))): str(r.get("sentences", "")).strip()
            for r in sents if str(r.get("sentences", "")).strip()}
    stats = {"sentences_total": len(text), "mentions_total": 0, "mentions_by_type": {}, "not_verbatim": 0,
             "no_match": 0, "below_threshold": 0, "mapped": 0, "min_conf": min_conf, "sheets_missing": []}
    by_sent: dict[tuple, list] = {}
    for typ, col in SPAN_COL.items():
        rows = _sheet(sheets, f"{typ}_Mapped")
        if rows is None:
            stats["sheets_missing"].append(f"{typ}_Mapped")
            continue
        for r in rows:
            span = str(r.get(col, "")).strip()
            idx = r.get("sentence_index", r.get("sentence_id", ""))
            key = (_id(r.get("drug_id", "")), _id(idx))
            if not span or key not in text:
                continue
            stats["mentions_total"] += 1
            stats["mentions_by_type"][typ] = stats["mentions_by_type"].get(typ, 0) + 1
            i = text[key].lower().find(span.lower())
            if i < 0:
                stats["not_verbatim"] += 1
                continue
            quote = text[key][i:i + len(span)]
            m = onto.best_match(span)
            if m is None:
                stats["no_match"] += 1
                continue
            term, score = m
            if score < min_conf:
                stats["below_threshold"] += 1
                continue
            stats["mapped"] += 1
            ent = normalise({"quote": quote, "canonical": term.label, "hpo_id": term.hpo_id, "type": "symptom"})
            if all(e["hpo_id"] != ent["hpo_id"] for e in by_sent.setdefault(key, [])):
                by_sent[key].append(ent)
    rows = [{"id": f"psytar-{k[0]}-{k[1]}", "diary": text[k], "target": {"entities": ents}, "lang": "en",
             "gold_complete": False, "partial": True, "source": "PsyTAR", "licence": "CC BY 4.0"}
            for k, ents in sorted(by_sent.items())]
    stats["rows"] = len(rows)
    stats["mapping_coverage"] = round(stats["mapped"] / stats["mentions_total"], 4) if stats["mentions_total"] else None
    stats["citation"] = CITATION
    return rows, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default=str(DEFAULT_XLSX), help="PsyTAR_dataset.xlsx or the zip that holds it")
    ap.add_argument("--url", default="", help="direct link to the zip, if you have one")
    ap.add_argument("--min-conf", type=float, default=0.95)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    path = Path(a.xlsx)
    if not path.exists() and a.url:
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(a.url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        except Exception as e:
            sys.exit(f"download failed: {e!r}")
    if not path.exists():
        sys.exit(f"{path} not found. Download PsyTAR (CC BY 4.0) in a browser from\n"
                 "https://www.askapatient.com/research/pharmacovigilance/corpus-ades-psychiatric-medications.asp\n"
                 "(the site blocks scripted requests) and save it there, then rerun.")
    from clario.knowledge import Ontology
    rows, stats = build(read_xlsx(workbook_bytes(path)), Ontology.load(), a.min_conf)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    out.with_suffix(".stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps({k: v for k, v in stats.items() if k != "citation"}, indent=2))


if __name__ == "__main__":
    main()
