#!/usr/bin/env python3
"""Benchmark an OpenAI-compatible endpoint with Clario workloads.

  extract: one synthetic diary snippet -> entities JSON (short prompt, short output)
  brief:   shared ~2k-token package summary -> clinician brief JSON (long prompt, prefix-cacheable)
  extract_sc: the extract prompt with n=--sc-n samples per request at temperature 0.7 (the app's self-consistency
              path); the result rows carry the cost multiple against plain extract at the same concurrency.
GPU util: --gpu-samples FILE (written on the host by `python3 eval/hardware.py sample --out FILE`, for runs inside a
container without amd-smi) or, if amd-smi is on PATH, sampled in-process once per second.

uv run --with openai --with httpx python bench/bench.py --base-url URL --model M --label L \
    [--api-key-env LLM_API_KEY] [--workload extract|brief|both] [--concurrency 1,8,32] [--n 32] [--stream]
"""
import argparse, asyncio, datetime, json, os, pathlib, statistics, sys, threading, time

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


async def one(client, args, workload, i):
    msgs, schema, name = build(workload, i)
    rf = ({"type": "json_object"} if args.json_object else
          {"type": "json_schema", "json_schema": {"name": name, "schema": schema}})
    sc = workload == "extract_sc"
    kw = dict(model=args.model, messages=msgs, temperature=0.7 if sc else 0.0, max_tokens=args.max_tokens[workload], response_format=rf)
    if sc:
        kw["n"] = args.sc_n
    t0 = time.perf_counter()
    ttft = None
    try:
        if sc:
            r = await client.chat.completions.create(**kw)
            dt = time.perf_counter() - t0
            bad = 0
            for c in r.choices:
                try:
                    json.loads(c.message.content or "")
                except Exception:
                    bad += 1
            usage = r.usage
            toks = (usage.completion_tokens if usage else None) or 1
            return {"ok": bad == 0 and len(r.choices) == args.sc_n, "lat": dt, "ttft": None, "tokens": toks,
                    "ptoks": usage.prompt_tokens if usage else None, "err": None if bad == 0 else "invalid_json"}
        if args.stream:
            parts, usage = [], None
            stream = await client.chat.completions.create(stream=True, stream_options={"include_usage": True}, **kw)
            async for ch in stream:
                if ch.usage:
                    usage = ch.usage
                if ch.choices and ch.choices[0].delta.content:
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    parts.append(ch.choices[0].delta.content)
            txt = "".join(parts)
        else:
            r = await client.chat.completions.create(**kw)
            txt, usage = r.choices[0].message.content or "", r.usage
        dt = time.perf_counter() - t0
        try:
            json.loads(txt); ok, err = True, None
        except Exception:
            ok, err = False, "invalid_json"
        toks = (usage.completion_tokens if usage else None) or max(1, len(txt) // 4)
        ptoks = usage.prompt_tokens if usage else None
        return {"ok": ok, "lat": dt, "ttft": ttft, "tokens": toks, "ptoks": ptoks, "err": err}
    except Exception as e:
        return {"ok": False, "lat": time.perf_counter() - t0, "ttft": None, "tokens": 0, "ptoks": None,
                "err": f"{type(e).__name__}: {str(e)[:160]}"}


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
    return {**gpu, "workload": workload, "concurrency": conc, "n": args.n, "wall_s": rnd(wall), "ok": len(good),
            "errors": len(errs), "error_samples": sorted(set(errs))[:3],
            "req_per_s": rnd(len(good) / wall, 3), "out_tok_per_s": rnd(sum(r["tokens"] for r in good) / wall, 1),
            "p50_s": rnd(statistics.median(lats)) if lats else None, "p95_s": rnd(pct(lats, 0.95)),
            "ttft_p50_s": rnd(statistics.median(ttfts), 3) if ttfts else None, "ttft_p95_s": rnd(pct(ttfts, 0.95), 3),
            "mean_prompt_tokens": round(statistics.mean(ptoks)) if ptoks else None,
            "mean_out_tokens": round(statistics.mean(r["tokens"] for r in good)) if good else None}


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
    ap.add_argument("--workload", choices=["extract", "brief", "both", "sc", "all"], default="both",
                    help="both = extract+brief; sc = extract_sc only; all = extract, brief, extract_sc")
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
    GPU.start(args.gpu_samples)
    key = os.environ.get(args.api_key_env) or ("ollama" if args.allow_no_key else None)
    if not key:
        raise SystemExit(f"env {args.api_key_env} not set (or pass --allow-no-key)")
    client = AsyncOpenAI(base_url=args.base_url, api_key=key, timeout=httpx.Timeout(args.timeout), max_retries=0)
    workloads = {"both": ["extract", "brief"], "sc": ["extract_sc"], "all": ["extract", "brief", "extract_sc"]}.get(
        args.workload, [args.workload])
    rows = []
    for w in workloads:
        for c in [int(x) for x in args.concurrency.split(",")]:
            row = await run_level(client, args, w, c)
            rows.append(row)
            print(f"done {w} c={c}: {row}", flush=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = pathlib.Path(args.out_dir) / f"{args.label}-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {"label": args.label, "base_url": args.base_url, "model": args.model, "timestamp": ts, "n_per_level": args.n,
            "stream": args.stream, "mode": "json_object" if args.json_object else "json_schema", "results": rows,
            "self_consistency": sc_cost(rows, args.sc_n), "hardware": HW.detect()}
    out.write_text(json.dumps(meta, indent=2))
    if args.results_dir:  # every number in the README traces to a file here: n, dataset, model, backend, date
        prov = {"label": args.label, "dataset": "bench/prompts.py (synthetic diaries and package summary)", "model": args.model,
                "backend": args.backend, "date": datetime.date.today().isoformat(), "n": args.n, "n_per_level": args.n,
                "mode": meta["mode"], "stream": args.stream, "source_file": str(out.name), "results": rows,
                "self_consistency": meta["self_consistency"], "hardware": meta["hardware"], "sc_n": args.sc_n,
                "concurrency_levels": [int(x) for x in args.concurrency.split(",")]}
        dest = pathlib.Path(args.results_dir) / f"bench_{args.label}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(prov, indent=2))
    GPU.stop()
    md = f"### {args.label} ({args.model}, {meta['mode']}, stream={args.stream})\n\n" + table(rows) + "\n"
    out.with_suffix(".md").write_text(md)
    print("\n" + md + f"\nsaved {out} and {out.with_suffix('.md').name}")


if __name__ == "__main__":
    asyncio.run(main())
