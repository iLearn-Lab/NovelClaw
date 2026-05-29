from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from fastapi import Depends, FastAPI, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .db import engine, get_db
from .models import Base, User
from .security import SESSION_SECRET
from .settings import BASE_DIR, settings


SELECTED_MODE_KEY = "selected_mode"
VALID_MODES = {"mode_a", "mode_b"}

app = FastAPI(title=settings.app_name)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie=settings.session_cookie_name,
    https_only=settings.https_only,
    same_site="lax",
    domain=settings.session_cookie_domain or None,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
Base.metadata.create_all(bind=engine)


def _redirect(path: str, code: int = status.HTTP_303_SEE_OTHER):
    return RedirectResponse(path, status_code=code)


def _safe_next_path(target: str, default: str = "/select-mode") -> str:
    raw = str(target or "").strip()
    if not raw:
        return default
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc:
        return default
    path = parts.path or "/"
    if not path.startswith("/") or path.startswith("//"):
        return default
    return urlunsplit(("", "", path, parts.query, ""))


def _ui_language(request: Request) -> str:
    session_lang = str(request.session.get("ui_language", "") or "").lower()
    if session_lang in {"zh", "en"}:
        return session_lang
    configured = str(settings.ui_language or "").lower()
    return configured if configured in {"zh", "en"} else "en"


def _portal_context(request: Request, **extra):
    ctx = {"request": request, "ui_language": _ui_language(request)}
    ctx.update(extra)
    return ctx


def _selected_mode(request: Request) -> str:
    mode = str(request.session.get(SELECTED_MODE_KEY, "") or "").lower()
    return mode if mode in VALID_MODES else ""


def _selected_mode_label(mode: str, lang: str) -> str:
    labels = {
        "mode_a": "MultiAgent 小说工作台" if lang != "en" else "MultiAgent Novel Workspace",
        "mode_b": "NovelClaw 小说工作台" if lang != "en" else "NovelClaw Workspace",
    }
    return labels.get(mode, "未选择" if lang != "en" else "Not selected")


def _external_host(request: Request) -> str:
    host = request.url.hostname or "localhost"
    if host in {"0.0.0.0", "::"}:
        host = "localhost"
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def _workspace_url(request: Request, configured_url: str, port: str, path: str) -> str:
    configured = (configured_url or "").strip()
    if configured:
        return configured
    safe_path = path if path.startswith("/") else f"/{path}"
    return urlunsplit((request.url.scheme, f"{_external_host(request)}:{port}", safe_path, "", ""))


def _ensure_preview_user(request: Request, db: Session) -> User:
    uid = request.session.get("uid")
    if uid:
      try:
          user_id = int(uid)
      except (TypeError, ValueError):
          request.session.pop("uid", None)
      else:
          existing = db.get(User, user_id)
          if existing:
              return existing

    email = settings.preview_user_email
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(email=email, password_hash="preview-mode")
        db.add(user)
        db.commit()
        db.refresh(user)
    request.session["uid"] = user.id
    return user


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def root():
    return _redirect("/select-mode")


@app.get("/select-mode")
def select_mode(request: Request, db: Session = Depends(get_db)):
    user = _ensure_preview_user(request, db)
    lang = _ui_language(request)
    current_mode = _selected_mode(request)
    mode_a_url = _workspace_url(request, settings.app_multiagent_url, settings.app_multiagent_port, "/dashboard")
    mode_b_url = _workspace_url(request, settings.app_claw_url, settings.app_claw_port, "/dashboard")
    return templates.TemplateResponse(
        "select_mode.html",
        _portal_context(
            request,
            preview_session=user.email,
            current_mode=current_mode,
            current_mode_label=_selected_mode_label(current_mode, lang),
            mode_a_url="/mode-a",
            mode_b_url="/mode-b",
            mode_a_display_url=mode_a_url,
            mode_b_display_url=mode_b_url,
        ),
    )


@app.get("/mode-a")
def choose_mode_a(request: Request, db: Session = Depends(get_db)):
    _ensure_preview_user(request, db)
    request.session[SELECTED_MODE_KEY] = "mode_a"
    return _redirect(_workspace_url(request, settings.app_multiagent_url, settings.app_multiagent_port, "/dashboard"))


@app.get("/mode-b")
def choose_mode_b(request: Request, db: Session = Depends(get_db)):
    _ensure_preview_user(request, db)
    request.session[SELECTED_MODE_KEY] = "mode_b"
    return _redirect(_workspace_url(request, settings.app_claw_url, settings.app_claw_port, "/dashboard"))


@app.post("/ui-language")
def set_ui_language(request: Request, lang: str = Form(...), next: str = Form("/select-mode")):
    request.session["ui_language"] = "zh" if str(lang or "").lower().startswith("zh") else "en"
    return _redirect(_safe_next_path(next))


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return _redirect("/select-mode")


@app.get("/login")
@app.get("/register")
@app.get("/verify-email")
@app.get("/forgot-password")
@app.get("/reset-password")
@app.get("/account/password")
def legacy_entry():
    return _redirect("/select-mode")
