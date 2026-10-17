"""AMD Token Factory backend: detection, defaults, single-choice sampling, 429 handling, no GPU telemetry."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from clario import gpu as gpumetrics
from clario import llm as llm_mod
from clario.app import create_app
from clario.config import Settings
from clario.llm import OpenAICompat, make_llm, retry_delay

TF = "https://developer.amd.com.cn/radeon/api/v1"
SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
MSGS = [{"role": "user", "content": "x"}]


@pytest.fixture
def env(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_BACKEND", "LLM_CONCURRENCY", "LLM_IS_AMD", "CLARIO_OFFLINE",
              "CLARIO_DOC_CONCURRENCY", "CLARIO_GPU_METRICS_URL"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def completion(n_choices: int = 1, tokens: int = 5) -> dict:
    return {"id": "c", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": i, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps({"a": str(i)})}}
                        for i in range(n_choices)],
            "usage": {"prompt_tokens": 3, "completion_tokens": tokens, "total_tokens": tokens + 3}}


def make(settings: Settings, handler) -> OpenAICompat:
    llm = OpenAICompat(settings)
    llm.client = AsyncOpenAI(base_url=settings.llm_base_url, api_key="k", max_retries=0,
                             http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return llm


def test_detected_from_host_with_defaults(env):
    env.setenv("LLM_BASE_URL", TF)
    for mode in ("patient", "clinic"):
        env.setenv("CLARIO_MODE", mode)
        s = Settings.from_env()
        assert s.token_factory and s.llm_backend == "amd-token-factory" and s.llm_on_amd
        assert s.llm_model == "Gemma-4-31B-IT"  # case-sensitive id, same model for clinic and the patient demo
        assert s.llm_concurrency == 4 and s.doc_workers == 4
    env.setenv("CLARIO_DOC_CONCURRENCY", "32")
    env.setenv("LLM_CONCURRENCY", "50")
    s = Settings.from_env()
    assert s.llm_concurrency == 8 and s.doc_workers == 8  # never above the gateway's in-flight limit per key


def test_forced_by_env_and_other_backends_unchanged(env):
    env.setenv("LLM_BASE_URL", "https://proxy.example/v1")
    env.setenv("LLM_BACKEND", "token-factory")
    assert Settings.from_env().llm_backend == "amd-token-factory"
    env.delenv("LLM_BACKEND")
    env.setenv("LLM_IS_AMD", "1")
    s = Settings.from_env(mode="clinic")
    assert (s.llm_backend, s.llm_on_amd, s.token_factory) == ("amd-vllm", True, False)
    env.delenv("LLM_IS_AMD")
    s = Settings.from_env()
    assert (s.llm_backend, s.llm_on_amd, s.llm_concurrency, s.doc_workers) == ("openai-compatible", False, 8, 32)
    env.setenv("LLM_BACKEND", "nonsense")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_offline_wins_over_token_factory(env):
    env.setenv("LLM_BASE_URL", TF)
    env.setenv("CLARIO_OFFLINE", "1")
    s = Settings.from_env()
    assert s.llm_backend == "offline-fixtures" and not s.token_factory and not s.llm_on_amd


def test_client_reports_backend_and_amd(env):
    env.setenv("LLM_BASE_URL", TF)
    c = make_llm(Settings.from_env())
    assert (c.backend, c.model, c.is_amd) == ("amd-token-factory", "Gemma-4-31B-IT", True)
    assert c.client.max_retries == 0  # our own 429 loop, no SDK retries on top


def test_samples_never_send_n_on_token_factory(env):
    env.setenv("LLM_BASE_URL", TF)
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        assert "n" not in body
        return httpx.Response(200, json=completion())

    llm = make(Settings.from_env(), handler)
    texts, st = asyncio.run(llm.samples("t", MSGS, 5, temperature=0.7, schema=SCHEMA))
    assert len(texts) == 5 and len(seen) == 5 and st.tokens == 25
    assert all(b["response_format"]["type"] == "json_schema" for b in seen)  # schema mode untouched


def test_n_refusal_switches_to_single_requests_and_keeps_schema(env):
    """A server that rejects n with 400 (Token Factory does) must not cost the JSON schema mode."""
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        if body.get("n", 1) > 1:
            return httpx.Response(400, json={"error": {"message": "Model X does not support the n parameter for multiple choices."}})
        return httpx.Response(200, json=completion())

    llm = make(Settings.from_env(llm_base_url="http://llm.test/v1"), handler)
    texts, _ = asyncio.run(llm.samples("t", MSGS, 3, schema=SCHEMA))
    assert len(texts) == 3 and llm._schema_mode == "json_schema" and not llm._n_ok
    seen.clear()
    asyncio.run(llm.samples("t", MSGS, 3, schema=SCHEMA))
    assert len(seen) == 3 and all("n" not in b for b in seen)


def test_429_waits_for_retry_after(env, monkeypatch):
    env.setenv("LLM_BASE_URL", TF)
    calls, waits = [], []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, headers={"retry-after": "2"}, json={"error": {"message": "rate limited"}})
        return httpx.Response(200, json=completion())

    async def fake_sleep(t):
        waits.append(t)

    monkeypatch.setattr(llm_mod.asyncio, "sleep", fake_sleep)
    llm = make(Settings.from_env(), handler)
    text, _ = asyncio.run(llm.complete("t", MSGS, json_mode=True))
    assert json.loads(text) == {"a": "0"} and len(calls) == 3 and waits == [2.0, 2.0]


def test_429_with_long_retry_after_fails_fast(env, monkeypatch):
    env.setenv("LLM_BASE_URL", TF)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "3600"}, json={"error": {"message": "daily budget"}})

    llm = make(Settings.from_env(), handler)
    with pytest.raises(llm_mod.LLMError):
        asyncio.run(llm.complete("t", MSGS))
    assert len(calls) == 1


def test_retry_delay():
    assert retry_delay({"retry-after": "3"}, 0) == 3.0
    assert retry_delay({"retry-after-ms": "500"}, 0) == 0.5
    assert retry_delay({"retry-after": "120"}, 0) is None
    assert 1.0 <= retry_delay({}, 0) <= 2.0 and 4.0 <= retry_delay(None, 2) <= 5.0


def test_in_flight_requests_capped(env):
    env.setenv("LLM_BASE_URL", TF)
    env.setenv("LLM_CONCURRENCY", "2")
    state = {"now": 0, "peak": 0}

    async def handler(req):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        return httpx.Response(200, json=completion())

    llm = make(Settings.from_env(), handler)

    async def go():
        await asyncio.gather(*[llm.samples("t", MSGS, 5, schema=SCHEMA) for _ in range(3)])

    asyncio.run(go())
    assert state["peak"] <= 2


def test_no_gpu_telemetry_on_token_factory(tmp_path, env, monkeypatch):
    monkeypatch.setattr(gpumetrics, "read_cached", lambda ttl=2.0: {"gpu_name": "local card", "util_pct": 5})
    s = Settings.from_env(llm_base_url=TF, data_dir=tmp_path, mode="clinic")
    assert asyncio.run(gpumetrics.read_gpu(s)) is None
    with TestClient(create_app(s)) as c:
        h = c.get("/api/health").json()["llm"]
        assert (h["backend"], h["is_amd"], h["base_url_host"]) == ("amd-token-factory", True, "developer.amd.com.cn")
        assert c.get("/api/system/gpu").json() is None
