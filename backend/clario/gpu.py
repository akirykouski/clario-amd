"""GPU telemetry from amd-smi. Stdlib only, so the same file runs inside the gpu-metrics sidecar.

Output shape: {gpu_name, util_pct, vram_used_gb, vram_total_gb} or None.

The amd-smi JSON shapes handled here come from AMD's amd-smi documentation and have NOT been
verified on real MI300X hardware. Parsing is defensive: values may be plain numbers, {"value", "unit"}
objects or "N/A", and the top level may be a list or {"gpu_data": [...]}. Anything unreadable yields None.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_UNIT_TO_GB = {"b": 1 / 1024**3, "kb": 1 / 1024**2, "mb": 1 / 1024, "gb": 1.0, "gib": 1.0, "tb": 1024.0}


def _num(v: Any, default_unit: str | None = None) -> tuple[float, str | None] | None:
    """Number and unit from 12, "12", "12 MB", {"value": 12, "unit": "MB"}; None for N/A."""
    unit = default_unit
    if isinstance(v, dict):
        unit = str(v.get("unit") or unit or "") or None
        v = v.get("value")
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v), unit
    if isinstance(v, str):
        parts = v.strip().split()
        try:
            n = float(parts[0])
        except (IndexError, ValueError):
            return None
        return n, (parts[1] if len(parts) > 1 else unit)
    return None


def _gb(v: Any, default_unit: str = "MB") -> float | None:
    got = _num(v, default_unit)
    if not got:
        return None
    n, unit = got
    factor = _UNIT_TO_GB.get((unit or default_unit).strip().lower())
    return None if factor is None else n * factor


def _gpus(doc: Any) -> list[dict]:
    if isinstance(doc, dict):
        for k in ("gpu_data", "gpus", "data"):
            if isinstance(doc.get(k), list):
                return [g for g in doc[k] if isinstance(g, dict)]
        return [doc] if doc else []
    return [g for g in doc if isinstance(g, dict)] if isinstance(doc, list) else []


def _pick(d: Any, *path: str) -> Any:
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def parse_amd_smi(metric: Any, static: Any = None) -> dict | None:
    """Combine `amd-smi metric --json` (and optionally `amd-smi static --json`) into one summary."""
    gpus = _gpus(metric)
    if not gpus:
        return None
    utils, used, total = [], 0.0, 0.0
    for g in gpus:
        u = _num(_pick(g, "usage", "gfx_activity"))
        if u:
            utils.append(u[0])
        mu = _pick(g, "mem_usage")
        mu = mu if isinstance(mu, dict) else {}
        uv, tv = _gb(mu.get("used_vram")), _gb(mu.get("total_vram"))
        if uv is not None:
            used += uv
        if tv is not None:
            total += tv
    if not utils and total == 0:
        return None
    name = None
    for g in _gpus(static):
        name = _pick(g, "asic", "market_name") or _pick(g, "board", "product_name")
        if name:
            break
    return {"gpu_name": str(name) if name else "AMD GPU",
            "util_pct": round(sum(utils) / len(utils), 1) if utils else None,
            "vram_used_gb": round(used, 1), "vram_total_gb": round(total, 1)}


def _run_json(*cmd: str, timeout: float = 8.0) -> Any:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True).stdout
    return json.loads(out)


def read_local() -> dict | None:
    """Query amd-smi on this machine. None when it is missing or fails."""
    exe = shutil.which("amd-smi")
    if not exe:
        return None
    try:
        metric = _run_json(exe, "metric", "--json")
        try:
            static = _run_json(exe, "static", "--json")
        except Exception:  # noqa: BLE001 - the name is optional
            static = None
        return parse_amd_smi(metric, static)
    except Exception:  # noqa: BLE001 - telemetry must never raise
        return None


_cache: dict[str, Any] = {"t": -1e9, "v": None}


def read_cached(ttl: float = 2.0) -> dict | None:
    now = time.monotonic()
    if now - _cache["t"] > ttl:
        _cache.update(t=now, v=read_local())
    return _cache["v"]


def serve(port: int = 9100, host: str = "0.0.0.0") -> None:
    """Sidecar: any GET returns the JSON summary (or null)."""
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            with lock:
                body = json.dumps(read_cached()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a: Any) -> None:
            pass

    ThreadingHTTPServer((host, port), H).serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 9100)
