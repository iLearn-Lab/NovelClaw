from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(BASE_DIR / ".env", override=False)
load_dotenv(BASE_DIR.parent / ".env", override=False)


def env_or_default(name: str, default: str) -> str:
    val = os.getenv(name)
    if val is None:
        return default
    val = val.strip()
    return val if val else default


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_database_url() -> str:
    raw = env_or_default("APP_DATABASE_URL", f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}")
    if not raw.startswith("sqlite:///"):
        return raw
    db_path = raw[len("sqlite:///"):].strip()
    if not db_path or db_path == ":memory:":
        return raw
    candidate = Path(db_path).expanduser()
    if not candidate.is_absolute():
        candidate = (BASE_DIR.parent / candidate).resolve()
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{candidate.as_posix()}"


@dataclass(frozen=True)
class Settings:
    app_name: str = "NovelClaw Portal"
    database_url: str = _resolve_database_url()
    https_only: bool = env_flag("APP_HTTPS_ONLY", False)
    session_cookie_name: str = os.getenv("APP_SESSION_COOKIE_NAME", "session").strip() or "session"
    session_cookie_domain: str = os.getenv("APP_SESSION_COOKIE_DOMAIN", "").strip()
    app_base_url: str = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    app_multiagent_url: str = os.getenv("APP_MULTIAGENT_URL", "").strip()
    app_claw_url: str = os.getenv("APP_CLAW_URL", "").strip()
    app_multiagent_port: str = os.getenv("APP_MULTIAGENT_PORT", "8011").strip() or "8011"
    app_claw_port: str = os.getenv("APP_CLAW_PORT", "8012").strip() or "8012"
    ui_language: str = os.getenv("WEB_UI_LANGUAGE", "en").lower()
    preview_user_email: str = os.getenv("APP_PREVIEW_USER_EMAIL", "preview@novelclaw.local").strip().lower() or "preview@novelclaw.local"
    session_secret_env: str = os.getenv("APP_SESSION_SECRET", "")


settings = Settings()
