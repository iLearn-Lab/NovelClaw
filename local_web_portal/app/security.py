from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from passlib.context import CryptContext

from .settings import DATA_DIR, settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_SECRET_FILE = DATA_DIR / "session.secret"
ENCRYPTION_KEY_FILE = DATA_DIR / "fernet.key"


def _write_secret_file(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Windows may not support chmod semantics as expected.
        pass


def _get_or_create_session_secret() -> str:
    if settings.session_secret_env:
        return settings.session_secret_env
    if SESSION_SECRET_FILE.exists():
        return SESSION_SECRET_FILE.read_text(encoding="utf-8").strip()

    value = secrets.token_urlsafe(64)
    _write_secret_file(SESSION_SECRET_FILE, value)
    return value


def _get_or_create_encryption_key() -> str:
    if settings.encryption_key_env:
        return settings.encryption_key_env
    if ENCRYPTION_KEY_FILE.exists():
        return ENCRYPTION_KEY_FILE.read_text(encoding="utf-8").strip()

    value = Fernet.generate_key().decode("utf-8")
    _write_secret_file(ENCRYPTION_KEY_FILE, value)
    return value


SESSION_SECRET = _get_or_create_session_secret()
FERNET = Fernet(_get_or_create_encryption_key().encode("utf-8"))


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def encrypt_api_key(raw_key: str) -> str:
    return FERNET.encrypt(raw_key.encode("utf-8")).decode("utf-8")


def decrypt_api_key(cipher_text: str) -> str:
    return FERNET.decrypt(cipher_text.encode("utf-8")).decode("utf-8")

