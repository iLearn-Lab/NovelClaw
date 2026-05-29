from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from agents.idea_copilot_agent import (
    IdeaCopilotAgent,
    append_assistant_turn,
    append_user_reply,
    build_generation_idea,
    dump_state,
    latest_assistant_turn,
    load_state,
)
from .auth_bridge import sync_user_from_auth_db
from .db import SessionLocal, engine, get_db
from .i18n import get_locale, install_i18n, set_locale, translate
from .job_launcher import start_generation_job_process
from .models import ApiCredential, Base, GenerationJob, IdeaCopilotSession, ProviderConfig, User
from .provider_registry import (
    ProviderSpec,
    get_provider_specs,
    is_valid_slug,
    merge_provider_specs,
    normalize_slug,
    normalize_wire_api,
)
from .security import SESSION_SECRET, decrypt_api_key, encrypt_api_key, hash_password, verify_password
from .settings import BASE_DIR, RUNS_DIR, settings

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

EVENT_LABELS = {
    "global_outline": "event.global_outline",
    "chapter_outline_ready": "event.chapter_outline_ready",
    "chapter_plan": "event.chapter_plan",
    "chapter_outline": "event.chapter_outline",
    "chapter_length_plan": "event.chapter_length_plan",
    "chapter_length_warning": "event.chapter_length_warning",
    "character_setting": "event.character_setting",
    "world_setting": "event.world_setting",
    "memory_snapshot": "event.memory_snapshot",
}

MEMORY_COUNT_KEYS = (
    "texts",
    "outlines",
    "characters",
    "world_settings",
    "plot_points",
    "fact_cards",
)

app = FastAPI(title=settings.app_name)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie=settings.session_cookie_name,
    same_site="lax",
    https_only=settings.https_only,
    domain=settings.session_cookie_domain or None,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
install_i18n(templates)


SHARED_PORTAL_PATHS = {
    "/login",
    "/register",
    "/verify-email",
    "/forgot-password",
    "/reset-password",
    "/account/password",
    "/select-mode",
    "/mode-a",
    "/mode-b",
    "/healthz",
}


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    # Detached job launchers send periodic heartbeats while work is active.
    # If the heartbeat stops past the cutoff, the job is treated as stale.
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        running_cutoff = now - timedelta(seconds=max(60, settings.startup_recovery_seconds))
        queued_cutoff = now - timedelta(seconds=max(60, settings.stale_queued_seconds))

        stale_running_jobs = db.execute(
            select(GenerationJob).where(
                GenerationJob.status == "running",
                GenerationJob.updated_at < running_cutoff,
            )
        ).scalars().all()
        stale_queued_jobs = db.execute(
            select(GenerationJob).where(
                GenerationJob.status == "queued",
                GenerationJob.created_at < queued_cutoff,
            )
        ).scalars().all()

        for job in stale_running_jobs:
            job.status = "failed"
            prefix = (job.error_message + "\n") if job.error_message else ""
            job.error_message = prefix + "[system] marked as failed after app restart (worker thread was lost)."
            job.finished_at = now
            job.updated_at = now

        for job in stale_queued_jobs:
            job.status = "failed"
            prefix = (job.error_message + "\n") if job.error_message else ""
            job.error_message = prefix + "[system] queued too long without active worker; marked failed on startup."
            job.finished_at = now
            job.updated_at = now

        if stale_running_jobs or stale_queued_jobs:
            db.commit()


def _current_user(request: Request, db: Session) -> Optional[User]:
    uid = request.session.get("uid")
    if not uid:
        return None
    try:
        user_id = int(uid)
    except (TypeError, ValueError):
        return None
    return sync_user_from_auth_db(db, user_id)


def _require_user(request: Request, db: Session) -> User:
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return user


def _is_shared_portal_path(path: str) -> bool:
    return any(path == item or path.startswith(f"{item}/") for item in SHARED_PORTAL_PATHS)


def _shared_path(path: str) -> str:
    normalized = (path or "").strip() or "/"
    normalized = normalized if normalized.startswith("/") else f"/{normalized}"
    if _is_shared_portal_path(normalized) and settings.shared_portal_url:
        return f"{settings.shared_portal_url}{normalized}"
    return normalized


def _external_host(request: Request) -> str:
    host = request.url.hostname or "localhost"
    if host in {"0.0.0.0", "::"}:
        host = "localhost"
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def _shared_portal_url(request: Request, path: str) -> str:
    normalized = (path or "").strip() or "/select-mode"
    normalized = normalized if normalized.startswith("/") else f"/{normalized}"
    if settings.shared_portal_url:
        return f"{settings.shared_portal_url}{normalized}"
    return urlunsplit((request.url.scheme, f"{_external_host(request)}:{settings.shared_portal_port}", normalized, "", ""))


def _app_path(path: str) -> str:
    normalized = _shared_path(path)
    if _is_shared_portal_path(normalized) and settings.shared_portal_url:
        return f"{settings.shared_portal_url}{normalized}"
    if not settings.base_path:
        return normalized
    if normalized == settings.base_path or normalized.startswith(f"{settings.base_path}/"):
        return normalized
    if _is_shared_portal_path(normalized):
        return normalized
    return f"{settings.base_path}{normalized}"


def _current_public_path(request: Request) -> str:
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{_app_path(request.url.path)}{query}"


def _redirect(path: str, **query: str) -> RedirectResponse:
    parts = urlsplit(path)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in query.items():
        if value is None:
            continue
        params[key] = str(value)
    target_path = _app_path(parts.path)
    target = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            target_path,
            urlencode(params, doseq=True),
            parts.fragment,
        )
    )
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def _safe_next_path(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return _app_path("/")
    return raw


def _redirect_back_or(default_path: str, next_path: str | None = None, **query: str) -> RedirectResponse:
    target = _safe_next_path(next_path) if next_path else default_path
    return _redirect(target, **query)


def _mask_hint(raw: str) -> str:
    if len(raw) < 8:
        return "********"
    return f"{raw[:4]}...{raw[-4:]}"


templates.env.globals["app_path"] = _app_path
templates.env.globals["shared_path"] = _shared_path
templates.env.globals["current_public_path"] = _current_public_path
templates.env.globals["app_base_path"] = settings.base_path


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _workspace_payload(
    request: Request,
    db: Session,
    user: User,
    *,
    job_limit: int = 20,
    session_limit: int = 20,
) -> Dict[str, object]:
    provider_specs = _provider_specs_for_user(db, user.id)
    provider_list = list(provider_specs.keys())
    custom_providers = _list_custom_providers(db, user.id)

    creds = db.execute(select(ApiCredential).where(ApiCredential.user_id == user.id)).scalars().all()
    cred_map = {c.provider: c for c in creds}

    jobs = (
        db.execute(
            select(GenerationJob)
            .where(GenerationJob.user_id == user.id)
            .order_by(GenerationJob.created_at.desc())
            .limit(max(1, int(job_limit)))
        )
        .scalars()
        .all()
    )
    idea_sessions = (
        db.execute(
            select(IdeaCopilotSession)
            .where(IdeaCopilotSession.user_id == user.id)
            .order_by(IdeaCopilotSession.updated_at.desc())
            .limit(max(1, int(session_limit)))
        )
        .scalars()
        .all()
    )

    return {
        "request": request,
        "user": user,
        "jobs": jobs,
        "idea_sessions": idea_sessions,
        "cred_map": cred_map,
        "providers": provider_list,
        "provider_specs": provider_specs,
        "custom_providers": custom_providers,
        "default_provider": settings.default_provider if settings.default_provider in provider_specs else (provider_list[0] if provider_list else ""),
        "message": request.query_params.get("message", ""),
        "error": request.query_params.get("error", ""),
    }


def _tail_text(path: Path, max_chars: int = 12000) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
        return ANSI_ESCAPE_RE.sub("", text)
    except Exception:
        return ""


def _resolve_run_dir(run_id: str) -> Path:
    primary = RUNS_DIR / run_id
    if primary.exists():
        return primary
    legacy = BASE_DIR / "runs" / run_id
    if legacy.exists():
        return legacy
    return primary


def _memory_index_candidates(run_id: str = "") -> List[Path]:
    configured_root = os.getenv("VECTOR_DB_PATH", "").strip()
    roots: List[Path] = []
    if configured_root:
        roots.append(Path(configured_root).expanduser())
    roots.append(BASE_DIR.parent / "vector_db")

    candidates: List[Path] = []
    for root in roots:
        if run_id:
            candidates.append((root / "memory" / f"run_{run_id}" / "memory_index.json").resolve())
        candidates.append((root / "memory" / "memory_index.json").resolve())
        candidates.append((root / "memory_index.json").resolve())
    return candidates


def _load_memory_index(run_id: str = "") -> tuple[Dict, str]:
    for path in _memory_index_candidates(run_id):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return (data if isinstance(data, dict) else {}), str(path)
        except Exception:
            continue
    fallback = _memory_index_candidates(run_id)[0] if _memory_index_candidates(run_id) else Path("memory_index.json")
    return {}, str(fallback)


def _compact_preview(text: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def _build_memory_preview(index: Dict, index_path: str) -> Dict[str, object]:
    groups: List[Dict[str, object]] = []
    labels = {
        "outlines": "Outlines",
        "texts": "Texts",
        "characters": "Characters",
        "world_settings": "World",
        "plot_points": "Plot Points",
        "fact_cards": "Fact Cards",
    }
    for bucket in MEMORY_COUNT_KEYS:
        entries = list(index.get(bucket) or []) if isinstance(index, dict) else []
        latest: List[Dict[str, str]] = []
        for item in reversed(entries[-4:]):
            if not isinstance(item, dict):
                continue
            latest.append(
                {
                    "topic": str(item.get("topic") or "").strip(),
                    "preview": _compact_preview(str(item.get("content") or "").strip(), 220),
                    "timestamp": str(item.get("timestamp") or "").strip(),
                }
            )
        groups.append(
            {
                "slug": bucket,
                "label": labels.get(bucket, bucket.replace("_", " ").title()),
                "count": len(entries),
                "entries": latest,
            }
        )
    return {"groups": groups, "index_path": index_path}


def _list_custom_providers(db: Session, user_id: int) -> List[ProviderConfig]:
    return (
        db.execute(
            select(ProviderConfig)
            .where(ProviderConfig.user_id == user_id)
            .order_by(ProviderConfig.slug.asc())
        )
        .scalars()
        .all()
    )


def _custom_provider_specs_for_user(db: Session, user_id: int) -> Dict[str, ProviderSpec]:
    specs: Dict[str, ProviderSpec] = {}
    for row in _list_custom_providers(db, user_id):
        slug = normalize_slug(row.slug)
        if not is_valid_slug(slug):
            continue
        base_url = (row.base_url or "").strip()
        model = (row.model or "").strip()
        if not base_url or not model:
            continue
        specs[slug] = ProviderSpec(
            slug=slug,
            label=(row.label or "").strip() or slug.upper(),
            base_url=base_url,
            model=model,
            wire_api=normalize_wire_api(row.wire_api),
        )
    return specs


def _provider_specs_for_user(db: Session, user_id: int) -> Dict[str, ProviderSpec]:
    base_specs = get_provider_specs(settings)
    custom_specs = _custom_provider_specs_for_user(db, user_id)
    return merge_provider_specs(base_specs, custom_specs.values(), allow_override=False)


def _provider_api_key(db: Session, user_id: int, provider: str) -> str:
    row = db.execute(
        select(ApiCredential).where(
            ApiCredential.user_id == user_id,
            ApiCredential.provider == provider,
        )
    ).scalar_one_or_none()
    if not row:
        raise ValueError("provider.api_key_missing")
    try:
        return decrypt_api_key(row.encrypted_key)
    except Exception as exc:
        raise ValueError("provider.api_key_decrypt_failed") from exc


def _create_generation_job(db: Session, user_id: int, provider: str, idea: str) -> GenerationJob:
    job = GenerationJob(
        user_id=user_id,
        provider=provider,
        idea=idea,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _start_generation_worker(job_id: int) -> None:
    try:
        start_generation_job_process(job_id)
    except Exception as exc:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            job = db.get(GenerationJob, job_id)
            if job and job.status == "queued":
                job.status = "failed"
                job.error_message = f"[system] failed to start detached job launcher: {exc}"
                job.finished_at = now
                job.updated_at = now
                db.commit()
        print(f"[launcher] failed to start job_id={job_id}: {exc}")


def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _default_progress_snapshot() -> Dict:
    return {
        "phase": "running",
        "phase_label": "运行中",
        "phase_note": "",
        "elapsed_seconds": 0,
        "current_chapter": 0,
        "planned_total": 0,
        "chapter_words": 0,
        "total_words": 0,
        "percent": 0,
        "last_log_at": "",
        "idle_seconds": -1,
        "stalled": False,
        "stall_reason": "",
        "memory_counts": {
            "texts": 0,
            "outlines": 0,
            "characters": 0,
            "world_settings": 0,
            "plot_points": 0,
            "fact_cards": 0,
        },
    }


def _parse_progress_log(progress_log_text: str) -> Dict:
    snapshot = {
        "current_chapter": 0,
        "planned_total": 0,
        "chapter_words": 0,
        "total_words": 0,
        "phase_note": "",
        "memory_counts": {k: 0 for k in MEMORY_COUNT_KEYS},
    }
    if not progress_log_text:
        return snapshot

    for raw in progress_log_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("chapter="):
            try:
                parts = dict(
                    kv.strip().split("=", 1)
                    for kv in line.split(",")
                    if "=" in kv
                )
                snapshot["current_chapter"] = int(parts.get("chapter", snapshot["current_chapter"]))
                snapshot["planned_total"] = int(parts.get("planned_total", snapshot["planned_total"]))
                snapshot["chapter_words"] = int(parts.get("words", snapshot["chapter_words"]))
            except Exception:
                pass
        elif line.startswith("total_words="):
            try:
                snapshot["total_words"] = int(line.split("=", 1)[1].strip())
            except Exception:
                pass
        elif line.startswith("[event]"):
            try:
                parts = [seg.strip() for seg in line.split("|")]
                if len(parts) < 2:
                    continue

                event_name = parts[1]
                detail_parts: List[str] = []
                chapter_no = 0

                for seg in parts[2:]:
                    if seg.startswith("chapter "):
                        m_ch = re.search(r"chapter\s+(\d+)", seg)
                        if m_ch:
                            chapter_no = int(m_ch.group(1))
                    elif seg:
                        detail_parts.append(seg)

                detail = " | ".join(detail_parts)
                if chapter_no > 0:
                    snapshot["current_chapter"] = max(snapshot["current_chapter"], chapter_no)

                if event_name == "chapter_outline_ready" and snapshot["planned_total"] <= 0:
                    m_plan = re.search(r"count\s*=\s*(\d+)", detail)
                    if m_plan:
                        snapshot["planned_total"] = int(m_plan.group(1))

                if event_name == "memory_snapshot":
                    detail_map = {
                        k.strip(): v.strip()
                        for k, v in (
                            item.split("=", 1)
                            for item in detail.split(",")
                            if "=" in item
                        )
                    }
                    for key in MEMORY_COUNT_KEYS:
                        if key in detail_map:
                            try:
                                snapshot["memory_counts"][key] = int(detail_map[key])
                            except Exception:
                                pass

                label = EVENT_LABELS.get(event_name, event_name.replace("_", " "))
                snapshot["phase_note"] = f"{label}: {detail}" if detail else label
            except Exception:
                pass
    return snapshot


def _read_status_file(run_dir: Optional[Path]) -> Dict:
    if not run_dir:
        return {}
    path = run_dir / "status.json"
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _infer_phase(worker_log_text: str) -> str:
    if not worker_log_text:
        return "waiting_worker"
    lines = [ln.strip() for ln in worker_log_text.splitlines() if ln.strip()]
    if not lines:
        return "waiting_worker"
    checks = [
        ("Traceback", "error"),
        ("[system] worker started", "worker_started"),
        ("[IdeaAnalyzer]", "idea_analyzing"),
        ("[Analyzer]", "task_analyzing"),
        ("[Organizer]", "planning"),
        ("[Outline]", "outline_building"),
        ("[写作Agent]", "writing"),
        ("[Memory]", "memory_storing"),
        ("[TurningPoint]", "turning_point"),
        ("[Consistency]", "consistency_check"),
        ("[RealtimeEditor]", "editing"),
        ("[Reward]", "reward_calc"),
        ("[Executor] 已完成计划章节数", "finishing"),
    ]
    for line in reversed(lines[-80:]):
        for marker, phase in checks:
            if marker in line:
                return phase
    return "running"


def _infer_action_from_worker_log(worker_log_text: str) -> str:
    if not worker_log_text:
        return ""
    lines = [ln.strip() for ln in worker_log_text.splitlines() if ln.strip()]
    if not lines:
        return ""

    noise_prefixes = (
        "Loading weights:",
        "Key",
        "|",
        "-",
        "[system] worker started",
    )
    for line in reversed(lines[-120:]):
        if not line:
            continue
        if any(line.startswith(p) for p in noise_prefixes):
            continue
        if "BertModel LOAD REPORT" in line:
            continue
        if line.startswith("UNEXPECTED") or line.startswith("[3m"):
            continue
        return line[:180]
    return ""


def _phase_label(phase: str) -> str:
    if phase.startswith("agent_") and phase.endswith("_done"):
        return "Agent step done"
    if phase.startswith("agent_"):
        return "Agent running"
    mapping = {
        "queued": "Queued",
        "running": "Running",
        "succeeded": "Succeeded",
        "failed": "Failed",
        "canceled": "Canceled",
        "waiting_worker": "Waiting worker start",
        "worker_started": "Worker started",
        "idea_analyzing": "Analyzing idea",
        "task_analyzing": "Analyzing task",
        "planning": "Planning",
        "outline_building": "Building outline",
        "writing": "Writing chapter",
        "memory_storing": "Storing memory",
        "turning_point": "Checking turning points",
        "consistency_check": "Consistency check",
        "editing": "Realtime editing",
        "reward_calc": "Calculating reward",
        "finishing": "Finalizing",
        "init": "Initializing",
        "idea_analyzed": "Idea analyzed",
        "planning_done": "Planning done",
        "outline_global_done": "Global outline done",
        "outline_chapters_done": "Chapter outlines done",
        "chapter_start": "Chapter started",
        "chapter_done": "Chapter done",
        "realtime_edit": "Realtime edit",
        "finalizing": "Final output",
        "error": "Error",
    }
    return mapping.get(phase, "Running")


def _build_progress_snapshot(job: GenerationJob, run_dir: Optional[Path], worker_log_text: str, progress_log_text: str) -> Dict:
    now = datetime.now(timezone.utc)
    snapshot = _default_progress_snapshot()
    created_at = _to_utc(job.created_at)
    finished_at = _to_utc(job.finished_at)
    updated_at = _to_utc(job.updated_at)

    terminal = job.status in {"succeeded", "failed", "canceled"}
    end_ref = finished_at or (updated_at if terminal else now)

    elapsed_seconds = 0
    if created_at:
        try:
            elapsed_seconds = max(0, int((end_ref - created_at).total_seconds()))
        except Exception:
            elapsed_seconds = 0

    parsed = _parse_progress_log(progress_log_text)
    current_chapter = parsed["current_chapter"]
    planned_total = parsed["planned_total"]
    chapter_words = parsed["chapter_words"]
    total_words = parsed["total_words"]

    status_state = _read_status_file(run_dir)
    if status_state:
        current_chapter = int(status_state.get("chapter_no") or current_chapter or 0)
        planned_total = int(status_state.get("planned_total") or planned_total or 0)
        chapter_words = int(status_state.get("chapter_words") or chapter_words or 0)
        total_words = int(status_state.get("total_words") or total_words or 0)

    percent = 0
    if planned_total > 0 and current_chapter > 0:
        percent = int(min(100, max(0, (current_chapter / planned_total) * 100)))

    last_log_at = ""
    idle_seconds: Optional[int] = None
    if run_dir:
        worker_log = run_dir / "worker.log"
        if worker_log.exists():
            try:
                mtime = datetime.fromtimestamp(worker_log.stat().st_mtime, tz=timezone.utc)
                last_log_at = mtime.isoformat()
                anchor = end_ref if terminal else now
                idle_seconds = max(0, int((anchor - mtime).total_seconds()))
            except Exception:
                pass

    phase = job.status if terminal else str(status_state.get("stage") or _infer_phase(worker_log_text))
    phase_label = _phase_label(phase)
    phase_note = str(
        status_state.get("message")
        or parsed.get("phase_note")
        or _infer_action_from_worker_log(worker_log_text)
        or ""
    )
    parsed_memory_counts = parsed.get("memory_counts") or {}
    status_memory_counts = status_state.get("memory_counts") or {}
    memory_counts: Dict[str, int] = {}
    for key in MEMORY_COUNT_KEYS:
        raw_val = status_memory_counts.get(key, parsed_memory_counts.get(key, 0))
        try:
            memory_counts[key] = int(raw_val or 0)
        except Exception:
            memory_counts[key] = 0

    stalled = False
    stall_reason = ""
    if job.status == "running":
        if not worker_log_text and elapsed_seconds > 20:
            stalled = True
            stall_reason = "No worker logs yet after 20s; worker may not have started correctly."
        elif idle_seconds is not None and idle_seconds > 90:
            stalled = True
            stall_reason = f"No new logs for {idle_seconds}s; the job may be stalled."

        if status_state and status_state.get("updated_at"):
            try:
                ts = str(status_state.get("updated_at")).replace("Z", "+00:00")
                sdt = datetime.fromisoformat(ts)
                if sdt.tzinfo is None:
                    sdt = sdt.replace(tzinfo=timezone.utc)
                idle_status = max(0, int((now - sdt.astimezone(timezone.utc)).total_seconds()))
                if idle_status > 90:
                    stalled = True
                    stall_reason = f"Status heartbeat not updated for {idle_status}s; the job may be stalled."
            except Exception:
                pass

    snapshot.update(
        {
            "phase": phase,
            "phase_label": phase_label,
            "phase_note": phase_note,
            "elapsed_seconds": elapsed_seconds,
            "current_chapter": current_chapter,
            "planned_total": planned_total,
            "chapter_words": chapter_words,
            "total_words": total_words,
            "percent": percent,
            "last_log_at": last_log_at,
            "idle_seconds": idle_seconds if idle_seconds is not None else -1,
            "stalled": stalled,
            "stall_reason": stall_reason,
            "memory_counts": memory_counts if isinstance(memory_counts, dict) else {},
        }
    )
    return snapshot


def _default_progress_snapshot(locale: str) -> Dict:
    return {
        "phase": "running",
        "phase_label": translate("phase.running", locale),
        "phase_note": "",
        "elapsed_seconds": 0,
        "current_chapter": 0,
        "planned_total": 0,
        "chapter_words": 0,
        "total_words": 0,
        "percent": 0,
        "last_log_at": "",
        "idle_seconds": -1,
        "stalled": False,
        "stall_reason": "",
        "memory_counts": {
            "texts": 0,
            "outlines": 0,
            "characters": 0,
            "world_settings": 0,
            "plot_points": 0,
            "fact_cards": 0,
        },
    }


def _parse_progress_log(progress_log_text: str, locale: str) -> Dict:
    snapshot = {
        "current_chapter": 0,
        "planned_total": 0,
        "chapter_words": 0,
        "total_words": 0,
        "phase_note": "",
        "memory_counts": {k: 0 for k in MEMORY_COUNT_KEYS},
    }
    if not progress_log_text:
        return snapshot

    for raw in progress_log_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("chapter="):
            try:
                parts = dict(
                    kv.strip().split("=", 1)
                    for kv in line.split(",")
                    if "=" in kv
                )
                snapshot["current_chapter"] = int(parts.get("chapter", snapshot["current_chapter"]))
                snapshot["planned_total"] = int(parts.get("planned_total", snapshot["planned_total"]))
                snapshot["chapter_words"] = int(parts.get("words", snapshot["chapter_words"]))
            except Exception:
                pass
        elif line.startswith("total_words="):
            try:
                snapshot["total_words"] = int(line.split("=", 1)[1].strip())
            except Exception:
                pass
        elif line.startswith("[event]"):
            try:
                parts = [seg.strip() for seg in line.split("|")]
                if len(parts) < 2:
                    continue

                event_name = parts[1]
                detail_parts: List[str] = []
                chapter_no = 0

                for seg in parts[2:]:
                    if seg.startswith("chapter "):
                        m_ch = re.search(r"chapter\s+(\d+)", seg)
                        if m_ch:
                            chapter_no = int(m_ch.group(1))
                    elif seg:
                        detail_parts.append(seg)

                detail = " | ".join(detail_parts)
                if chapter_no > 0:
                    snapshot["current_chapter"] = max(snapshot["current_chapter"], chapter_no)

                if event_name == "chapter_outline_ready" and snapshot["planned_total"] <= 0:
                    m_plan = re.search(r"count\s*=\s*(\d+)", detail)
                    if m_plan:
                        snapshot["planned_total"] = int(m_plan.group(1))

                if event_name == "memory_snapshot":
                    detail_map = {
                        k.strip(): v.strip()
                        for k, v in (
                            item.split("=", 1)
                            for item in detail.split(",")
                            if "=" in item
                        )
                    }
                    for key in MEMORY_COUNT_KEYS:
                        if key in detail_map:
                            try:
                                snapshot["memory_counts"][key] = int(detail_map[key])
                            except Exception:
                                pass

                label_key = EVENT_LABELS.get(event_name)
                label = translate(label_key, locale) if label_key else event_name.replace("_", " ")
                snapshot["phase_note"] = f"{label}: {detail}" if detail else label
            except Exception:
                pass
    return snapshot


def _phase_label(phase: str, locale: str) -> str:
    if phase.startswith("agent_") and phase.endswith("_done"):
        return translate("phase.agent_step_done", locale)
    if phase.startswith("agent_"):
        return translate("phase.agent_running", locale)
    label = translate(f"phase.{phase}", locale)
    if label == f"phase.{phase}":
        return translate("phase.running", locale)
    return label


def _build_progress_snapshot(
    job: GenerationJob,
    run_dir: Optional[Path],
    worker_log_text: str,
    progress_log_text: str,
    locale: str,
) -> Dict:
    now = datetime.now(timezone.utc)
    snapshot = _default_progress_snapshot(locale)
    created_at = _to_utc(job.created_at)
    finished_at = _to_utc(job.finished_at)
    updated_at = _to_utc(job.updated_at)

    terminal = job.status in {"succeeded", "failed", "canceled"}
    end_ref = finished_at or (updated_at if terminal else now)

    elapsed_seconds = 0
    if created_at:
        try:
            elapsed_seconds = max(0, int((end_ref - created_at).total_seconds()))
        except Exception:
            elapsed_seconds = 0

    parsed = _parse_progress_log(progress_log_text, locale)
    current_chapter = parsed["current_chapter"]
    planned_total = parsed["planned_total"]
    chapter_words = parsed["chapter_words"]
    total_words = parsed["total_words"]

    status_state = _read_status_file(run_dir)
    if status_state:
        current_chapter = int(status_state.get("chapter_no") or current_chapter or 0)
        planned_total = int(status_state.get("planned_total") or planned_total or 0)
        chapter_words = int(status_state.get("chapter_words") or chapter_words or 0)
        total_words = int(status_state.get("total_words") or total_words or 0)

    percent = 0
    if planned_total > 0 and current_chapter > 0:
        percent = int(min(100, max(0, (current_chapter / planned_total) * 100)))

    last_log_at = ""
    idle_seconds: Optional[int] = None
    if run_dir:
        worker_log = run_dir / "worker.log"
        if worker_log.exists():
            try:
                mtime = datetime.fromtimestamp(worker_log.stat().st_mtime, tz=timezone.utc)
                last_log_at = mtime.isoformat()
                anchor = end_ref if terminal else now
                idle_seconds = max(0, int((anchor - mtime).total_seconds()))
            except Exception:
                pass

    phase = job.status if terminal else str(status_state.get("stage") or _infer_phase(worker_log_text))
    phase_label = _phase_label(phase, locale)
    phase_note = str(
        status_state.get("message")
        or parsed.get("phase_note")
        or _infer_action_from_worker_log(worker_log_text)
        or ""
    )
    parsed_memory_counts = parsed.get("memory_counts") or {}
    status_memory_counts = status_state.get("memory_counts") or {}
    memory_counts: Dict[str, int] = {}
    for key in MEMORY_COUNT_KEYS:
        raw_val = status_memory_counts.get(key, parsed_memory_counts.get(key, 0))
        try:
            memory_counts[key] = int(raw_val or 0)
        except Exception:
            memory_counts[key] = 0

    stalled = False
    stall_reason = ""
    if job.status == "running":
        if not worker_log_text and elapsed_seconds > 20:
            stalled = True
            stall_reason = translate("job.stall.no_worker_logs", locale)
        elif idle_seconds is not None and idle_seconds > 90:
            stalled = True
            stall_reason = translate("job.stall.no_new_logs", locale, seconds=idle_seconds)

        if status_state and status_state.get("updated_at"):
            try:
                ts = str(status_state.get("updated_at")).replace("Z", "+00:00")
                sdt = datetime.fromisoformat(ts)
                if sdt.tzinfo is None:
                    sdt = sdt.replace(tzinfo=timezone.utc)
                idle_status = max(0, int((now - sdt.astimezone(timezone.utc)).total_seconds()))
                if idle_status > 90:
                    stalled = True
                    stall_reason = translate("job.stall.status_heartbeat", locale, seconds=idle_status)
            except Exception:
                pass

    snapshot.update(
        {
            "phase": phase,
            "phase_label": phase_label,
            "phase_note": phase_note,
            "elapsed_seconds": elapsed_seconds,
            "current_chapter": current_chapter,
            "planned_total": planned_total,
            "chapter_words": chapter_words,
            "total_words": total_words,
            "percent": percent,
            "last_log_at": last_log_at,
            "idle_seconds": idle_seconds if idle_seconds is not None else -1,
            "stalled": stalled,
            "stall_reason": stall_reason,
            "memory_counts": memory_counts if isinstance(memory_counts, dict) else {},
        }
    )
    return snapshot


def _load_chapter_outputs(run_dir: Path) -> List[Dict]:
    """
    Load latest finalized chapter files from runs/<run_id>/chapters.
    Keep only the highest iteration per chapter.
    """
    chapter_dir = run_dir / "chapters"
    if not chapter_dir.exists():
        return []

    pattern = re.compile(r"^chapter_(\d+)_iter_(\d+)_final\.txt$")
    latest_by_chapter: Dict[int, Dict] = {}

    for path in chapter_dir.glob("chapter_*_iter_*_final.txt"):
        m = pattern.match(path.name)
        if not m:
            continue
        chapter_no = int(m.group(1))
        iteration = int(m.group(2))

        prev = latest_by_chapter.get(chapter_no)
        if prev and iteration <= prev["iteration"]:
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = ""

        latest_by_chapter[chapter_no] = {
            "chapter": chapter_no,
            "iteration": iteration,
            "filename": path.name,
            "content": content.strip(),
        }

    return [latest_by_chapter[k] for k in sorted(latest_by_chapter.keys())]


def _latest_chapter_file(run_dir: Path, chapter_no: int) -> Optional[Path]:
    chapter_dir = run_dir / "chapters"
    if not chapter_dir.exists():
        return None
    pattern = re.compile(rf"^chapter_{chapter_no:02d}_iter_(\d+)_final\.txt$")
    best_path: Optional[Path] = None
    best_iter = -1
    for path in chapter_dir.glob(f"chapter_{chapter_no:02d}_iter_*_final.txt"):
        m = pattern.match(path.name)
        if not m:
            continue
        iteration = int(m.group(1))
        if iteration > best_iter:
            best_iter = iteration
            best_path = path
    return best_path


def _latest_chapter_files(run_dir: Path) -> List[Path]:
    chapter_dir = run_dir / "chapters"
    if not chapter_dir.exists():
        return []
    pattern = re.compile(r"^chapter_(\d+)_iter_(\d+)_final\.txt$")
    latest: Dict[int, Dict[str, object]] = {}
    for path in chapter_dir.glob("chapter_*_iter_*_final.txt"):
        m = pattern.match(path.name)
        if not m:
            continue
        chapter_no = int(m.group(1))
        iteration = int(m.group(2))
        prev = latest.get(chapter_no)
        if prev and iteration <= int(prev["iteration"]):
            continue
        latest[chapter_no] = {"iteration": iteration, "path": path}
    return [latest[k]["path"] for k in sorted(latest.keys()) if isinstance(latest[k]["path"], Path)]


@app.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    if _current_user(request, db):
        return _redirect("/dashboard")
    return _redirect("/select-mode")


@app.get("/select-mode")
@app.get("/mode-a")
@app.get("/mode-b")
def shared_portal_entry(request: Request):
    return RedirectResponse(_shared_portal_url(request, request.url.path), status_code=status.HTTP_303_SEE_OTHER)


@app.get("/register")
def register_page(request: Request, db: Session = Depends(get_db)):
    if _current_user(request, db):
        return _redirect("/dashboard")
    return _redirect("/select-mode")


@app.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    _ = (request, email, password, confirm_password, db)
    return _redirect("/select-mode")


@app.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if _current_user(request, db):
        return _redirect("/dashboard")
    return _redirect("/select-mode")


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    _ = (request, email, password, db)
    return _redirect("/select-mode")


@app.post("/logout")
def logout(request: Request):
    return _redirect("/logout")


@app.post("/language")
def change_language(request: Request, locale: str = Form(...), next: str = Form("/")):
    set_locale(request, locale)
    return _redirect(_safe_next_path(next))


@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("dashboard.html", _workspace_payload(request, db, user, job_limit=8, session_limit=8))


@app.get("/jobs")
def jobs_page(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("jobs.html", _workspace_payload(request, db, user, job_limit=60, session_limit=8))


@app.get("/providers")
def providers_page(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("providers.html", _workspace_payload(request, db, user, job_limit=8, session_limit=8))


@app.get("/sessions")
def sessions_page(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("sessions.html", _workspace_payload(request, db, user, job_limit=12, session_limit=60))


@app.post("/api-keys")
def save_api_key(
    request: Request,
    provider: str = Form(...),
    api_key: str = Form(...),
    next: str = Form("/providers"),
    db: Session = Depends(get_db),
):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    provider = provider.strip().lower()
    api_key = api_key.strip()
    provider_specs = _provider_specs_for_user(db, user.id)

    if provider not in provider_specs:
        return _redirect_back_or("/providers", next, error="notice.provider.unsupported")
    if len(api_key) < 12:
        return _redirect_back_or("/providers", next, error="notice.provider.key_short")

    cred = db.execute(
        select(ApiCredential).where(
            ApiCredential.user_id == user.id,
            ApiCredential.provider == provider,
        )
    ).scalar_one_or_none()

    encrypted = encrypt_api_key(api_key)
    if cred:
        cred.encrypted_key = encrypted
        cred.key_hint = _mask_hint(api_key)
    else:
        cred = ApiCredential(
            user_id=user.id,
            provider=provider,
            encrypted_key=encrypted,
            key_hint=_mask_hint(api_key),
        )
        db.add(cred)

    db.commit()
    return _redirect_back_or("/providers", next, message="notice.provider.key_saved")


@app.post("/providers")
def save_provider_config(
    request: Request,
    slug: str = Form(...),
    label: str = Form(""),
    base_url: str = Form(...),
    model: str = Form(...),
    wire_api: str = Form("chat"),
    next: str = Form("/providers"),
    db: Session = Depends(get_db),
):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    norm_slug = normalize_slug(slug)
    norm_label = (label or "").strip()
    norm_base_url = (base_url or "").strip()
    norm_model = (model or "").strip()
    norm_wire_api = normalize_wire_api(wire_api)

    if not is_valid_slug(norm_slug):
        return _redirect_back_or("/providers", next, error="notice.provider.slug_invalid")
    if not norm_base_url:
        return _redirect_back_or("/providers", next, error="notice.provider.base_url_empty")
    if not norm_model:
        return _redirect_back_or("/providers", next, error="notice.provider.model_empty")
    if not (norm_base_url.startswith("http://") or norm_base_url.startswith("https://")):
        return _redirect_back_or("/providers", next, error="notice.provider.base_url_invalid")

    # Built-in and env-defined providers are reserved.
    base_specs = get_provider_specs(settings)
    if norm_slug in base_specs:
        return _redirect_back_or("/providers", next, error="notice.provider.slug_reserved")

    row = db.execute(
        select(ProviderConfig).where(
            ProviderConfig.user_id == user.id,
            ProviderConfig.slug == norm_slug,
        )
    ).scalar_one_or_none()

    if row:
        row.label = norm_label
        row.base_url = norm_base_url
        row.model = norm_model
        row.wire_api = norm_wire_api
    else:
        row = ProviderConfig(
            user_id=user.id,
            slug=norm_slug,
            label=norm_label,
            base_url=norm_base_url,
            model=norm_model,
            wire_api=norm_wire_api,
        )
        db.add(row)

    db.commit()
    return _redirect_back_or("/providers", next, message="notice.provider.saved")


@app.post("/providers/{slug}/delete")
def delete_provider_config(slug: str, request: Request, next: str = Form("/providers"), db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    norm_slug = normalize_slug(slug)
    row = db.execute(
        select(ProviderConfig).where(
            ProviderConfig.user_id == user.id,
            ProviderConfig.slug == norm_slug,
        )
    ).scalar_one_or_none()
    if not row:
        return _redirect_back_or("/providers", next, error="notice.provider.not_found")

    # Remove key for this custom provider as well to avoid stale entries.
    cred = db.execute(
        select(ApiCredential).where(
            ApiCredential.user_id == user.id,
            ApiCredential.provider == norm_slug,
        )
    ).scalar_one_or_none()
    if cred:
        db.delete(cred)

    db.delete(row)
    db.commit()
    return _redirect_back_or("/providers", next, message="notice.provider.deleted")


@app.post("/idea-copilot/start")
def start_idea_copilot(
    request: Request,
    idea: str = Form(...),
    provider: str = Form(...),
    next: str = Form("/sessions"),
    db: Session = Depends(get_db),
):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    idea = idea.strip()
    provider = provider.strip().lower()
    if not idea:
        return _redirect_back_or("/sessions", next, error="notice.idea.empty")

    provider_specs = _provider_specs_for_user(db, user.id)
    spec = provider_specs.get(provider)
    if not spec:
        return _redirect_back_or("/sessions", next, error="notice.provider.unsupported")

    try:
        api_key = _provider_api_key(db, user.id, provider)
    except ValueError as exc:
        return _redirect_back_or("/sessions", next, error=str(exc))

    session = IdeaCopilotSession(
        user_id=user.id,
        provider=provider,
        status="active",
        original_idea=idea,
        refined_idea=idea,
        conversation_json=dump_state({"version": 1, "messages": [], "refined_idea": idea, "round": 0}),
        round_count=0,
        readiness_score=0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    state = load_state(session.conversation_json)
    agent = IdeaCopilotAgent(spec, api_key)
    try:
        turn = agent.generate_turn(
            original_idea=idea,
            state=state,
            latest_user_reply="",
        )
    except Exception as exc:
        turn = {
            "role": "assistant",
            "analysis": f"首轮协同提问失败：{exc}",
            "refined_idea": idea,
            "questions": ["请先补充：你最想写的核心冲突是什么？"],
            "readiness": 10,
            "ready_hint": "请补充关键信息后继续提问。",
        }

    state = append_assistant_turn(state, turn)
    session.conversation_json = dump_state(state)
    session.refined_idea = str(state.get("refined_idea") or idea)
    session.round_count = int(state.get("round", 0) or 0)
    session.readiness_score = int(turn.get("readiness", 0) or 0)
    db.commit()
    return _redirect(f"/idea-copilot/{session.id}")


@app.get("/idea-copilot/{session_id}")
def idea_copilot_detail(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea session not found")

    state = load_state(session.conversation_json)
    latest_turn = latest_assistant_turn(state)
    messages = list(state.get("messages") or [])
    provider_specs = _provider_specs_for_user(db, user.id)

    return templates.TemplateResponse(
        "idea_copilot.html",
        {
            "request": request,
            "user": user,
            "session_data": session,
            "session_state": state,
            "messages": messages,
            "latest_turn": latest_turn,
            "provider_label": (provider_specs.get(session.provider).label if provider_specs.get(session.provider) else session.provider.upper()),
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@app.post("/idea-copilot/{session_id}/reply")
def idea_copilot_reply(
    session_id: int,
    request: Request,
    reply: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea session not found")
    if session.status != "active":
        return _redirect(f"/idea-copilot/{session_id}", error="notice.copilot.session_inactive")

    answer = reply.strip()
    if not answer:
        return _redirect(f"/idea-copilot/{session_id}", error="notice.copilot.reply_empty")

    provider_specs = _provider_specs_for_user(db, user.id)
    spec = provider_specs.get(session.provider)
    if not spec:
        return _redirect(f"/idea-copilot/{session_id}", error="notice.copilot.provider_missing")
    try:
        api_key = _provider_api_key(db, user.id, session.provider)
    except ValueError as exc:
        return _redirect(f"/idea-copilot/{session_id}", error=str(exc))

    state = load_state(session.conversation_json)
    state = append_user_reply(state, answer)
    agent = IdeaCopilotAgent(spec, api_key)
    try:
        turn = agent.generate_turn(
            original_idea=session.original_idea,
            state=state,
            latest_user_reply=answer,
        )
    except Exception as exc:
        return _redirect(f"/idea-copilot/{session_id}", error=str(exc))

    state = append_assistant_turn(state, turn)
    session.conversation_json = dump_state(state)
    session.refined_idea = str(state.get("refined_idea") or session.refined_idea or session.original_idea)
    session.round_count = int(state.get("round", 0) or 0)
    session.readiness_score = int(turn.get("readiness", 0) or 0)
    db.commit()
    return _redirect(f"/idea-copilot/{session_id}", message="notice.copilot.updated")


@app.post("/idea-copilot/{session_id}/confirm")
def idea_copilot_confirm(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea session not found")
    if session.status != "active":
        if session.final_job_id:
            return _redirect(f"/jobs/{session.final_job_id}")
        return _redirect(f"/idea-copilot/{session_id}", error="notice.copilot.session_inactive")

    state = load_state(session.conversation_json)
    final_idea = build_generation_idea(session.original_idea, state)
    if not final_idea.strip():
        return _redirect(f"/idea-copilot/{session_id}", error="notice.copilot.final_idea_empty")

    job = _create_generation_job(db, user.id, session.provider, final_idea)
    session.status = "confirmed"
    session.final_job_id = job.id
    session.refined_idea = str(state.get("refined_idea") or session.refined_idea or session.original_idea)
    session.round_count = int(state.get("round", 0) or 0)
    session.finished_at = datetime.now(timezone.utc)
    db.commit()

    _start_generation_worker(job.id)
    return _redirect(f"/jobs/{job.id}")


@app.post("/idea-copilot/{session_id}/cancel")
def idea_copilot_cancel(session_id: int, request: Request, next: str = Form("/sessions"), db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea session not found")

    if session.status == "active":
        session.status = "canceled"
        session.finished_at = datetime.now(timezone.utc)
        db.commit()
    return _redirect_back_or("/sessions", next, message="notice.copilot.canceled")


@app.post("/jobs")
def create_job(
    request: Request,
    idea: str = Form(...),
    provider: str = Form(...),
    next: str = Form("/jobs"),
    db: Session = Depends(get_db),
):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    idea = idea.strip()
    provider = provider.strip().lower()
    provider_specs = _provider_specs_for_user(db, user.id)

    if not idea:
        return _redirect_back_or("/jobs", next, error="notice.idea.empty")
    if provider not in provider_specs:
        return _redirect_back_or("/jobs", next, error="notice.provider.unsupported")

    try:
        _provider_api_key(db, user.id, provider)
    except ValueError as exc:
        return _redirect_back_or("/jobs", next, error=str(exc))

    job = _create_generation_job(db, user.id, provider, idea)
    _start_generation_worker(job.id)
    return _redirect(f"/jobs/{job.id}")


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, request: Request, next: str = Form(""), db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if job.status in {"queued", "running"}:
        run_id = (job.run_id or "").strip()
        if run_id:
            run_dir = _resolve_run_dir(run_id)
            try:
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "cancel.flag").write_text("1", encoding="utf-8")
            except Exception:
                pass
        job.status = "canceled"
        prefix = (job.error_message + "\n") if job.error_message else ""
        job.error_message = prefix + "[user] canceled manually."
        now = datetime.now(timezone.utc)
        job.finished_at = now
        job.updated_at = now
        db.commit()
        return _redirect_back_or(f"/jobs/{job.id}", next)

    return _redirect_back_or(f"/jobs/{job.id}", next)


@app.post("/jobs/{job_id}/delete")
def delete_job(job_id: int, request: Request, next: str = Form("/jobs"), db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if job.status in {"queued", "running"}:
        return _redirect_back_or("/jobs", next, error="notice.job.delete_running")

    run_id = (job.run_id or "").strip()
    run_dir = _resolve_run_dir(run_id) if run_id else None

    db.delete(job)
    db.commit()

    # Best-effort cleanup of on-disk artifacts.
    if run_dir and run_dir.exists():
        try:
            shutil.rmtree(run_dir, ignore_errors=True)
        except Exception:
            pass

    return _redirect_back_or("/jobs", next, message="notice.job.deleted")


@app.get("/jobs/{job_id}")
def job_detail(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    locale = get_locale(request)

    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    output_text = ""
    if job.output_path:
        path = Path(job.output_path)
        if path.exists():
            output_text = path.read_text(encoding="utf-8")

    worker_log_text = ""
    progress_log_text = ""
    chapter_outputs: List[Dict] = []
    run_dir: Optional[Path] = None
    if job.run_id:
        run_dir = _resolve_run_dir(job.run_id)
        worker_log_text = _tail_text(run_dir / "worker.log")
        progress_log_text = _tail_text(run_dir / "progress.log")
        chapter_outputs = _load_chapter_outputs(run_dir)
    try:
        progress_snapshot = _build_progress_snapshot(job, run_dir, worker_log_text, progress_log_text, locale)
    except Exception:
        progress_snapshot = _default_progress_snapshot(locale)
    memory_index, memory_index_path = _load_memory_index((job.run_id or "").strip())
    memory_preview = _build_memory_preview(memory_index, memory_index_path)

    return templates.TemplateResponse(
        "job_detail.html",
        {
            "request": request,
            "user": user,
            "job": job,
            "output_text": output_text,
            "worker_log_text": worker_log_text,
            "progress_log_text": progress_log_text,
            "chapter_outputs": chapter_outputs,
            "progress_snapshot": progress_snapshot,
            "memory_preview": memory_preview,
        },
    )


@app.get("/jobs/{job_id}/logs")
def job_logs(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    locale = get_locale(request)

    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    worker_log_text = ""
    progress_log_text = ""
    run_dir: Optional[Path] = None
    if job.run_id:
        run_dir = _resolve_run_dir(job.run_id)
        worker_log_text = _tail_text(run_dir / "worker.log")
        progress_log_text = _tail_text(run_dir / "progress.log")
    try:
        progress_snapshot = _build_progress_snapshot(job, run_dir, worker_log_text, progress_log_text, locale)
    except Exception:
        progress_snapshot = _default_progress_snapshot(locale)

    return JSONResponse(
        {
            "job_id": job.id,
            "status": job.status,
            "run_id": job.run_id,
            "worker_log": worker_log_text,
            "progress_log": progress_log_text,
            "updated_at": job.updated_at.isoformat() if job.updated_at else "",
            "error_message": job.error_message or "",
            "progress_snapshot": progress_snapshot,
        }
    )


@app.get("/jobs/{job_id}/chapters")
def job_chapters(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    chapters: List[Dict] = []
    if job.run_id:
        run_dir = _resolve_run_dir(job.run_id)
        chapters = _load_chapter_outputs(run_dir)

    return JSONResponse(
        {
            "job_id": job.id,
            "status": job.status,
            "run_id": job.run_id,
            "chapter_count": len(chapters),
            "chapters": chapters,
        }
    )


@app.get("/jobs/{job_id}/download/output")
def download_job_output(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    run_id = (job.run_id or "").strip()
    file_name = f"job_{job.id}_{run_id or 'no_run'}_output.txt"

    if job.output_path:
        out_path = Path(job.output_path)
        if out_path.exists() and out_path.is_file():
            return FileResponse(
                str(out_path),
                media_type="text/plain; charset=utf-8",
                filename=file_name,
            )

    if not run_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No output available yet")

    run_dir = _resolve_run_dir(run_id)
    chapters = _load_chapter_outputs(run_dir)
    if not chapters:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No output available yet")

    parts: List[str] = []
    for ch in chapters:
        chapter_no = ch.get("chapter", "?")
        content = (ch.get("content") or "").strip()
        parts.append(f"Chapter {chapter_no}\n\n{content}")
    merged = ("\n\n" + ("=" * 60) + "\n\n").join(parts)

    return PlainTextResponse(
        merged,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@app.get("/jobs/{job_id}/download/chapter/{chapter_no}")
def download_job_chapter(job_id: int, chapter_no: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if chapter_no <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid chapter number")
    if not job.run_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No chapter output available yet")

    run_dir = _resolve_run_dir(job.run_id)
    chapter_path = _latest_chapter_file(run_dir, chapter_no)
    if not chapter_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter output not found")

    return FileResponse(
        str(chapter_path),
        media_type="text/plain; charset=utf-8",
        filename=chapter_path.name,
    )


@app.get("/jobs/{job_id}/download/chapters")
def download_job_chapters(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if not job.run_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No chapter output available yet")

    run_dir = _resolve_run_dir(job.run_id)
    chapter_files = _latest_chapter_files(run_dir)
    if not chapter_files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No chapter output available yet")

    zip_path = run_dir / f"job_{job.id}_chapters_latest.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in chapter_files:
            zf.write(path, arcname=path.name)

    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )
