from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from utils.file_io import atomic_write_text, tail_text
from utils.processes import run_logged_process

from .db import SessionLocal
from .models import ApiCredential, CapabilityPreference, GenerationJob, IdeaCopilotSession, ProviderConfig
from .provider_registry import (
    ProviderSpec,
    get_provider_specs,
    is_valid_slug,
    merge_provider_specs,
    normalize_slug,
    normalize_wire_api,
)
from .security import decrypt_api_key
from capability_registry import default_enabled_capability_slugs, normalize_capability_slugs
from .settings import BASE_DIR, RUNS_DIR, settings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cancel_flag_path(run_id: str) -> Path:
    return RUNS_DIR / run_id / "cancel.flag"


def _is_cancel_requested(run_id: str) -> bool:
    try:
        return _cancel_flag_path(run_id).exists()
    except Exception:
        return False


def _job_status_is_running(db: Session, job_id: int) -> bool:
    # Use a fresh DB session to avoid stale transaction snapshots.
    _ = db  # keep signature stable for existing callers
    with SessionLocal() as s:
        fresh = s.get(GenerationJob, job_id)
        return bool(fresh and fresh.status == "running")


def _custom_provider_specs_for_user(db: Session, user_id: int) -> dict[str, ProviderSpec]:
    rows = (
        db.execute(
            select(ProviderConfig).where(ProviderConfig.user_id == user_id)
        )
        .scalars()
        .all()
    )
    specs: dict[str, ProviderSpec] = {}
    for row in rows:
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


def _enabled_capabilities_for_user(db: Session, user_id: int) -> set[str]:
    rows = (
        db.execute(
            select(CapabilityPreference).where(CapabilityPreference.user_id == user_id)
        )
        .scalars()
        .all()
    )
    enabled = set(default_enabled_capability_slugs())
    for row in rows:
        slug = str(getattr(row, "slug", "") or "").strip().lower()
        if not slug:
            continue
        if getattr(row, "enabled", False):
            enabled.add(slug)
        else:
            enabled.discard(slug)
    return normalize_capability_slugs(enabled)


def _provider_env(
    provider: str,
    api_key: str,
    provider_specs: Optional[dict[str, ProviderSpec]] = None,
    language: Optional[str] = None,
    source_language: Optional[str] = None,
    translation_mode: Optional[str] = None,
    enabled_capabilities: Optional[set[str]] = None,
) -> dict[str, str]:
    provider = provider.lower().strip()
    provider_specs = provider_specs or get_provider_specs(settings)
    spec = provider_specs.get(provider)
    if not spec:
        raise ValueError(_txt(language, f"不支持的提供商: {provider}", f"Unsupported provider: {provider}"))

    env = {
        "LLM_PROVIDER": provider,
        "LLM_API_KEY": api_key,
        "LLM_BASE_URL": spec.base_url,
        "MODEL_NAME": spec.model,
        "WIRE_API": spec.wire_api,
        "RUNS_DIR": str(RUNS_DIR),
        "MAX_ITERATIONS": str(settings.max_iterations),
        "MAX_TOTAL_ITERATIONS": str(settings.max_total_iterations),
        "EXECUTION_MODE": settings.execution_mode,
        "CLAW_MAX_STEPS": str(settings.claw_max_steps),
        "LANGUAGE": (language or settings.ui_language or "en").lower(),
        "SOURCE_LANGUAGE": (source_language or language or settings.ui_language or "en").lower(),
        "TRANSLATION_MODE": translation_mode or "follow_input",
        "FAST_MODE": "1" if settings.fast_mode else "0",
        "FULL_CYCLE_INTERVAL": str(settings.full_cycle_interval),
        "CHAPTERS_PER_ITER": str(settings.chapters_per_iter),
        "MAX_CHAPTER_SUBROUNDS": str(settings.max_chapter_subrounds),
        "EVAL_INTERVAL": str(settings.eval_interval),
        "LLM_TIMEOUT_SECONDS": os.getenv("LLM_TIMEOUT_SECONDS", "0"),
        "LLM_MAX_RETRIES": os.getenv("LLM_MAX_RETRIES", "1"),
        # Web portal workers must not trigger HuggingFace embedding downloads.
        "MEMORY_ONLY_MODE": "1",
        "ENABLE_RAG": "0",
        "ENABLE_STATIC_KB": "0",
        "ENABLE_EVALUATOR": os.getenv("WEB_ENABLE_EVALUATOR", "1"),
        "EMBEDDING_MODEL": "none",
        "DISABLE_EMBEDDING_DOWNLOADS": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        # Force UTF-8 output from worker process on Windows to avoid mojibake.
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        # Force unbuffered stdout/stderr so web tail logs update in near real-time.
        "PYTHONUNBUFFERED": "1",
        "APP_DATABASE_URL": settings.database_url,
        "APP_RUNS_DIR": str(RUNS_DIR),
        "ENABLED_CAPABILITIES": ",".join(sorted(enabled_capabilities or default_enabled_capability_slugs())),
    }

    # Backward-compat env aliases used by legacy config paths.
    env["OPENAI_API_KEY"] = api_key
    env["OPENAI_BASE_URL"] = spec.base_url

    if provider == "deepseek":
        env["DEEPSEEK_API_KEY"] = api_key
        env["DEEPSEEK_BASE_URL"] = spec.base_url
    elif provider == "openai":
        env["OPENAI_API_KEY"] = api_key
        env["OPENAI_BASE_URL"] = spec.base_url
    elif provider == "codex":
        env["CODEX_API_KEY"] = api_key
        env["CODEX_BASE_URL"] = spec.base_url

    return env


def _is_en(language: Optional[str]) -> bool:
    return str(language or "").lower().startswith("en")


def _txt(language: Optional[str], zh: str, en: str) -> str:
    return en if _is_en(language) else zh


def _env_api_key_for_provider(provider: str) -> str:
    slug = normalize_slug(provider)
    names = []
    if slug:
        names.append(f"{slug.upper().replace('-', '_')}_API_KEY")
    if slug == "openai":
        names.append("OPENAI_API_KEY")
    elif slug == "codex":
        names.append("CODEX_API_KEY")
    names.append("LLM_API_KEY")

    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        value = str(os.getenv(name, "") or "").strip()
        lowered = value.lower()
        if not value or lowered.startswith("your-") or lowered.startswith("change-"):
            continue
        return value
    return ""


def _job_language_profile(db: Session, job_id: int) -> tuple[str, str, str]:
    session = db.execute(
        select(IdeaCopilotSession)
        .where(IdeaCopilotSession.final_job_id == job_id)
        .order_by(IdeaCopilotSession.updated_at.desc())
    ).scalar_one_or_none()
    if not session:
        fallback = settings.ui_language if settings.ui_language in {"en", "zh"} else "en"
        return fallback, fallback, "follow_input"

    try:
        state = json.loads(session.conversation_json or "{}")
    except Exception:
        state = {}

    preferred = str(state.get("preferred_language") or settings.ui_language or "en").lower()
    if preferred not in {"en", "zh"}:
        preferred = "en"
    source = str(state.get("source_language") or preferred).lower()
    if source not in {"en", "zh"}:
        source = preferred
    translation_mode = str(state.get("translation_mode") or "follow_input")
    return preferred, source, translation_mode


def _save_job_artifacts(run_id: str, result: dict) -> tuple[str, str]:
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    output_path = run_dir / "output.txt"
    result_json_path = run_dir / "result.json"
    round_results_path = run_dir / "round_results.json"
    metadata_path = run_dir / "metadata.json"
    final_text = result.get("final_text", "")
    language = str(result.get("language") or "en").lower()
    is_en = language.startswith("en")

    header_lines = [
        f"Topic: {result.get('topic', '')}" if is_en else f"主题: {result.get('topic', '')}",
        f"Text type: {result.get('text_type', '')}" if is_en else f"文本类型: {result.get('text_type', '')}",
        f"Length: {result.get('length', 0)} chars" if is_en else f"文本长度: {result.get('length', 0)} 字",
        f"Iterations: {result.get('iterations', 0)}" if is_en else f"迭代次数: {result.get('iterations', 0)}",
        "",
        "=" * 60,
        "Generated text:" if is_en else "生成的文本：",
        "=" * 60,
        "",
        final_text,
    ]
    atomic_write_text(output_path, "\n".join(header_lines), encoding="utf-8")

    metadata = {
        "run_id": run_id,
        "topic": result.get("topic", ""),
        "text_type": result.get("text_type", ""),
        "genre": result.get("genre", ""),
        "style_tags": result.get("style_tags", []),
        "length": result.get("length", 0),
        "iterations": result.get("iterations", 0),
        "chapters_written": result.get("chapters_written", 0),
        "best_reward": result.get("best_reward", 0),
        "consistency": result.get("consistency", {}),
        "created_at": datetime.now().isoformat(),
    }
    atomic_write_text(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    atomic_write_text(result_json_path, json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    atomic_write_text(round_results_path,
        json.dumps(result.get("round_results", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(output_path), final_text[:600].strip()


def _tail_text(path: Path, max_chars: int = 4000) -> str:
    return tail_text(path, max_chars)


def _run_worker_subprocess(
    idea: str,
    provider: str,
    api_key: str,
    run_id: str,
    provider_specs: Optional[dict[str, ProviderSpec]] = None,
    language: Optional[str] = None,
    source_language: Optional[str] = None,
    translation_mode: Optional[str] = None,
    enabled_capabilities: Optional[set[str]] = None,
    is_running_check: Optional[Callable[[], bool]] = None,
) -> dict:
    worker_out = RUNS_DIR / run_id / "worker_result.json"
    worker_out.parent.mkdir(parents=True, exist_ok=True)
    worker_log = RUNS_DIR / run_id / "worker.log"

    cmd = [
        sys.executable,
        "-u",
        "-m",
        "local_web_portal.worker_process",
        "--idea",
        idea,
        "--output-json",
        str(worker_out),
    ]

    env = os.environ.copy()
    env.update(
        _provider_env(
            provider,
            api_key,
            provider_specs=provider_specs,
            language=language,
            source_language=source_language,
            translation_mode=translation_mode,
            enabled_capabilities=enabled_capabilities,
        )
    )
    env["RUN_ID"] = run_id

    return_code = run_logged_process(
        cmd, cwd=BASE_DIR.parent, env=env, log_path=worker_log,
        cancel_requested=lambda: _is_cancel_requested(run_id),
        is_running=is_running_check,
        timeout=settings.job_timeout_seconds,
        idle_timeout=settings.job_idle_timeout_seconds,
    )

    if not worker_out.exists():
        raise RuntimeError(
            _txt(language, "Worker did not produce output file.\n", "Worker did not produce output file.\n")
            + _txt(language, f"log_tail:\n{_tail_text(worker_log, max_chars=2500)}", f"log_tail:\n{_tail_text(worker_log, max_chars=2500)}")
        )

    payload = json.loads(worker_out.read_text(encoding="utf-8"))
    payload["_stdout"] = _tail_text(worker_log, max_chars=4000)
    payload["_stderr"] = ""
    payload["_returncode"] = return_code
    payload["_worker_log_path"] = str(worker_log)
    return payload


def run_generation_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        # Claim once in the database, including when two requests start together.
        claimed = db.execute(
            update(GenerationJob)
            .where(GenerationJob.id == job_id, GenerationJob.status == "queued")
            .values(status="running", updated_at=_utcnow())
        ).rowcount
        db.commit()
        if not claimed:
            return
        job = db.get(GenerationJob, job_id)

        preferred_language, source_language, translation_mode = _job_language_profile(db, job_id)

        cred_stmt = select(ApiCredential).where(
            ApiCredential.user_id == job.user_id,
            ApiCredential.provider == job.provider,
        )
        credential = db.execute(cred_stmt).scalar_one_or_none()
        raw_api_key = decrypt_api_key(credential.encrypted_key) if credential else _env_api_key_for_provider(job.provider)
        if not raw_api_key:
            raise RuntimeError(_txt(preferred_language, "该提供商尚未保存 API Key。", "No API key saved for this provider."))

        run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_u{job.user_id}_j{job.id}"
        job.run_id = run_id
        job.updated_at = _utcnow()
        db.commit()

        provider_specs = merge_provider_specs(
            get_provider_specs(settings),
            _custom_provider_specs_for_user(db, job.user_id).values(),
            allow_override=False,
        )
        worker_payload = _run_worker_subprocess(
            job.idea,
            job.provider,
            raw_api_key,
            run_id,
            provider_specs=provider_specs,
            language=preferred_language,
            source_language=source_language,
            translation_mode=translation_mode,
            enabled_capabilities=_enabled_capabilities_for_user(db, job.user_id),
            is_running_check=lambda: _job_status_is_running(db, job_id),
        )

        if not _job_status_is_running(db, job_id):
            return

        if not worker_payload.get("ok") or worker_payload.get("_returncode", 0) != 0:
            worker_error = worker_payload.get("error", _txt(preferred_language, "未知的工作进程错误。", "Unknown worker error."))
            worker_tb = worker_payload.get("traceback", "")
            worker_stderr = worker_payload.get("_stderr", "")
            raise RuntimeError(
                _txt(preferred_language, f"{worker_error}\n\n{worker_tb}\n\n工作进程标准错误:\n{worker_stderr}", f"{worker_error}\n\n{worker_tb}\n\nworker_stderr:\n{worker_stderr}")
            )

        result = worker_payload.get("result", {})
        output_path, excerpt = _save_job_artifacts(run_id, result)

        # Cancellation wins even if it arrives while artifacts are being saved.
        db.execute(
            update(GenerationJob)
            .where(GenerationJob.id == job_id, GenerationJob.status == "running")
            .values(status="succeeded", run_id=run_id, output_path=output_path,
                    result_excerpt=excerpt, error_message="", finished_at=_utcnow(),
                    updated_at=_utcnow())
        )
        db.commit()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            job = db.get(GenerationJob, job_id, populate_existing=True)
            if job and job.status == "running":
                if job.run_id:
                    run_dir = RUNS_DIR / job.run_id
                    run_dir.mkdir(parents=True, exist_ok=True)
                    (run_dir / "error.txt").write_text(str(exc), encoding="utf-8")
                db.execute(
                    update(GenerationJob)
                    .where(GenerationJob.id == job_id, GenerationJob.status == "running")
                    .values(status="failed", error_message=str(exc)[:4000],
                            finished_at=_utcnow(), updated_at=_utcnow())
                )
                db.commit()
        except Exception as db_exc:
            fallback_dir = RUNS_DIR / f"job_{job_id}_db_failure"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            (fallback_dir / "error.txt").write_text(
                f"primary_error={exc}\n\ndb_error={db_exc}",
                encoding="utf-8",
            )
    finally:
        db.close()
