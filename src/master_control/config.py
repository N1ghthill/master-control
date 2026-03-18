from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "master-control"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_OPENAI_REASONING_EFFORT = "none"
DEFAULT_OPENAI_TIMEOUT_S = 20.0
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/api"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_TIMEOUT_S = 60.0
DEFAULT_PROVIDER_PROBE_TIMEOUT_S = 0.75


@dataclass(slots=True)
class Settings:
    app_name: str
    log_level: str
    provider: str
    state_dir: Path
    db_path: Path
    openai_api_key: str | None = None
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL
    openai_model: str = DEFAULT_OPENAI_MODEL
    openai_reasoning_effort: str | None = DEFAULT_OPENAI_REASONING_EFFORT
    openai_timeout_s: float = DEFAULT_OPENAI_TIMEOUT_S
    openai_store: bool = False
    openai_organization: str | None = None
    openai_project: str | None = None
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_timeout_s: float = DEFAULT_OLLAMA_TIMEOUT_S
    ollama_keep_alive: str | None = None
    ollama_api_key: str | None = None
    provider_probe_timeout_s: float = DEFAULT_PROVIDER_PROBE_TIMEOUT_S

    @classmethod
    def from_env(cls) -> "Settings":
        state_dir = Path(os.getenv("MC_STATE_DIR", DEFAULT_STATE_DIR))
        db_path = Path(os.getenv("MC_DB_PATH", state_dir / "mc.sqlite3"))
        return cls(
            app_name="master-control",
            log_level=os.getenv("MC_LOG_LEVEL", "INFO"),
            provider=os.getenv("MC_PROVIDER", "auto"),
            state_dir=state_dir,
            db_path=db_path,
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            openai_model=os.getenv("MC_OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            openai_reasoning_effort=os.getenv(
                "MC_OPENAI_REASONING_EFFORT",
                DEFAULT_OPENAI_REASONING_EFFORT,
            ),
            openai_timeout_s=_parse_float_env("MC_OPENAI_TIMEOUT_S", DEFAULT_OPENAI_TIMEOUT_S),
            openai_store=_parse_bool_env("MC_OPENAI_STORE", False),
            openai_organization=os.getenv("OPENAI_ORGANIZATION") or os.getenv("OPENAI_ORG_ID"),
            openai_project=os.getenv("OPENAI_PROJECT"),
            ollama_base_url=os.getenv("MC_OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
            ollama_model=os.getenv("MC_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
            ollama_timeout_s=_parse_float_env("MC_OLLAMA_TIMEOUT_S", DEFAULT_OLLAMA_TIMEOUT_S),
            ollama_keep_alive=os.getenv("MC_OLLAMA_KEEP_ALIVE"),
            ollama_api_key=os.getenv("OLLAMA_API_KEY"),
            provider_probe_timeout_s=_parse_float_env(
                "MC_PROVIDER_PROBE_TIMEOUT_S",
                DEFAULT_PROVIDER_PROBE_TIMEOUT_S,
            ),
        )

    def ensure_directories(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)


def _parse_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default
