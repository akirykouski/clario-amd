#!/usr/bin/env python3
"""Benchmark an OpenAI-compatible endpoint with Clario workloads.

  extract: one synthetic diary snippet -> entities JSON (short prompt, short output)
  brief:   shared ~2k-token package summary -> clinician brief JSON (long prompt, prefix-cacheable)
  extract_sc: the extract prompt with n=--sc-n samples per request at temperature 0.7 (the app's self-consistency
              path); the result rows carry the cost multiple against plain extract at the same concurrency. A server
              that rejects `n` (AMD Token Factory) gets sc_n separate requests per item, as the app sends them.
  app:     the app's own extraction path (backend clario.extract.extract: primary + CLARIO_SC_N samples + HPO picks)
           on the bench diaries, once at --sc-n and once at sc_n=1; rows count HTTP requests and tokens per note.
           Needs the backend importable (run with backend/.venv/bin/python).
Rate-limited gateways: --rpm and --max-inflight cap requests client side; a 429 waits for Retry-After and retries.
Latency is timed from the start of the attempt that succeeded, so client-side waits are not counted in p50/p95.
GPU util: --gpu-samples FILE (written on the host by `python3 eval/hardware.py sample --out FILE`, for runs inside a
container without amd-smi) or, if amd-smi is on PATH, sampled in-process once per second.

uv run --with openai --with httpx python bench/bench.py --base-url URL --model M --label L \
    [--api-key-env LLM_API_KEY] [--workload extract|brief|both] [--concurrency 1,8,32] [--n 32] [--stream]
"""
import argparse, asyncio, collections, datetime, json, os, pathlib, random, statistics, sys, threading, time

import httpx
from openai import AsyncOpenAI

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import prompts as P

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "eval"))
import hardware as HW


def build(workload, i):
    if workload in ("extract", "extract_sc"):
        text = P.DIARY[i % len(P.DIARY)]
        msgs = [{"role": "system", "content": P.EXTRACT_SYSTEM},
                {"role": "user", "content": f"Diary entry:\n{text}\n\nReturn the entities JSON."}]
        return msgs, P.EXTRACT_SCHEMA, "entities"
    msgs = [{"role": "system", "content": P.BRIEF_SYSTEM},
            {"role": "user", "content": P.PACKAGE_SUMMARY + "\n\nDraft the clinician brief JSON."}]
    return msgs, P.BRIEF_SCHEMA, "brief"


class AsyncGate:
    """At most `inflight` requests at once and `rpm` request starts per rolling 60 s (0 = no limit)."""

    def __init__(self, rpm=0, inflight=0):
        self.rpm, self.inflight = rpm, inflight
        self.sem = asyncio.Semaphore(inflight) if inflight else None
        self.starts = collections.deque()
        self.lock = asyncio.Lock()
        self.retries = 0

    async def __aenter__(self):
        if self.sem:
            await self.sem.acquire()
        while self.rpm:
            async with self.lock:
                now = time.monotonic()
                while self.starts and now - self.starts[0] >= 60:
                    self.starts.popleft()
                if len(self.starts) < self.rpm:
                    self.starts.append(now)
                    break
                wait = 60 - (now - self.starts[0]) + 0.05
            await asyncio.sleep(wait)
        return self

    async def __aexit__(self, *exc):
        if self.sem:
            self.sem.release()
        return False


GATE = AsyncGate()


def retry_wait(e, attempt, cap=120.0):
    h = (e.response.headers if getattr(e, "response", None) is not None else None) or {}
    try:
        wait = float(h["retry-after-ms"]) / 1000 if h.get("retry-after-ms") else float(h["retry-after"]) if h.get("retry-after") else None
    except (TypeError, ValueError):
        wait = None
    wait = min(2.0 ** attempt, 30.0) + random.uniform(0, 1) if wait is None else wait
    return None if wait > cap else wait


async def gated(fn, retries=6):
    """Run `await fn()` inside the gate; on 429 wait Retry-After and retry. fn times itself."""
    import openai
    for attempt in range(retries + 1):
        try:
            async with GATE:
                return await fn()
        except openai.RateLimitError as e:
            wait = retry_wait(e, attempt)
            if wait is None or attempt == retries:
                raise
            GATE.retries += 1
            await asyncio.sleep(wait)
    raise AssertionError("unreachable")


def n_refused(e):
    return getattr(e, "status_code", None) == 400 and "n parameter" in str(getattr(e, "message", "") or e).lower()


def usage_cost(usage):
    c = (getattr(usage, "model_extra", None) or {}).get("cost") if usage is not None else None
    return float(c) if isinstance(c, (int, float)) else 0.0


async def timed_create(client, kw):
    t0 = time.perf_counter()
    r = await client.chat.completions.create(**kw)
    return r, time.perf_counter() - t0


async def one_sc(client, args, kw):
    """Self-consistency item: one request with n choices, or sc_n separate concurrent requests when n is refused."""
    import openai
    if args.n_ok:
        try:
            r, dt = await gated(lambda: timed_create(client, kw | {"n": args.sc_n}))
            texts = [c.message.content or "" for c in r.choices]
            u = r.usage
            return texts, dt, (u.completion_tokens if u else 0), (u.prompt_tokens if u else None), 1, usage_cost(u), [dt]
        except openai.BadRequestError as e:
            if not n_refused(e):
                raise
            args.n_ok = False
    t0 = time.perf_counter()
    outs = await asyncio.gather(*[gated(lambda: timed_create(client, kw)) for _ in range(args.sc_n)])
    wall = time.perf_counter() - t0
    texts = [r.choices[0].message.content or "" for r, _ in outs]
    toks = sum((r.usage.completion_tokens or 0) if r.usage else 0 for r, _ in outs)
    ptoks = sum((r.usage.prompt_tokens or 0) if r.usage else 0 for r, _ in outs) or None
    # item latency: the slowest of the parallel requests (each timed from its own start, gate waits excluded);
    # item_wall_s in the row also includes client-side rate-limit waits
    dts = [dt for _, dt in outs]
    return texts, max(dts), toks, ptoks, len(outs), sum(usage_cost(r.usage) for r, _ in outs), dts + [wall]


async def one(client, args, workload, i):
    msgs, schema, name = build(workload, i)
    rf = ({"type": "json_object"} if args.json_object else
          {"type": "json_schema", "json_schema": {"name": name, "schema": schema}})
    sc = workload == "extract_sc"
    kw = dict(model=args.model, messages=msgs, temperature=0.7 if sc else 0.0, max_tokens=args.max_tokens[workload], response_format=rf)
    t0 = time.perf_counter()
    ttft = None
    try:
        if sc:
            texts, dt, toks, ptoks, nreq, cost, dts = await one_sc(client, args, kw)
            bad = 0
            for t in texts:
                try:
                    json.loads(t)
                except Exception:
                    bad += 1
            return {"ok": bad == 0 and len(texts) == args.sc_n, "lat": dt, "ttft": None, "tokens": toks or 1,
                    "ptoks": ptoks, "err": None if bad == 0 else "invalid_json", "requests": nreq, "cost": cost,
                    "item_wall": dts[-1], "req_lat": dts[:-1] if nreq > 1 else dts}
        if args.stream:
            async def run_stream():
                t0 = time.perf_counter()
                parts, usage, ttft = [], None, None
                stream = await client.chat.completions.create(stream=True, stream_options={"include_usage": True}, **kw)
                async for ch in stream:
                    if ch.usage:
                        usage = ch.usage
                    if ch.choices and ch.choices[0].delta.content:
                        if ttft is None:
                            ttft = time.perf_counter() - t0
                        parts.append(ch.choices[0].delta.content)
                return "".join(parts), usage, ttft, time.perf_counter() - t0
            txt, usage, ttft, dt = await gated(run_stream)
        else:
            r, dt = await gated(lambda: timed_create(client, kw))
            txt, usage = r.choices[0].message.content or "", r.usage
        try:
            json.loads(txt); ok, err = True, None
        except Exception:
            ok, err = False, "invalid_json"
        toks = (usage.completion_tokens if usage else None) or max(1, len(txt) // 4)
        ptoks = usage.prompt_tokens if usage else None
        return {"ok": ok, "lat": dt, "ttft": ttft, "tokens": toks, "ptoks": ptoks, "err": err, "requests": 1,
                "cost": usage_cost(usage), "req_lat": [dt]}
    except Exception as e:
        return {"ok": False, "lat": time.perf_counter() - t0, "ttft": None, "tokens": 0, "ptoks": None,
                "err": f"{type(e).__name__}: {str(e)[:160]}", "requests": 0, "cost": 0.0}


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None


def rnd(x, n=2):
    return None if x is None else round(x, n)


async def run_level(client, args, workload, conc):
    sem = asyncio.Semaphore(conc)

    async def guarded(i):
        async with sem:
            return await one(client, args, workload, i)
    t0 = time.perf_counter()
    e0 = time.time()
    res = await asyncio.gather(*[guarded(i) for i in range(args.n)])
    wall = time.perf_counter() - t0
    e1 = time.time()
    good = [r for r in res if r["ok"]]
    lats = [r["lat"] for r in good]
    ttfts = [r["ttft"] for r in good if r["ttft"] is not None]
    ptoks = [r["ptoks"] for r in good if r["ptoks"]]
    errs = [r["err"] for r in res if r["err"]]
    gpu = GPU.window(e0, e1)
    extra = level_extra(res, good)
    return {**gpu, "workload": workload, "concurrency": conc, "n": args.n, "wall_s": rnd(wall), "ok": len(good),
            "errors": len(errs), "error_samples": sorted(set(errs))[:3],
            "req_per_s": rnd(len(good) / wall, 3), "out_tok_per_s": rnd(sum(r["tokens"] for r in good) / wall, 1),
            "p50_s": rnd(statistics.median(lats)) if lats else None, "p95_s": rnd(pct(lats, 0.95)),
            "ttft_p50_s": rnd(statistics.median(ttfts), 3) if ttfts else None, "ttft_p95_s": rnd(pct(ttfts, 0.95), 3),
            "mean_prompt_tokens": round(statistics.mean(ptoks)) if ptoks else None,
            "mean_out_tokens": round(statistics.mean(r["tokens"] for r in good)) if good else None, **extra}


def level_extra(res, good):
    """Per level: HTTP requests, the gateway's reported cost, per-request decode speed, and (sc) requests per item."""
    reqs = sum(r.get("requests", 0) for r in res)
    speeds = [r["tokens"] / r["lat"] for r in good if r.get("requests", 1) == 1 and r["lat"]]
    out = {"http_requests": reqs, "cost_usd": round(sum(r.get("cost", 0.0) for r in res), 6),
           "per_request_out_tok_per_s_p50": rnd(statistics.median(speeds), 1) if speeds else None}
    if any("item_wall" in r for r in good):
        walls = [r["item_wall"] for r in good if "item_wall" in r]
        out.update(requests_per_item=rnd(reqs / len(res), 2), item_wall_p50_s=rnd(statistics.median(walls)),
                   item_wall_p95_s=rnd(pct(walls, 0.95)))
    return out


async def run_app(args, sc_n, conc):
    """The app's extraction path on the bench diaries: counts every HTTP request and its tokens per note."""
    backend = pathlib.Path(__file__).resolve().parent.parent / "backend"
    sys.path.insert(0, str(backend))
    os.environ.update(LLM_BASE_URL=args.base_url, LLM_API_KEY=args.key, LLM_MODEL=args.model, CLARIO_SC_N=str(sc_n),
                      LLM_CONCURRENCY=str(max(1, min(8, args.max_inflight or 4))))
    os.environ.pop("CLARIO_OFFLINE", None)
    from clario.config import ExtractOpts, Settings
    from clario.extract import extract
    from clario.knowledge import Ontology
    from clario.llm import make_llm
    s = Settings.from_env()
    llm = make_llm(s)
    onto = Ontology.load()
    real = llm.client.chat.completions.create
    note = {}

    async def counted(**kw):  # every HTTP request the app makes goes through the gate and is counted for its note
        tag = kw.pop("_note", None)
        r, dt = await gated(lambda: _timed(real, kw))
        acc = note.setdefault(tag, {"requests": 0, "prompt": 0, "completion": 0, "cost": 0.0})
        acc["requests"] += 1
        acc["prompt"] += (r.usage.prompt_tokens or 0) if r.usage else 0
        acc["completion"] += (r.usage.completion_tokens or 0) if r.usage else 0
        acc["cost"] += usage_cost(r.usage)
        return r
    current = __import__("contextvars").ContextVar("note", default=None)

    async def create(**kw):
        return await counted(_note=current.get(), **kw)
    llm.client.chat.completions.create = create
    opts = ExtractOpts.from_settings(s)
    sem = asyncio.Semaphore(conc)
    e0 = time.time()

    async def item(i):
        async with sem:
            current.set(i)
            t0 = time.perf_counter()
            try:
                ents, _ = await extract(llm, f"bench{i}", P.DIARY[i % len(P.DIARY)], onto, opts)
                return {"ok": True, "wall": time.perf_counter() - t0, "entities": len(ents), "err": None}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "wall": time.perf_counter() - t0, "entities": 0, "err": f"{type(e).__name__}: {str(e)[:160]}"}
    t0 = time.perf_counter()
    res = await asyncio.gather(*[item(i) for i in range(args.n)])
    wall = time.perf_counter() - t0
    good = [i for i, r in enumerate(res) if r["ok"]]
    per = [note.get(i, {"requests": 0, "prompt": 0, "completion": 0, "cost": 0.0}) for i in good]
    walls = [res[i]["wall"] for i in good]
    errs = [r["err"] for r in res if r["err"]]

    def mean(k):
        return round(statistics.mean(p[k] for p in per), 2) if per else None
    return {**GPU.window(e0, time.time()), "workload": f"app_note_sc{sc_n}", "concurrency": conc, "n": args.n,
            "sc_n": sc_n, "hpo_pick": opts.hpo_pick, "wall_s": rnd(wall), "ok": len(good), "errors": len(errs),
            "error_samples": sorted(set(errs))[:3], "req_per_s": rnd(len(good) / wall, 3),
            "out_tok_per_s": rnd(sum(p["completion"] for p in per) / wall, 1),
            "p50_s": rnd(statistics.median(walls)) if walls else None, "p95_s": rnd(pct(walls, 0.95)),
            "ttft_p50_s": None, "ttft_p95_s": None,
            "mean_prompt_tokens": mean("prompt"), "mean_out_tokens": mean("completion"),
            "requests_per_note": mean("requests"), "requests_per_note_max": max((p["requests"] for p in per), default=None),
            "prompt_tokens_per_note": mean("prompt"), "completion_tokens_per_note": mean("completion"),
            "cost_usd_per_note": round(statistics.mean(p["cost"] for p in per), 7) if per else None,
            "entities_per_note": round(statistics.mean(res[i]["entities"] for i in good), 2) if good else None,
            "http_requests": sum(p["requests"] for p in note.values()),
            "note": "latency = wall time per note through the app's extract(), client-side rate-limit waits included"}


async def _timed(fn, kw):
    t0 = time.perf_counter()
    r = await fn(**kw)
    return r, time.perf_counter() - t0


def app_cost(rows):
    """Self-consistency cost on the app path: per-note requests, tokens and latency at sc_n against sc_n=1."""
    by = {r["sc_n"]: r for r in rows if r["workload"].startswith("app_note_")}
    if 1 not in by or len(by) < 2:
        return None
    b = by[1]
    out = []
    for n, r in sorted(by.items()):
        if n == 1:
            continue
        def x(k):
            return round(r[k] / b[k], 2) if r.get(k) and b.get(k) else None
        out.append({"sc_n": n, "requests_per_note": r["requests_per_note"], "requests_per_note_without_sc": b["requests_per_note"],
                    "completion_tokens_per_note": r["completion_tokens_per_note"],
                    "completion_tokens_per_note_without_sc": b["completion_tokens_per_note"],
                    "prompt_tokens_per_note": r["prompt_tokens_per_note"],
                    "prompt_tokens_per_note_without_sc": b["prompt_tokens_per_note"],
                    "requests_x": x("requests_per_note"), "completion_tokens_x": x("completion_tokens_per_note"),
                    "latency_p50_x": x("p50_s"), "cost_usd_per_note": r["cost_usd_per_note"],
                    "cost_usd_per_note_without_sc": b["cost_usd_per_note"]})
    return out


class GpuWindow:
    """GPU util per level: from a host-written samples file, else an in-process 1 Hz sampler when amd-smi exists."""

    def __init__(self):
        self.path, self.live, self._stop, self._started = None, [], threading.Event(), False

    def start(self, path):
        self.path = path or None
        if not path and HW.shutil.which("amd-smi") and not self._started:
            self._started = True
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        gpu = HW._gpu_mod()
        while not self._stop.is_set():
            g = gpu.read_local()
            if g:
                self.live.append({"ts": time.time(), "util_pct": g.get("util_pct"), "vram_used_gb": g.get("vram_used_gb")})
            self._stop.wait(1.0)

    def window(self, t0, t1):
        return HW.summarize(HW.load_samples(self.path) if self.path else self.live, t0, t1)

    def stop(self):
        self._stop.set()


GPU = GpuWindow()


def sc_cost(rows, sc_n):
    """Self-consistency cost against plain extract at the same concurrency (same prompts, n samples per request)."""
    base = {r["concurrency"]: r for r in rows if r["workload"] == "extract"}
    out = []
    for r in rows:
        b = base.get(r["concurrency"])
        if r["workload"] != "extract_sc" or not b or not b.get("p50_s") or not r.get("p50_s"):
            continue
        out.append({"concurrency": r["concurrency"], "sc_n": sc_n,
                    "latency_p50_x": round(r["p50_s"] / b["p50_s"], 2),
                    "out_tokens_per_item_x": round(r["mean_out_tokens"] / b["mean_out_tokens"], 2) if b.get("mean_out_tokens") else None,
                    "items_per_s_x": round(r["req_per_s"] / b["req_per_s"], 2) if b.get("req_per_s") else None})
    return out


def table(rows):
    h = "| workload | conc | n | ok | err | req/s | out tok/s | p50 s | p95 s | TTFT p50 s | TTFT p95 s | prompt tok | out tok | GPU util mean / max % | VRAM peak GB |\n" + "|" + "---|" * 15
    f = lambda v: "-" if v is None else v
    lines = [h] + [f"| {r['workload']} | {r['concurrency']} | {r['n']} | {r['ok']} | {r['errors']} | {r['req_per_s']} | "
                   f"{r['out_tok_per_s']} | {f(r['p50_s'])} | {f(r['p95_s'])} | {f(r['ttft_p50_s'])} | {f(r['ttft_p95_s'])} | "
                   f"{f(r['mean_prompt_tokens'])} | {f(r['mean_out_tokens'])} | "
                   f"{f(r.get('gpu_util_mean_pct'))} / {f(r.get('gpu_util_max_pct'))} | {f(r.get('gpu_vram_peak_gb'))} |" for r in rows]
    return "\n".join(lines)


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key-env", default="LLM_API_KEY", help="env var holding the key (default LLM_API_KEY; 'ollama' placeholder used if unset and --allow-no-key)")
    ap.add_argument("--allow-no-key", action="store_true", help="use a dummy key (Ollama)")
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--workload", choices=["extract", "brief", "both", "sc", "all", "app", "tf"], default="both",
                    help="both = extract+brief; sc = extract_sc only; all = extract, brief, extract_sc; "
                         "app = the app's extract() at --sc-n and at 1; tf = all + app")
    ap.add_argument("--rpm", type=int, default=0, help="client-side cap on requests started per minute (0 = none)")
    ap.add_argument("--max-inflight", type=int, default=0, help="client-side cap on requests in flight (0 = none)")
    ap.add_argument("--app-concurrency", type=int, default=2, help="notes in parallel for the app workload")
    ap.add_argument("--display-label", default="", help='how the result is named on screen, e.g. "Gemma 4 31B · AMD Token Factory"')
    ap.add_argument("--sc-n", type=int, default=5, help="samples per request for the extract_sc workload")
    ap.add_argument("--gpu-samples", default="", help="jsonl from `python3 eval/hardware.py sample --out F` on the host")
    ap.add_argument("--concurrency", default="1,8,32", help="comma list")
    ap.add_argument("--n", type=int, default=32, help="requests per workload per concurrency level")
    ap.add_argument("--max-tokens-extract", type=int, default=400)
    ap.add_argument("--max-tokens-brief", type=int, default=900)
    ap.add_argument("--stream", action="store_true", help="stream to record TTFT")
    ap.add_argument("--json-object", action="store_true", help="json_object instead of json_schema")
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--out-dir", default=str(pathlib.Path(__file__).parent / "results"))
    ap.add_argument("--backend", default="openai-compatible", help="e.g. vllm-rocm-mi300x (recorded in the eval/results file)")
    ap.add_argument("--results-dir", default=str(pathlib.Path(__file__).resolve().parent.parent / "eval" / "results"),
                    help="where the provenance copy bench_<label>.json goes ('' to skip)")
    args = ap.parse_args()
    args.max_tokens = {"extract": args.max_tokens_extract, "extract_sc": args.max_tokens_extract, "brief": args.max_tokens_brief}
    if "anthropic.com" in args.base_url:
        raise SystemExit("refusing anthropic.com: Claude is never benchmarked as an AMD/vLLM result")
    global GATE
    GATE = AsyncGate(args.rpm, args.max_inflight)
    args.n_ok = True
    GPU.start(args.gpu_samples)
    key = os.environ.get(args.api_key_env) or ("ollama" if args.allow_no_key else None)
    if not key:
        raise SystemExit(f"env {args.api_key_env} not set (or pass --allow-no-key)")
    client = AsyncOpenAI(base_url=args.base_url, api_key=key, timeout=httpx.Timeout(args.timeout), max_retries=0)
    args.key = key
    workloads = {"both": ["extract", "brief"], "sc": ["extract_sc"], "all": ["extract", "brief", "extract_sc"],
                 "app": [], "tf": ["extract", "brief", "extract_sc"]}.get(args.workload, [args.workload])
    rows = []
    for w in workloads:
        for c in [int(x) for x in args.concurrency.split(",")]:
            row = await run_level(client, args, w, c)
            rows.append(row)
            print(f"done {w} c={c}: {row}", flush=True)
    if args.workload in ("app", "tf"):
        for n in sorted({args.sc_n, 1}, reverse=True):
            row = await run_app(args, n, args.app_concurrency)
            rows.append(row)
            print(f"done app sc_n={n}: {row}", flush=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = pathlib.Path(args.out_dir) / f"{args.label}-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {"label": args.label, "base_url": args.base_url, "model": args.model, "timestamp": ts, "n_per_level": args.n,
            "stream": args.stream, "mode": "json_object" if args.json_object else "json_schema", "results": rows,
            "self_consistency": sc_cost(rows, args.sc_n), "hardware": HW.detect(), "backend": args.backend,
            "display_label": args.display_label or None, "app_self_consistency": app_cost(rows),
            "client_limits": {"rpm": args.rpm, "max_inflight": args.max_inflight} if (args.rpm or args.max_inflight) else None,
            "rate_limited_retries": GATE.retries, "n_param_supported": args.n_ok}
    out.write_text(json.dumps(meta, indent=2))
    if args.results_dir:  # every number in the README traces to a file here: n, dataset, model, backend, date
        prov = {"label": args.label, "dataset": "bench/prompts.py (synthetic diaries and package summary)", "model": args.model,
                "backend": args.backend, "date": datetime.date.today().isoformat(), "n": args.n, "n_per_level": args.n,
                "mode": meta["mode"], "stream": args.stream, "source_file": str(out.name), "results": rows,
                "self_consistency": meta["self_consistency"], "hardware": meta["hardware"], "sc_n": args.sc_n,
                "concurrency_levels": [int(x) for x in args.concurrency.split(",")],
                "display_label": meta["display_label"], "app_self_consistency": meta["app_self_consistency"],
                "client_limits": meta["client_limits"], "rate_limited_retries": meta["rate_limited_retries"],
                "n_param_supported": meta["n_param_supported"], "base_url": args.base_url}
        dest = pathlib.Path(args.results_dir) / f"bench_{args.label}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(prov, indent=2))
    GPU.stop()
    md = f"### {args.label} ({args.model}, {meta['mode']}, stream={args.stream})\n\n" + table(rows) + "\n"
    out.with_suffix(".md").write_text(md)
    print("\n" + md + f"\nsaved {out} and {out.with_suffix('.md').name}")


if __name__ == "__main__":
    asyncio.run(main())
