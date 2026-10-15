"""Hardware provenance and GPU sampling for result files. Stdlib only, runs on the droplet host (amd-smi lives there).

    python eval/hardware.py                         print the hardware record as JSON
    python eval/hardware.py sample --out F          append one JSON line per second (ts, util_pct, vram_used_gb) until killed
    python eval/hardware.py stamp FILE [FILE ...]   add the hardware record to result files that lack one

Hardware record: {"gpu_name", "gpu_count", "vram_total_gb", "source"}.
Resolution order: env CLARIO_HARDWARE (JSON or plain name; bootstrap.sh exports it from the host so containers
without amd-smi still label results) -> amd-smi on this machine -> rocm-smi -> "none (no GPU telemetry)".
amd-smi JSON shapes follow AMD's docs and are unverified on real MI300X (see backend/clario/gpu.py).
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GPU_PY = os.path.join(os.path.dirname(HERE), "backend", "clario", "gpu.py")


def _gpu_mod():
    spec = importlib.util.spec_from_file_location("clario_gpu_stdlib", GPU_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _count(exe):
    try:
        out = subprocess.run([exe, "metric", "--json"], capture_output=True, text=True, timeout=10, check=True).stdout
        doc = json.loads(out)
        return len(_gpu_mod()._gpus(doc)) or None
    except Exception:  # noqa: BLE001
        return None


def detect():
    env = os.environ.get("CLARIO_HARDWARE", "").strip()
    if env:
        try:
            d = json.loads(env)
            if isinstance(d, dict) and d.get("gpu_name"):
                return d
        except ValueError:
            return {"gpu_name": env, "gpu_count": None, "vram_total_gb": None, "source": "env"}
    exe = shutil.which("amd-smi")
    if exe:
        try:
            g = _gpu_mod().read_local()
        except Exception:  # noqa: BLE001
            g = None
        if g:
            return {"gpu_name": g["gpu_name"], "gpu_count": _count(exe), "vram_total_gb": g.get("vram_total_gb"),
                    "source": "amd-smi"}
    exe = shutil.which("rocm-smi")
    if exe:
        try:
            out = subprocess.run([exe, "--showproductname"], capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                if "Card Series" in line or "Card series" in line or "Card model" in line:
                    return {"gpu_name": line.split(":", 2)[-1].strip(), "gpu_count": None, "vram_total_gb": None,
                            "source": "rocm-smi"}
        except Exception:  # noqa: BLE001
            pass
    return {"gpu_name": "none (no GPU telemetry)", "gpu_count": None, "vram_total_gb": None, "source": "none"}


def stamp(paths, hw=None):
    hw = hw or detect()
    for p in paths:
        r = json.load(open(p))
        if r.get("hardware"):
            print(f"keep {os.path.basename(p)}: hardware already set")
            continue
        r["hardware"] = hw
        json.dump(r, open(p, "w"), indent=2)
        print(f"stamped {os.path.basename(p)}: {hw['gpu_name']}")


def sample(out, interval=1.0, count=0):
    """Append {ts, util_pct, vram_used_gb} lines. count=0 runs until killed."""
    gpu = _gpu_mod()
    i = 0
    with open(out, "a") as f:
        while not count or i < count:
            g = gpu.read_local()
            if g:
                f.write(json.dumps({"ts": time.time(), "util_pct": g.get("util_pct"), "vram_used_gb": g.get("vram_used_gb")}) + "\n")
                f.flush()
            i += 1
            time.sleep(interval)


def load_samples(path):
    out = []
    try:
        for line in open(path):
            if line.strip():
                out.append(json.loads(line))
    except OSError:
        pass
    return out


def summarize(samples, t0, t1):
    """GPU util mean/max and peak VRAM over [t0, t1] (epoch seconds). Nulls when no sample falls in the window."""
    w = [s for s in samples if t0 <= s["ts"] <= t1]
    u = [s["util_pct"] for s in w if s.get("util_pct") is not None]
    v = [s["vram_used_gb"] for s in w if s.get("vram_used_gb") is not None]
    return {"gpu_samples": len(w), "gpu_util_mean_pct": round(sum(u) / len(u), 1) if u else None,
            "gpu_util_max_pct": max(u) if u else None, "gpu_vram_peak_gb": max(v) if v else None}


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(json.dumps(detect(), indent=2))
    elif a[0] == "sample" and "--out" in a:
        sample(a[a.index("--out") + 1], float(a[a.index("--interval") + 1]) if "--interval" in a else 1.0,
               int(a[a.index("--count") + 1]) if "--count" in a else 0)
    elif a[0] == "stamp" and len(a) > 1:
        stamp(a[1:])
    else:
        sys.exit(__doc__)
