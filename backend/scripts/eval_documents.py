"""Run a folder of generated referti (see make_referti.py) through the page extraction and score it.

    CLARIO_OFFLINE=1 uv run python scripts/eval_documents.py --dir /tmp/referti --offline
    LLM_BASE_URL=... LLM_MODEL=... uv run python scripts/eval_documents.py --dir /tmp/scans

Writes eval/results/documents.json (live) or documents.offline-fixture.json (--offline). The offline
fixture replays the truth sidecar, so its numbers prove the plumbing only, never model accuracy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clario import documents as docs  # noqa: E402
from clario.config import Settings  # noqa: E402
from clario.llm import make_llm  # noqa: E402

FIELDS = ("value", "unit", "ref_low", "ref_high")


def _fold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("µ", "u"))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace(" ", "")


def _same_num(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-9)


def compare(truth: dict, pred: dict | None) -> dict[str, bool]:
    if pred is None:
        return {f: False for f in FIELDS}
    if truth["value_numeric"] is not None:
        val = pred["value_numeric"] is not None and _same_num(truth["value_numeric"], pred["value_numeric"])
    else:
        val = _fold(truth["value_text"]) == _fold(pred.get("value_text"))
    return {"value": val, "unit": _fold(truth["unit"]) == _fold(pred["unit"]),
            "ref_low": _same_num(truth["ref_low"], pred["ref_low"]),
            "ref_high": _same_num(truth["ref_high"], pred["ref_high"])}


async def run(folder: Path, s: Settings, limit: int | None) -> dict:
    llm = make_llm(s)
    pdfs = sorted(folder.glob("*.pdf"))[:limit]
    if not pdfs:
        raise SystemExit(f"no PDFs in {folder}")
    work = []  # (page, truth rows for that page)
    for f in pdfs:
        tf = f.with_suffix(".truth.json")
        if not tf.exists():
            raise SystemExit(f"missing {tf.name}")
        truth = json.loads(tf.read_text())
        by_page = {p["page"]: p["tests"] for p in truth["pages"]}
        for pg in docs.pdf_pages(f.read_bytes(), f.name):
            work.append((pg, by_page.get(pg.index, [])))
    sem = asyncio.Semaphore(s.doc_workers)

    async def one(i: int, pg: docs.Page):
        async with sem:
            return await docs.extract_page(llm, pg, i + 1, vision_model=s.llm_vision_model,
                                           threshold=s.review_threshold, n_samples=s.doc_samples)

    t0 = time.perf_counter()
    results = await asyncio.gather(*(one(i, pg) for i, (pg, _t) in enumerate(work)), return_exceptions=True)
    wall = time.perf_counter() - t0
    hits = {f: 0 for f in FIELDS}
    n_rows = n_found = n_failed = 0
    for (pg, truth_rows), res in zip(work, results):
        if isinstance(res, Exception):
            n_failed += 1
            preds: dict[str, dict] = {}
        else:
            preds = {docs.test_key(r["test_name"]): r for r in res.rows}
        for t in truth_rows:
            p = preds.get(docs.test_key(t["test_name"]))
            n_rows += 1
            n_found += p is not None
            for f, ok in compare(t, p).items():
                hits[f] += ok
    note = ("Offline fixture replays the truth sidecar. Proves the plumbing only, not model accuracy or speed."
            if s.offline else None)
    return {
        "task": "document_extraction",
        "field_exact_match": {f: round(hits[f] / n_rows, 4) for f in FIELDS},
        "row_recall": round(n_found / n_rows, 4),
        "n": len(pdfs), "n_pages": len(work), "n_rows": n_rows, "pages_failed": n_failed,
        "pages_per_sec": round(len(work) / wall, 2) if wall else None, "wall_s": round(wall, 2),
        "concurrency": s.doc_workers,
        "dataset": f"synthetic-referti/{folder.name}",
        "model": s.llm_vision_model or llm.model, "backend": llm.backend,
        "date": date.today().isoformat(),
        "offline_fixture": s.offline,
        **({"note": note} if note else {}),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=None, help="max documents")
    ap.add_argument("--offline", action="store_true", help="fixture model, plumbing check only")
    a = ap.parse_args()
    s = Settings.from_env(mode="patient", **({"offline": True} if a.offline else {}))
    if s.offline and not a.offline:
        a.offline = True  # CLARIO_OFFLINE=1 in the environment
    res = asyncio.run(run(a.dir, s, a.limit))
    name = "documents.offline-fixture.json" if s.offline else "documents.json"
    out = a.out or ROOT / "eval" / "results" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
