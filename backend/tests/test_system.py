"""GPU telemetry route, amd-smi parser, demo-instance flag.

The amd-smi samples below follow the shape in AMD's amd-smi docs. They are NOT captured from real
MI300X hardware: re-check against `amd-smi metric --json` on the droplet.
"""

import socket
import threading
import time

from fastapi.testclient import TestClient

from clario import gpu
from clario.app import create_app
from conftest import settings

METRIC_LIST = [
    {"gpu": 0,
     "usage": {"gfx_activity": {"value": 37, "unit": "%"}, "umc_activity": {"value": 12, "unit": "%"}},
     "mem_usage": {"total_vram": {"value": 196592, "unit": "MB"}, "used_vram": {"value": 98296, "unit": "MB"}}},
]
STATIC_LIST = [{"gpu": 0, "asic": {"market_name": "AMD Instinct MI300X", "vendor_id": "0x1002"}}]


def test_parse_list_shape():
    out = gpu.parse_amd_smi(METRIC_LIST, STATIC_LIST)
    assert out == {"gpu_name": "AMD Instinct MI300X", "util_pct": 37.0, "vram_used_gb": 96.0, "vram_total_gb": 192.0}


def test_parse_wrapped_shape_and_plain_numbers():
    doc = {"gpu_data": [{"usage": {"gfx_activity": 10}, "mem_usage": {"total_vram": "1024 MB", "used_vram": "512 MB"}},
                        {"usage": {"gfx_activity": 30}, "mem_usage": {"total_vram": "1024 MB", "used_vram": "N/A"}}]}
    out = gpu.parse_amd_smi(doc)
    assert out["gpu_name"] == "AMD GPU"
    assert out["util_pct"] == 20.0
    assert out["vram_used_gb"] == 0.5 and out["vram_total_gb"] == 2.0


def test_parse_garbage_is_none():
    for bad in (None, [], {}, "x", 5, [{"foo": 1}], [{"usage": {"gfx_activity": "N/A"}, "mem_usage": None}]):
        assert gpu.parse_amd_smi(bad) is None


def test_gpu_route_null_without_amd_smi(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu.shutil, "which", lambda _n: None)
    gpu._cache.update(t=-1e9, v=None)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as c:
        r = c.get("/api/system/gpu")
    assert r.status_code == 200 and r.json() is None


def test_gpu_route_uses_local_amd_smi(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu.shutil, "which", lambda _n: "/usr/bin/amd-smi")
    monkeypatch.setattr(gpu, "_run_json", lambda *cmd, **_k: METRIC_LIST if "metric" in cmd else STATIC_LIST)
    gpu._cache.update(t=-1e9, v=None)
    with TestClient(create_app(settings(tmp_path, "clinic"))) as c:
        assert c.get("/api/system/gpu").json()["vram_total_gb"] == 192.0


def test_gpu_route_proxies_sidecar(tmp_path, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(gpu.shutil, "which", lambda _n: "/usr/bin/amd-smi")
    monkeypatch.setattr(gpu, "_run_json", lambda *cmd, **_k: METRIC_LIST if "metric" in cmd else STATIC_LIST)
    gpu._cache.update(t=-1e9, v=None)
    threading.Thread(target=gpu.serve, args=(port, "127.0.0.1"), daemon=True).start()
    time.sleep(0.3)
    cfg = settings(tmp_path, "clinic", gpu_metrics_url=f"http://127.0.0.1:{port}/")
    with TestClient(create_app(cfg)) as c:
        got = c.get("/api/system/gpu").json()
    assert got["gpu_name"] == "AMD Instinct MI300X"


def test_gpu_route_sidecar_down_is_null(tmp_path):
    cfg = settings(tmp_path, "clinic", gpu_metrics_url="http://127.0.0.1:9/")
    with TestClient(create_app(cfg)) as c:
        assert c.get("/api/system/gpu").json() is None


def test_health_demo_flag(tmp_path, monkeypatch):
    for mode in ("patient", "clinic"):
        with TestClient(create_app(settings(tmp_path / mode, mode))) as c:
            assert c.get("/api/health").json()["demo_instance"] is False
        with TestClient(create_app(settings(tmp_path / f"{mode}-demo", mode, demo_instance=True))) as c:
            assert c.get("/api/health").json()["demo_instance"] is True


def test_demo_and_gpu_env(monkeypatch):
    from clario.config import Settings
    monkeypatch.setenv("CLARIO_DEMO_INSTANCE", "1")
    monkeypatch.setenv("CLARIO_GPU_METRICS_URL", "http://gpu-metrics:9100/")
    s = Settings.from_env()
    assert s.demo_instance and s.gpu_metrics_url == "http://gpu-metrics:9100/"
