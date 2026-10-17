"""Lab pages on AMD Token Factory: MinerU OCR -> markdown -> Gemma 31B structures it; image path as the fallback."""

import asyncio
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from clario import documents as docs
from clario import privacy
from clario.app import create_app
from clario.config import Settings
from clario.llm import LLM, LLMError, OpenAICompat, Stats
from conftest import PASS, settings

TF = "https://developer.amd.com.cn/radeon/api/v1"
DEMO = Path(__file__).resolve().parents[1] / "clario" / "data" / "demo"

MARKDOWN = """# Centro Diagnostico Borgo Alto

Paziente: Giulia Ferrante Nata il: 12/02/1992

Data del prelievo: 07/04/2025 Pagina 1 di 1

<table><tr><td>Esame</td><td>Risultato</td><td>Unita&#x27;</td><td>Valori di riferimento</td></tr>\
<tr><td>Sodio</td><td>149</td><td>mmol/L</td><td>136 - 145</td></tr>\
<tr><td>PCR</td><td>1,8</td><td>mg/L</td><td>0,0 - 5,0</td></tr>\
<tr><td>Colesterolo totale</td><td>264</td><td>mg/dL</td><td>&lt; 200</td></tr>\
<tr><td>ANA</td><td>Positivo 1:80</td><td></td><td>Negativo</td></tr></table>
"""


def _rows(pcr_value=1.8):
    return {"date": None, "rows": [
        {"test_name": "Sodio", "value_numeric": 149, "unit": "mmol/L", "ref_low": 136, "ref_high": 145, "confidence": 0.95},
        {"test_name": "PCR", "value_numeric": pcr_value, "unit": "mg/L", "ref_low": 0, "ref_high": 5, "confidence": 0.95},
        {"test_name": "Colesterolo totale", "value_numeric": 264, "unit": "mg/dL", "ref_high": 200, "confidence": 0.9},
        {"test_name": "ANA", "value_text": "Positivo 1:80", "confidence": 0.9}]}


class FakeOCR(LLM):
    """OCR returns MARKDOWN (or fails); the text model returns `doc`. Records what each call saw."""

    backend, model = "amd-token-factory", "Gemma-4-31B-IT"

    def __init__(self, doc, fail_ocr=False):
        super().__init__(4)
        self.doc, self.fail_ocr, self.seen, self.ocr_calls = doc, fail_ocr, [], []

    async def ocr(self, task, image_url, *, model, payload=None, purpose=None):
        self.ocr_calls.append((model, image_url[:23]))
        if self.fail_ocr:
            raise LLMError("ocr down")
        return MARKDOWN, Stats(self.backend, model)

    async def _complete(self, task, messages, json_mode, max_tokens, payload):
        self.seen.append((messages, payload))
        return json.dumps(self.doc), Stats(self.backend, self.model)


def test_settings_default_to_mineru_on_token_factory(monkeypatch):
    for k in ("LLM_OCR_MODEL", "CLARIO_DOC_SAMPLES", "LLM_BACKEND", "CLARIO_OFFLINE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", TF)
    s = Settings.from_env()
    assert s.llm_ocr_model == "MinerU2.5-Pro" and s.doc_samples == 1  # one structuring call per page on the shared key
    monkeypatch.setenv("LLM_OCR_MODEL", "off")
    assert Settings.from_env().llm_ocr_model is None
    monkeypatch.setenv("LLM_BASE_URL", "https://vllm.example/v1")
    monkeypatch.delenv("LLM_OCR_MODEL")
    s = Settings.from_env()
    assert s.llm_ocr_model is None and s.doc_samples == 3  # other backends keep the image path and 3 samples


def test_date_from_text_prefers_collection_and_skips_birth():
    assert docs.date_from_text(MARKDOWN) == "2025-04-07"
    assert docs.date_from_text("Nata il: 12/02/1992\nReferto del 03/05/2025") == "2025-05-03"
    assert docs.date_from_text("Nato il 01/01/1980") is None
    assert docs.date_from_text("Collected on 2025-09-15") == "2025-09-15"


def test_grounding_checks_name_and_every_number():
    ok = docs.RawLab.model_validate({"test_name": "PCR", "value_numeric": "1,8", "ref_low": 0, "ref_high": 5})
    assert docs.grounded(ok, MARKDOWN)
    assert not docs.grounded(ok.model_copy(update={"value_numeric": 18.0}), MARKDOWN)
    assert not docs.grounded(ok.model_copy(update={"test_name": "TSH"}), MARKDOWN)
    ana = docs.RawLab.model_validate({"test_name": "ANA", "value_text": "Positivo 1:80"})
    assert docs.grounded(ana, MARKDOWN) and not docs.grounded(ana.model_copy(update={"value_text": "Negativo 1:640"}), MARKDOWN)


async def test_ocr_then_text_model():
    llm = FakeOCR(_rows())
    page = docs.Page(b"jpeg", 1, "ref.pdf")
    res = await docs.extract_page(llm, page, 2, vision_model="Gemma-4-31B-IT", ocr_model="MinerU2.5-Pro",
                                  structure="model", n_samples=1)
    assert res.reader == "ocr" and res.model == "MinerU2.5-Pro + Gemma-4-31B-IT"
    assert llm.ocr_calls == [("MinerU2.5-Pro", "data:image/jpeg;base64,")]
    msgs, payload = llm.seen[0]
    assert isinstance(msgs[1]["content"], str) and "Positivo 1:80" in msgs[1]["content"]  # text only, no image part
    assert "_model" not in payload  # structuring runs on the text model
    by = {r["test_name"]: r for r in res.rows}
    assert by["Sodio"]["flag"] == "high" and by["Sodio"]["review"] == "auto" and by["Sodio"]["page"] == 2
    assert all(r["date"] == "2025-04-07" for r in res.rows)  # read in code: the model said null
    assert by["ANA"]["value_text"] == "Positivo 1:80"


async def test_row_not_in_the_ocr_text_waits_for_a_person():
    res = await docs.extract_page(FakeOCR(_rows(pcr_value=18)), docs.Page(b"j", 1, "r"), 1,
                                  ocr_model="MinerU2.5-Pro", structure="model", n_samples=1)
    pcr = next(r for r in res.rows if r["test_name"] == "PCR")
    assert pcr["review"] == "needs_review" and pcr["confidence"] == docs.UNGROUNDED_CAP


async def test_ocr_failure_falls_back_to_the_image():
    llm = FakeOCR(_rows(), fail_ocr=True)
    res = await docs.extract_page(llm, docs.Page(b"j", 1, "r"), 1, vision_model="Gemma-4-31B-IT",
                                  ocr_model="MinerU2.5-Pro", n_samples=1)
    msgs, payload = llm.seen[0]
    assert res.reader == "vision" and payload["_model"] == "Gemma-4-31B-IT"
    assert any(p.get("type") == "image_url" for p in msgs[1]["content"])
    assert len(res.rows) == 4


async def test_table_read_in_code_needs_no_second_call():
    llm = FakeOCR(_rows())
    res = await docs.extract_page(llm, docs.Page(b"j", 1, "r"), 3, ocr_model="MinerU2.5-Pro", n_samples=3)
    assert res.reader == "ocr-table" and res.model == "MinerU2.5-Pro" and llm.seen == []  # one request per page
    by = {r["test_name"]: r for r in res.rows}
    assert (by["PCR"]["value_numeric"], by["PCR"]["ref_low"], by["PCR"]["ref_high"], by["PCR"]["unit"]) == (1.8, 0.0, 5.0, "mg/L")
    assert (by["Colesterolo totale"]["ref_low"], by["Colesterolo totale"]["ref_high"], by["Colesterolo totale"]["flag"]) == (None, 200.0, "high")
    assert by["ANA"]["value_text"] == "Positivo 1:80" and by["ANA"]["ref_low"] is None
    assert all(r["review"] == "auto" and r["date"] == "2025-04-07" and r["page"] == 3 for r in res.rows)


def test_parse_table_odd_cells_wait_and_no_table_means_model():
    md = ("<table><tr><td>Test</td><td>Result</td><td>Unit</td><td>Reference range</td></tr>"
          "<tr><td>TSH</td><td>4,52 H</td><td>mIU/L</td><td>0,40 - 4,00</td></tr>"
          "<tr><td>Ferritina</td><td>1 2</td><td>ng/mL</td><td>15 - 150</td></tr>"
          "<tr><td>PCR</td><td>3</td><td>mg/L</td><td>0,5 -</td></tr></table>")
    by = {r.test_name: r for r in docs.parse_table(md).rows}
    assert by["TSH"].value_numeric == 4.52 and by["TSH"].confidence == docs.TABLE_CONFIDENCE  # H marker stripped
    assert by["Ferritina"].confidence == docs.UNGROUNDED_CAP and by["PCR"].confidence == docs.UNGROUNDED_CAP
    pipe = "| Esame | Risultato | Unita | Valori di riferimento |\n|---|---|---|---|\n| Sodio | 149 | mmol/L | 136 - 145 |"
    assert [(r.test_name, r.value_numeric, r.ref_high) for r in docs.parse_table(pipe).rows] == [("Sodio", 149.0, 145.0)]
    assert docs.parse_table("Referto senza tabella. Emoglobina 13,2 g/dL") is None


def test_openai_compat_posts_to_ocr_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", TF)
    seen = []

    def handler(req):
        seen.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"model": "MinerU2.5-Pro", "pages": [{"index": 0, "markdown": "| a |"}],
                                         "usage_info": {"pages_processed": 1}})

    llm = OpenAICompat(Settings.from_env())
    llm.client = AsyncOpenAI(base_url=TF, api_key="k", max_retries=0,
                             http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    text, st = asyncio.run(llm.ocr("document", "data:image/jpeg;base64,AAAA", model="MinerU2.5-Pro"))
    assert text == "| a |" and st.model == "MinerU2.5-Pro"
    url, body = seen[0]
    assert url == TF + "/ocr"
    assert body == {"model": "MinerU2.5-Pro", "document": {"type": "image_url", "image_url": "data:image/jpeg;base64,AAAA"}}


def test_ocr_429_waits_for_retry_after(monkeypatch):
    from clario import llm as llm_mod

    monkeypatch.setenv("LLM_BASE_URL", TF)
    calls, waits = [], []

    def handler(req):
        calls.append(1)
        if len(calls) < 2:
            return httpx.Response(429, headers={"retry-after": "3"}, json={"error": {"message": "rate limited"}})
        return httpx.Response(200, json={"pages": [{"markdown": "ok"}]})

    async def fake_sleep(t):
        waits.append(t)

    monkeypatch.setattr(llm_mod.asyncio, "sleep", fake_sleep)
    llm = OpenAICompat(Settings.from_env())
    llm.client = AsyncOpenAI(base_url=TF, api_key="k", max_retries=0,
                             http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(llm.ocr("document", "data:x", model="MinerU2.5-Pro"))[0] == "ok" and waits == [3.0]


async def test_ocr_call_is_in_the_hash_chained_log(tmp_path):
    log = privacy.CallLog(privacy.FileStore(tmp_path / "log.jsonl"))
    llm = privacy.PrivacyLLM(FakeOCR(_rows()), log, pseudonymize=True)
    res = await docs.extract_page(llm, docs.Page(b"j", 1, "r"), 1, ocr_model="MinerU2.5-Pro", structure="model",
                                  n_samples=1)
    assert res.reader == "ocr" and len(res.rows) == 4
    recs = log.calls()
    by_model = {r["model"]: r for r in recs}
    assert set(by_model) == {"MinerU2.5-Pro", "Gemma-4-31B-IT"} and all(r["purpose"] == "document" for r in recs)
    assert by_model["MinerU2.5-Pro"]["images"] == 1 and not by_model["MinerU2.5-Pro"]["redacted"]
    text_rec = by_model["Gemma-4-31B-IT"]
    assert text_rec["images"] == 0 and text_rec["replacements"] >= 2  # name and dates hidden from the text model
    assert log.verify()["ok"]


def test_offline_batch_through_ocr_path(tmp_path):
    with TestClient(create_app(settings(tmp_path, llm_ocr_model="MinerU2.5-Pro"))) as c:
        c.post("/api/vault/setup", json={"passphrase": PASS})
        files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in sorted(DEMO.glob("*.pdf"))]
        bid = c.post("/api/documents/batch", files=files).json()["batch_id"]
        last = None
        with c.stream("GET", f"/api/documents/batch/{bid}/events") as r:
            for line in r.iter_lines():
                if line.startswith("data:"):
                    last = json.loads(line[5:].strip())
                    if last["done"]:
                        break
        assert last["errors"] == 0 and last["model"] == "MinerU2.5-Pro"  # table read in code
        assert last["backend"] == "offline-fixtures" and last["elapsed_s"] >= 0
        data = c.get("/api/labs").json()
        n_truth = sum(len(p["tests"]) for f in DEMO.glob("*.truth.json") for p in json.loads(f.read_text())["pages"])
        assert data["n_results"] == n_truth
        truth_dates = {json.loads(f.read_text())["date"] for f in DEMO.glob("*.truth.json")}
        assert {v["date"] for t in data["tests"] for v in t["values"]} == truth_dates
        calls = c.get("/api/privacy/calls?limit=50").json()
        assert sum(r["model"] == "MinerU2.5-Pro" for r in calls) == 3
