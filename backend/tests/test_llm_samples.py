import asyncio
import json

import httpx
from openai import AsyncOpenAI

from clario.config import Settings
from clario.llm import OpenAICompat

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


def completion(n_choices: int, tokens: int = 5) -> dict:
    return {"id": "c", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": i, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps({"a": str(i)})}}
                        for i in range(n_choices)],
            "usage": {"prompt_tokens": 3, "completion_tokens": tokens, "total_tokens": tokens + 3}}


def make(handler) -> OpenAICompat:
    llm = OpenAICompat(Settings.from_env(llm_base_url="http://llm.test/v1"))
    llm.client = AsyncOpenAI(base_url="http://llm.test/v1", api_key="k", max_retries=0,
                             http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return llm


def run(coro):
    return asyncio.run(coro)


def test_samples_use_n_and_json_schema():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        return httpx.Response(200, json=completion(body.get("n", 1)))

    llm = make(handler)
    texts, st = run(llm.samples("t", [{"role": "user", "content": "x"}], 3, temperature=0.7, schema=SCHEMA))
    assert len(texts) == 3 and [json.loads(t)["a"] for t in texts] == ["0", "1", "2"]
    assert len(seen) == 1 and seen[0]["n"] == 3 and seen[0]["temperature"] == 0.7
    assert seen[0]["response_format"] == {"type": "json_schema", "json_schema": {"name": "out", "schema": SCHEMA}}
    assert st.tokens == 5 and st.backend


def test_schema_refused_falls_back_to_guided_json_then_plain():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        rf = body.get("response_format", {}).get("type")
        if rf == "json_schema":
            return httpx.Response(400, json={"error": {"message": "unsupported"}})
        if "guided_json" in body:
            return httpx.Response(422, json={"error": {"message": "unknown field"}})
        return httpx.Response(200, json=completion(1))

    llm = make(handler)
    msgs = [{"role": "user", "content": "x"}]
    texts, _ = run(llm.samples("t", msgs, 1, schema=SCHEMA))
    assert json.loads(texts[0]) == {"a": "0"}
    assert [("guided_json" in b, b.get("response_format", {}).get("type")) for b in seen] == [
        (False, "json_schema"), (True, None), (False, "json_object")]
    assert llm._schema_mode is None
    seen.clear()
    run(llm.samples("t", msgs, 1, schema=SCHEMA))  # remembers: no more refused attempts
    assert len(seen) == 1 and "guided_json" not in seen[0]


def test_guided_json_accepted_after_json_schema_refusal():
    def handler(req):
        body = json.loads(req.content)
        if "response_format" in body and body["response_format"]["type"] == "json_schema":
            return httpx.Response(501, json={"error": {"message": "no"}})
        assert body["guided_json"] == SCHEMA
        return httpx.Response(200, json=completion(1))

    llm = make(handler)
    texts, _ = run(llm.samples("t", [{"role": "user", "content": "x"}], 1, schema=SCHEMA))
    assert json.loads(texts[0]) == {"a": "0"} and llm._schema_mode == "guided_json"


def test_server_ignoring_n_gets_concurrent_calls():
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body.get("n"))
        return httpx.Response(200, json=completion(1))  # always one choice

    llm = make(handler)
    texts, st = run(llm.samples("t", [{"role": "user", "content": "x"}], 4))
    assert len(texts) == 4 and calls == [4, None, None, None]
    assert st.tokens == 20


def test_base_and_offline_samples_are_sequential_calls():
    from clario.fixtures import OfflineLLM

    llm = OfflineLLM(2)
    texts, st = run(llm.samples("rationale", [], 3, payload={"condition": "X", "overlapping_features": ["a"]}))
    assert len(texts) == 3 and st.tokens == 180
    # hedged phrase is unstable across samples, plain phrase is stable
    texts, _ = run(llm.samples("extract", [], 5, payload={"text": "Maybe my knees ache. Tired."}))
    has = lambda t, q: any(q in e["quote"].lower() for e in json.loads(t)["entities"])  # noqa: E731
    assert sum(has(t, "knees ache") for t in texts) == 3 and sum(has(t, "tired") for t in texts) == 5
