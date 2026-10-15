import io
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clario import documents as docs
from clario.app import create_app
from clario.documents import RawDoc, RawLab, consistency, extract_page
from clario.llm import LLM, Stats
from conftest import PASS, settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_documents  # noqa: E402
import make_referti  # noqa: E402


def make(tmp_path: Path, n_docs=2, pages=2, seed=5, noise=False) -> Path:
    d = tmp_path / "referti"
    d.mkdir(exist_ok=True)
    for doc, pdf in make_referti.make_docs(n_docs, pages, seed, noise):
        (d / f"{doc['doc_id']}.pdf").write_bytes(pdf)
        (d / f"{doc['doc_id']}.truth.json").write_text(json.dumps(doc))
    return d


def upload(client, paths: list[Path]):
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in paths]
    return client.post("/api/documents/batch", files=files)


def events(client, bid) -> list[dict]:
    out = []
    with client.stream("GET", f"/api/documents/batch/{bid}/events") as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                out.append(json.loads(line[5:].strip()))
                if out[-1]["done"]:
                    break
    return out


@pytest.fixture
def folder(tmp_path):
    return make(tmp_path)


# ------------------------------------------------------------ rendering + generator
def test_pdf_split_page_count_and_size_cap(folder):
    pdfs = sorted(folder.glob("*.pdf"))
    pages = docs.pdf_pages(pdfs[0].read_bytes(), pdfs[0].name)
    assert len(pages) == 2 and [p.index for p in pages] == [1, 2]
    from PIL import Image

    im = Image.open(io.BytesIO(pages[0].jpeg))
    assert im.format == "JPEG" and max(im.size) == docs.MAX_DIM
    small = docs.pdf_pages(pdfs[0].read_bytes(), "x", max_dim=800)
    assert max(Image.open(io.BytesIO(small[0].jpeg)).size) == 800
    assert len(docs.file_pages("a.jpg", pages[0].jpeg)) == 1  # a photo is one page
    with pytest.raises(ValueError):
        docs.pdf_pages(b"%PDF-1.4 garbage", "bad.pdf")


def test_generator_truth_matches_rendered_values(folder):
    import pypdfium2 as pdfium

    for f in folder.glob("*.pdf"):
        truth = json.loads(f.with_suffix(".truth.json").read_text())
        pdf = pdfium.PdfDocument(f.read_bytes())
        assert len(pdf) == len(truth["pages"]) == 2
        for i, pg in enumerate(truth["pages"]):
            text = pdf[i].get_textpage().get_text_bounded()
            assert 8 <= len(pg["tests"]) <= 25
            assert truth["date_it"] in text and truth["lab"]["name"] in text
            for t in pg["tests"]:
                assert t["test_name"] in text and t["shown"] in text
                if t["value_numeric"] is not None:  # exact printed value round-trips to the truth number
                    assert float(t["shown"].replace(",", ".")) == t["value_numeric"]
        assert docs.decode_truth(pdf.get_metadata_dict()["Keywords"])["doc_id"] == truth["doc_id"]


def test_generator_has_in_and_out_of_range_and_is_seeded(tmp_path):
    a = make_referti.make_docs(3, 1, seed=9)
    b = make_referti.make_docs(3, 1, seed=9)
    assert [d for d, _ in a] == [d for d, _ in b]
    flags = {t["flag"] for d, _ in a for p in d["pages"] for t in p["tests"]}
    assert {"normal", "high"} <= flags


def test_scan_noise_output_is_image_pdf_with_truth(tmp_path):
    (doc, pdf), = make_referti.make_docs(1, 1, seed=4, noise=True)
    import pypdfium2 as pdfium

    p = pdfium.PdfDocument(pdf)
    assert p[0].get_textpage().get_text_bounded().strip() == ""  # no text layer, pixels only
    assert docs.pdf_pages(pdf)[0].offline["rows"] == doc["pages"][0]["tests"]


# ------------------------------------------------------------ rules in code
def test_flag_is_recomputed_in_code():
    assert docs.compute_flag(5.1, 0.0, 5.0, "normal") == "high"
    assert docs.compute_flag(0.3, 0.5, 0.9, None) == "low"
    assert docs.compute_flag(0.6, 0.5, 0.9, "high") == "normal"
    assert docs.compute_flag(None, None, None, "high") is None  # no printed range: no flag
    assert docs.compute_flag(5.0, None, None, "normal") is None


def test_raw_lab_reads_italian_decimals_and_text_results():
    r = RawLab.model_validate({"test_name": "TSH", "value_numeric": "4,52", "ref_low": "0,4", "date": "08/04/2025"})
    assert (r.value_numeric, r.ref_low, r.date) == (4.52, 0.4, "2025-04-08")
    r = RawLab.model_validate({"test_name": "ANA", "value_numeric": "Positivo 1:160"})
    assert r.value_numeric is None and r.value_text == "Positivo 1:160"


class FakeSamples(LLM):
    """Three samples: the second disagrees on C3's value, the third on its unit."""

    backend, model = "fake", "fake-v"

    def __init__(self, texts):
        super().__init__(4)
        self.texts = texts

    async def _complete(self, *a, **k):
        return self.texts[0], Stats("fake", "fake-v")

    async def samples(self, task, messages, n, **kw):
        return [(t, Stats("fake", "fake-v")) for t in self.texts[:n]]


def _doc(c3_val, c3_unit):
    return json.dumps({"rows": [{"test_name": "C3", "value_numeric": c3_val, "unit": c3_unit, "confidence": 0.99},
                                {"test_name": "C4", "value_numeric": 22, "unit": "mg/dL", "confidence": 0.99}]})


async def test_self_consistency_confidence_when_client_has_samples():
    llm = FakeSamples([_doc(100, "mg/dL"), _doc(110, "mg/dL"), _doc(100, "g/L")])
    page = docs.Page(b"x", 1, "t")
    res = await extract_page(llm, page, 1, threshold=0.7, n_samples=3)
    by = {r["test_name"]: r for r in res.rows}
    assert by["C4"]["confidence"] == 1.0 and by["C4"]["review"] == "auto"
    assert round(by["C3"]["confidence"], 2) == 0.67 and by["C3"]["review"] == "needs_review"
    docs_ = [RawDoc.model_validate(json.loads(t)) for t in llm.texts]
    assert [round(c, 2) for c in consistency(docs_)] == [0.67, 1.0]


async def test_model_confidence_used_without_samples():
    class Plain(LLM):
        backend, model = "fake", "fake-v"

        def __init__(self, texts):
            super().__init__(4)
            self.texts = texts

        async def _complete(self, *a, **k):
            return self.texts[0], Stats("fake", "fake-v")

    llm = Plain([json.dumps({"rows": [{"test_name": "VES", "value_numeric": 30, "unit": "mm/h", "confidence": 0.4},
                                      {"test_name": "PCR", "value_numeric": 2, "unit": "mg/L"}]})])
    res = await extract_page(llm, docs.Page(b"x", 1, "t"), 3)
    by = {r["test_name"]: r for r in res.rows}
    assert by["VES"]["review"] == "needs_review" and by["VES"]["page"] == 3
    assert by["PCR"]["confidence"] is None and by["PCR"]["review"] == "needs_review"  # no signal means a person looks


# ------------------------------------------------------------ API
def test_batch_upload_sse_and_labs(unlocked, folder):
    pdfs = sorted(folder.glob("*.pdf"))
    r = upload(unlocked, pdfs)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pages"] == 4 and body["batch_id"].startswith("b_")
    evs = events(unlocked, body["batch_id"])
    last = evs[-1]
    assert set(last) >= {"pages_done", "pages_total", "pages_per_sec", "gpu"}
    assert last["pages_done"] == last["pages_total"] == 4 and last["done"] and last["gpu"] is None
    assert isinstance(last["pages_per_sec"], float) and last["errors"] == 0

    entries = unlocked.get("/api/entries").json()
    assert [e["text"] for e in entries] == ["Imported documents (4 pages)"]
    data = unlocked.get("/api/labs").json()
    truth = [json.loads(f.with_suffix(".truth.json").read_text()) for f in pdfs]
    n_truth = sum(len(p["tests"]) for t in truth for p in t["pages"])
    assert data["n_results"] == n_truth
    c3 = next(t for t in data["tests"] if t["test_key"] == "c3")
    assert len(c3["values"]) == 4 and [v["date"] for v in c3["values"]] == sorted(v["date"] for v in c3["values"])  # history across documents
    assert c3["unit"] == "mg/dL"
    assert data["out_of_range"] == sum(t["out_of_range"] for t in data["tests"])
    for t in data["tests"]:
        assert t["out_of_range"] == (t["latest"]["flag"] in ("low", "high"))


def test_progress_stream_carries_the_gpu_reading(tmp_path, folder):
    async def gpu_reader(_settings):
        return {"name": "AMD Instinct MI300X", "util": 61}

    with TestClient(create_app(settings(tmp_path), gpu_reader=gpu_reader)) as c:
        c.post("/api/vault/setup", json={"passphrase": PASS})
        bid = upload(c, sorted(folder.glob("*.pdf"))[:1]).json()["batch_id"]
        assert events(c, bid)[-1]["gpu"] == {"name": "AMD Instinct MI300X", "util": 61}


def test_threshold_routes_low_confidence_rows_to_review(tmp_path, folder):
    pdf = sorted(folder.glob("*.pdf"))[:1]
    counts = {}
    for thr in (0.7, 0.5):  # fixture confidences: 0.93 and, on every 6th row, 0.55
        with TestClient(create_app(settings(tmp_path / str(thr), review_threshold=thr))) as c:
            c.post("/api/vault/setup", json={"passphrase": PASS})
            events(c, upload(c, pdf).json()["batch_id"])
            d = c.get("/api/labs").json()
            counts[thr] = d["needs_review"]
            if thr == 0.7:
                rows = [v for t in d["tests"] for v in t["values"]]
                assert all((v["review"] == "needs_review") == (v["confidence"] < 0.7) for v in rows)
    assert counts[0.7] > 0 and counts[0.5] == 0


def _first_review_row(client):
    for t in client.get("/api/labs").json()["tests"]:
        for v in t["values"]:
            if v["review"] == "needs_review":
                return t, v
    raise AssertionError("no needs_review row")


def test_confirm_correct_reject(unlocked, folder):
    events(unlocked, upload(unlocked, sorted(folder.glob("*.pdf"))).json()["batch_id"])
    total = unlocked.get("/api/labs").json()["n_results"]
    t, v = _first_review_row(unlocked)
    r = unlocked.patch(f"/api/labs/{v['id']}", json={"action": "confirm"})
    assert r.status_code == 200 and r.json()["review"] == "confirmed"

    t2, v2 = _first_review_row(unlocked)
    hi = t2["ref_high"]
    if hi is None:  # qualitative test: correct the text instead
        r = unlocked.patch(f"/api/labs/{v2['id']}", json={"action": "correct", "value_text": "Negativo"})
        assert r.json()["review"] == "corrected" and r.json()["value_text"] == "Negativo"
    else:
        r = unlocked.patch(f"/api/labs/{v2['id']}", json={"action": "correct", "value_numeric": hi + 10})
        assert r.json()["review"] == "corrected" and r.json()["flag"] == "high"
        r = unlocked.patch(f"/api/labs/{v2['id']}", json={"action": "correct", "value_numeric": hi - 0.0001})
        assert r.json()["flag"] == "normal"  # recomputed in code

    assert unlocked.patch(f"/api/labs/{v2['id']}", json={"action": "correct"}).status_code == 422
    assert unlocked.patch("/api/labs/nope", json={"action": "confirm"}).status_code == 404
    assert unlocked.patch(f"/api/labs/{v2['id']}", json={"action": "bogus"}).status_code == 422

    t3, v3 = _first_review_row(unlocked)
    assert unlocked.patch(f"/api/labs/{v3['id']}", json={"action": "reject"}).json()["review"] == "rejected"
    after = unlocked.get("/api/labs").json()
    assert after["n_results"] == total - 1
    ids = {x["id"] for t in after["tests"] for x in t["values"]}
    assert v3["id"] not in ids and v["id"] in ids
    assert unlocked.get("/api/labs?include_rejected=true").json()["n_results"] == total


def test_upload_rejects_junk_and_locked(patient, unlocked):
    assert patient.post("/api/documents/batch", files=[("files", ("a.pdf", b"%PDF-1.4 nope", "application/pdf"))]).status_code == 422
    assert patient.post("/api/documents/batch", files=[("files", ("a.txt", b"hello", "text/plain"))]).status_code == 422
    patient.post("/api/vault/lock")
    assert patient.post("/api/documents/batch", files=[("files", ("a.pdf", b"x", "application/pdf"))]).status_code == 423
    assert patient.get("/api/labs").status_code == 423


def test_pages_are_encrypted_at_rest(unlocked, folder):
    pdf = sorted(folder.glob("*.pdf"))[0]
    events(unlocked, upload(unlocked, [pdf]).json()["batch_id"])
    db = (unlocked.app.state.settings.data_dir / "clario.db").read_bytes()
    assert b"Emoglobina" not in db and b"JFIF" not in db and b"Laboratorio" not in db


# ------------------------------------------------------------ eval script
async def test_eval_script_runs_offline_on_two_tiny_docs(tmp_path):
    folder = make(tmp_path, n_docs=2, pages=1, seed=2)
    s = settings(tmp_path)
    res = await eval_documents.run(folder, s, None)
    assert res["n"] == 2 and res["n_pages"] == 2 and res["offline_fixture"] is True
    assert res["backend"] == "offline-fixtures"
    assert res["field_exact_match"] == {"value": 1.0, "unit": 1.0, "ref_low": 1.0, "ref_high": 1.0}
    assert res["pages_per_sec"] > 0 and res["date"] and res["dataset"] and res["model"]
    assert eval_documents.compare({"value_numeric": 5.0, "value_text": None, "unit": "mg/L", "ref_low": 0.0, "ref_high": 5.0},
                                  {"value_numeric": 5.1, "value_text": None, "unit": "mg/L", "ref_low": 0.0, "ref_high": 5.0}
                                  )["value"] is False
