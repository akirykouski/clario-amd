"""One OpenAI-compatible client for every backend: Ollama, Lemonade (Ryzen AI), vLLM on Instinct.

Each call records latency, completion tokens and tokens/s so the UI can show where it ran.
JSON outputs are parsed defensively and validated with pydantic, with one retry.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, TypeVar

from pydantic import BaseModel, ValidationError

from .config import Settings

T = TypeVar("T", bound=BaseModel)


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
                      schema: dict | None = None, payload: dict | None = None) -> tuple[list[str], Stats]:
        """n independent JSON completions of the same prompt (self-consistency). Base: n sequential calls."""
        outs: list[str] = []
        total: Stats | None = None
        for _ in range(max(1, n)):
            text, st = await self.complete(task, messages, json_mode=True, payload=payload)
            outs.append(text)
            total = merge_stats(total, st)
        return outs, total  # type: ignore[return-value]

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
    def __init__(self, s: Settings):
        super().__init__(s.llm_concurrency)
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=300, max_retries=1)
        self.backend, self.model, self.is_amd = s.llm_backend, s.llm_model, s.llm_is_amd
        self._json_ok = True
        self._schema_mode: str | None = "json_schema"  # json_schema -> guided_json -> None (plain parsing)

    def _json_refused(self, e, kw: dict) -> bool:
        """Some servers (e.g. Ollama with Gemma 4) reject JSON mode with 400/422/501. Drop it and rely on parsing."""
        if "response_format" not in kw or getattr(e, "status_code", None) not in (400, 422, 501):
            return False
        self._json_ok = False
        kw.pop("response_format")
        return True

    def _kw(self, messages, json_mode, max_tokens) -> dict:
        kw: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0.1}
        if max_tokens:
            kw["max_tokens"] = max_tokens
        if json_mode and self._json_ok:
            kw["response_format"] = {"type": "json_object"}
        return kw

    async def _complete(self, task, messages, json_mode, max_tokens, payload):
        import openai

        kw = self._kw(messages, json_mode, max_tokens)
        t0 = time.perf_counter()
        try:
            try:
                resp = await self.client.chat.completions.create(**kw)
            except openai.APIStatusError as e:
                if not self._json_refused(e, kw):
                    raise
                t0 = time.perf_counter()
                resp = await self.client.chat.completions.create(**kw)
        except openai.OpenAIError as e:
            raise LLMError(f"{self.backend} call failed: {e}") from e
        dt = time.perf_counter() - t0
        toks = resp.usage.completion_tokens if resp.usage else None
        return (resp.choices[0].message.content or ""), Stats(
            self.backend, self.model, round(dt * 1000, 1), toks, round(toks / dt, 1) if toks and dt else None)

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
                return await self.client.chat.completions.create(**kw)
            except openai.APIStatusError as e:
                if not self._schema_refused(e, schema):
                    raise
        raise LLMError(f"{self.backend}: server refused every JSON mode")

    async def samples(self, task, messages, n, *, temperature=0.7, schema=None, payload=None):
        import openai

        n = max(1, n)
        kw = self._kw(messages, True, None) | {"temperature": temperature}
        t0 = time.perf_counter()
        try:
            async with self._sem:
                resp = await self._create(dict(kw) | ({"n": n} if n > 1 else {}), schema)
                texts = [c.message.content or "" for c in resp.choices[:n]]
                toks = resp.usage.completion_tokens if resp.usage else None
                if len(texts) < n:  # server ignored `n`: fill up with concurrent single calls
                    more = await asyncio.gather(*[self._create(dict(kw), schema) for _ in range(n - len(texts))])
                    for r in more:
                        texts.append(r.choices[0].message.content or "")
                        toks = (toks or 0) + (r.usage.completion_tokens if r.usage else 0) or None
        except openai.OpenAIError as e:
            raise LLMError(f"{self.backend} call failed: {e}") from e
        dt = time.perf_counter() - t0
        return texts, Stats(self.backend, self.model, round(dt * 1000, 1), toks,
                            round(toks / dt, 1) if toks and dt else None)

    async def stream(self, task, messages, *, max_tokens=None, payload=None):
        import openai

        kw = self._kw(messages, True, max_tokens) | {"stream": True, "stream_options": {"include_usage": True}}
        t0 = time.perf_counter()
        n_chunks, toks = 0, None
        try:
            try:
                it = await self.client.chat.completions.create(**kw)
            except openai.APIStatusError as e:
                if not self._json_refused(e, kw):
                    raise
                it = await self.client.chat.completions.create(**kw)
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


def make_llm(s: Settings) -> LLM:
    if s.offline:
        from .fixtures import OfflineLLM

        return OfflineLLM(s.llm_concurrency)
    return OpenAICompat(s)
