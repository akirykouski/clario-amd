"""Environment-driven settings. One codebase, two modes: patient (device) and clinic (AMD server)."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_LOCAL_BASE = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible API


@dataclass(frozen=True)
class Settings:
    mode: str = "patient"  # "patient" | "clinic"
    llm_base_url: str = DEFAULT_LOCAL_BASE
    llm_api_key: str = "ollama"
    llm_model: str = "gemma4:e4b"
    llm_is_amd: bool = False
    llm_concurrency: int = 8
    offline: bool = False
    data_dir: Path = Path.home() / ".clario"
    clinic_name: str = "Clario clinic"
    frontend_dist: Path | None = None
    auto_lock_minutes: int = 15

    @property
    def llm_host(self) -> str | None:
        return None if self.offline else urlparse(self.llm_base_url).hostname

    @property
    def llm_backend(self) -> str:
        if self.offline:
            return "offline-fixtures"
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
        s = cls(
            mode=mode,
            llm_base_url=(e.get("LLM_BASE_URL") or DEFAULT_LOCAL_BASE).strip(),
            llm_api_key=(e.get("LLM_API_KEY") or "ollama").strip(),
            llm_model=(e.get("LLM_MODEL") or ("gemma4:e4b" if mode == "patient" else "google/gemma-4-31B-it")).strip(),
            llm_is_amd=(e.get("LLM_IS_AMD") or "0").strip() in ("1", "true", "yes"),
            llm_concurrency=max(1, int(e.get("LLM_CONCURRENCY") or 8)),
            offline=(e.get("CLARIO_OFFLINE") or "").strip().lower() in ("1", "true", "yes"),
            data_dir=Path(e.get("CLARIO_DATA_DIR") or default_dir),
            clinic_name=e.get("CLARIO_CLINIC_NAME") or "Clario clinic",
            frontend_dist=Path(dist) if dist else here.parent / "frontend" / "dist",
            auto_lock_minutes=int(e.get("CLARIO_AUTO_LOCK_MINUTES") or 15),
        )
        return replace(s, **overrides) if overrides else s
