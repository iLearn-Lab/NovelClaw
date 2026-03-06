from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def _resolve_runs_dir() -> Path:
    raw = os.getenv("APP_RUNS_DIR", "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (BASE_DIR.parent / candidate).resolve()
        return candidate
    return (BASE_DIR.parent / "runs").resolve()


RUNS_DIR = _resolve_runs_dir()

DATA_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env", override=False)


def env_or_default(name: str, default: str) -> str:
    val = os.getenv(name)
    if val is None:
        return default
    val = val.strip()
    return val if val else default


@dataclass(frozen=True)
class Settings:
    app_name: str = "Long Story Portal"
    database_url: str = env_or_default(
        "APP_DATABASE_URL",
        f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}",
    )
    https_only: bool = os.getenv("APP_HTTPS_ONLY", "0") == "1"
    default_provider: str = os.getenv("WEB_DEFAULT_PROVIDER", "deepseek").lower()
    max_iterations: int = int(os.getenv("WEB_MAX_ITERATIONS", "8"))
    max_total_iterations: int = int(os.getenv("WEB_MAX_TOTAL_ITERATIONS", "16"))
    job_timeout_seconds: int = int(os.getenv("WEB_JOB_TIMEOUT_SECONDS", "3600"))
    # Jobs are executed by in-process daemon threads; after app restart they cannot resume.
    # Recover stale running/queued jobs quickly to avoid "ghost running" states in UI.
    startup_recovery_seconds: int = int(os.getenv("WEB_STARTUP_RECOVERY_SECONDS", "180"))
    stale_queued_seconds: int = int(os.getenv("WEB_STALE_QUEUED_SECONDS", "180"))

    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    codex_base_url: str = os.getenv("CODEX_BASE_URL", "https://codex-api.packycode.com/v1")
    codex_model: str = os.getenv("CODEX_MODEL", "gpt-5.2")

    session_secret_env: str = os.getenv("APP_SESSION_SECRET", "")
    encryption_key_env: str = os.getenv("APP_ENCRYPTION_KEY", "")


settings = Settings()
