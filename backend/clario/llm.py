"""One OpenAI-compatible client for every backend: Ollama, Lemonade (Ryzen AI), vLLM on Instinct, AMD Token Factory.

Each call records latency, completion tokens and tokens/s so the UI can show where it ran.
JSON outputs are parsed defensively and validated with pydantic, with one retry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, TypeVar

from pydantic import BaseModel, ValidationError

from .config import Settings

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)

RETRY_AFTER_CAP_S = 60.0  # a longer wait (e.g. the daily budget is spent) fails the call instead of hanging it


def retry_delay(headers, attempt: int) -> float | None:
    """Seconds to wait before retrying a 429: Retry-After (or retry-after-ms) when the server sends it, else
    exponential backoff with jitter. None when the server asks for more than RETRY_AFTER_CAP_S."""
    h = headers or {}
    wait: float | None = None
    try:
        if h.get("retry-after-ms"):
            wait = float(h["retry-after-ms"]) / 1000
        elif h.get("retry-after"):
            wait = float(h["retry-after"])
    except (TypeError, ValueError):
        wait = None  # an HTTP-date form: fall back to backoff
    if wait is None:
        wait = min(2.0 ** attempt, 30.0) + random.uniform(0, 1)
    return None if wait > RETRY_AFTER_CAP_S else max(0.0, wait)


def _n_refused(e) -> bool:
    """400 because the server cannot return several choices (Token Factory: "does not support the n parameter")."""
    if getattr(e, "status_code", None) != 400:
        return False
    return "n parameter" in str(getattr(e, "message", "") or e).lower()


class LLMError(RuntimeError):
    pass


@dataclass
class Stats:
    backend: str
    model: str
    latency_ms: float = 0.0
    tokens: int | None = None
    tokens_per_s: float | None = None

    def as_dict(self) -> dict:
        return {"backend": self.backend, "model": self.model, "latency_ms": self.latency_ms,
                "tokens": self.tokens, "tokens_per_s": self.tokens_per_s}


def merge_stats(a: Stats | None, b: Stats) -> Stats:
    """Sum latency and tokens of sequential calls."""
    if a is None:
        return b
    toks = (a.tokens or 0) + (b.tokens or 0) or None
    lat = a.latency_ms + b.latency_ms
    return Stats(a.backend, a.model, round(lat, 1), toks, round(toks / (lat / 1000), 1) if toks and lat else None)


def extract_json(text: str | None) -> Any:
    """First JSON object or array in `text`; tolerates code fences and chatter."""
    if not text:
        raise ValueError("empty response")
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for m in re.finditer(r"[\{\[]", t):
        try:
            return dec.raw_decode(t[m.start():])[0]
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON found in model output")


class LLM:
    """Base: subclasses implement `_complete`."""

    backend = "unconfigured"
    model = "none"
    is_amd = False

    def __init__(self, concurrency: int = 8):
        self._sem = asyncio.Semaphore(concurrency)

    async def _complete(self, task: str, messages: list[dict], json_mode: bool, max_tokens: int | None,
                        payload: dict | None) -> tuple[str, Stats]:
        raise NotImplementedError

    async def complete(self, task: str, messages: list[dict], *, json_mode: bool = False,
                       max_tokens: int | None = None, payload: dict | None = None) -> tuple[str, Stats]:
        async with self._sem:
            return await self._complete(task, messages, json_mode, max_tokens, payload)

    async def stream(self, task: str, messages: list[dict], *, max_tokens: int | None = None,
                     payload: dict | None = None) -> AsyncIterator[tuple[str, Stats | None]]:
        """Yields (delta, None) chunks then ("", final_stats). Default: one non-streamed call."""
        text, st = await self.complete(task, messages, json_mode=True, max_tokens=max_tokens, payload=payload)
        yield text, None
        yield "", st

    async def samples(self, task: str, messages: list[dict], n: int, *, temperature: float = 0.7,
                      schema: dict | None = None, payload: dict | None = None,
                      purpose: str | None = None) -> tuple[list[str], Stats]:
        """n independent JSON completions of the same prompt (self-consistency). Base: n sequential calls.
        `purpose` labels the call in the privacy log (PrivacyLLM); a plain client ignores it."""
        outs: list[str] = []
        total: Stats | None = None
        for _ in range(max(1, n)):
            text, st = await self.complete(task, messages, json_mode=True, payload=payload)
            outs.append(text)
            total = merge_stats(total, st)
        return outs, total  # type: ignore[return-value]

    async def ocr(self, task: str, image_url: str, *, model: str, payload: dict | None = None,
                  purpose: str | None = None) -> tuple[str, Stats]:
        """One page (a data: URL) -> markdown, through an OCR model (Token Factory `POST /ocr`). Base: no OCR."""
        raise LLMError(f"{self.backend} has no OCR endpoint")

    async def json(self, task: str, messages: list[dict], cls: type[T], *, max_tokens: int | None = None,
                   payload: dict | None = None) -> tuple[T, Stats]:
        msgs = list(messages)
        err: Exception | None = None
        for _ in range(2):
            text, st = await self.complete(task, msgs, json_mode=True, max_tokens=max_tokens, payload=payload)
            try:
                return cls.model_validate(extract_json(text)), st
            except (ValueError, ValidationError) as e:
                err = e
                msgs = msgs + [{"role": "assistant", "content": text[:2000]},
                               {"role": "user", "content": "Reply again with ONLY the JSON object for the schema. No prose."}]
        raise LLMError(f"invalid JSON after retry: {err}")


class OpenAICompat(LLM):
    def __init__(self, s: Settings, concurrency: int | None = None):
        super().__init__(concurrency or s.llm_concurrency)
        from openai import AsyncOpenAI

        tf = s.token_factory
        # Token Factory: our own 429 loop (honours Retry-After), so the SDK does not retry on top of it
        self.client = AsyncOpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=300, max_retries=0 if tf else 1)
        self.backend, self.model, self.is_amd = s.llm_backend, s.llm_model, s.llm_on_amd
        self._json_ok = True
        self._schema_mode: str | None = "json_schema"  # json_schema -> guided_json -> None (plain parsing)
        # Token Factory rejects n > 1 with 400: n separate requests instead. Other servers learn it from that 400.
        self._n_ok = not tf
        # every HTTP request takes a slot, so self-consistency fan-out cannot exceed the key's in-flight limit
        self._inflight = asyncio.Semaphore(s.llm_concurrency if tf else 1024)
        self._rate_retries = 6 if tf else 2

    async def _call(self, kw: dict, *, hold_slot: bool = True, send=None):
        """One request (chat.completions unless `send` is given). A 429 is retried after Retry-After (or backoff),
        up to _rate_retries times."""
        import openai

        send = send or self.client.chat.completions.create
        for attempt in range(self._rate_retries + 1):
            try:
                if not hold_slot:
                    return await send(**kw)
                async with self._inflight:
                    return await send(**kw)
            except openai.RateLimitError as e:
                wait = retry_delay(e.response.headers if e.response is not None else None, attempt)
                if wait is None or attempt == self._rate_retries:
                    raise
                log.warning("%s: rate limited (429), retry %d in %.1fs", self.backend, attempt + 1, wait)
                await asyncio.sleep(wait)
        raise AssertionError("unreachable")

    def _json_refused(self, e, kw: dict) -> bool:
        """Some servers (e.g. Ollama with Gemma 4) reject JSON mode with 400/422/501. Drop it and rely on parsing."""
        if "response_format" not in kw or getattr(e, "status_code", None) not in (400, 422, 501):
            return False
        self._json_ok = False
        kw.pop("response_format")
        return True

    def _kw(self, messages, json_mode, max_tokens, model: str | None = None) -> dict:
        kw: dict[str, Any] = {"model": model or self.model, "messages": messages, "temperature": 0.1}
        if max_tokens:
            kw["max_tokens"] = max_tokens
        if json_mode and self._json_ok:
            kw["response_format"] = {"type": "json_object"}
        return kw

    async def _complete(self, task, messages, json_mode, max_tokens, payload):
        import openai

        # messages may carry image parts; payload["_model"] picks a vision model for this call
        kw = self._kw(messages, json_mode, max_tokens, (payload or {}).get("_model"))
        t0 = time.perf_counter()
        try:
            try:
                resp = await self._call(kw)
            except openai.APIStatusError as e:
                if not self._json_refused(e, kw):
                    raise
                t0 = time.perf_counter()
                resp = await self._call(kw)
        except openai.OpenAIError as e:
            raise LLMError(f"{self.backend} call failed: {e}") from e
        dt = time.perf_counter() - t0
        toks = resp.usage.completion_tokens if resp.usage else None
        return (resp.choices[0].message.content or ""), Stats(
            self.backend, self.model, round(dt * 1000, 1), toks, round(toks / dt, 1) if toks and dt else None)

    async def ocr(self, task, image_url, *, model, payload=None, purpose=None):
        """Token Factory OCR (`POST {base}/ocr`, MinerU): takes a data: URL, returns the page as markdown."""
        import openai

        async def send(**body):
            return await self.client.post("/ocr", cast_to=object, body=body)

        body = {"model": model, "document": {"type": "image_url", "image_url": image_url}}
        t0 = time.perf_counter()
        try:
            async with self._sem:
                resp = await self._call(body, send=send)
        except openai.OpenAIError as e:
            raise LLMError(f"{self.backend} OCR failed: {e}") from e
        dt = time.perf_counter() - t0
        pages = resp.get("pages") if isinstance(resp, dict) else None
        if not isinstance(pages, list):
            raise LLMError(f"{self.backend} OCR returned no pages")
        text = "\n\n".join(str(p.get("markdown") or "") for p in pages if isinstance(p, dict))
        return text, Stats(self.backend, model, round(dt * 1000, 1), None, None)

    def _schema_kw(self, kw: dict, schema: dict | None) -> None:
        """Put the JSON schema on the request using the best mode this server has accepted so far."""
        kw.pop("response_format", None)
        kw.pop("extra_body", None)
        if schema and self._schema_mode == "json_schema":
            kw["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}
        elif schema and self._schema_mode == "guided_json":
            kw["extra_body"] = {"guided_json": schema}
        elif self._json_ok:
            kw["response_format"] = {"type": "json_object"}

    def _schema_refused(self, e, schema: dict | None) -> bool:
        """400/422/501 on a schema request: step down json_schema -> guided_json -> plain JSON mode -> plain parsing."""
        if getattr(e, "status_code", None) not in (400, 422, 501):
            return False
        if schema and self._schema_mode == "json_schema":
            self._schema_mode = "guided_json"
        elif schema and self._schema_mode == "guided_json":
            self._schema_mode = None
        elif self._json_ok:
            self._json_ok = False
        else:
            return False
        return True

    async def _create(self, kw: dict, schema: dict | None):
        import openai

        for _ in range(4):
            self._schema_kw(kw, schema)
            try:
                return await self._call(kw)
            except openai.APIStatusError as e:
                if _n_refused(e):  # not a JSON-mode problem: the caller retries with single choices
                    raise
                if not self._schema_refused(e, schema):
                    raise
        raise LLMError(f"{self.backend}: server refused every JSON mode")

    async def samples(self, task, messages, n, *, temperature=0.7, schema=None, payload=None, purpose=None):
        import openai

        n = max(1, n)
        model = (payload or {}).get("_model")  # a vision model for this call, as in _complete
        kw = self._kw(messages, True, None, model) | {"temperature": temperature}
        t0 = time.perf_counter()
        try:
            async with self._sem:
                texts, toks = [], None
                if n == 1 or self._n_ok:
                    try:
                        resp = await self._create(dict(kw) | ({"n": n} if n > 1 else {}), schema)
                        texts = [c.message.content or "" for c in resp.choices[:n]]
                        toks = resp.usage.completion_tokens if resp.usage else None
                    except openai.APIStatusError as e:
                        if not _n_refused(e):
                            raise
                        self._n_ok = False
                if len(texts) < n:  # server ignored `n`: fill up with concurrent single calls
                    more = await asyncio.gather(*[self._create(dict(kw), schema) for _ in range(n - len(texts))])
                    for r in more:
                        texts.append(r.choices[0].message.content or "")
                        toks = (toks or 0) + (r.usage.completion_tokens if r.usage else 0) or None
        except openai.OpenAIError as e:
            raise LLMError(f"{self.backend} call failed: {e}") from e
        dt = time.perf_counter() - t0
        return texts, Stats(self.backend, model or self.model, round(dt * 1000, 1), toks,
                            round(toks / dt, 1) if toks and dt else None)

    async def stream(self, task, messages, *, max_tokens=None, payload=None):
        import openai

        kw = self._kw(messages, True, max_tokens) | {"stream": True, "stream_options": {"include_usage": True}}
        t0 = time.perf_counter()
        n_chunks, toks = 0, None
        try:
            async with self._inflight:  # the request is in flight until the last chunk
                try:
                    it = await self._call(kw, hold_slot=False)
                except openai.APIStatusError as e:
                    if not self._json_refused(e, kw):
                        raise
                    it = await self._call(kw, hold_slot=False)
                async for chunk in it:
                    if chunk.usage:
                        toks = chunk.usage.completion_tokens
                    if chunk.choices and chunk.choices[0].delta.content:
                        n_chunks += 1
                        yield chunk.choices[0].delta.content, None
        except openai.OpenAIError as e:
            raise LLMError(f"{self.backend} stream failed: {e}") from e
        dt = time.perf_counter() - t0
        toks = toks or n_chunks
        yield "", Stats(self.backend, self.model, round(dt * 1000, 1), toks, round(toks / dt, 1) if dt else None)


def make_llm(s: Settings, call_log=None) -> LLM:
    """The configured client. With a `call_log`, wrapped so every call is logged (and redacted when remote)."""
    # one pool wide enough for document batches (CLARIO_DOC_CONCURRENCY), else the client would starve vLLM batching
    concurrency = s.llm_concurrency if s.token_factory else max(s.llm_concurrency, s.doc_workers)
    if s.offline:
        from .fixtures import OfflineLLM

        inner: LLM = OfflineLLM(concurrency)
    else:
        inner = OpenAICompat(s, concurrency)
    if call_log is None:
        return inner
    from .privacy import wrap

    return wrap(inner, s, call_log)  # type: ignore[return-value]
