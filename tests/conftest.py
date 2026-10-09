from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", params=["novelclaw", "multiagent", "auth-portal"])
def service(request, tmp_path_factory):
    """Load each independently deployed app with isolated state and no real keys."""
    name = request.param
    temp = tmp_path_factory.mktemp(name)
    prefixes = (
        "local_web_portal",
        "config",
        "utils",
        "rag",
        "agents",
        "workflow",
        "capability_registry",
    )
    for module in list(sys.modules):
        if module.split(".")[0] in prefixes:
            del sys.modules[module]
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT / "apps" / name))
        for key, value in {
            "APP_DATA_DIR": str(temp / "data"),
            "APP_DATABASE_URL": f"sqlite:///{(temp / 'app.db').as_posix()}",
            "APP_AUTH_DATABASE_URL": "",
            "APP_RUNS_DIR": str(temp / "runs"),
            "APP_SESSION_SECRET": "test-session-secret",
            "APP_SESSION_COOKIE_NAME": "session",
            "APP_ENCRYPTION_KEY": "",
            "APP_AGENT_API_KEY": "test-agent-token",
            "APP_HTTPS_ONLY": "0",
            "APP_BASE_PATH": "",
            "APP_MULTIAGENT_URL": "",
            "APP_CLAW_URL": "",
            "WEB_UI_LANGUAGE": "zh",
            "WEB_MODELLESS_MODE": "0",
            "MEMORY_ONLY_MODE": "1",
            "ENABLE_RAG": "0",
            "EMBEDDING_MODEL": "none",
            "VECTOR_DB_PATH": str(temp / "vector_db"),
            "OPENAI_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
            "CODEX_API_KEY": "",
            "LLM_API_KEY": "",
        }.items():
            patch.setenv(key, value)
        main = importlib.import_module("local_web_portal.app.main")
        db = importlib.import_module("local_web_portal.app.db")
        models = importlib.import_module("local_web_portal.app.models")
        with TestClient(main.app) as client:
            yield SimpleNamespace(
                name=name, main=main, db=db, models=models, client=client, temp=temp
            )
        db.engine.dispose()
        if getattr(db, "auth_engine", None) is not None:
            db.auth_engine.dispose()


@pytest.fixture
def workspace(service):
    if service.name == "auth-portal":
        pytest.skip("Writing workspace only")
    return service


@pytest.fixture
def signed_in(workspace):
    import base64
    import json
    from itsdangerous import TimestampSigner

    with workspace.db.SessionLocal() as db:
        user = workspace.models.User(
            email=f"reader-{uuid4().hex}@example.test", password_hash="test"
        )
        db.add(user)
        db.commit()
        uid = user.id
    session = base64.b64encode(json.dumps({"uid": uid, "ui_language": "zh"}).encode())
    cookie = TimestampSigner("test-session-secret").sign(session).decode()
    workspace.client.cookies.set("session", cookie)
    yield SimpleNamespace(**vars(workspace), user_id=uid)
    workspace.client.cookies.clear()
