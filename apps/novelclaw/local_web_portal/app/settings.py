from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
load_dotenv(BASE_DIR / ".env", override=False)
load_dotenv(BASE_DIR.parent / ".env", override=False)


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


def env_or_default(name: str, default: str) -> str:
    val = os.getenv(name)
    if val is None:
        return default
    val = val.strip()
    return val if val else default


def _resolve_database_url() -> str:
    raw = env_or_default("APP_DATABASE_URL", f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}")
    if not raw.startswith("sqlite"):
        return raw

    prefix = "sqlite:///"
    if not raw.startswith(prefix):
        return raw

    db_path = raw[len(prefix):].strip()
    if not db_path or db_path == ":memory:":
        return raw

    candidate = Path(db_path).expanduser()
    if not candidate.is_absolute():
        candidate = (BASE_DIR.parent / candidate).resolve()
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{candidate.as_posix()}"


def _resolve_optional_database_url(name: str) -> str:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ""
    if not raw.startswith("sqlite"):
        return raw

    prefix = "sqlite:///"
    if not raw.startswith(prefix):
        return raw

    db_path = raw[len(prefix):].strip()
    if not db_path or db_path == ":memory:":
        return raw

    candidate = Path(db_path).expanduser()
    if not candidate.is_absolute():
        candidate = (BASE_DIR.parent / candidate).resolve()
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{candidate.as_posix()}"


@dataclass(frozen=True)
class Settings:
    app_name: str = "Long Story Portal"
    database_url: str = _resolve_database_url()
    auth_database_url: str = _resolve_optional_database_url("APP_AUTH_DATABASE_URL")
    https_only: bool = os.getenv("APP_HTTPS_ONLY", "0") == "1"
    session_cookie_name: str = env_or_default("APP_SESSION_COOKIE_NAME", "session")
    session_cookie_domain: str = os.getenv("APP_SESSION_COOKIE_DOMAIN", "").strip()
    shared_portal_url: str = os.getenv("APP_SHARED_PORTAL_URL", "").strip().rstrip("/")
    shared_portal_port: str = os.getenv("APP_SHARED_PORTAL_PORT", "8010").strip() or "8010"
    base_path: str = os.getenv("APP_BASE_PATH", "").strip().rstrip("/")
    agent_api_key: str = os.getenv("APP_AGENT_API_KEY", "").strip()
    agent_user_email: str = os.getenv("APP_AGENT_USER_EMAIL", "agent@novelclaw.local").strip().lower() or "agent@novelclaw.local"
    modelless_mode: bool = os.getenv("WEB_MODELLESS_MODE", "1") == "1"
    default_provider: str = os.getenv("WEB_DEFAULT_PROVIDER", "deepseek").lower()
    ui_language: str = os.getenv("WEB_UI_LANGUAGE", "en").lower()
    max_iterations: int = int(os.getenv("WEB_MAX_ITERATIONS", "8"))
    max_total_iterations: int = int(os.getenv("WEB_MAX_TOTAL_ITERATIONS", "16"))
    execution_mode: str = os.getenv("WEB_EXECUTION_MODE", "claw").lower()
    claw_max_steps: int = int(os.getenv("WEB_CLAW_MAX_STEPS", "6"))
    job_timeout_seconds: int = int(os.getenv("WEB_JOB_TIMEOUT_SECONDS", "0"))
    job_idle_timeout_seconds: int = int(os.getenv("WEB_JOB_IDLE_TIMEOUT_SECONDS", "0"))
    # Jobs are executed by in-process daemon threads; after app restart they cannot resume.
    # Recover stale running/queued jobs quickly to avoid "ghost running" states in UI.
    startup_recovery_seconds: int = int(os.getenv("WEB_STARTUP_RECOVERY_SECONDS", "180"))
    stale_queued_seconds: int = int(os.getenv("WEB_STALE_QUEUED_SECONDS", "180"))
    fast_mode: bool = os.getenv("WEB_FAST_MODE", "1") == "1"
    full_cycle_interval: int = int(os.getenv("WEB_FULL_CYCLE_INTERVAL", "3"))
    chapters_per_iter: int = int(os.getenv("WEB_CHAPTERS_PER_ITER", "1"))
    max_chapter_subrounds: int = int(os.getenv("WEB_MAX_CHAPTER_SUBROUNDS", "2"))
    eval_interval: int = int(os.getenv("WEB_EVAL_INTERVAL", "8"))

    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    codex_base_url: str = os.getenv("CODEX_BASE_URL", "https://codex-api.packycode.com/v1")
    codex_model: str = os.getenv("CODEX_MODEL", "gpt-5.2")

    session_secret_env: str = os.getenv("APP_SESSION_SECRET", "")
    encryption_key_env: str = os.getenv("APP_ENCRYPTION_KEY", "")


settings = Settings()
