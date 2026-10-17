"""Rate-limited gateway support in eval.py (AMD Token Factory): client-side gate, n fallback, resumable cache."""
import json
import os
import types

import eval as ev


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_rate_gate_spaces_requests_to_the_rpm_cap():
    c = Clock()
    g = ev.RateGate(rpm=3, clock=c, sleep=c.sleep)
    starts = []
    for _ in range(7):
        with g:
            starts.append(c.t)
    assert starts[:3] == [0.0, 0.0, 0.0]
    assert 60 <= starts[3] < 61 and 60 <= starts[5] < 61 and 120 <= starts[6] < 122
    for i in range(len(starts)):  # never more than 3 starts in any 60 s window
        assert sum(1 for s in starts if starts[i] <= s < starts[i] + 60) <= 3


def test_retry_delay_honours_retry_after_and_caps():
    assert ev.retry_delay({"retry-after": "7"}, 0) == 7.0
    assert ev.retry_delay({"retry-after-ms": "1500"}, 0) == 1.5
    assert ev.retry_delay({"retry-after": "3600"}, 0) is None  # daily budget spent: fail, do not hang
    assert 1 <= ev.retry_delay({}, 0) <= 2


def test_n_refused_detects_token_factory_400():
    e = types.SimpleNamespace(status_code=400, message="Error code: 400 - does not support the n parameter")
    assert ev.n_refused(e)
    assert not ev.n_refused(types.SimpleNamespace(status_code=400, message="bad schema"))
    assert not ev.n_refused(types.SimpleNamespace(status_code=500, message="n parameter"))


def test_infer_backend_token_factory():
    assert ev.infer_backend("https://developer.amd.com.cn/radeon/api/v1") == "amd-token-factory"


OUT = json.dumps({"entities": [{"quote": "knees ache", "canonical": "knee pain", "hpo_id": None, "type": "symptom",
                                "negated": False, "family_history": False, "onset_hint": None, "severity": None,
                                "confidence": None}]})
EMPTY = json.dumps({"entities": []})


def fake(calls):
    def complete(d, acc=None):
        calls.append("primary")
        if acc is not None:
            acc["requests"] += 1; acc["completion_tokens"] += 10
        return OUT, 0.5, 10

    def samples(d, n, temperature=0.7, acc=None):
        calls.append(f"samples{n}")
        if acc is not None:
            acc["requests"] += n; acc["completion_tokens"] += 10 * n
        return [OUT, OUT, EMPTY, OUT][:n]
    complete.samples = samples
    complete.tracks_usage = True
    return complete


def test_run_records_cache_resumes_without_calls(tmp_path):
    gold = [{"id": "a", "diary": "my knees ache", "gold": [], "gold_complete": True}]
    calls = []
    recs, _ = ev.run_records(gold, fake(calls), 1, sc_n=4, cache_dir=str(tmp_path / "c"), cache_tag="t")
    assert calls == ["primary", "samples4"] and recs[0]["pred"][0]["confidence"] == 0.75
    assert recs[0]["usage"]["requests"] == 5 and not recs[0]["cached"]
    calls.clear()
    again, _ = ev.run_records(gold, fake(calls), 1, sc_n=4, cache_dir=str(tmp_path / "c"), cache_tag="t")
    assert calls == [] and again[0]["cached"] and again[0]["pred"][0]["confidence"] == 0.75
    assert again[0]["usage"]["requests"] == 5  # the first run's cost is kept with the row
    other, _ = ev.run_records(gold, fake(calls), 1, sc_n=4, cache_dir=str(tmp_path / "c"), cache_tag="other model")
    assert calls == ["primary", "samples4"] and not other[0]["cached"]


def test_run_records_does_not_cache_errors(tmp_path):
    gold = [{"id": "a", "diary": "x", "gold": [], "gold_complete": True}]

    def boom(d):
        raise RuntimeError("429 forever")
    recs, _ = ev.run_records(gold, boom, 1, cache_dir=str(tmp_path))
    assert recs[0]["err"] and os.listdir(tmp_path) == []


class FakeOpenAI:
    """Stands in for openai.OpenAI: refuses n > 1 like Token Factory, counts requests."""
    log = []

    def __init__(self, **kw):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

    def create(self, **kw):
        import openai
        FakeOpenAI.log.append(kw)
        if kw.get("n", 1) > 1:
            import httpx
            resp = httpx.Response(400, request=httpx.Request("POST", "http://x"))
            raise openai.BadRequestError("does not support the n parameter", response=resp, body=None)
        usage = types.SimpleNamespace(prompt_tokens=100, completion_tokens=20, model_extra={"cost": 0.001})
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=OUT))], usage=usage)


def test_samples_fall_back_to_single_requests_and_count_usage(monkeypatch):
    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    FakeOpenAI.log = []
    complete = ev.make_complete("http://x/v1", "m", "k", schema={"type": "object"}, rpm=100, inflight=2)
    acc = ev.new_usage()
    texts = complete.samples("my knees ache", 5, acc=acc)
    assert texts == [OUT] * 5
    assert [k.get("n") for k in FakeOpenAI.log] == [5, None, None, None, None, None]
    assert all(k["response_format"]["type"] == "json_schema" for k in FakeOpenAI.log)
    assert acc["requests"] == 5 and acc["completion_tokens"] == 100 and abs(acc["cost_usd"] - 0.005) < 1e-9
    FakeOpenAI.log = []
    complete.samples("my knees ache", 3, acc=acc)  # learnt: no second n attempt
    assert [k.get("n") for k in FakeOpenAI.log] == [None, None, None]
