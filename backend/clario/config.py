"""Environment-driven settings. One codebase, two modes: patient (device) and clinic (AMD server)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_LOCAL_BASE = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible API

# AMD Token Factory: hosted, OpenAI-compatible, Gemma 4 on AMD. Detected from the LLM_BASE_URL host, or forced with
# LLM_BACKEND=token-factory. Model ids are case-sensitive. The key is shared by the team (20 RPM, 8 in flight).
TOKEN_FACTORY_HOST = "developer.amd.com.cn"
TOKEN_FACTORY_MODEL = "Gemma-4-31B-IT"
TOKEN_FACTORY_CONCURRENCY = 4  # default parallel requests; the gateway allows 8 per key, shared with batch jobs
TOKEN_FACTORY_MAX_CONCURRENCY = 8
# Lab report pages on Token Factory: MinerU reads the page into markdown (POST /v1/ocr), Gemma 31B structures the text
TOKEN_FACTORY_OCR_MODEL = "MinerU2.5-Pro"


def is_token_factory_url(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    return host == TOKEN_FACTORY_HOST or host.endswith("." + TOKEN_FACTORY_HOST)


def _flag(v: str | None, default: bool | None = None) -> bool | None:
    """Boolean env var: unset or empty -> `default`; else 1/true/yes/on."""
    v = (v or "").strip().lower()
    return default if not v else v in ("1", "true", "yes", "on")


CALIBRATION_FILE = "conformal_threshold.json"  # written by eval/conformal.py


def load_review_calibration(path: Path) -> tuple[str, dict | None]:
    """Read the statistically certified review threshold. Returns (status, data); data only when status is "used".
    Status: used | missing | invalid | dry_run_ignored | no_valid_threshold. A dry-run (fixture) file is never used."""
    try:
        d = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return "missing", None
    except (OSError, ValueError):
        return "invalid", None
    if not isinstance(d, dict):
        return "invalid", None
    if d.get("dry_run"):
        return "dry_run_ignored", None
    t = d.get("threshold")
    if t is None and d.get("status") == "no_valid_threshold":
        return "no_valid_threshold", None
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= t <= 1:
        return "invalid", None
    return "used", d


@dataclass(frozen=True)
class ExtractOpts:
    """Extraction knobs. The one place their defaults live: Settings and the extractor both read them from here."""

    sc_n: int = 5  # self-consistency samples; 1 disables
    trust_model_confidence: bool = False
    hpo_pick: bool = True  # second call: model picks the HPO id from ontology candidates
    review_threshold: float = 0.7  # below this confidence an entity or lab row waits for a person

    @classmethod
    def from_settings(cls, s: "Settings") -> "ExtractOpts":
        return cls(s.sc_n, s.trust_model_confidence, s.hpo_pick, s.review_threshold)


@dataclass(frozen=True)
class Settings:
    mode: str = "patient"  # "patient" | "clinic"
    llm_base_url: str = DEFAULT_LOCAL_BASE
    llm_api_key: str = "ollama"
    llm_model: str = "gemma4:e4b"
    llm_is_amd: bool = False  # LLM_IS_AMD=1: our own vLLM on an AMD Instinct GPU
    llm_provider: str | None = None  # LLM_BACKEND: "token-factory" forces AMD Token Factory; unset = detect by host
    llm_concurrency: int = 8
    offline: bool = False
    data_dir: Path = Path.home() / ".clario"
    clinic_name: str = "Clario clinic"
    frontend_dist: Path | None = None
    auto_lock_minutes: int = 15
    pseudonymize: bool | None = None  # None = auto: on in patient mode when the model is remote
    llm_vision_model: str | None = None  # chat model that reads page images (fallback, or the only path without OCR)
    llm_ocr_model: str | None = None  # LLM_OCR_MODEL: page -> markdown via POST /ocr, then the text model structures it
    doc_structure: str = "table"  # CLARIO_DOC_STRUCTURE: table = read a recognised OCR table in code; model = text model
    doc_concurrency: int | None = None  # None = 4 local, 32 remote (so vLLM can batch), LLM_CONCURRENCY on Token Factory
    doc_samples: int = 3  # self-consistency samples per page when the client supports them (1 on Token Factory)
    review_threshold: float = ExtractOpts.review_threshold

    # Where review_threshold came from: "conformal" (eval/results/conformal_threshold.json or CLARIO_REVIEW_CALIBRATION,
    # a finite-sample guarantee at review_alpha), "env" (CLARIO_REVIEW_THRESHOLD / default 0.7) or "override" (code).
    review_source: str = "env"
    review_alpha: float | None = None
    review_delta: float | None = None
    review_calibration_n: int | None = None
    review_calibration_status: str = "missing"
    review_calibration_file: str | None = None

    sc_n: int = ExtractOpts.sc_n
    trust_model_confidence: bool = ExtractOpts.trust_model_confidence
    hpo_pick: bool = ExtractOpts.hpo_pick
    demo_instance: bool = False
    clinic_url: str | None = None  # default address on the patient Share page (demo instance preset)
    gpu_metrics_url: str | None = None

    @property
    def doc_workers(self) -> int:
        if self.token_factory:  # rate-limited shared key: pages wait for the same few slots as every other call
            return min(self.doc_concurrency or self.llm_concurrency, self.llm_concurrency)
        if self.doc_concurrency:
            return self.doc_concurrency
        return 32 if self.llm_backend in ("amd-vllm", "openai-compatible") else 4

    @property
    def token_factory(self) -> bool:
        """The model runs on AMD Token Factory (hosted, rate limited, no GPU telemetry for us)."""
        if self.offline:
            return False
        return self.llm_provider == "token-factory" or is_token_factory_url(self.llm_base_url)

    @property
    def llm_on_amd(self) -> bool:
        """Model calls run on AMD hardware: our own vLLM on Instinct (LLM_IS_AMD) or AMD Token Factory."""
        return not self.offline and (self.llm_is_amd or self.token_factory)

    @property
    def llm_host(self) -> str | None:
        return None if self.offline else urlparse(self.llm_base_url).hostname

    @property
    def llm_backend(self) -> str:
        if self.offline:
            return "offline-fixtures"
        if self.token_factory:
            return "amd-token-factory"
        if self.llm_is_amd:
            return "amd-vllm"
        host = self.llm_host or ""
        if ":11434" in self.llm_base_url:
            return "ollama-local"
        if host in ("localhost", "127.0.0.1"):
            return "local"
        return "openai-compatible"

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        e = os.environ
        mode = (e.get("CLARIO_MODE") or "patient").strip().lower()
        if mode not in ("patient", "clinic"):
            raise ValueError("CLARIO_MODE must be 'patient' or 'clinic'")
        here = Path(__file__).resolve().parent.parent
        default_dir = Path.home() / (".clario" if mode == "patient" else ".clario-clinic")
        dist = e.get("FRONTEND_DIST")
        d = ExtractOpts()
        cal_path = Path(e.get("CLARIO_REVIEW_CALIBRATION") or here.parent / "eval" / "results" / CALIBRATION_FILE)
        cal_status, cal = load_review_calibration(cal_path)
        threshold = float(cal["threshold"]) if cal else float(e.get("CLARIO_REVIEW_THRESHOLD") or d.review_threshold)
        base_url = (e.get("LLM_BASE_URL") or DEFAULT_LOCAL_BASE).strip()
        provider = (e.get("LLM_BACKEND") or "").strip().lower() or None
        if provider not in (None, "auto", "token-factory"):
            raise ValueError("LLM_BACKEND must be 'token-factory', 'auto' or unset")
        provider = None if provider == "auto" else provider
        tf = provider == "token-factory" or is_token_factory_url(base_url)
        if tf:
            default_model = TOKEN_FACTORY_MODEL
        else:
            default_model = "gemma4:e4b" if mode == "patient" else "google/gemma-4-31B-it"
        concurrency = max(1, int(e.get("LLM_CONCURRENCY") or (TOKEN_FACTORY_CONCURRENCY if tf else 8)))
        if tf:
            concurrency = min(concurrency, TOKEN_FACTORY_MAX_CONCURRENCY)
        ocr = (e.get("LLM_OCR_MODEL") or "").strip()
        ocr_model = None if ocr.lower() in ("off", "none", "0") else (ocr or (TOKEN_FACTORY_OCR_MODEL if tf else None))
        s = cls(
            mode=mode,
            llm_base_url=base_url,
            llm_api_key=(e.get("LLM_API_KEY") or "ollama").strip(),
            llm_model=(e.get("LLM_MODEL") or default_model).strip(),
            llm_is_amd=bool(_flag(e.get("LLM_IS_AMD"))),
            llm_provider=provider,
            llm_concurrency=concurrency,
            offline=bool(_flag(e.get("CLARIO_OFFLINE"))),
            data_dir=Path(e.get("CLARIO_DATA_DIR") or default_dir),
            clinic_name=e.get("CLARIO_CLINIC_NAME") or "Clario clinic",
            frontend_dist=Path(dist) if dist else here.parent / "frontend" / "dist",
            auto_lock_minutes=int(e.get("CLARIO_AUTO_LOCK_MINUTES") or 15),
            pseudonymize=_flag(e.get("CLARIO_PSEUDONYMIZE")),
            llm_vision_model=(e.get("LLM_VISION_MODEL") or "").strip() or None,
            doc_concurrency=max(1, int(e["CLARIO_DOC_CONCURRENCY"])) if e.get("CLARIO_DOC_CONCURRENCY") else None,
            llm_ocr_model=ocr_model,
            doc_structure="model" if (e.get("CLARIO_DOC_STRUCTURE") or "").strip().lower() == "model" else "table",
            # shared 20 RPM key: one structuring call per page; the OCR text is checked in code instead (documents.py)
            doc_samples=max(1, int(e.get("CLARIO_DOC_SAMPLES") or (1 if tf else 3))),
            sc_n=max(1, int(e.get("CLARIO_SC_N") or d.sc_n)),
            trust_model_confidence=bool(_flag(e.get("CLARIO_TRUST_MODEL_CONFIDENCE"), d.trust_model_confidence)),
            hpo_pick=bool(_flag(e.get("CLARIO_HPO_PICK"), d.hpo_pick)),
            review_threshold=threshold,
            review_source="conformal" if cal else "env",
            review_alpha=cal.get("alpha") if cal else None,
            review_delta=cal.get("delta") if cal else None,
            review_calibration_n=cal.get("n") if cal else None,
            review_calibration_status=cal_status,
            review_calibration_file=str(cal_path) if cal else None,
            demo_instance=bool(_flag(e.get("CLARIO_DEMO_INSTANCE"))),
            clinic_url=(e.get("CLARIO_CLINIC_URL") or "").strip() or None,
            gpu_metrics_url=(e.get("CLARIO_GPU_METRICS_URL") or "").strip() or None,
        )
        if "review_threshold" in overrides:  # an explicit value in code beats both the file and the env
            overrides = {"review_source": "override", "review_alpha": None, "review_delta": None,
                         "review_calibration_n": None, **overrides}
        return replace(s, **overrides) if overrides else s
