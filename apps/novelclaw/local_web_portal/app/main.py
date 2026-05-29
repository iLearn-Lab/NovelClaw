from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlsplit, urlunsplit

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from config import Config
from rag.memory_system import MemorySystem
from utils.language_detector import detect_language
from utils.llm_client import LLMClient

from agents.idea_copilot_agent import (
    IdeaCopilotAgent,
    append_assistant_turn,
    append_user_reply,
    build_generation_idea,
    dump_state,
    latest_assistant_turn,
    load_state,
    merge_generation_preferences,
    normalize_generation_preferences,
)
from .db import SessionLocal, engine, get_db, open_auth_db
from .job_runner import run_generation_job
from .models import ApiCredential, Base, CapabilityPreference, GenerationJob, IdeaCopilotSession, ProviderConfig, User
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
from capability_registry import CAPABILITY_REGISTRY, capability_map, default_enabled_capability_slugs, normalize_capability_slugs

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

EVENT_LABELS = {
    "global_outline": "Claw builds global outline",
    "chapter_outline_ready": "Claw prepares chapter outline set",
    "chapter_plan": "Claw chapter plan",
    "chapter_outline": "Claw chapter outline",
    "chapter_length_plan": "Chapter length plan",
    "chapter_length_warning": "Chapter length warning",
    "character_setting": "Character setting",
    "world_setting": "World setting",
    "memory_snapshot": "Memory snapshot",
}

EVENT_LABELS_ZH = {
    "global_outline": "全局大纲",
    "chapter_outline_ready": "章节大纲就绪",
    "chapter_plan": "章节计划",
    "chapter_outline": "章节大纲",
    "chapter_length_plan": "章节长度计划",
    "chapter_length_warning": "章节长度警告",
    "character_setting": "人物设定",
    "world_setting": "世界设定",
    "memory_snapshot": "记忆快照",
}


_ZH_FALLBACKS: Dict[str, str] = {
    "Creative Writing Console": "创作控制台",
    "Create": "创作",
    "Writing Chat": "写作对话",
    "Storyboard": "故事板",
    "Style Guide": "风格指南",
    "Assets": "资产",
    "Manuscripts": "稿件",
    "Characters": "角色",
    "World": "世界观",
    "Capabilities": "能力",
    "Skills": "技能",
    "Agent Config": "Agent 配置",
    "Control": "控制",
    "Sessions": "会话",
    "Runs": "运行任务",
    "Status": "状态",
    "Setup": "设置",
    "Environment": "环境",
    "NovelClaw running": "NovelClaw 运行中",
    "mode": "模式",
    "max_steps": "最大步数",
    "This is the real-time NovelClaw workspace. Start, continue, delete, and review conversations without being kicked out to another page.": "这里是 NovelClaw 的实时写作工作台。新建会话、继续对话、删除会话和查看当前打磨结果，都可以在这一页完成。",
    "New conversation": "新建对话",
    "Current session": "当前会话",
    "Open details": "查看详情",
    "Delete the current writing session? This cannot be undone.": "确定删除当前写作会话吗？此操作无法撤销。",
    "Delete current conversation": "删除当前对话",
    "You": "你",
    "Thinking": "正在思考",
    "NovelClaw analysis": "NovelClaw 分析",
    "Next questions": "下一步问题",
    "Current writing brief": "当前写作简报",
    "Suggested next answers:": "建议下一步回答：",
    "Readiness": "准备度",
    "No conversation yet.": "还没有对话记录。",
    "Welcome to NovelClaw": "欢迎来到 NovelClaw",
    "Create a writing session on the left to see the live collaboration here.": "先在左侧创建一个写作会话，这里会实时显示协作内容。",
    "Execution mode": "执行模式",
    "Active sessions": "活跃会话",
    "Running jobs": "运行中任务",
    "Dynamic memory": "动态记忆",
    "NovelClaw Status": "NovelClaw 状态",
    "Start a new writing session": "开始新的写作会话",
    "Describe the premise, genre, cast, tone, constraints, target length, and what you want NovelClaw to help with.": "描述故事设定、题材、角色、语气、约束、目标篇幅，以及你希望 NovelClaw 如何协助你。",
    "Start NovelClaw": "启动 NovelClaw",
    "Configure a provider and API key on the Models page first.": "请先在 Models 页面配置 provider 和 API Key。",
    "Recent sessions": "最近会话",
    "New session": "新会话",
    "rounds": "轮",
    "Open": "打开",
    "Details": "详情",
    "Delete this writing session? This cannot be undone.": "确定删除这个写作会话吗？此操作无法撤销。",
    "Delete": "删除",
    "Current Project": "当前项目",
    "Plot points": "大纲",
    "World facts": "世界观事实",
    "Chapter outputs": "章节产出",
    "Current collaboration session": "当前协作会话",
    "Rounds": "轮次",
    "Provider": "提供商",
    "This is not a fake shell around an old flow. The goal is to turn your pipeline into a real writing claw with dynamic memory, capability routing, revision loops, and reusable writing assets.": "这不是套在旧流程外面的假壳子。目标是把你的写作管线改造成真正的 NovelClaw，具备动态记忆、能力调度、修订循环和可复用写作资产。",
    "Good first inputs": "建议你先提供的信息",
    "What is the premise, audience, and core conflict?": "故事前提、目标读者和核心冲突是什么？",
    "What viewpoint, tone, and pacing do you want?": "你希望采用什么视角、语气和节奏？",
    "What are the hard constraints for cast, world, and taboo patterns?": "对角色、世界观和禁忌套路有哪些硬约束？",
    "Continue refining": "继续打磨",
    "Back to workspace": "回到工作台",
    "Delete conversation": "删除对话",
    "Idea Refinement": "创意打磨",
    "Idea Refinement Session": "创意打磨会话",
    "Bring AI chat, progress, readiness, and final confirmation into one workspace.": "把 AI 对话、进度、准备度与最终确认整合进同一个工作区。",
    "Current Idea Status": "当前创意状态",
    "Original Idea": "原始想法",
    "Current Refined Draft": "当前打磨稿",
    "Confirm the refined idea and start generation": "确认打磨稿，开始正式生成",
    "Cancel session": "取消会话",
    "Conversation": "对话流",
    "This is not rigid Q&A. It is a collaborative loop around what is missing, what should change, and what comes next.": "这里不是死板问答，而是围绕“缺什么、改什么、下一步做什么”的协同打磨。",
    "Add more details for this round": "继续补充本轮信息",
    "Answer the questions, add style and constraints, call out cliches to avoid, or request pacing and character arcs...": "\u56de\u7b54\u95ee\u9898\u3001\u8865\u5145\u98ce\u683c\u4e0e\u7ea6\u675f\u3001\u6307\u51fa\u4e0d\u60f3\u8981\u7684\u5957\u8def\u3001\u8981\u6c42\u8282\u594f\u6216\u4eba\u7269\u5f27\u7ebf...",
    "Submit and continue refining": "提交并继续打磨",
    "Open generation job": "打开生成任务",
    "This session has ended.": "当前会话已结束。",
    "Models": "模型",
    "Save API Key": "保存 API Key",
    "Select a provider": "选择提供商",
    "Enter API key": "输入 API Key",
    "Providers": "提供商",
    "Refresh Status": "刷新状态",
    "Refresh Runs": "刷新任务",
    "Refresh Workspace": "刷新工作区",
    "Workspace Overview": "工作区概览",
    "Draft Texts": "草稿文本",
    "Chapter Files": "章节文件",
    "Memory Banks": "记忆库",
    "Chapter Outputs": "章节产出",
    "Workspace Files": "工作区文件",
    "No workspace files to show yet.": "当前没有可显示的工作区文件。",
    "Character Entry": "角色条目",
    "No character data yet.": "暂时还没有角色数据。",
    "World constraints and continuity facts currently available to the loop.": "查看当前可被循环使用的世界约束和连续性事实。",
    "World Settings": "世界设定",
    "Continuity Facts": "连续性事实",
    "No world data yet.": "暂时还没有世界观数据。",
    "No fact cards yet.": "暂时还没有事实卡片。",
    "Review chapter briefs, outlines, and plot beats currently available to the writing loop.": "查看当前可被写作循环使用的章节简报、大纲和情节点。",
    "Outlines": "大纲",
    "Outline": "大纲",
    "Plot Beats": "情节点",
    "No outline items yet.": "暂时还没有大纲条目。",
    "No plot beats yet.": "暂时还没有情节点。",
    "Keep the current style summary, tags, and unresolved writing questions visible.": "保持当前风格摘要、标签和待解决写作问题的可见性。",
    "Style Summary": "风格摘要",
    "Style Tags": "风格标签",
    "No style tags yet.": "暂时还没有风格标签。",
    "Open Questions": "待解决问题",
    "No open questions right now.": "当前没有待解决问题。",
    "Review current and past runs, then open the live NovelClaw execution detail.": "查看当前和历史任务，并进入实时的 NovelClaw 执行详情。",
    "created": "创建于",
    "No runs yet.": "还没有任务。",
    "Monitor providers, memory banks, loop settings, and running jobs.": "监控 providers、记忆库、循环设置和运行中任务。",
    "API Health": "API 健康度",
    "Max Steps": "最大步数",
    "Active Sessions": "活跃会话",
    "Running Jobs": "运行中任务",
    "Total Jobs": "任务总数",
    "Critical environment values that affect NovelClaw runtime behavior.": "影响 NovelClaw 运行时行为的关键环境变量。",
    "No environment values to display.": "没有可显示的环境值。",
    "This is the integration surface for future browser, tool, knowledge, and publishing connectors.": "这里是未来浏览器、工具、知识接口和发布连接器的集成层。",
    "NovelClaw already wires together internal agents, dynamic memory, provider settings, and the executor. MCP is the next layer for external tools.": "NovelClaw 当前已经串起内部 agents、动态记忆、provider 配置和执行器。MCP 会是下一层外部工具接入面。",
    "Writing Skills": "写作技能",
    "This is a real capability control page. At this stage, OpenClaw only chooses the next step from enabled Claw actions.": "这里已经是真实能力开关页。当前阶段里，OpenClaw 只会从“已启用”的 Claw 动作中选择下一步。",
    "Core Always On": "核心常开",
    "Enabled": "已启用",
    "Disabled": "已禁用",
    "Disable": "禁用",
    "Enable": "启用",
    "See how your existing agents are used by the NovelClaw loop instead of sitting behind a fixed workflow.": "查看现有 agents 如何被 NovelClaw 循环真实调用，而不是躲在固定流程后面。",
    "Loop Config": "循环配置",
    "Execution Mode": "执行模式",
    "Latest Run": "最新运行",
    "Routing Logic": "路由逻辑",
    "NovelClaw observes the current candidate, dynamic memory, issue types, and support outputs before choosing the next agent call.": "NovelClaw 会观察当前候选稿、动态记忆、问题类型和辅助输出，再决定下一次 agent 调用。",
    "Generation Job Detail": "生成任务详情",
    "Monitor live status, chapter outputs, logs, and final results in one place.": "实时查看运行状态、章节产出、日志流和最终结果。",
    "Job": "任务",
    "Queued": "已排队",
    "Running": "运行中",
    "Succeeded": "已成功",
    "Failed": "失败",
    "Canceled": "已取消",
    "Unknown": "未知",
    "Cancel this job": "取消任务",
    "Job Input": "任务输入",
    "Run ID": "运行 ID",
    "Output Path": "输出路径",
    "Download Full Output": "下载完整结果",
    "Download All Chapters (.zip)": "下载全部章节 (.zip)",
    "Execution Status": "执行状态",
    "Phase": "阶段",
    "Elapsed": "已耗时",
    "Idle": "空闲",
    "Current action": "当前动作",
    "Chapter progress": "章节进度",
    "Chapter words": "本章字数",
    "Total words": "累计字数",
    "Memory": "记忆",
    "Texts": "文本",
    "Worlds": "世界设定",
    "Facts": "事实卡",
    "Live Progress": "实时进度",
    "This shows real worker output, not browser polling logs.": "这里显示的是真实工作进程输出，不是浏览器轮询日志。",
    "No worker log yet.": "尚无工作进程日志。",
    "Progress Log": "进度日志",
    "No progress log yet.": "尚无进度日志。",
    "Claw / Agent Trace": "Claw / Agent 轨迹",
    "This turns key progress events into a readable step trace so you can see which capabilities Claw is using.": "这会把 progress.log 里的关键事件转成可读的步骤轨迹，让你看到 Claw 正在使用哪些能力。",
    "No Claw / Agent events yet.": "还没有 Claw / Agent 事件。",
    "Chapter Results": "章节结果",
    "Shows the latest finalized content for each chapter and auto-refreshes while the job runs.": "这里会显示每章最新定稿内容，并在任务运行时自动刷新。",
    "Chapter": "章节",
    "Iteration": "迭代",
    "Download Chapter": "下载章节",
    "No chapter output yet.": "尚无章节输出。",
    "Error": "错误",
    "Generated Text": "生成结果",
    "Result": "结果",
    "This job is still running or has not produced output yet. Refresh in a few seconds.": "任务仍在运行，或暂未产生结果。请稍后刷新页面。",
    "Back to dashboard": "返回仪表盘",
    "Possible stall detected, please check worker logs.": "检测到可能卡住，请检查工作日志。",
}


def _lang_text(lang: str, zh: str, en: str) -> str:
    if str(lang or "").lower().startswith("en"):
        return en
    return _ZH_FALLBACKS.get(en, zh)


def _ui_language(request: Request) -> str:
    session_lang = str(request.session.get("ui_language", "") or "").lower()
    if session_lang in {"zh", "en"}:
        return session_lang
    configured = str(settings.ui_language or "").lower()
    return configured if configured in {"zh", "en"} else "en"


def _ui_text(lang: str, zh: str, en: str) -> str:
    return _lang_text(lang, zh, en)


def _console_texts(lang: str) -> Dict[str, str]:
    return {
        "brand_subtitle": _ui_text(lang, "创作控制台", "Creative Writing Console"),
        "nav_create": _ui_text(lang, "创作", "Create"),
        "nav_chat": _ui_text(lang, "写作对话", "Writing Chat"),
        "nav_storyboard": _ui_text(lang, "故事板", "Storyboard"),
        "nav_style": _ui_text(lang, "风格指南", "Style Guide"),
        "nav_assets": _ui_text(lang, "资产", "Assets"),
        "nav_manuscripts": _ui_text(lang, "稿件与记忆", "Drafts & Memory"),
        "nav_characters": _ui_text(lang, "角色", "Characters"),
        "nav_world": _ui_text(lang, "世界观", "World"),
        "nav_capabilities": _ui_text(lang, "能力", "Capabilities"),
        "nav_skills": _ui_text(lang, "技能", "Skills"),
        "nav_mcp": "MCP",
        "nav_agents": _ui_text(lang, "Agent 配置", "Agent Config"),
        "nav_control": _ui_text(lang, "控制", "Control"),
        "nav_sessions": _ui_text(lang, "会话", "Sessions"),
        "nav_runs": _ui_text(lang, "运行任务", "Runs"),
        "nav_status": _ui_text(lang, "状态", "Status"),
        "nav_setup": _ui_text(lang, "设置", "Setup"),
        "nav_models": _ui_text(lang, "模型", "Models"),
        "nav_environment": _ui_text(lang, "环境", "Environment"),
        "runtime_running": _ui_text(lang, "NovelClaw 运行中", "NovelClaw running"),
        "runtime_mode": _ui_text(lang, "模式", "mode"),
        "runtime_max_steps": _ui_text(lang, "最大步数", "max_steps"),
        "lang_zh": "中文",
        "lang_en": "EN",
        "models_page_title": _ui_text(lang, "模型配置", "Models"),
        "models_page_desc": _ui_text(lang, "配置 NovelClaw 使用的提供商、模型与 API Key。", "Configure the providers, models, and API keys used by NovelClaw."),
        "models_heading_providers": _ui_text(lang, "已配置提供商", "Providers"),
        "models_api_key_label": _ui_text(lang, "API Key：", "API key:"),
        "models_saved": _ui_text(lang, "已保存", "Saved"),
        "models_not_saved": _ui_text(lang, "未保存", "Not saved"),
        "models_no_providers": _ui_text(lang, "还没有提供商。", "No providers yet."),
        "models_save_api_key": _ui_text(lang, "保存 API Key", "Save API Key"),
        "models_select_provider": _ui_text(lang, "选择提供商", "Select a provider"),
        "models_enter_api_key": _ui_text(lang, "输入 API Key", "Enter API key"),
        "models_api_key_note": _ui_text(lang, "Key 会加密保存到本地数据库。", "Keys are encrypted before being stored in the local database."),
        "models_provider_form": _ui_text(lang, "新增或更新提供商", "Add or update provider"),
        "models_slug_placeholder": _ui_text(lang, "唯一标识，例如 openrouter_custom", "Unique slug, e.g. openrouter_custom"),
        "models_label_placeholder": _ui_text(lang, "显示名称", "Display label"),
        "models_base_url_placeholder": _ui_text(lang, "基础 URL", "Base URL"),
        "models_model_placeholder": _ui_text(lang, "模型名", "Model name"),
        "models_save_provider": _ui_text(lang, "保存提供商", "Save Provider"),
        "models_delete_provider": _ui_text(lang, "删除", "Delete"),
    }


def _modelless_mode_enabled() -> bool:
    return bool(getattr(settings, "modelless_mode", False))


def _modelless_notice(lang: str) -> str:
    return _ui_text(
        lang,
        "当前部署以无模型工作台模式运行。门户可以正常启动、登录、查看工作区和管理本地状态，但不会触发任何需要 provider、API Key 或 model 的流程。若你之后要启用生成，再把 local_web_portal/.env 里的 WEB_MODELLESS_MODE 改为 0。",
        "This deployment is running in model-free workspace mode. The portal can start, log in, browse the workspace, and manage local state without triggering any provider, API key, or model-dependent flow. If you later want generation, set WEB_MODELLESS_MODE=0 in local_web_portal/.env.",
    )





def _job_language(job: Optional[GenerationJob]) -> str:
    idea = str(getattr(job, "idea", "") or "")
    lowered = idea.lower()
    for key in ("preferred_output_language", "preferred_language", "source_language", "ui_language"):
        match = re.search(rf"{key}\s*[:=]\s*(en|zh)\b", lowered)
        if match:
            return match.group(1)
    for pattern, lang in (
        (r"首选输出语言\s*[:：=]\s*(?:英文|英语|en)", "en"),
        (r"首选输出语言\s*[:：=]\s*(?:中文|汉语|zh)", "zh"),
        (r"源语言\s*[:：=]\s*(?:英文|英语|en)", "en"),
        (r"源语言\s*[:：=]\s*(?:中文|汉语|zh)", "zh"),
    ):
        if re.search(pattern, idea, re.IGNORECASE):
            return lang
    detected = detect_language(idea)
    return detected if detected in {"en", "zh"} else "en"


def _event_label(event_name: str, language: str) -> str:
    labels = EVENT_LABELS if str(language).lower().startswith("en") else EVENT_LABELS_ZH
    return labels.get(event_name, event_name.replace("_", " "))

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
    # Recover jobs left in non-terminal state after a server/process restart.
    # Note: web jobs run in daemon threads; after restart those threads are gone.
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
        clean_uid = int(uid)
    except (TypeError, ValueError):
        return None

    user = db.get(User, clean_uid)
    if user:
        return user
    return _sync_user_from_auth_db(db, clean_uid)


def _sync_user_from_auth_db(db: Session, user_id: int) -> Optional[User]:
    auth_db = open_auth_db()
    if auth_db is None:
        return None
    try:
        auth_user = auth_db.get(User, user_id)
        if not auth_user:
            return None

        existing = db.get(User, user_id)
        if existing:
            return existing

        shadow_user = User(
            id=int(auth_user.id),
            email=str(auth_user.email or "").strip(),
            password_hash=str(auth_user.password_hash or ""),
            created_at=getattr(auth_user, "created_at", None) or datetime.now(timezone.utc),
        )
        db.add(shadow_user)
        db.commit()
        return db.get(User, user_id)
    except Exception:
        db.rollback()
        return None
    finally:
        auth_db.close()


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


def _static_asset_path(path: str) -> str:
    asset = (path or "").strip().lstrip("/")
    return _app_path(f"/static/{asset}")


def _current_public_path(request: Request) -> str:
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{_app_path(request.url.path)}{query}"


def _redirect(path: str) -> RedirectResponse:
    parts = urlsplit(path)
    target = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            _app_path(parts.path),
            parts.query,
            parts.fragment,
        )
    )
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def _safe_next_path(target: str, default: str = "/console/chat") -> str:
    normalized = (target or "").strip()
    if not normalized or not normalized.startswith("/") or normalized.startswith("//"):
        return _app_path(default)
    return normalized


def _redirect_with_notice(path: str, *, message: str = "", error: str = "") -> RedirectResponse:
    query_parts = []
    if message:
        query_parts.append(f"message={quote_plus(message)}")
    if error:
        query_parts.append(f"error={quote_plus(error)}")
    if query_parts:
        parts = urlsplit(path)
        existing_query = parts.query
        merged_query = "&".join([item for item in [existing_query, *query_parts] if item])
        path = urlunsplit((parts.scheme, parts.netloc, parts.path, merged_query, parts.fragment))
    return _redirect(path)


def _reject_when_modelless(
    request: Request,
    *,
    path: str = "/console/chat",
    fetch_status: int = 409,
) -> RedirectResponse | JSONResponse:
    message = _modelless_notice(_ui_language(request))
    if request.headers.get("x-requested-with") == "fetch":
        return JSONResponse({"ok": False, "error": message}, status_code=fetch_status)
    return _redirect_with_notice(path, error=message)


def _mask_hint(raw: str) -> str:
    if len(raw) < 8:
        return "********"
    return f"{raw[:4]}...{raw[-4:]}"


templates.env.globals["app_path"] = _app_path
templates.env.globals["static_asset_path"] = _static_asset_path
templates.env.globals["shared_path"] = _shared_path
templates.env.globals["current_public_path"] = _current_public_path
templates.env.globals["app_base_path"] = settings.base_path


@app.get("/healthz")
def healthz():
    return {"ok": True}


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


def _capability_preferences_for_user(db: Session, user_id: int) -> Dict[str, CapabilityPreference]:
    rows = (
        db.execute(
            select(CapabilityPreference).where(CapabilityPreference.user_id == user_id)
        )
        .scalars()
        .all()
    )
    return {str(row.slug or "").strip().lower(): row for row in rows if row.slug}


def _enabled_capability_slugs_for_user(db: Session, user_id: int) -> set[str]:
    pref_map = _capability_preferences_for_user(db, user_id)
    enabled = set(default_enabled_capability_slugs())
    for slug, row in pref_map.items():
        if getattr(row, "enabled", False):
            enabled.add(slug)
        else:
            enabled.discard(slug)
    return normalize_capability_slugs(enabled)


def _build_capability_catalog(db: Session, user_id: int, language: str) -> List[Dict[str, object]]:
    pref_map = _capability_preferences_for_user(db, user_id)
    enabled = _enabled_capability_slugs_for_user(db, user_id)
    items: List[Dict[str, object]] = []
    for spec in sorted(CAPABILITY_REGISTRY, key=lambda item: (item.order, item.slug)):
        items.append(
            {
                "slug": spec.slug,
                "name": spec.name_en if str(language or "").lower().startswith("en") else spec.name_zh,
                "category": spec.category_en if str(language or "").lower().startswith("en") else spec.category_zh,
                "description": spec.description_en if str(language or "").lower().startswith("en") else spec.description_zh,
                "enabled": bool(spec.always_enabled or spec.slug in enabled),
                "always_enabled": bool(spec.always_enabled),
                "manager_action": spec.manager_action or "",
                "is_configured": spec.slug in pref_map,
            }
        )
    return items


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
    if _modelless_mode_enabled():
        return {}
    base_specs = get_provider_specs(settings)
    custom_specs = _custom_provider_specs_for_user(db, user_id)
    return merge_provider_specs(base_specs, custom_specs.values(), allow_override=False)


def _all_provider_specs_for_user(db: Session, user_id: int) -> Dict[str, ProviderSpec]:
    base_specs = get_provider_specs(settings)
    custom_specs = _custom_provider_specs_for_user(db, user_id)
    return merge_provider_specs(base_specs, custom_specs.values(), allow_override=False)


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


def _provider_api_key(db: Session, user_id: int, provider: str) -> str:
    row = db.execute(
        select(ApiCredential).where(
            ApiCredential.user_id == user_id,
            ApiCredential.provider == provider,
        )
    ).scalar_one_or_none()
    if row:
        try:
            return decrypt_api_key(row.encrypted_key)
        except Exception as exc:
            raise ValueError(f"Failed to decrypt API key: {exc}") from exc

    env_key = _env_api_key_for_provider(provider)
    if env_key:
        return env_key
    raise ValueError("Save your API key for that provider first")


def _load_console_jobs(db: Session, user_id: int, limit: int = 20) -> List[GenerationJob]:
    return (
        db.execute(
            select(GenerationJob)
            .where(GenerationJob.user_id == user_id)
            .order_by(GenerationJob.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def _load_console_sessions(db: Session, user_id: int, limit: int = 20) -> List[IdeaCopilotSession]:
    return (
        db.execute(
            select(IdeaCopilotSession)
            .where(IdeaCopilotSession.user_id == user_id)
            .order_by(IdeaCopilotSession.updated_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def _memory_index_candidates(run_id: str) -> List[Path]:
    base_root = BASE_DIR.parent
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        return []
    return [
        (base_root / "vector_db" / "memory" / f"run_{clean_run_id}" / "memory_index.json").resolve(),
    ]


def _load_memory_index_for_run(run_id: str) -> Dict:
    candidates = _memory_index_candidates(run_id)
    for path in candidates:
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


def _empty_memory_index() -> Dict[str, object]:
    return {
        "schema_version": 2,
        "texts": [],
        "outlines": [],
        "characters": [],
        "world_settings": [],
        "plot_points": [],
        "fact_cards": [],
        "claw": {bank: [] for bank in MemorySystem.CLAW_BANKS},
    }


def _ensure_memory_index_shape(index: Dict) -> Dict:
    value = index if isinstance(index, dict) else {}
    value.setdefault("schema_version", 2)
    for key in ("texts", "outlines", "characters", "world_settings", "plot_points", "fact_cards"):
        bucket = value.get(key)
        value[key] = bucket if isinstance(bucket, list) else []
    claw = value.get("claw")
    if not isinstance(claw, dict):
        claw = {}
        value["claw"] = claw
    for bank in MemorySystem.CLAW_BANKS:
        entries = claw.get(bank)
        claw[bank] = entries if isinstance(entries, list) else []
    return value


def _load_editable_memory_index_for_run(run_id: str) -> Dict:
    loaded = _load_memory_index_for_run(run_id)
    if not loaded:
        return _empty_memory_index()
    return _ensure_memory_index_shape(loaded)


def _save_memory_index_for_run(run_id: str, index: Dict) -> None:
    path_value = _memory_index_path_for_run(run_id)
    if not path_value:
        raise ValueError("Memory index path is unavailable")
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_ensure_memory_index_shape(index), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _job_for_run_id(db: Session, user_id: int, run_id: str) -> Optional[GenerationJob]:
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        return None
    return db.execute(
        select(GenerationJob)
        .where(
            GenerationJob.user_id == user_id,
            GenerationJob.run_id == clean_run_id,
        )
        .order_by(GenerationJob.updated_at.desc(), GenerationJob.id.desc())
    ).scalars().first()


def _memory_topic_hint(index: Dict, fallback: str = "global") -> str:
    claw = index.get("claw", {}) if isinstance(index, dict) else {}
    if isinstance(claw, dict):
        for bank in MemorySystem.CLAW_BANKS:
            entries = claw.get(bank) or []
            if entries:
                topic = str((entries[-1] or {}).get("topic") or "").strip()
                if topic:
                    return topic
    for bucket in ("texts", "outlines", "characters", "world_settings", "plot_points", "fact_cards"):
        items = index.get(bucket) or []
        if items:
            topic = str((items[-1] or {}).get("topic") or "").strip()
            if topic:
                return topic
    return fallback


@lru_cache(maxsize=1)
def _portal_memory_system() -> MemorySystem:
    cfg = Config(require_api_key=False)
    cfg.language = settings.ui_language if settings.ui_language in {"en", "zh"} else "en"
    cfg.memory_only_mode = True
    cfg.enable_rag = False
    cfg.enable_static_kb = False
    cfg.embedding_model = "none"
    return MemorySystem(cfg)


def _remember_session_turn(
    session: IdeaCopilotSession,
    state: Dict,
    *,
    user_reply: str = "",
    turn: Optional[Dict] = None,
    confirmed: bool = False,
    final_topic: str = "",
) -> None:
    try:
        memory = _portal_memory_system()
        topic = str(state.get("refined_idea") or session.refined_idea or session.original_idea or final_topic or f"session:{session.id}").strip()
        if not topic:
            topic = f"session:{session.id}"
        preferred_language = str(state.get("preferred_language") or "en").lower()
        source_language = str(state.get("source_language") or preferred_language or "en").lower()
        memory.store_claw_memory(
            "session_profile",
            (
                f"session_id={session.id}\n"
                f"provider={session.provider}\n"
                f"status={session.status}\n"
                f"round={int(state.get('round', 0) or 0)}"
            ),
            topic,
            metadata={"session_id": session.id},
            store_vector=False,
        )
        memory.store_claw_memory(
            "language_profile",
            (
                f"preferred_language={preferred_language}\n"
                f"source_language={source_language}\n"
                f"translation_mode={state.get('translation_mode', 'follow_input')}"
            ),
            topic,
            metadata={"session_id": session.id},
            store_vector=False,
        )
        refined = str(state.get("refined_idea") or session.refined_idea or session.original_idea or "").strip()
        if refined:
            memory.store_claw_memory(
                "task_briefs",
                refined,
                topic,
                metadata={"session_id": session.id},
                store_vector=True,
            )
            memory.store_claw_memory(
                "story_premise",
                refined,
                topic,
                metadata={"session_id": session.id},
                store_vector=False,
            )
        if user_reply.strip():
            memory.store_claw_memory(
                "user_preferences",
                user_reply.strip(),
                topic,
                metadata={"session_id": session.id},
                store_vector=True,
            )
        if turn:
            analysis = str(turn.get("analysis") or "").strip()
            if analysis:
                memory.store_claw_memory(
                    "working_set",
                    analysis,
                    topic,
                    metadata={"session_id": session.id, "kind": "analysis"},
                    store_vector=True,
                )
            style_targets = turn.get("style_targets") or []
            if isinstance(style_targets, list) and style_targets:
                memory.store_claw_memory(
                    "style_guide",
                    "\n".join(str(item) for item in style_targets[:8]),
                    topic,
                    metadata={"session_id": session.id},
                    store_vector=False,
                )
            questions = turn.get("questions") or []
            if isinstance(questions, list) and questions:
                memory.store_claw_memory(
                    "decision_log",
                    "next_questions=\n" + "\n".join(str(q) for q in questions[:3]),
                    topic,
                    metadata={"session_id": session.id},
                    store_vector=False,
                )
        if confirmed:
            memory.store_claw_memory(
                "decision_log",
                "session_confirmed_for_generation",
                topic,
                metadata={"session_id": session.id},
                store_vector=False,
            )
    except Exception:
        pass
def _build_workspace_files(run_id: str) -> List[Dict[str, str]]:
    if not run_id:
        return []
    run_dir = _resolve_run_dir(run_id)
    if not run_dir.exists():
        return []
    files: List[Dict[str, str]] = []
    for name in ["output.txt", "result.json", "round_results.json", "metadata.json", "worker.log", "progress.log"]:
        path = run_dir / name
        if not path.exists():
            continue
        files.append(
            {
                "name": name,
                "path": str(path),
                "size": f"{max(1, int(path.stat().st_size / 1024))} KB",
                "preview": _tail_text(path, max_chars=300),
            }
        )
    workspace_dir = run_dir / "workspace"
    if workspace_dir.exists():
        for path in sorted([item for item in workspace_dir.rglob("*") if item.is_file()])[:20]:
            files.append(
                {
                    "name": str(path.relative_to(run_dir)).replace("\\", "/"),
                    "path": str(path),
                    "size": f"{max(1, int(path.stat().st_size / 1024))} KB",
                    "preview": _tail_text(path, max_chars=300),
                }
            )
    return files


def _build_memory_overview(run_id: str) -> Dict:
    index = _load_memory_index_for_run(run_id)
    claw = index.get("claw", {}) if isinstance(index, dict) else {}
    counts = {
        "texts": len(index.get("texts", [])) if isinstance(index, dict) else 0,
        "outlines": len(index.get("outlines", [])) if isinstance(index, dict) else 0,
        "characters": len(index.get("characters", [])) if isinstance(index, dict) else 0,
        "world_settings": len(index.get("world_settings", [])) if isinstance(index, dict) else 0,
        "plot_points": len(index.get("plot_points", [])) if isinstance(index, dict) else 0,
        "fact_cards": len(index.get("fact_cards", [])) if isinstance(index, dict) else 0,
    }
    claw_counts = {key: len(value or []) for key, value in claw.items()} if isinstance(claw, dict) else {}
    latest_claw = {}
    if isinstance(claw, dict):
        for key, value in claw.items():
            latest_claw[key] = value[-1] if value else None
    return {
        "index": index,
        "counts": counts,
        "claw_counts": claw_counts,
        "latest_claw": latest_claw,
        "index_path": _memory_index_path_for_run(run_id),
    }


def _tail_items(items: List[Dict], limit: int = 8) -> List[Dict]:
    return list(items[-limit:]) if items else []


def _build_agent_catalog() -> List[Dict[str, str]]:
    return [
        {"slug": "openclaw_manager", "name": "OpenClaw Manager", "role": "dynamic orchestration", "desc": "Chooses the next writing action from live signals instead of following a fixed workflow."},
        {"slug": "idea_analyzer", "name": "IdeaAnalyzer", "role": "idea shaping", "desc": "Turns raw ideas into a stable writing brief with genre, conflict, tone, cast, and constraints."},
        {"slug": "analyzer", "name": "Analyzer", "role": "task understanding", "desc": "Decides whether the current turn needs planning, drafting, rewriting, worldbuilding, or cleanup."},
        {"slug": "plot", "name": "Plot Agent", "role": "plot progression", "desc": "Builds outlines, chapter briefs, conflict escalations, and turning-point candidates."},
        {"slug": "character", "name": "Character Agent", "role": "character arc", "desc": "Maintains character setup, motivation, relationships, and behavior boundaries."},
        {"slug": "world", "name": "World Agent", "role": "world constraints", "desc": "Stores world rules, setting boundaries, and reusable canon facts for later writing."},
        {"slug": "retrieval", "name": "Retrieval Agent", "role": "memory retrieval", "desc": "Pulls relevant context back from memory, chapters, facts, and prior drafts."},
        {"slug": "writer", "name": "Writer Agent", "role": "draft generation", "desc": "Drafts, continues, and rewrites prose. This is the core writing engine inside NovelClaw."},
        {"slug": "evaluator", "name": "Evaluator Agent", "role": "quality review", "desc": "Scores coherence, pacing, emotion, structure, and task-fit of candidate drafts."},
        {"slug": "judge", "name": "Judge Agent", "role": "candidate selection", "desc": "Chooses between close draft candidates when the loop needs a final decision."},
        {"slug": "turning_point_tracker", "name": "TurningPointTracker", "role": "turning-point tracking", "desc": "Tracks story beats and whether the chapter is meaningfully advancing."},
        {"slug": "consistency_checker", "name": "ConsistencyChecker", "role": "continuity checking", "desc": "Checks character, world, timeline, and fact consistency across outputs."},
        {"slug": "realtime_editor", "name": "RealtimeEditor", "role": "live editing", "desc": "Finds weak spans and applies targeted revision passes during iteration."},
    ]


def _build_story_assets(memory_overview: Dict, active_session: Optional[IdeaCopilotSession], latest_job: Optional[GenerationJob]) -> Dict:
    index = memory_overview.get("index", {}) if isinstance(memory_overview, dict) else {}
    outlines = list(index.get("outlines", []) or [])
    plot_points = list(index.get("plot_points", []) or [])
    characters = list(index.get("characters", []) or [])
    world_settings = list(index.get("world_settings", []) or [])
    fact_cards = list(index.get("fact_cards", []) or [])
    texts = list(index.get("texts", []) or [])
    refined_idea = active_session.refined_idea if active_session and active_session.refined_idea else (active_session.original_idea if active_session else "")
    run_id = latest_job.run_id if latest_job and latest_job.run_id else ""
    run_dir = _resolve_run_dir(run_id) if run_id else None
    chapter_outputs = _load_chapter_outputs(run_dir) if run_dir else []
    latest_chapter = chapter_outputs[-1] if chapter_outputs else None
    latest_text = texts[-1] if texts else None
    assets_language = detect_language(refined_idea) if refined_idea else "en"
    project_name = refined_idea or _lang_text(assets_language, "未命名项目", "Untitled Project")
    if len(project_name) > 28:
        project_name = project_name[:28] + "..."
    return {
        "project_name": project_name,
        "refined_idea": refined_idea,
        "latest_run_id": run_id,
        "outlines": _tail_items(outlines, 10),
        "plot_points": _tail_items(plot_points, 10),
        "characters": _tail_items(characters, 12),
        "world_settings": _tail_items(world_settings, 8),
        "fact_cards": _tail_items(fact_cards, 12),
        "texts": _tail_items(texts, 6),
        "latest_text": latest_text,
        "chapter_outputs": chapter_outputs,
        "latest_chapter": latest_chapter,
    }


def _empty_story_assets() -> Dict[str, object]:
    return {
        "project_name": "",
        "refined_idea": "",
        "latest_run_id": "",
        "outlines": [],
        "plot_points": [],
        "characters": [],
        "world_settings": [],
        "fact_cards": [],
        "texts": [],
        "latest_text": None,
        "chapter_outputs": [],
        "latest_chapter": None,
    }


def _build_workspace_bootstrap(
    story_assets: Dict,
    memory_overview: Dict,
    memory_bank_groups: List[Dict[str, object]],
    language: str,
    *,
    download_job_id: int = 0,
) -> Dict[str, object]:
    index = memory_overview.get("index", {}) if isinstance(memory_overview, dict) else {}
    claw = index.get("claw", {}) if isinstance(index, dict) else {}
    outlines = []
    for item in list(story_assets.get("outlines") or [])[-24:]:
        structure = item.get("structure") if isinstance(item.get("structure"), dict) else {}
        kind = str(structure.get("kind") or "outline").strip() or "outline"
        title = str(structure.get("title") or "").strip()
        chapter = structure.get("chapter")
        if not title:
            if kind == "global_outline":
                title = _lang_text(language, "全局大纲", "Global Outline")
            elif kind == "chapter_outline" and chapter:
                title = _lang_text(language, f"第 {chapter} 章大纲", f"Chapter {chapter} Outline")
            else:
                title = kind.replace("_", " ").strip().title()
        outlines.append(
            {
                "id": str(item.get("id") or ""),
                "kind": kind,
                "chapter": chapter,
                "title": title,
                "content": str(item.get("content") or "").strip(),
                "timestamp": str(item.get("timestamp") or ""),
                "source": str(structure.get("source") or ""),
            }
        )

    tactical_banks = {}
    for bank in [
        "story_premise",
        "task_briefs",
        "style_guide",
        "chapter_briefs",
        "scene_cards",
        "working_set",
        "decision_log",
        "entity_state",
        "relationship_state",
        "world_state",
        "continuity_facts",
    ]:
        entries = list(claw.get(bank, []) or []) if isinstance(claw, dict) else []
        tactical_banks[bank] = [_serialize_claw_entry(item) for item in entries[-10:]][::-1]

    chapters = []
    for item in story_assets.get("chapter_outputs") or []:
        chapters.append(
            {
                "chapter": item.get("chapter"),
                "iteration": item.get("iteration"),
                "filename": item.get("filename"),
                "content": str(item.get("content") or "").strip(),
            }
        )

    plot_points = []
    for item in story_assets.get("plot_points") or []:
        plot_points.append(
            {
                "position": str(item.get("position") or "").strip(),
                "content": str(item.get("content") or "").strip(),
                "timestamp": str(item.get("timestamp") or ""),
            }
        )

    return {
        "project_name": str(story_assets.get("project_name") or ""),
        "run_id": str(story_assets.get("latest_run_id") or ""),
        "download_job_id": int(download_job_id or 0),
        "chapters": chapters,
        "outlines": outlines,
        "plot_points": plot_points,
        "tactical_banks": tactical_banks,
        "memory_groups": memory_bank_groups,
    }


def _stringify_memory_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " / ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return " / ".join(f"{key}: {val}" for key, val in value.items() if str(val).strip())
    return str(value).strip()



def _compact_preview(text: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def _extract_generation_brief_summary(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    lines = [line.rstrip() for line in raw.splitlines()]
    header = lines[0].strip() if lines else ""
    if header not in {"[NovelClaw generation brief]", "[NovelClaw 生成简报]"}:
        return raw

    summary_lines: List[str] = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            if summary_lines and summary_lines[-1] != "":
                summary_lines.append("")
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            break
        summary_lines.append(line)
    return "\n".join(summary_lines).strip() or raw


def _extract_markdown_section(text: str, heading: str) -> str:
    raw = str(text or "").strip()
    if not raw or heading not in raw:
        return ""
    lines = raw.splitlines()
    capture = False
    kept: List[str] = []
    heading_level = heading.count("#")
    for line in lines:
        stripped = line.strip()
        if stripped == heading:
            capture = True
            continue
        if not capture:
            continue
        if stripped.startswith("#") and stripped.count("#") <= heading_level:
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _clean_chapter_brief_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    planning_section = _extract_markdown_section(raw, "## Unified Planning Packet")
    if planning_section:
        return planning_section

    cleaned_lines: List[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        if stripped in {"## Support Signals", "## Claw History", "## Candidate Excerpt"}:
            break
        if re.match(r"^#\s+", stripped):
            continue
        if re.match(r"^-\s*(topic|chapter|reward|issues|length)\s*:", stripped, re.IGNORECASE):
            continue
        if re.match(r"^(topic|chapter|reward|issues|length)\s*=", stripped, re.IGNORECASE):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip() or raw


def _display_claw_entry_text(entry: Dict[str, object]) -> Tuple[str, str]:
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    topic = _extract_generation_brief_summary(entry.get("topic") or "")
    content = str(entry.get("content") or "").strip()
    bank = str(entry.get("bank") or "").strip()
    tool = str(metadata.get("tool") or metadata.get("source_type") or "").strip()

    if bank in {"task_briefs", "story_premise"}:
        content = _extract_generation_brief_summary(content)
        topic = _compact_preview(_extract_generation_brief_summary(topic or content), 100)
    elif bank == "chapter_briefs" or tool in {"sync_storyboard", "storyboard_sync"} or "## Unified Planning Packet" in content:
        content = _clean_chapter_brief_text(content)
        if not topic:
            first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
            topic = _compact_preview(first_line, 100)
    else:
        topic = _compact_preview(topic, 100)

    return topic, content


def _session_status_label(language: str, value: object) -> str:
    normalized = str(value or "").strip().lower()
    mapping = {
        "active": _lang_text(language, "进行中", "Active"),
        "confirmed": _lang_text(language, "已确认", "Confirmed"),
        "queued": _lang_text(language, "排队中", "Queued"),
        "running": _lang_text(language, "运行中", "Running"),
        "succeeded": _lang_text(language, "已完成", "Succeeded"),
        "failed": _lang_text(language, "失败", "Failed"),
        "canceled": _lang_text(language, "已取消", "Canceled"),
        "deleted": _lang_text(language, "已删除", "Deleted"),
        "new": _lang_text(language, "新建中", "New"),
    }
    return mapping.get(normalized, str(value or "").strip())


def _find_memory_bucket_item(index: Dict, bucket: str, item_id: str) -> Optional[Dict[str, object]]:
    items = index.get(bucket) if isinstance(index, dict) else None
    if not isinstance(items, list):
        return None
    target_id = str(item_id or "").strip()
    if not target_id:
        return None
    for item in items:
        if isinstance(item, dict) and str(item.get("id") or "").strip() == target_id:
            return item
    return None



def _nonempty_lines(text: str) -> List[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]



def _strip_list_prefix(text: str) -> str:
    return re.sub(r"^[\-?*#\d\s\.\)\(]+", "", str(text or "").strip())



def _parse_text_pairs(text: str) -> Dict[str, str]:
    pairs: Dict[str, str] = {}
    for line in _nonempty_lines(text):
        cleaned = _strip_list_prefix(line)
        for sep in ("?", ":"):
            if sep not in cleaned:
                continue
            key, value = cleaned.split(sep, 1)
            key = key.strip().lower()
            value = value.strip()
            if key and value and len(key) <= 24:
                pairs[key] = value
                break
    return pairs



def _field_from_aliases(attrs: Dict[str, object], pairs: Dict[str, str], aliases: List[str]) -> str:
    for alias in aliases:
        alias_key = alias.lower()
        if alias_key in attrs:
            value = _stringify_memory_value(attrs.get(alias_key))
            if value:
                return value
        if alias_key in pairs:
            value = _stringify_memory_value(pairs.get(alias_key))
            if value:
                return value
    return ""


def _normalize_entity_name(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).lower()


def _character_entry_chapter(item: Dict[str, object], attrs: Dict[str, object], pairs: Dict[str, str]) -> Optional[int]:
    for source in (attrs, pairs):
        for key in ("chapter", "chapter_no", "current_chapter"):
            raw = source.get(key) if isinstance(source, dict) else None
            if raw in (None, ""):
                continue
            match = re.search(r"\d+", str(raw))
            if match:
                return int(match.group(0))
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    raw_meta = metadata.get("chapter") if isinstance(metadata, dict) else None
    if raw_meta not in (None, ""):
        match = re.search(r"\d+", str(raw_meta))
        if match:
            return int(match.group(0))
    return None


def _is_character_record(name: str, raw_text: str, attrs: Dict[str, object]) -> bool:
    normalized = _normalize_entity_name(name)
    if not normalized:
        return False
    if normalized.endswith("_world_setting"):
        return False
    blocked_tokens = ("规则", "设定", "边界", "框架", "生态", "world_setting", "world state", "rule", "canon")
    lowered_name = str(name or "").lower()
    if any(token in lowered_name or token in str(name or "") for token in blocked_tokens):
        return False
    if _stringify_memory_value(attrs.get("role")):
        return True
    lowered_raw = str(raw_text or "").lower()
    if any(token in lowered_raw for token in ("world setting", "world state", "continuity fact", "canon fact")):
        return False
    if any(token in str(raw_text or "") for token in ("规则", "设定", "边界", "事实卡")):
        return False
    return True


def _character_change_summary(name: str, raw_text: str, attrs: Dict[str, object], pairs: Dict[str, str]) -> str:
    for aliases in (
        ["summary", "简介", "概述", "角色简介", "人物简介"],
        ["change", "变化", "状态变化", "growth", "arc", "弧光", "发展"],
        ["goal", "目标", "purpose", "want"],
        ["motivation", "动机", "驱动力", "desire"],
        ["conflict", "冲突", "压力", "risk"],
    ):
        value = _field_from_aliases(attrs, pairs, aliases)
        if value:
            return _compact_preview(value, 220)
    lines = [line for line in _nonempty_lines(raw_text) if name not in line]
    return _compact_preview(lines[0] if lines else raw_text, 220)


def _memory_index_path_for_run(run_id: str) -> str:
    candidates = _memory_index_candidates(run_id)
    for path in candidates:
        if path.exists():
            return str(path)
    return str(candidates[0]) if candidates else ""



def _build_storyboard_view(story_assets: Dict, language: str) -> Dict[str, object]:
    outline_cards = []
    spotlight = None
    for idx, item in enumerate(story_assets.get("outlines", []) or [], start=1):
        structure = item.get("structure") if isinstance(item.get("structure"), dict) else {}
        kind = str(structure.get("kind") or "").strip() or "outline"
        chapter = structure.get("chapter")
        title = str(structure.get("title") or "").strip()
        if not title:
            if kind == "global_outline":
                title = _lang_text(language, "全局大纲", "Global Outline")
            elif kind == "chapter_outline" and chapter:
                title = _lang_text(language, f"第 {chapter} 章大纲", f"Chapter {chapter} Outline")
            else:
                title = kind.replace("_", " ").strip().title()
        bucket = "global" if kind == "global_outline" or not chapter else "chapter"
        card = {
            "id": str(item.get("id") or ""),
            "title": title,
            "kind": kind,
            "bucket": bucket,
            "chapter": chapter,
            "summary": _compact_preview(item.get("content") or "", 420 if bucket == "global" else 280),
            "detail": str(item.get("content") or "").strip(),
            "meta": [
                segment
                for segment in [
                    _lang_text(language, f"第 {chapter} 章", f"Chapter {chapter}") if chapter else _lang_text(language, "全局", "Global"),
                    structure.get("phase"),
                    item.get("timestamp"),
                ]
                if segment
            ],
            "chip": _lang_text(language, "总纲", "Master") if bucket == "global" else _lang_text(language, "章节", "Chapter"),
        }
        outline_cards.append(card)
        if spotlight is None or bucket == "global":
            spotlight = card

    plot_points = []
    for idx, item in enumerate(story_assets.get("plot_points", []) or [], start=1):
        plot_points.append(
            {
                "index": idx,
                "title": item.get("position") or _lang_text(language, f"情节点 {idx}", f"Beat {idx}"),
                "summary": _compact_preview(item.get("content") or "", 240),
                "detail": str(item.get("content") or "").strip(),
                "timestamp": str(item.get("timestamp") or ""),
            }
        )

    chapter_outputs = []
    for item in story_assets.get("chapter_outputs", []) or []:
        chapter_no = item.get("chapter")
        title = (
            _lang_text(language, f"第 {chapter_no} 章", f"Chapter {chapter_no}")
            if chapter_no
            else (item.get("filename") or _lang_text(language, "章节文件", "Chapter file"))
        )
        chapter_outputs.append(
            {
                "chapter": chapter_no,
                "iteration": item.get("iteration"),
                "title": title,
                "filename": item.get("filename") or "",
                "summary": _compact_preview(item.get("content") or "", 260),
                "detail": str(item.get("content") or "").strip(),
            }
        )

    return {
        "spotlight_outline": spotlight,
        "outlines": outline_cards,
        "plot_points": plot_points,
        "chapter_outputs": chapter_outputs,
        "latest_chapter": story_assets.get("latest_chapter"),
    }



def _build_character_cards(story_assets: Dict, language: str) -> List[Dict[str, object]]:
    field_specs = [
        (_lang_text(language, "身份", "Role"), ["role", "identity", "身份", "定位", "职业", "position"]),
        (_lang_text(language, "目标", "Goal"), ["goal", "目标", "purpose", "want"]),
        (_lang_text(language, "动机", "Motivation"), ["motivation", "动机", "驱动力", "desire"]),
        (_lang_text(language, "冲突", "Conflict"), ["conflict", "冲突", "压力", "risk"]),
        (_lang_text(language, "关系", "Relationships"), ["relationships", "relation", "关系", "人际", "bond"]),
        (_lang_text(language, "边界", "Boundaries"), ["boundary", "boundaries", "底线", "禁忌", "限制"]),
    ]
    groups: Dict[str, Dict[str, object]] = {}
    for idx, item in enumerate(story_assets.get("characters", []) or [], start=1):
        attrs_raw = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        attrs = {str(key).strip().lower(): value for key, value in attrs_raw.items()} if isinstance(attrs_raw, dict) else {}
        raw_text = str(item.get("character_info") or item.get("content") or "").strip()
        pairs = _parse_text_pairs(raw_text)
        name = (
            item.get("character_name")
            or item.get("name")
            or _field_from_aliases(attrs, pairs, ["name", "character_name", "姓名", "名字", "角色名", "人物名"])
            or f"{_lang_text(language, '角色', 'Character')} {idx}"
        )
        display_name = str(name).strip()
        if not _is_character_record(display_name, raw_text, attrs):
            continue
        summary = _character_change_summary(display_name, raw_text, attrs, pairs)
        fields = [{"label": label, "value": _field_from_aliases(attrs, pairs, aliases)} for label, aliases in field_specs]
        tags = []
        for key, value in attrs.items():
            rendered = _stringify_memory_value(value)
            if not rendered:
                continue
            if any(rendered == field["value"] for field in fields if field["value"]):
                continue
            tags.append({"label": key, "value": rendered})
            if len(tags) >= 6:
                break
        group_key = _normalize_entity_name(display_name)
        timestamp = str(item.get("timestamp") or "")
        chapter = _character_entry_chapter(item, attrs, pairs)
        group = groups.setdefault(
            group_key,
            {
                "name": display_name,
                "summary": "",
                "raw_text": "",
                "timestamp": "",
                "fields_map": {},
                "tags_map": {},
                "changes_map": {},
            },
        )
        if timestamp >= str(group.get("timestamp") or ""):
            group["name"] = display_name
            group["summary"] = summary
            group["raw_text"] = raw_text
            group["timestamp"] = timestamp
        for field in fields:
            if field["value"]:
                group["fields_map"][field["label"]] = field["value"]
        for tag in tags:
            group["tags_map"][tag["label"]] = tag["value"]
        change_key = f"chapter:{chapter}" if chapter else f"entry:{item.get('id') or timestamp or idx}"
        current_change = group["changes_map"].get(change_key)
        next_change = {"chapter": chapter, "timestamp": timestamp, "summary": summary, "raw_text": raw_text}
        if not current_change or timestamp >= str(current_change.get("timestamp") or ""):
            group["changes_map"][change_key] = next_change
    cards: List[Dict[str, object]] = []
    for group in groups.values():
        changes = sorted(
            list(group["changes_map"].values()),
            key=lambda item: (str(item.get("timestamp") or ""), int(item.get("chapter") or 0)),
            reverse=True,
        )
        latest_chapter = next((item.get("chapter") for item in changes if item.get("chapter")), None)
        cards.append(
            {
                "name": str(group["name"]).strip(),
                "summary": _compact_preview(str(group["summary"] or ""), 220),
                "fields": [
                    {"label": label, "value": group["fields_map"].get(label)}
                    for label, _aliases in field_specs
                    if group["fields_map"].get(label)
                ],
                "tags": [{"label": key, "value": value} for key, value in list(group["tags_map"].items())[:6]],
                "raw_text": str(group["raw_text"] or "").strip(),
                "timestamp": str(group["timestamp"] or ""),
                "changes": changes[:8],
                "change_count": len(changes),
                "latest_chapter": latest_chapter,
            }
        )
    cards.sort(key=lambda item: (str(item.get("timestamp") or ""), str(item.get("name") or "")), reverse=True)
    return cards



def _build_world_cards(story_assets: Dict, language: str) -> Dict[str, List[Dict[str, object]]]:
    settings: List[Dict[str, object]] = []
    for idx, item in enumerate(story_assets.get("world_settings", []) or [], start=1):
        raw_text = str(item.get("setting_info") or item.get("content") or "").strip()
        pairs = _parse_text_pairs(raw_text)
        title = item.get("name") or pairs.get("设定名称") or pairs.get("名称") or pairs.get("name") or f"{_lang_text(language, '设定', 'Setting')} {idx}"
        fields = [
            {"label": _lang_text(language, "类别", "Category"), "value": pairs.get("类别") or pairs.get("类型") or pairs.get("category", "")},
            {"label": _lang_text(language, "规则", "Rule"), "value": pairs.get("规则") or pairs.get("rule", "")},
            {"label": _lang_text(language, "限制", "Boundary"), "value": pairs.get("限制") or pairs.get("边界") or pairs.get("boundary", "")},
            {"label": _lang_text(language, "影响", "Impact"), "value": pairs.get("影响") or pairs.get("impact", "")},
        ]
        lines = [line for line in _nonempty_lines(raw_text) if str(title) not in line]
        summary = lines[0] if lines else raw_text
        settings.append(
            {
                "title": str(title).strip(),
                "summary": _compact_preview(summary, 220),
                "fields": [field for field in fields if field["value"]],
                "raw_text": raw_text,
                "timestamp": item.get("timestamp") or "",
            }
        )
    facts: List[Dict[str, object]] = []
    for idx, item in enumerate(story_assets.get("fact_cards", []) or [], start=1):
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        title = meta.get("title") or item.get("card_type") or f"{_lang_text(language, '事实卡', 'Fact Card')} {idx}"
        facts.append(
            {
                "title": str(title).strip(),
                "type": item.get("card_type") or _lang_text(language, "通用", "General"),
                "summary": _compact_preview(item.get("content") or "", 220),
                "raw_text": str(item.get("content") or "").strip(),
                "timestamp": item.get("timestamp") or "",
            }
        )
    return {"settings": settings, "facts": facts}



def _memory_bank_meta(language: str) -> Dict[str, Dict[str, str]]:
    return {
        "session_profile": {"name": _lang_text(language, "会话画像", "Session Profile"), "desc": _lang_text(language, "记录当前会话状态、轮次、provider 和确认状态。", "Stores session state, round count, provider, and confirmation status.")},
        "language_profile": {"name": _lang_text(language, "语言配置", "Language Profile"), "desc": _lang_text(language, "记录中英文偏好与翻译模式。", "Stores language preference and translation mode.")},
        "user_preferences": {"name": _lang_text(language, "用户偏好", "User Preferences"), "desc": _lang_text(language, "记录你明确提出的风格、禁忌和工作要求。", "Captures your explicit style, taboo, and workflow requests.")},
        "task_briefs": {"name": _lang_text(language, "任务简报", "Task Briefs"), "desc": _lang_text(language, "保存当前写作 brief，供后续 loop 重复引用。", "Keeps the active writing brief available to later loop steps.")},
        "story_premise": {"name": _lang_text(language, "故事前提", "Story Premise"), "desc": _lang_text(language, "存放故事核心 premise 与题材设定。", "Stores the core premise and genre setup.")},
        "style_guide": {"name": _lang_text(language, "风格指南", "Style Guide"), "desc": _lang_text(language, "积累语气、节奏、视角和风格要求。", "Accumulates voice, pacing, POV, and style requirements.")},
        "chapter_briefs": {"name": _lang_text(language, "章节简报", "Chapter Briefs"), "desc": _lang_text(language, "保存章节级目标与任务分解。", "Stores chapter-level goals and task breakdowns.")},
        "scene_cards": {"name": _lang_text(language, "场景卡", "Scene Cards"), "desc": _lang_text(language, "保存场景级事件、冲突和目的。", "Stores scene-level events, conflicts, and purposes.")},
        "entity_state": {"name": _lang_text(language, "实体状态", "Entity State"), "desc": _lang_text(language, "保存角色、势力、物件等状态变化。", "Tracks state changes for characters, factions, and objects.")},
        "relationship_state": {"name": _lang_text(language, "关系状态", "Relationship State"), "desc": _lang_text(language, "追踪角色关系和情感张力。", "Tracks relationships and emotional tension.")},
        "world_state": {"name": _lang_text(language, "世界状态", "World State"), "desc": _lang_text(language, "记录世界规则、设定边界和变化。", "Stores world rules, boundaries, and changes.")},
        "continuity_facts": {"name": _lang_text(language, "连续性事实", "Continuity Facts"), "desc": _lang_text(language, "保存后续章节不能违背的事实卡。", "Stores canon facts that later chapters must respect.")},
        "tool_observations": {"name": _lang_text(language, "工具观察", "Tool Observations"), "desc": _lang_text(language, "记录本地工具执行后的观察结果。", "Keeps observations emitted by local tool actions.")},
        "decision_log": {"name": _lang_text(language, "决策日志", "Decision Log"), "desc": _lang_text(language, "保留 loop 的判断、问题和确认节点。", "Preserves loop decisions, questions, and confirmation checkpoints.")},
        "revision_notes": {"name": _lang_text(language, "修订笔记", "Revision Notes"), "desc": _lang_text(language, "保存需要修订的缺陷与目标。", "Stores issues and targets for revision passes.")},
        "working_set": {"name": _lang_text(language, "工作记忆", "Working Set"), "desc": _lang_text(language, "保存当前轮最需要保留在手边的分析。", "Keeps the most immediately relevant working analysis in play." )},
    }

def _memory_bank_group_specs(language: str) -> List[Dict[str, object]]:
    return [
        {
            "slug": "premise",
            "name": _lang_text(language, "故事前提", "Story Premise"),
            "description": _lang_text(language, "作品 premise、题材方向与最核心的故事命题。", "Core premise, genre direction, and the central story proposition."),
            "banks": ["story_premise"],
        },
        {
            "slug": "author_brief",
            "name": _lang_text(language, "作者要求", "Author Briefing"),
            "description": _lang_text(language, "任务简报、风格要求、用户偏好与双语配置。", "Task brief, style targets, user preferences, and bilingual configuration."),
            "banks": ["task_briefs", "style_guide", "user_preferences", "language_profile"],
        },
        {
            "slug": "chapter_planning",
            "name": _lang_text(language, "章节规划", "Chapter Planning"),
            "description": _lang_text(language, "章节目标、场景拆分和推进路线。", "Chapter goals, scene decomposition, and progression routes."),
            "banks": ["chapter_briefs", "scene_cards"],
        },
        {
            "slug": "revision_loop",
            "name": _lang_text(language, "修订循环", "Revision Loop"),
            "description": _lang_text(language, "修订目标、过程判断和当前工作记忆。", "Revision targets, loop decisions, and active working memory."),
            "banks": ["revision_notes", "working_set", "decision_log"],
        },
        {
            "slug": "canon_state",
            "name": _lang_text(language, "设定连续性", "Canon State"),
            "description": _lang_text(language, "角色、关系、世界状态与不能违背的事实。", "Characters, relationships, world state, and continuity facts."),
            "banks": ["entity_state", "relationship_state", "world_state", "continuity_facts"],
        },
        {
            "slug": "runtime",
            "name": _lang_text(language, "运行现场", "Runtime Trace"),
            "description": _lang_text(language, "会话状态与工具观察，帮助你理解系统此刻在想什么。", "Session state and tool observations that explain what the system is doing right now."),
            "banks": ["session_profile", "tool_observations"],
        },
    ]


def _serialize_claw_entry(entry: Dict) -> Dict[str, object]:
    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    display_topic, display_content = _display_claw_entry_text(entry)
    return {
        "id": str(entry.get("id") or ""),
        "topic": display_topic,
        "content": display_content,
        "timestamp": str(entry.get("timestamp") or ""),
        "chapter": metadata.get("chapter"),
        "kind": str(metadata.get("kind") or metadata.get("type") or ""),
        "source": str(metadata.get("source") or ""),
        "metadata": metadata,
    }


def _build_memory_bank_groups_from_index(index: Dict, language: str, *, entry_limit: int = 12) -> List[Dict[str, object]]:
    meta = _memory_bank_meta(language)
    claw = index.get("claw", {}) if isinstance(index, dict) else {}
    groups: List[Dict[str, object]] = []
    for spec in _memory_bank_group_specs(language):
        banks: List[Dict[str, object]] = []
        total_count = 0
        for bank in spec["banks"]:
            entries = list(claw.get(bank, []) or []) if isinstance(claw, dict) else []
            serialized_entries = [_serialize_claw_entry(item) for item in entries[-entry_limit:]]
            serialized_entries.reverse()
            latest = serialized_entries[0] if serialized_entries else {}
            total_count += len(entries)
            banks.append(
                {
                    "slug": bank,
                    "name": meta[bank]["name"],
                    "description": meta[bank]["desc"],
                    "count": len(entries),
                    "latest_preview": _compact_preview(latest.get("content") or "", 160) if latest else "",
                    "latest_topic": _compact_preview(latest.get("topic") or "", 80) if latest else "",
                    "entries": serialized_entries,
                }
            )
        groups.append(
            {
                "slug": spec["slug"],
                "name": spec["name"],
                "description": spec["description"],
                "count": total_count,
                "banks": banks,
            }
        )
    return groups


def _build_memory_bank_cards(memory_overview: Dict, language: str) -> List[Dict[str, object]]:
    claw_counts = memory_overview.get("claw_counts", {}) if isinstance(memory_overview, dict) else {}
    latest_claw = memory_overview.get("latest_claw", {}) if isinstance(memory_overview, dict) else {}
    meta = _memory_bank_meta(language)
    cards: List[Dict[str, object]] = []
    for slug, spec in meta.items():
        latest = latest_claw.get(slug) if isinstance(latest_claw, dict) else None
        latest_content = latest.get("content") if isinstance(latest, dict) else ""
        cards.append(
            {
                "slug": slug,
                "name": spec["name"],
                "description": spec["desc"],
                "count": int(claw_counts.get(slug, 0) or 0),
                "latest_preview": _compact_preview(latest_content or "", 180),
                "latest_topic": _compact_preview(latest.get("topic") or "", 100) if isinstance(latest, dict) else "",
                "timestamp": latest.get("timestamp") or "" if isinstance(latest, dict) else "",
            }
        )
    cards.sort(key=lambda item: (item["count"], item["name"]), reverse=True)
    return cards



def _build_agent_runtime(agent_catalog: List[Dict[str, str]], capability_catalog: List[Dict[str, object]], story_assets: Dict, memory_overview: Dict, language: str) -> List[Dict[str, object]]:
    enabled_actions = {str(item.get("manager_action") or "") for item in capability_catalog if item.get("enabled") and item.get("manager_action")}
    claw_counts = memory_overview.get("claw_counts", {}) if isinstance(memory_overview, dict) else {}
    cards: List[Dict[str, object]] = []
    for agent in agent_catalog:
        slug = str(agent.get("slug") or "")
        evidence_count = 0
        if slug == "openclaw_manager":
            evidence_count = len(enabled_actions)
        elif slug == "plot":
            evidence_count = len(story_assets.get("outlines", []) or []) + len(story_assets.get("plot_points", []) or [])
        elif slug == "character":
            evidence_count = len(story_assets.get("characters", []) or [])
        elif slug == "world":
            evidence_count = len(story_assets.get("world_settings", []) or []) + len(story_assets.get("fact_cards", []) or [])
        elif slug == "retrieval":
            evidence_count = sum(int(value or 0) for value in claw_counts.values())
        elif slug == "writer":
            evidence_count = len(story_assets.get("texts", []) or []) + len(story_assets.get("chapter_outputs", []) or [])
        elif slug in {"evaluator", "judge", "consistency_checker", "realtime_editor"}:
            evidence_count = int(claw_counts.get("revision_notes", 0) or 0) + int(claw_counts.get("decision_log", 0) or 0)
        else:
            evidence_count = int(claw_counts.get("working_set", 0) or 0)
        cards.append({
            "slug": slug,
            "name": agent.get("name") or slug,
            "role": agent.get("role") or "",
            "description": agent.get("desc") or "",
            "status": _lang_text(language, "活跃可用", "Live") if evidence_count else _lang_text(language, "待触发", "Idle"),
            "evidence_count": evidence_count,
        })
    return cards



def _build_mcp_surface(capability_catalog: List[Dict[str, object]], provider_count: int, memory_cards: List[Dict[str, object]], language: str) -> Dict[str, object]:
    local_tools = [item for item in capability_catalog if str(item.get("category") or "") in {_lang_text(language, "本地工具", "Local Tools"), 'Local Tools'}]
    enabled_tools = [item for item in local_tools if item.get("enabled")]
    external_connectors = [
        {"name": "Browser", "status": _lang_text(language, "未接入", "Not connected"), "detail": _lang_text(language, "还没有把浏览器自动化接进 MCP。", "Browser automation is not connected to MCP yet.")},
        {"name": "Filesystem", "status": _lang_text(language, "已由内部工具代理", "Handled internally"), "detail": _lang_text(language, "当前由本地 workspace tools 直接处理，而不是走外部 MCP server。", "Currently handled by local workspace tools instead of an external MCP server.")},
        {"name": "Publish", "status": _lang_text(language, "未接入", "Not connected"), "detail": _lang_text(language, "发布、导出和平台同步仍未接入。", "Publishing, export, and platform sync are not wired in yet.")},
    ]
    return {
        "provider_count": provider_count,
        "enabled_local_tools": enabled_tools,
        "memory_ready_banks": len([item for item in memory_cards if int(item.get("count", 0) or 0) > 0]),
        "external_connectors": external_connectors,
    }


def _build_style_profile(active_session: Optional[IdeaCopilotSession], latest_turn: Dict) -> Dict[str, List[str] | str]:
    base = (active_session.refined_idea if active_session and active_session.refined_idea else (active_session.original_idea if active_session else "")).strip()
    hints: List[str] = []
    for token in [
        "first person", "third person", "ensemble", "restrained", "lyrical", "dark", "cozy", "suspense",
        "fantasy", "romance", "science fiction", "thriller", "slow burn", "fast pace", "epic", "literary",
        "第一人称", "第三人称", "群像", "悬疑", "奇幻", "赛博", "治愈", "热血",
    ]:
        if token.lower() in base.lower():
            hints.append(token)
    questions = latest_turn.get("questions") if isinstance(latest_turn, dict) else []
    return {
        "summary": base or "No style summary yet. Start a session and clarify voice, tone, and pacing.",
        "tags": hints[:8],
        "questions": questions[:4] if isinstance(questions, list) else [],
    }
def _build_model_overview(
    provider_specs: Dict[str, ProviderSpec],
    cred_map: Dict[str, ApiCredential],
    custom_providers: List[ProviderConfig],
    language: str,
) -> Dict:
    providers = []
    for slug, spec in provider_specs.items():
        credential = cred_map.get(slug)
        providers.append(
            {
                "slug": slug,
                "label": spec.label or slug,
                "base_url": spec.base_url,
                "model": spec.model,
                "wire_api": spec.wire_api,
                "has_key": bool(credential),
                "key_hint": credential.key_hint if credential else _ui_text(language, "未保存", "Not saved"),
                "is_custom": any((row.slug or "") == slug for row in custom_providers),
            }
        )
    return {
        "providers": providers,
        "modelless_mode": _modelless_mode_enabled(),
        "notice": _modelless_notice(language) if _modelless_mode_enabled() else "",
    }



def _build_env_overview() -> List[Dict[str, str]]:
    keys = [
        "WEB_EXECUTION_MODE",
        "WEB_CLAW_MAX_STEPS",
        "WEB_MAX_ITERATIONS",
        "WEB_MAX_TOTAL_ITERATIONS",
        "WEB_FAST_MODE",
        "WEB_ENABLE_EVALUATOR",
        "WEB_ENABLE_RAG",
        "WEB_ENABLE_STATIC_KB",
        "APP_DATABASE_URL",
    ]
    overview = []
    for key in keys:
        overview.append({"key": key, "value": os.getenv(key, "") or "(default)"})
    return overview


def _console_context(request: Request, db: Session, user: User, active_nav: str) -> Dict:
    ui_language = _ui_language(request)

    def ui_text(zh: str, en: str) -> str:
        return _ui_text(ui_language, zh, en)

    provider_specs = _provider_specs_for_user(db, user.id)
    provider_list = list(provider_specs.keys())
    custom_providers = _list_custom_providers(db, user.id)
    creds = db.execute(select(ApiCredential).where(ApiCredential.user_id == user.id)).scalars().all()
    cred_map = {c.provider: c for c in creds}
    jobs = _load_console_jobs(db, user.id)
    idea_sessions = _load_console_sessions(db, user.id)
    compose_new = request.query_params.get("new", "").strip().lower() in {"1", "true", "yes", "on"}
    requested_session_id = request.query_params.get("session_id", "").strip()
    active_session = None
    if requested_session_id.isdigit():
        active_session = next((item for item in idea_sessions if item.id == int(requested_session_id)), None)
    chat_session = None if compose_new else active_session
    session_state = load_state(chat_session.conversation_json) if chat_session else {
        "messages": [],
        "refined_idea": "",
        "round": 0,
        "preferred_language": ui_language,
        "source_language": ui_language,
        "ui_language": ui_language,
        "translation_mode": "follow_input",
    }
    if not session_state.get("ui_language"):
        session_state["ui_language"] = ui_language

    latest_turn = latest_assistant_turn(session_state) if chat_session else {
        "role": "assistant",
        "analysis": ui_text(
            "欢迎来到 Claw 控制台。先告诉我你的目标、风格和限制，我会动态决定下一步。",
            "Welcome to the Claw console. Tell me your goals, style, and constraints, and I will decide the next step dynamically.",
        ),
        "questions": [
            ui_text("你当前最想完成的研究/写作任务是什么？", "What writing or research task matters most right now?"),
            ui_text("你希望 Claw 优先调度哪些能力？", "Which capabilities should Claw prioritize first?"),
        ],
        "readiness": 0,
        "ready_hint": ui_text(
            "先创建一个创意打磨会话，Claw 才能开始持续迭代。",
            "Start an idea-refinement session first so Claw can begin iterating continuously.",
        ),
    }
    session_job = None
    if chat_session and chat_session.final_job_id:
        session_job = next((job for job in jobs if job.id == chat_session.final_job_id), None)
    latest_job = session_job
    run_id = session_job.run_id if session_job and session_job.run_id else ""
    has_session_scope = bool(chat_session and run_id)
    memory_overview = _build_memory_overview(run_id) if has_session_scope else {
        "index": _empty_memory_index(),
        "counts": {key: 0 for key in ("texts", "outlines", "characters", "world_settings", "plot_points", "fact_cards")},
        "claw_counts": {bank: 0 for bank in MemorySystem.CLAW_BANKS},
        "latest_claw": {},
        "index_path": "",
    }
    workspace_files = _build_workspace_files(run_id)
    agent_catalog = _build_agent_catalog()
    capability_catalog = _build_capability_catalog(db, user.id, ui_language)
    story_assets = _build_story_assets(memory_overview, chat_session, session_job) if chat_session else _empty_story_assets()
    storyboard_view = _build_storyboard_view(story_assets, ui_language)
    character_cards = _build_character_cards(story_assets, ui_language)
    world_view = _build_world_cards(story_assets, ui_language)
    memory_bank_cards = _build_memory_bank_cards(memory_overview, ui_language)
    memory_bank_groups = _build_memory_bank_groups_from_index(memory_overview.get("index", {}), ui_language)
    workspace_bootstrap = _build_workspace_bootstrap(
        story_assets,
        memory_overview,
        memory_bank_groups,
        ui_language,
        download_job_id=int(chat_session.final_job_id or 0) if chat_session and chat_session.final_job_id else 0,
    )
    agent_runtime = _build_agent_runtime(_build_agent_catalog(), capability_catalog, story_assets, memory_overview, ui_language)
    style_profile = _build_style_profile(chat_session, latest_turn)
    model_overview = _build_model_overview(provider_specs, cred_map, custom_providers, ui_language)
    mcp_surface = _build_mcp_surface(capability_catalog, len(provider_list), memory_bank_cards, ui_language)
    env_overview = _build_env_overview()
    status_summary = {
        "api_health": (
            ui_text("无模型模式", "model-free mode")
            if _modelless_mode_enabled()
            else (ui_text("正常", "healthy") if provider_list else ui_text("未配置", "not configured"))
        ),
        "agent_mode": settings.execution_mode,
        "running_jobs": len([job for job in jobs if job.status == "running"]),
        "tool_count": len([key for key, value in memory_overview.get("claw_counts", {}).items() if value]),
        "active_sessions": len([session for session in idea_sessions if session.status not in {"canceled", "deleted"}]),
        "session_label": (
            f"#{chat_session.id}" if chat_session else ui_text("未选择", "None selected")
        ),
        "session_status": _session_status_label(ui_language, chat_session.status) if chat_session else ui_text("新建中", "New"),
        "claw_max_steps": settings.claw_max_steps,
        "memory_count": sum(memory_overview.get("counts", {}).values()),
        "chapter_outputs": len(story_assets.get("chapter_outputs") or []),
        "plot_points": len(story_assets.get("plot_points") or []),
        "characters": len(character_cards),
        "world_facts": len(story_assets.get("world_settings") or []),
    }
    current_path = _current_public_path(request)

    return {
        "request": request,
        "user": user,
        "active_nav": active_nav,
        "ui_language": ui_language,
        "current_path": current_path,
        "ui_texts": _console_texts(ui_language),
        "ui_text": ui_text,
        "jobs": jobs,
        "idea_sessions": idea_sessions,
        "active_session": active_session,
        "chat_session": chat_session,
        "compose_new": compose_new,
        "session_state": session_state,
        "messages": list(session_state.get("messages") or []),
        "latest_turn": latest_turn,
        "cred_map": cred_map,
        "providers": provider_list,
        "provider_specs": provider_specs,
        "custom_providers": custom_providers,
        "modelless_mode": _modelless_mode_enabled(),
        "modelless_notice": _modelless_notice(ui_language) if _modelless_mode_enabled() else "",
        "default_provider": settings.default_provider if settings.default_provider in provider_specs else (provider_list[0] if provider_list else ""),
        "workspace_files": workspace_files,
        "memory_overview": memory_overview,
        "memory_bank_cards": memory_bank_cards,
        "memory_bank_groups": memory_bank_groups,
        "workspace_bootstrap": workspace_bootstrap,
        "agent_catalog": agent_catalog,
        "agent_runtime": agent_runtime,
        "session_status_text": lambda value: _session_status_label(ui_language, value),
        "capability_catalog": capability_catalog,
        "story_assets": story_assets,
        "storyboard_view": storyboard_view,
        "character_cards": character_cards,
        "world_view": world_view,
        "style_profile": style_profile,
        "model_overview": model_overview,
        "mcp_surface": mcp_surface,
        "env_overview": env_overview,
        "status_summary": status_summary,
        "claw_config": {"execution_mode": settings.execution_mode, "max_steps": settings.claw_max_steps},
        "message": request.query_params.get("message", ""),
        "error": request.query_params.get("error", ""),
    }


def _console_page_context(request: Request, db: Session, user: User, active_nav: str, **extra: object) -> Dict:
    context = _console_context(request, db, user, active_nav=active_nav)
    context.update(extra)
    return context


def _idea_session_payload(session: IdeaCopilotSession, state: Dict, provider_label: str) -> Dict[str, object]:
    latest_turn = latest_assistant_turn(state)
    return {
        "session_id": session.id,
        "status": session.status,
        "final_job_id": session.final_job_id,
        "provider_label": provider_label,
        "round_count": int(session.round_count or 0),
        "readiness_score": int(session.readiness_score or 0),
        "refined_idea": str(state.get("refined_idea") or session.refined_idea or session.original_idea or ""),
        "messages": list(state.get("messages") or []),
        "latest_turn": latest_turn,
        "reply_pending": bool(state.get("reply_pending") or False),
        "reply_error": str(state.get("reply_error") or ""),
        "updated_at": session.updated_at.isoformat() if getattr(session, "updated_at", None) else "",
    }


def _looks_like_generation_intent(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False

    negative_markers = [
        "不要开始",
        "先别开始",
        "先不要生成",
        "先别生成",
        "not yet",
        "don't start",
        "do not start",
        "don't generate",
        "do not generate",
        "wait before generating",
    ]
    if any(marker in text for marker in negative_markers):
        return False

    positive_markers = [
        "开始生成",
        "开始写",
        "直接生成",
        "开始执行",
        "开始创作",
        "开始正文",
        "生成吧",
        "开工",
        "继续执行",
        "开始吧",
        "start generating",
        "start writing",
        "generate now",
        "go ahead",
        "proceed",
        "begin the job",
        "start the job",
        "start the run",
        "write now",
    ]
    if any(marker in text for marker in positive_markers):
        return True

    positive_patterns = [
        r"开始.*(生成|写|创作|执行|正文|章节)",
        r"(直接|现在|可以).*(生成|开写|写正文|创作)",
        r"(帮我|请).*完成.*(小说|故事|正文|文章)",
        r"(去整|整).*文章",
        r"进入.*(创作|执行).*(模式|阶段)?",
        r"继续.*(写|生成|创作)",
        r"可以.*(去写|开写|生成)",
        r"go ahead and (write|generate|start)",
        r"finish (the )?(novel|story|draft)",
        r"enter (execution|writing) mode",
        r"you can (start|write|generate) now",
        r"complete (this )?(novel|story|draft)",
    ]
    return any(re.search(pattern, text, re.I) for pattern in positive_patterns)


def _extract_json_object(text: str) -> Optional[str]:
    s = (text or "").strip()
    if not s:
        return None
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(s)):
        ch = s[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : idx + 1]
    return None


def _history_excerpt_for_generation(messages: List[Dict[str, Any]], limit: int = 8) -> str:
    rows: List[str] = []
    for item in messages[-limit:]:
        role = str(item.get("role") or "").strip().lower()
        if role == "user":
            rows.append(f"user: {str(item.get('content') or '').strip()[:300]}")
        elif role == "assistant":
            analysis = str(item.get("analysis") or "").strip()
            ready_hint = str(item.get("ready_hint") or "").strip()
            rows.append(f"assistant: {(analysis or ready_hint)[:300]}")
    return "\n".join(rows) if rows else "(no recent conversation)"


def _chinese_numeral_to_int(text: str) -> int:
    token = str(text or "").strip()
    if not token:
        return 0
    if token.isdigit():
        return int(token)
    numerals = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if token == "十":
        return 10
    if "十" in token:
        head, _, tail = token.partition("十")
        tens = numerals.get(head, 1 if head == "" else 0)
        ones = numerals.get(tail, 0 if tail == "" else -1)
        if tens > 0 and ones >= 0:
            return tens * 10 + ones
    total = 0
    for ch in token:
        if ch not in numerals:
            return 0
        total = total * 10 + numerals[ch]
    return total


def _extract_requested_chapter_count(message: str) -> int:
    text = str(message or "").strip()
    if not text:
        return 0
    digit_match = re.search(r"(\d+)\s*(?:章|chapter(?:s)?\b)", text, re.I)
    if digit_match:
        try:
            return max(0, int(digit_match.group(1)))
        except Exception:
            return 0
    zh_match = re.search(r"([零一二两三四五六七八九十]+)\s*章", text)
    if zh_match:
        return _chinese_numeral_to_int(zh_match.group(1))
    en_words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    word_match = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+chapters?\b", text, re.I)
    if word_match:
        return en_words.get(word_match.group(1).lower(), 0)
    return 0


def _normalize_generation_intent_payload(payload: Dict[str, Any], latest_user_reply: str) -> Dict[str, Any]:
    preferences = normalize_generation_preferences(
        {
            "generation_scope": payload.get("generation_scope"),
            "requested_chapters": payload.get("requested_chapters"),
            "chapter_pause_mode": payload.get("chapter_pause_mode"),
            "user_request": payload.get("user_request") or latest_user_reply,
        }
    )
    return {
        "should_start_generation": bool(payload.get("should_start_generation") or False),
        **preferences,
    }


def _heuristic_generation_intent(latest_user_reply: str) -> Dict[str, Any]:
    text = str(latest_user_reply or "").strip()
    lower = text.lower()
    requested_chapters = _extract_requested_chapter_count(text)

    negative_markers = [
        "不要开始", "先别开始", "先不要生成", "先别生成", "暂时别写", "not yet",
        "don't start", "do not start", "don't generate", "do not generate",
    ]
    all_markers = [
        "全部生成", "全书", "全部写完", "一口气写完", "直接写完", "一直生成", "全部章节",
        "the whole story", "whole book", "all chapters", "to the end", "run to end",
    ]
    chapter_by_chapter_markers = [
        "一章一章", "每章都问我", "每章停一下", "逐章确认", "chapter by chapter",
        "ask every chapter", "pause every chapter",
    ]
    run_to_end_markers = [
        "不要停", "别停", "继续到底", "直接到底", "run through", "keep going", "continue to the end",
    ]

    should_start = _looks_like_generation_intent(text) or bool(requested_chapters) or any(marker in lower for marker in all_markers)
    if any(marker in lower for marker in negative_markers):
        should_start = False

    payload: Dict[str, Any] = {
        "should_start_generation": should_start,
        "generation_scope": "auto",
        "requested_chapters": requested_chapters,
        "chapter_pause_mode": "manual_each_chapter",
        "user_request": text[:400],
    }
    if any(marker in lower for marker in chapter_by_chapter_markers):
        payload["generation_scope"] = "chapter_by_chapter"
        payload["chapter_pause_mode"] = "manual_each_chapter"
    elif any(marker in lower for marker in all_markers):
        payload["generation_scope"] = "all"
        payload["chapter_pause_mode"] = "run_to_end"
        payload["requested_chapters"] = 0
    elif requested_chapters > 0:
        payload["generation_scope"] = "limited"
        payload["chapter_pause_mode"] = "run_to_end"

    if any(marker in lower for marker in run_to_end_markers):
        payload["chapter_pause_mode"] = "run_to_end"
    return _normalize_generation_intent_payload(payload, text)


def _model_generation_intent(
    *,
    state: Dict[str, Any],
    original_idea: str,
    latest_user_reply: str,
    provider_slug: str,
    provider_base_url: str,
    provider_model: str,
    provider_wire_api: str,
    api_key: str,
) -> Optional[Dict[str, Any]]:
    if not api_key:
        return None
    preferred_language = str(state.get("preferred_language") or detect_language(latest_user_reply) or "en").lower()
    cfg = Config(require_api_key=False)
    cfg.language = preferred_language if preferred_language in {"zh", "en"} else "en"
    cfg.llm_provider = provider_slug
    cfg.api_key = api_key
    cfg.api_base_url = provider_base_url
    cfg.model_name = provider_model
    cfg.wire_api = provider_wire_api or "chat"
    cfg.temperature = 0.1
    cfg.max_tokens = 600
    client = LLMClient(cfg)
    system_prompt = """You detect generation-start intent for a writing copilot.
Return strict JSON only:
{
  "should_start_generation": false,
  "generation_scope": "auto",
  "requested_chapters": 0,
  "chapter_pause_mode": "manual_each_chapter",
  "user_request": ""
}
Rules:
- should_start_generation is true only when the latest user reply means the real writing run should start now.
- generation_scope must be one of auto, all, limited, chapter_by_chapter.
- requested_chapters is 0 unless the user clearly asks for a concrete chapter count.
- chapter_pause_mode must be manual_each_chapter or run_to_end.
- If uncertain, keep should_start_generation=false and generation_scope=auto.
"""
    user_prompt = f"""[original idea]
{original_idea[:1800]}

[current brief]
{str(state.get('refined_idea') or '')[:2400]}

[recent conversation]
{_history_excerpt_for_generation(list(state.get("messages") or []))}

[latest user reply]
{latest_user_reply}
"""
    try:
        raw = client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=400,
        )
        block = _extract_json_object(raw or "")
        if not block:
            return None
        parsed = json.loads(block)
        if not isinstance(parsed, dict):
            return None
        return _normalize_generation_intent_payload(parsed, latest_user_reply)
    except Exception:
        return None


def _analyze_generation_intent(
    *,
    state: Dict[str, Any],
    session: IdeaCopilotSession,
    latest_user_reply: str,
    spec: ProviderSpec,
    api_key: str,
) -> Dict[str, Any]:
    model_result = _model_generation_intent(
        state=state,
        original_idea=session.original_idea,
        latest_user_reply=latest_user_reply,
        provider_slug=spec.slug,
        provider_base_url=spec.base_url,
        provider_model=spec.model,
        provider_wire_api=spec.wire_api,
        api_key=api_key,
    )
    if model_result:
        return model_result
    return _heuristic_generation_intent(latest_user_reply)


def _generation_pref_summary(preferences: Dict[str, Any], preferred_language: str) -> Dict[str, str]:
    prefs = normalize_generation_preferences(preferences)
    requested = int(prefs.get("requested_chapters") or 0)
    scope = str(prefs.get("generation_scope") or "auto")
    pause_mode = str(prefs.get("chapter_pause_mode") or "manual_each_chapter")
    if preferred_language == "zh":
        if scope == "all":
            plan = "按你的意思连续生成整套已规划章节。"
        elif scope == "limited" and requested > 0:
            plan = f"按你的意思先连续生成 {requested} 章。"
        elif scope == "chapter_by_chapter":
            plan = "按你的意思逐章生成，并在每章后等你确认。"
        else:
            plan = "我会从当前 brief 进入正文生成。"
        pause_hint = (
            "执行中会连续推进，直到达到你要的范围。"
            if pause_mode == "run_to_end"
            else "每完成一章都会在当前聊天页出现 checkpoint，你可以继续、补充要求或停止。"
        )
        return {
            "analysis": f"收到，我现在切换到执行模式。{plan}",
            "ready_hint": pause_hint,
        }
    if scope == "all":
        plan = "I will run through the planned chapters continuously."
    elif scope == "limited" and requested > 0:
        plan = f"I will generate the next {requested} chapters first."
    elif scope == "chapter_by_chapter":
        plan = "I will write chapter by chapter and wait after each chapter."
    else:
        plan = "I will start the writing run from the current brief."
    pause_hint = (
        "The run will keep moving until it reaches your requested scope."
        if pause_mode == "run_to_end"
        else "After each chapter, a checkpoint will appear in the current chat so you can revise direction, add memory, or stop."
    )
    return {
        "analysis": f"Execution mode is starting now. {plan}",
        "ready_hint": pause_hint,
    }


def _assistant_turn_indicates_generation(turn: Dict[str, object]) -> bool:
    if not isinstance(turn, dict):
        return False

    readiness = int(turn.get("readiness", 0) or 0)
    questions = turn.get("questions") or []
    analysis = str(turn.get("analysis") or "").lower()
    ready_hint = str(turn.get("ready_hint") or "").lower()
    refined_idea = str(turn.get("refined_idea") or "").strip()

    signal_phrases = [
        "start the run",
        "starting the run",
        "enter execution",
        "switch from planning",
        "开始创作",
        "开始执行",
        "开始写",
        "开始正文",
        "进入执行",
        "进入创作",
        "可以开始",
        "直接生成",
    ]
    text = analysis + "\n" + ready_hint
    if any(phrase in text for phrase in signal_phrases):
        return True
    if readiness >= 90 and refined_idea and not list(questions):
        return True
    return False


def _start_generation_from_idea_session(db: Session, session: IdeaCopilotSession, user_id: int) -> GenerationJob:
    if session.final_job_id:
        existing = db.get(GenerationJob, session.final_job_id)
        if existing:
            return existing

    state = load_state(session.conversation_json)
    final_idea = build_generation_idea(session.original_idea, state)
    if not final_idea.strip():
        raise ValueError("Final idea is empty")

    job = _create_generation_job(db, user_id, session.provider, final_idea, commit=False)
    session.status = "confirmed"
    session.final_job_id = job.id
    session.refined_idea = str(state.get("refined_idea") or session.refined_idea or session.original_idea)
    session.round_count = int(state.get("round", 0) or 0)
    session.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    _remember_session_turn(session, state, confirmed=True, final_topic=final_idea)

    _start_generation_worker(job.id)
    return job


def _cancel_generation_job(job: Optional[GenerationJob], reason: str = "[user] canceled manually.") -> bool:
    if not job or job.status not in {"queued", "running"}:
        return False

    run_id = str(job.run_id or "").strip()
    if run_id:
        run_dir = _resolve_run_dir(run_id)
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "cancel.flag").write_text("1", encoding="utf-8")
        except Exception:
            pass

    job.status = "canceled"
    prefix = (job.error_message + "\n") if job.error_message else ""
    job.error_message = prefix + reason
    now = datetime.now(timezone.utc)
    job.finished_at = now
    job.updated_at = now
    return True


def _detach_job_from_sessions(db: Session, job_id: int) -> None:
    related_sessions = (
        db.execute(
            select(IdeaCopilotSession).where(IdeaCopilotSession.final_job_id == job_id)
        )
        .scalars()
        .all()
    )
    for session in related_sessions:
        session.final_job_id = None


def _run_idea_copilot_reply_worker(session_id: int) -> None:
    with SessionLocal() as db:
        session = db.get(IdeaCopilotSession, session_id)
        if not session:
            return
        user = db.get(User, session.user_id)
        if not user:
            return

        state = load_state(session.conversation_json)
        messages = list(state.get("messages") or [])
        latest_user_reply = ""
        for item in reversed(messages):
            if str(item.get("role") or "") == "user":
                latest_user_reply = str(item.get("content") or "")
                break

        provider_specs = _provider_specs_for_user(db, user.id)
        spec = provider_specs.get(session.provider)
        if not spec:
            state["reply_pending"] = False
            state["reply_error"] = "Provider is no longer available"
            session.conversation_json = dump_state(state)
            db.commit()
            return

        try:
            api_key = ""
            try:
                api_key = _provider_api_key(db, user.id, session.provider)
            except Exception:
                api_key = ""

            generation_intent = _analyze_generation_intent(
                state=state,
                session=session,
                latest_user_reply=latest_user_reply,
                spec=spec,
                api_key=api_key,
            )
            state["generation_preferences"] = merge_generation_preferences(state, generation_intent)

            if generation_intent.get("should_start_generation"):
                preferred_language = str(state.get("preferred_language") or detect_language(latest_user_reply) or "en").lower()
                if preferred_language not in {"zh", "en"}:
                    preferred_language = "en"
                summary = _generation_pref_summary(state.get("generation_preferences") or {}, preferred_language)
                turn = {
                    "role": "assistant",
                    "analysis": summary["analysis"],
                    "refined_idea": str(state.get("refined_idea") or session.refined_idea or session.original_idea or ""),
                    "questions": [],
                    "readiness": 100,
                    "ready_hint": summary["ready_hint"],
                    "language": preferred_language,
                    "style_targets": [],
                    "memory_targets": [],
                }
                state = append_assistant_turn(state, turn)
                state["reply_pending"] = False
                state["reply_error"] = ""
                session.conversation_json = dump_state(state)
                session.refined_idea = str(state.get("refined_idea") or session.refined_idea or session.original_idea)
                session.round_count = int(state.get("round", 0) or 0)
                session.readiness_score = 100
                db.commit()
                _remember_session_turn(session, state, turn=turn)
                _start_generation_from_idea_session(db, session, user.id)
                return

            api_key = api_key or _provider_api_key(db, user.id, session.provider)
            agent = IdeaCopilotAgent(spec, api_key)
            turn = agent.generate_turn(
                original_idea=session.original_idea,
                state=state,
                latest_user_reply=latest_user_reply,
            )
            state = append_assistant_turn(state, turn)
            state["reply_pending"] = False
            state["reply_error"] = ""
            session.conversation_json = dump_state(state)
            session.refined_idea = str(state.get("refined_idea") or session.refined_idea or session.original_idea)
            session.round_count = int(state.get("round", 0) or 0)
            session.readiness_score = int(turn.get("readiness", 0) or 0)
            db.commit()
            _remember_session_turn(session, state, turn=turn)
            if _assistant_turn_indicates_generation(turn):
                session = db.get(IdeaCopilotSession, session_id)
                if session:
                    session.readiness_score = max(int(turn.get("readiness", 0) or 0), 100)
                    db.commit()
                    _start_generation_from_idea_session(db, session, user.id)
        except Exception as exc:
            state = load_state(session.conversation_json)
            state["reply_pending"] = False
            state["reply_error"] = str(exc)
            session.conversation_json = dump_state(state)
            db.commit()


def _start_idea_copilot_reply_worker(session_id: int) -> None:
    worker = threading.Thread(target=_run_idea_copilot_reply_worker, args=(session_id,), daemon=True)
    worker.start()



def _create_generation_job(
    db: Session,
    user_id: int,
    provider: str,
    idea: str,
    *,
    commit: bool = True,
) -> GenerationJob:
    job = GenerationJob(
        user_id=user_id,
        provider=provider,
        idea=idea,
        status="queued",
    )
    db.add(job)
    if commit:
        db.commit()
        db.refresh(job)
    else:
        db.flush()
    return job


def _start_generation_worker(job_id: int) -> None:
    worker = threading.Thread(target=run_generation_job, args=(job_id,), daemon=True)
    worker.start()


def _extract_bearer_token(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return ""


def _require_agent_token(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> None:
    expected = str(settings.agent_api_key or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent API is disabled. Set APP_AGENT_API_KEY to enable /api/v1 endpoints.",
        )
    supplied = str(x_api_key or "").strip() or _extract_bearer_token(authorization)
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent API key")


def _agent_user(db: Session) -> User:
    email = settings.agent_user_email
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user:
        return user
    user = User(email=email, password_hash="agent-api")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


async def _json_payload(request: Request) -> Dict[str, object]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expected JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expected JSON object")
    return payload


def _payload_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _payload_text(payload: Dict[str, object], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _select_agent_provider(db: Session, user_id: int, raw_provider: str) -> str:
    provider_specs = _all_provider_specs_for_user(db, user_id)
    provider = normalize_slug(raw_provider or settings.default_provider)
    if not provider and provider_specs:
        provider = next(iter(provider_specs.keys()))
    if provider not in provider_specs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported provider: {provider or raw_provider}")
    return provider


def _build_agent_idea(payload: Dict[str, object]) -> str:
    idea = _payload_text(payload, "premise", "brief", "idea", "story", "summary")
    if not idea:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing story premise. Use premise, brief, or idea.")

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    metadata_lines: List[str] = []
    for key in (
        "title",
        "genre",
        "tone",
        "audience",
        "style",
        "constraints",
        "preferred_language",
        "source_language",
        "requested_chapters",
        "chapter_pause_mode",
        "generation_scope",
    ):
        value = payload.get(key, metadata.get(key))
        if value is None:
            continue
        text = str(value).strip()
        if text:
            metadata_lines.append(f"{key}: {text}")

    if not metadata_lines:
        return idea
    return f"{idea}\n\nAgent API metadata:\n" + "\n".join(metadata_lines)


def _upsert_api_key(db: Session, user_id: int, provider: str, api_key: str) -> ApiCredential:
    key = str(api_key or "").strip()
    if not key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="api_key cannot be empty")

    cred = db.execute(
        select(ApiCredential).where(
            ApiCredential.user_id == user_id,
            ApiCredential.provider == provider,
        )
    ).scalar_one_or_none()

    encrypted = encrypt_api_key(key)
    if cred:
        cred.encrypted_key = encrypted
        cred.key_hint = _mask_hint(key)
    else:
        cred = ApiCredential(
            user_id=user_id,
            provider=provider,
            encrypted_key=encrypted,
            key_hint=_mask_hint(key),
        )
        db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


def _agent_job(db: Session, user_id: int, story_id: int) -> GenerationJob:
    job = db.get(GenerationJob, story_id)
    if not job or job.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")
    return job


def _start_agent_job(db: Session, user_id: int, job: GenerationJob) -> GenerationJob:
    if _modelless_mode_enabled():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generation is disabled because WEB_MODELLESS_MODE=1. Set WEB_MODELLESS_MODE=0 before starting agent runs.",
        )
    provider_specs = _provider_specs_for_user(db, user_id)
    if job.provider not in provider_specs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported provider: {job.provider}")
    try:
        _provider_api_key(db, user_id, job.provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if job.status == "queued":
        _start_generation_worker(job.id)
    elif job.status in {"running", "succeeded"}:
        return job
    else:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot start story with status {job.status}")
    db.refresh(job)
    return job


def _job_progress_payload(job: GenerationJob) -> Dict[str, object]:
    worker_log_text = ""
    progress_log_text = ""
    run_dir: Optional[Path] = None
    chapters: List[Dict] = []
    if job.run_id:
        run_dir = _resolve_run_dir(job.run_id)
        worker_log_text = _tail_text(run_dir / "worker.log")
        progress_log_text = _tail_text(run_dir / "progress.log")
        chapters = _load_chapter_outputs(run_dir)
    try:
        progress_snapshot = _build_progress_snapshot(job, run_dir, worker_log_text, progress_log_text)
    except Exception:
        progress_snapshot = _default_progress_snapshot(_job_language(job))
    return {
        "progress_snapshot": progress_snapshot,
        "chapter_count": len(chapters),
        "worker_log_tail": worker_log_text,
        "progress_log_tail": progress_log_text,
    }


def _api_job_payload(job: GenerationJob, *, include_logs: bool = False) -> Dict[str, object]:
    progress = _job_progress_payload(job)
    payload = {
        "story_id": job.id,
        "job_id": job.id,
        "provider": job.provider,
        "status": job.status,
        "run_id": job.run_id or "",
        "premise": job.idea,
        "result_excerpt": job.result_excerpt or "",
        "error_message": job.error_message or "",
        "output_path": job.output_path or "",
        "created_at": job.created_at.isoformat() if job.created_at else "",
        "updated_at": job.updated_at.isoformat() if job.updated_at else "",
        "finished_at": job.finished_at.isoformat() if job.finished_at else "",
        "chapter_count": progress["chapter_count"],
        "progress_snapshot": progress["progress_snapshot"],
    }
    if include_logs:
        payload["worker_log_tail"] = progress["worker_log_tail"]
        payload["progress_log_tail"] = progress["progress_log_tail"]
    return payload


def _api_chapters_payload(job: GenerationJob, include_content: bool = True) -> List[Dict[str, object]]:
    if not job.run_id:
        return []
    chapters = _load_chapter_outputs(_resolve_run_dir(job.run_id))
    if include_content:
        return chapters
    return [{k: v for k, v in item.items() if k != "content"} for item in chapters]


@app.get("/api/v1/health")
def api_v1_health(_: None = Depends(_require_agent_token)):
    return {"ok": True, "modelless_mode": _modelless_mode_enabled()}


@app.get("/api/v1/providers")
def api_v1_providers(_: None = Depends(_require_agent_token), db: Session = Depends(get_db)):
    user = _agent_user(db)
    provider_specs = _all_provider_specs_for_user(db, user.id)
    rows = db.execute(select(ApiCredential).where(ApiCredential.user_id == user.id)).scalars().all()
    cred_map = {row.provider: row for row in rows}
    providers = []
    for slug, spec in provider_specs.items():
        configured = bool(slug in cred_map or _env_api_key_for_provider(slug))
        providers.append(
            {
                "slug": slug,
                "label": spec.label,
                "base_url": spec.base_url,
                "model": spec.model,
                "wire_api": spec.wire_api,
                "has_api_key": configured,
                "key_hint": cred_map[slug].key_hint if slug in cred_map else ("env" if _env_api_key_for_provider(slug) else ""),
            }
        )
    return {"modelless_mode": _modelless_mode_enabled(), "default_provider": settings.default_provider, "providers": providers}


@app.post("/api/v1/providers")
async def api_v1_save_provider(request: Request, _: None = Depends(_require_agent_token), db: Session = Depends(get_db)):
    user = _agent_user(db)
    payload = await _json_payload(request)
    slug = normalize_slug(_payload_text(payload, "slug", "provider"))
    base_url = _payload_text(payload, "base_url")
    model = _payload_text(payload, "model")
    label = _payload_text(payload, "label") or slug.upper()
    wire_api = normalize_wire_api(_payload_text(payload, "wire_api", "wire_mode") or "chat")
    if not is_valid_slug(slug):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid provider slug")
    if not base_url or not model:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="base_url and model are required")

    row = db.execute(
        select(ProviderConfig).where(
            ProviderConfig.user_id == user.id,
            ProviderConfig.slug == slug,
        )
    ).scalar_one_or_none()
    if row:
        row.label = label
        row.base_url = base_url
        row.model = model
        row.wire_api = wire_api
    else:
        row = ProviderConfig(user_id=user.id, slug=slug, label=label, base_url=base_url, model=model, wire_api=wire_api)
        db.add(row)
    db.commit()

    api_key = _payload_text(payload, "api_key")
    if api_key:
        _upsert_api_key(db, user.id, slug, api_key)
    return {"ok": True, "provider": {"slug": slug, "label": label, "base_url": base_url, "model": model, "wire_api": wire_api}}


@app.post("/api/v1/providers/{provider}/api-key")
async def api_v1_save_provider_key(provider: str, request: Request, _: None = Depends(_require_agent_token), db: Session = Depends(get_db)):
    user = _agent_user(db)
    provider = _select_agent_provider(db, user.id, provider)
    payload = await _json_payload(request)
    api_key = _payload_text(payload, "api_key", "key", "token")
    cred = _upsert_api_key(db, user.id, provider, api_key)
    return {"ok": True, "provider": provider, "key_hint": cred.key_hint}


@app.post("/api/v1/stories")
async def api_v1_create_story(request: Request, _: None = Depends(_require_agent_token), db: Session = Depends(get_db)):
    user = _agent_user(db)
    payload = await _json_payload(request)
    provider = _select_agent_provider(db, user.id, _payload_text(payload, "provider"))
    idea = _build_agent_idea(payload)
    job = _create_generation_job(db, user.id, provider, idea)
    if _payload_bool(payload.get("start"), default=_payload_bool(payload.get("auto_start"), default=False)):
        job = _start_agent_job(db, user.id, job)
    return JSONResponse(_api_job_payload(job), status_code=status.HTTP_201_CREATED)


@app.get("/api/v1/stories/{story_id}")
def api_v1_get_story(
    story_id: int,
    include_logs: bool = False,
    _: None = Depends(_require_agent_token),
    db: Session = Depends(get_db),
):
    user = _agent_user(db)
    job = _agent_job(db, user.id, story_id)
    return _api_job_payload(job, include_logs=include_logs)


@app.post("/api/v1/stories/{story_id}/start")
def api_v1_start_story(story_id: int, _: None = Depends(_require_agent_token), db: Session = Depends(get_db)):
    user = _agent_user(db)
    job = _agent_job(db, user.id, story_id)
    job = _start_agent_job(db, user.id, job)
    return _api_job_payload(job)


@app.post("/api/v1/stories/{story_id}/cancel")
def api_v1_cancel_story(story_id: int, _: None = Depends(_require_agent_token), db: Session = Depends(get_db)):
    user = _agent_user(db)
    job = _agent_job(db, user.id, story_id)
    canceled = _cancel_generation_job(job, reason=f"[agent-api] canceled via /api/v1/stories/{story_id}/cancel.")
    if canceled:
        db.commit()
    return {"ok": True, "canceled": canceled, "story": _api_job_payload(job)}


@app.get("/api/v1/stories/{story_id}/chapters")
def api_v1_story_chapters(
    story_id: int,
    include_content: bool = True,
    _: None = Depends(_require_agent_token),
    db: Session = Depends(get_db),
):
    user = _agent_user(db)
    job = _agent_job(db, user.id, story_id)
    chapters = _api_chapters_payload(job, include_content=include_content)
    return {"story_id": job.id, "status": job.status, "run_id": job.run_id or "", "chapter_count": len(chapters), "chapters": chapters}


@app.get("/api/v1/stories/{story_id}/chapters/{chapter_no}")
def api_v1_story_chapter(story_id: int, chapter_no: int, _: None = Depends(_require_agent_token), db: Session = Depends(get_db)):
    user = _agent_user(db)
    job = _agent_job(db, user.id, story_id)
    if not job.run_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No chapter output available yet")
    chapter_path = _latest_chapter_file(_resolve_run_dir(job.run_id), chapter_no)
    if not chapter_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter output not found")
    content = chapter_path.read_text(encoding="utf-8", errors="replace")
    return {"story_id": job.id, "chapter": chapter_no, "filename": chapter_path.name, "content": content}


@app.get("/api/v1/stories/{story_id}/export")
def api_v1_story_export(story_id: int, _: None = Depends(_require_agent_token), db: Session = Depends(get_db)):
    user = _agent_user(db)
    job = _agent_job(db, user.id, story_id)
    file_name = f"story_{job.id}_{job.run_id or 'no_run'}_export.txt"
    if job.output_path:
        out_path = Path(job.output_path)
        if out_path.exists() and out_path.is_file():
            return FileResponse(str(out_path), media_type="text/plain; charset=utf-8", filename=file_name)

    chapters = _api_chapters_payload(job, include_content=True)
    if not chapters:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No output available yet")
    parts = []
    for item in chapters:
        parts.append(f"Chapter {item.get('chapter', '?')}\n\n{str(item.get('content') or '').strip()}")
    merged = ("\n\n" + ("=" * 60) + "\n\n").join(parts)
    return PlainTextResponse(
        merged,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _default_progress_snapshot(language: str = "en") -> Dict:
    return {
        "phase": "running",
        "phase_label": _lang_text(language, "运行中", "Running"),
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

def _parse_progress_log(progress_log_text: str, language: str = "en") -> Dict:
    snapshot = {
        "current_chapter": 0,
        "planned_total": 0,
        "chapter_words": 0,
        "total_words": 0,
        "phase_note": "",
        "latest_event": "",
        "latest_event_label": "",
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

                label = _event_label(event_name, language)
                formatted_detail = _format_progress_detail(detail, language=language)
                short_detail = _compact_preview(formatted_detail, 160) if formatted_detail else ""
                snapshot["latest_event"] = event_name
                snapshot["latest_event_label"] = label
                snapshot["phase_note"] = f"{label}: {short_detail}" if short_detail else label
            except Exception:
                pass
    return snapshot


def _format_progress_detail(detail: str, language: str = "en") -> str:
    detail = str(detail or "").strip()
    if not detail:
        return ""

    key_labels = {
        "count": _lang_text(language, "数量", "Count"),
        "mode": _lang_text(language, "模式", "Mode"),
        "words": _lang_text(language, "字数", "Words"),
        "min": _lang_text(language, "最小值", "Min"),
        "max": _lang_text(language, "最大值", "Max"),
        "target": _lang_text(language, "目标", "Target"),
        "topic": _lang_text(language, "主题", "Topic"),
        "texts": _lang_text(language, "文本", "Texts"),
        "outlines": _lang_text(language, "大纲", "Outlines"),
        "characters": _lang_text(language, "人物", "Characters"),
        "world_settings": _lang_text(language, "世界设定", "World settings"),
        "plot_points": _lang_text(language, "情节点", "Plot points"),
        "fact_cards": _lang_text(language, "事实卡", "Fact cards"),
        "still_below_min": _lang_text(language, "仍低于下限", "Still below minimum"),
    }
    mode_labels = {
        "shrink_to_range": _lang_text(language, "压缩到范围内", "Shrink to range"),
        "truncate_fallback": _lang_text(language, "截断兜底", "Truncate fallback"),
        "expand_to_min": _lang_text(language, "扩写到下限", "Expand to minimum"),
        "final_truncate": _lang_text(language, "最终截断", "Final truncate"),
    }

    if "=" not in detail:
        return detail

    parts: List[str] = []
    for item in re.split(r"\s*\|\s*|\s*,\s*", detail):
        if not item:
            continue
        if "=" not in item:
            parts.append(item)
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        label = key_labels.get(key, key.replace("_", " "))
        if key == "mode":
            value = mode_labels.get(value, value)
        parts.append(f"{label}: {value}")
    return " | ".join(parts) if parts else detail


def _render_progress_log(progress_log_text: str, language: str = "en") -> str:
    if not progress_log_text:
        return ""

    rendered: List[str] = []
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
                rendered.append(
                    _lang_text(
                        language,
                        f"章节 {parts.get('chapter', '0')} | 本章字数: {parts.get('words', '0')} | 计划总章节: {parts.get('planned_total', '0')} | 目标: {parts.get('target', '0')} | 最小值: {parts.get('min', '0')} | 最大值: {parts.get('max', '0')} | 主题: {parts.get('topic', '')}",
                        f"Chapter {parts.get('chapter', '0')} | Chapter words: {parts.get('words', '0')} | Planned total: {parts.get('planned_total', '0')} | Target: {parts.get('target', '0')} | Min: {parts.get('min', '0')} | Max: {parts.get('max', '0')} | Topic: {parts.get('topic', '')}",
                    )
                )
            except Exception:
                rendered.append(line)
            continue
        if line.startswith("total_words="):
            try:
                total = line.split("=", 1)[1].strip()
                rendered.append(_lang_text(language, f"累计字数: {total}", f"Total words: {total}"))
            except Exception:
                rendered.append(line)
            continue
        if line.startswith("[event]"):
            try:
                parts = [seg.strip() for seg in line.split("|")]
                if len(parts) >= 2:
                    event_name = parts[1]
                    timestamp = parts[0].replace("[event]", "").strip()
                    chapter_no = ""
                    detail_parts: List[str] = []
                    for seg in parts[2:]:
                        if seg.startswith("chapter "):
                            chapter_no = seg.split(" ", 1)[1].strip()
                        elif seg:
                            detail_parts.append(seg)
                    label = _event_label(event_name, language)
                    detail = _format_progress_detail(" | ".join(detail_parts), language)
                    chapter_label = (
                        _lang_text(language, f"章节 {chapter_no}", f"Chapter {chapter_no}")
                        if chapter_no else ""
                    )
                    segments = [item for item in [timestamp, label, chapter_label, detail] if item]
                    rendered.append(" | ".join(segments))
                    continue
            except Exception:
                pass
        rendered.append(line)
    return "\n".join(rendered)


def _job_detail_texts(language: str) -> Dict[str, str]:
    return {
        "page_title": _lang_text(language, "NovelClaw 运行页", "NovelClaw Run"),
        "page_subtitle": _lang_text(language, "这里展示 NovelClaw 的实时执行状态、Claw 动作轨迹、章节产出和最终结果。", "This page shows NovelClaw's live execution state, Claw action trace, chapter outputs, and final result."),
        "job_title": _lang_text(language, "NovelClaw 运行", "NovelClaw Run"),
        "provider": _lang_text(language, "模型提供方", "Provider"),
        "status": _lang_text(language, "状态", "Status"),
        "status_queued": _lang_text(language, "排队中", "Queued"),
        "status_running": _lang_text(language, "运行中", "Running"),
        "status_succeeded": _lang_text(language, "已完成", "Succeeded"),
        "status_failed": _lang_text(language, "失败", "Failed"),
        "status_canceled": _lang_text(language, "已取消", "Canceled"),
        "status_unknown": _lang_text(language, "未知", "Unknown"),
        "cancel_job": _lang_text(language, "取消本次运行", "Cancel this run"),
        "job_input": _lang_text(language, "当前写作 brief", "Current writing brief"),
        "run_id": _lang_text(language, "运行 ID", "Run ID"),
        "output_path": _lang_text(language, "输出路径", "Output Path"),
        "download_output": _lang_text(language, "下载完整结果", "Download full output"),
        "download_chapters": _lang_text(language, "下载全部章节（zip）", "Download all chapters (.zip)"),
        "execution_status": _lang_text(language, "Claw 执行状态", "Claw execution status"),
        "phase": _lang_text(language, "阶段", "Phase"),
        "elapsed": _lang_text(language, "已耗时", "Elapsed"),
        "idle": _lang_text(language, "空闲时长", "Idle"),
        "current_action": _lang_text(language, "当前动作", "Current action"),
        "chapter_progress": _lang_text(language, "章节进度", "Chapter progress"),
        "chapter_words": _lang_text(language, "当前章节字数", "Chapter words"),
        "total_words": _lang_text(language, "累计字数", "Total words"),
        "memory": _lang_text(language, "动态记忆", "Dynamic memory"),
        "outlines": _lang_text(language, "大纲", "Outlines"),
        "texts": _lang_text(language, "正文", "Texts"),
        "characters": _lang_text(language, "角色", "Characters"),
        "worlds": _lang_text(language, "世界设定", "Worlds"),
        "facts": _lang_text(language, "事实卡", "Facts"),
        "live_progress": _lang_text(language, "实时进度", "Live progress"),
        "live_progress_hint": _lang_text(language, "这里显示的是真实工作进程输出，不是浏览器轮询日志。", "This shows real worker output, not browser polling logs."),
        "no_worker_log": _lang_text(language, "还没有工作进程日志。", "No worker log yet."),
        "progress_log": _lang_text(language, "进度日志", "Progress log"),
        "no_progress_log": _lang_text(language, "还没有进度日志。", "No progress log yet."),
        "agent_trace": _lang_text(language, "Claw 动作轨迹", "Claw action trace"),
        "agent_trace_hint": _lang_text(language, "这里会把 progress.log 里的关键事件转成可读步骤，让你看到 Claw 正在调用哪些能力。", "This turns key progress events into a readable step trace so you can see which capabilities Claw is using."),
        "no_agent_trace": _lang_text(language, "还没有 Claw 动作事件。", "No Claw events yet."),
        "chapter_results": _lang_text(language, "章节结果", "Chapter results"),
        "chapter_results_hint": _lang_text(language, "这里会显示每章当前最新的定稿内容，并在运行中自动刷新。", "Shows the latest finalized content for each chapter and auto-refreshes while the run is active."),
        "chapter": _lang_text(language, "章节", "Chapter"),
        "iteration": _lang_text(language, "轮次", "Iteration"),
        "download_chapter": _lang_text(language, "下载章节", "Download chapter"),
        "no_chapter_output": _lang_text(language, "还没有章节输出。", "No chapter output yet."),
        "error": _lang_text(language, "错误", "Error"),
        "generated_text": _lang_text(language, "最终结果", "Final result"),
        "result": _lang_text(language, "结果", "Result"),
        "result_pending": _lang_text(language, "运行仍在继续，或者结果尚未写出。请稍后刷新。", "The run is still active or has not produced a final result yet. Refresh in a few seconds."),
        "back_dashboard": _lang_text(language, "返回 NovelClaw 工作台", "Back to NovelClaw workspace"),
        "back_chat": _lang_text(language, "回到当前会话", "Back to current chat"),
        "stall_fallback": _lang_text(language, "检测到可能卡住，请查看工作进程日志。", "Possible stall detected, please check worker logs."),
        "trace_openclaw": _lang_text(language, "OpenClaw 模式", "OpenClaw mode"),
        "trace_openclaw_detail": _lang_text(language, "NovelClaw 已切换到原生 Claw 循环，不再先走固定 workflow 种子。", "NovelClaw has switched to the native Claw loop instead of seeding a fixed workflow first."),
        "trace_loop": _lang_text(language, "Claw 循环", "Claw loop"),
        "trace_decision": _lang_text(language, "动作决策", "Action decision"),
        "trace_action": _lang_text(language, "执行动作", "Action"),
        "trace_result": _lang_text(language, "动作结果", "Result"),
        "trace_candidate": _lang_text(language, "候选稿更新", "Candidate update"),
        "trace_ready": _lang_text(language, "满足收敛条件", "Ready to finalize"),
        "trace_complete": _lang_text(language, "Claw 循环完成", "Claw loop complete"),
    }

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
        ("[system] 工作进程已启动", "worker_started"),
        ("[IdeaAnalyzer]", "idea_analyzing"),
        ("[创意分析]", "idea_analyzing"),
        ("[Analyzer]", "task_analyzing"),
        ("[任务分析]", "task_analyzing"),
        ("[Organizer]", "planning"),
        ("[规划器]", "planning"),
        ("[Outline]", "outline_building"),
        ("[大纲]", "outline_building"),
        ("[写作Agent]", "writing"),
        ("[Writer Agent]", "writing"),
        ("[Memory]", "memory_storing"),
        ("[记忆]", "memory_storing"),
        ("[TurningPoint]", "turning_point"),
        ("[转折点]", "turning_point"),
        ("[Consistency]", "consistency_check"),
        ("[一致性]", "consistency_check"),
        ("[RealtimeEditor]", "editing"),
        ("[实时编辑]", "editing"),
        ("[Reward]", "reward_calc"),
        ("[评估]", "reward_calc"),
        ("[Executor] 已完成计划章节数", "finishing"),
        ("[Executor] Reached the planned chapter count", "finishing"),
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
        "[system]",
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


def _phase_label(phase: str, language: str = "en") -> str:
    if phase.startswith("agent_") and phase.endswith("_done"):
        return _lang_text(language, "Agent 步骤完成", "Agent step done")
    if phase.startswith("agent_"):
        return _lang_text(language, "Agent 运行中", "Agent running")
    mapping = {
        "queued": _lang_text(language, "排队中", "Queued"),
        "running": _lang_text(language, "运行中", "Running"),
        "succeeded": _lang_text(language, "已成功", "Succeeded"),
        "failed": _lang_text(language, "失败", "Failed"),
        "canceled": _lang_text(language, "已取消", "Canceled"),
        "waiting_worker": _lang_text(language, "等待 Worker 启动", "Waiting worker start"),
        "worker_started": _lang_text(language, "Worker 已启动", "Worker started"),
        "idea_analyzing": _lang_text(language, "正在分析创意", "Analyzing idea"),
        "task_analyzing": _lang_text(language, "正在分析任务", "Analyzing task"),
        "planning": _lang_text(language, "正在规划", "Planning"),
        "outline_building": _lang_text(language, "正在构建大纲", "Building outline"),
        "writing": _lang_text(language, "正在写章节", "Writing chapter"),
        "memory_storing": _lang_text(language, "正在写入记忆", "Storing memory"),
        "turning_point": _lang_text(language, "正在检查转折点", "Checking turning points"),
        "consistency_check": _lang_text(language, "正在一致性检查", "Consistency check"),
        "editing": _lang_text(language, "正在实时编辑", "Realtime editing"),
        "reward_calc": _lang_text(language, "正在计算奖励", "Calculating reward"),
        "finishing": _lang_text(language, "正在收尾", "Finalizing"),
        "init": _lang_text(language, "初始化中", "Initializing"),
        "idea_analyzed": _lang_text(language, "创意分析完成", "Idea analyzed"),
        "planning_done": _lang_text(language, "规划完成", "Planning done"),
        "outline_global_done": _lang_text(language, "全局大纲完成", "Global outline done"),
        "outline_chapters_done": _lang_text(language, "章节大纲完成", "Chapter outlines done"),
        "chapter_start": _lang_text(language, "章节开始", "Chapter started"),
        "chapter_done": _lang_text(language, "章节完成", "Chapter done"),
        "realtime_edit": _lang_text(language, "实时编辑", "Realtime edit"),
        "finalizing": _lang_text(language, "最终输出", "Final output"),
        "error": _lang_text(language, "错误", "Error"),
    }
    return mapping.get(phase, _lang_text(language, "运行中", "Running"))


def _build_progress_snapshot(job: GenerationJob, run_dir: Optional[Path], worker_log_text: str, progress_log_text: str) -> Dict:
    now = datetime.now(timezone.utc)
    language = _job_language(job)
    snapshot = _default_progress_snapshot(language)
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

    parsed = _parse_progress_log(progress_log_text, language=language)
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

    latest_event = str(parsed.get("latest_event") or "")
    event_phase_map = {
        "claw_native_loop": "planning",
        "global_outline": "planning",
        "chapter_outline_ready": "planning_done",
        "chapter_plan": "planning",
        "claw_loop_start": "planning",
        "claw_action_start": "running",
        "claw_action_result": "running",
        "claw_candidate_update": "realtime_edit",
        "claw_finalize_ready": "finalizing",
        "claw_loop_complete": "finalizing",
    }
    phase = job.status if terminal else str(event_phase_map.get(latest_event) or status_state.get("stage") or _infer_phase(worker_log_text))
    phase_label = _phase_label(phase, language=language)
    phase_note = str(
        parsed.get("phase_note")
        or status_state.get("message")
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
            stall_reason = _lang_text(language, "20 秒后仍未看到 Worker 日志，Worker 可能没有正常启动。", "No worker logs yet after 20s; the worker may not have started correctly.")
        elif idle_seconds is not None and idle_seconds > 90:
            stalled = True
            stall_reason = _lang_text(language, f"已有 {idle_seconds} 秒没有新日志，任务可能卡住了。", f"No new logs for {idle_seconds}s; the job may be stalled.")

        if status_state and status_state.get("updated_at"):
            try:
                ts = str(status_state.get("updated_at")).replace("Z", "+00:00")
                sdt = datetime.fromisoformat(ts)
                if sdt.tzinfo is None:
                    sdt = sdt.replace(tzinfo=timezone.utc)
                idle_status = max(0, int((now - sdt.astimezone(timezone.utc)).total_seconds()))
                if idle_status > 90:
                    stalled = True
                    stall_reason = _lang_text(language, f"状态心跳已有 {idle_status} 秒未更新，任务可能卡住了。", f"Status heartbeat not updated for {idle_status}s; the job may be stalled.")
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
    request.session.clear()
    return _redirect("/login")


@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("dashboard.html", _console_context(request, db, user, active_nav="chat"))


@app.get("/console/chat")
def console_chat(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("dashboard.html", _console_context(request, db, user, active_nav="chat"))


@app.get("/console/sessions")
def console_sessions(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("console_sessions.html", _console_context(request, db, user, active_nav="sessions"))


@app.get("/console/tasks")
def console_tasks(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return _redirect_with_notice(
        "/console/chat",
        message=_ui_text(_ui_language(request), "Claw \u8fd0\u884c\u73b0\u5728\u76f4\u63a5\u663e\u793a\u5728\u804a\u5929\u5de5\u4f5c\u53f0\u5185\u3002", "Claw runs are now shown directly inside the chat workspace."),
    )

@app.get("/console/workspace")
def console_workspace(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return _redirect(f"/console/manuscript{_session_suffix(request, db, user)}")


def _session_suffix(request: Request, db: Session, user: User) -> str:
    active_session_id = request.query_params.get("session_id", "").strip()
    if active_session_id:
        return f"?session_id={active_session_id}"
    try:
        context = _console_context(request, db, user, active_nav="chat")
        active_session = context.get("active_session")
        if active_session and getattr(active_session, "id", None):
            return f"?session_id={active_session.id}"
    except Exception:
        pass
    return ""


@app.get("/console/manuscript")
def console_manuscript(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return _redirect(f"/console/manuscript/read{_session_suffix(request, db, user)}")


@app.get("/console/memory")
def console_memory(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return _redirect(f"/console/memory/banks{_session_suffix(request, db, user)}")


@app.get("/console/manuscript/read")
def console_manuscript_read(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse(
        "console_manuscript_read.html",
        _console_page_context(request, db, user, active_nav="manuscript_read", workspace_section="read"),
    )


@app.get("/console/manuscript/outline")
def console_manuscript_outline(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse(
        "console_manuscript_outline.html",
        _console_page_context(request, db, user, active_nav="manuscript_outline", workspace_section="outline"),
    )


@app.get("/console/manuscript/planning")
def console_manuscript_planning(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse(
        "console_manuscript_planning.html",
        _console_page_context(request, db, user, active_nav="manuscript_planning", workspace_section="planning"),
    )


@app.get("/console/memory/banks")
def console_memory_banks(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return _redirect(f"/console/memory/zone/premise{_session_suffix(request, db, user)}")


@app.get("/console/memory/entries")
def console_memory_entries(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return _redirect(f"/console/memory/zone/premise{_session_suffix(request, db, user)}")


@app.get("/console/memory/revision")
def console_memory_revision_redirect(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return _redirect(f"/console/memory/zone/revision_loop{_session_suffix(request, db, user)}")


_MEMORY_ZONE_META = {
    "premise": ("故事前提", "Story Premise", "作品 premise、题材方向与故事核心命题。"),
    "author_brief": ("作者要求", "Author Brief", "Claw 写作时参考的作者偏好与风格要求。"),
    "chapter_planning": ("章节规划", "Chapter Planning", "章节 brief、大纲与场景卡。"),
    "revision_loop": ("修订循环", "Revision Loop", "修订记录与迭代决策日志。"),
    "canon_state": ("设定连续性", "Canon State", "世界观设定、角色状态与连续性事实。"),
    "runtime": ("运行现场", "Runtime", "运行时工作记忆与执行观察。"),
}


@app.get("/console/memory/zone/{slug}")
def console_memory_zone(slug: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    if slug not in _MEMORY_ZONE_META:
        slug = "premise"
    zh, en, desc = _MEMORY_ZONE_META[slug]
    return templates.TemplateResponse(
        "console_memory_zone.html",
        _console_page_context(
            request, db, user,
            active_nav=f"memory_zone_{slug}",
            workspace_section="entries",
            memory_zone_slug=slug,
            memory_zone_name_zh=zh,
            memory_zone_name_en=en,
            memory_zone_desc=desc,
        ),
    )
def _console_memory_revision_legacy(request: Request, db: Session = Depends(get_db)):
    pass  # replaced by zone routes above


@app.get("/console/storyboard")
def console_storyboard(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("console_storyboard.html", _console_context(request, db, user, active_nav="storyboard"))


@app.get("/console/characters")
def console_characters(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("console_characters.html", _console_context(request, db, user, active_nav="characters"))


@app.get("/console/world")
def console_world(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("console_world.html", _console_context(request, db, user, active_nav="world"))


@app.get("/console/style")
def console_style(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("console_style.html", _console_context(request, db, user, active_nav="style"))


@app.get("/console/skills")
def console_skills(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("console_skills.html", _console_context(request, db, user, active_nav="skills"))


@app.post("/capabilities/{slug}/toggle")
def toggle_capability(slug: str, request: Request, enabled: str = Form("0"), db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    normalized_slug = str(slug or "").strip().lower()
    spec = capability_map().get(normalized_slug)
    language = _ui_language(request)
    if not spec:
        return _redirect_with_notice("/console/skills", error=_ui_text(language, "未知能力", "Unknown capability"))
    if spec.always_enabled:
        return _redirect_with_notice("/console/skills", error=_ui_text(language, "这个核心能力不能被关闭", "This core capability cannot be disabled"))

    row = db.execute(
        select(CapabilityPreference).where(
            CapabilityPreference.user_id == user.id,
            CapabilityPreference.slug == normalized_slug,
        )
    ).scalar_one_or_none()
    enabled_value = str(enabled or "0").strip().lower() in {"1", "true", "yes", "on"}

    if row:
        row.enabled = enabled_value
    else:
        row = CapabilityPreference(user_id=user.id, slug=normalized_slug, enabled=enabled_value)
        db.add(row)

    db.commit()
    state_text = _ui_text(language, "已启用" if enabled_value else "已禁用", "enabled" if enabled_value else "disabled")
    name_text = spec.name_en if language.startswith("en") else spec.name_zh
    return _redirect_with_notice("/console/skills", message=f"{name_text} {state_text}")


@app.get("/console/mcp")
def console_mcp(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("console_mcp.html", _console_context(request, db, user, active_nav="mcp"))


@app.get("/console/agents")
def console_agents(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("console_agents.html", _console_context(request, db, user, active_nav="agents"))


@app.get("/console/models")
def console_models(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("console_models.html", _console_context(request, db, user, active_nav="models"))


@app.get("/console/env")
def console_env(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    ctx = _console_context(request, db, user, active_nav="env")
    ctx["env_form_values"] = {
        "web_execution_mode": os.getenv("WEB_EXECUTION_MODE", settings.execution_mode),
        "web_claw_max_steps": os.getenv("WEB_CLAW_MAX_STEPS", str(settings.claw_max_steps)),
        "web_max_iterations": os.getenv("WEB_MAX_ITERATIONS", str(settings.max_iterations)),
        "web_max_total_iterations": os.getenv("WEB_MAX_TOTAL_ITERATIONS", str(settings.max_total_iterations)),
        "min_chapter_chars": os.getenv("MIN_CHAPTER_CHARS", "3000"),
        "max_chapter_chars": os.getenv("MAX_CHAPTER_CHARS", "0"),
        "web_max_chapter_subrounds": os.getenv("WEB_MAX_CHAPTER_SUBROUNDS", str(settings.max_chapter_subrounds)),
        "web_chapters_per_iter": os.getenv("WEB_CHAPTERS_PER_ITER", str(settings.chapters_per_iter)),
        "web_fast_mode": os.getenv("WEB_FAST_MODE", "1" if settings.fast_mode else "0"),
        "web_full_cycle_interval": os.getenv("WEB_FULL_CYCLE_INTERVAL", str(settings.full_cycle_interval)),
        "web_eval_interval": os.getenv("WEB_EVAL_INTERVAL", str(settings.eval_interval)),
        "temperature": os.getenv("TEMPERATURE", "0.7"),
        "max_tokens": os.getenv("MAX_TOKENS", "8000"),
        "llm_timeout_seconds": os.getenv("LLM_TIMEOUT_SECONDS", "0"),
        "llm_max_retries": os.getenv("LLM_MAX_RETRIES", "1"),
        "web_memory_only_mode": os.getenv("WEB_MEMORY_ONLY_MODE", "1"),
        "context_max_chars": os.getenv("CONTEXT_MAX_CHARS", "12000"),
        "recent_context_items": os.getenv("RECENT_CONTEXT_ITEMS", "4"),
        "web_enable_evaluator": os.getenv("WEB_ENABLE_EVALUATOR", "0"),
        "web_enable_rag": os.getenv("WEB_ENABLE_RAG", "0"),
        "web_enable_static_kb": os.getenv("WEB_ENABLE_STATIC_KB", "0"),
        "turning_point_enabled": os.getenv("TURNING_POINT_ENABLED", "1"),
    }
    return templates.TemplateResponse("console_env.html", ctx)


@app.post("/console/env/save")
async def save_env_settings(
    request: Request,
    db: Session = Depends(get_db),
    # Claw engine
    web_execution_mode: str = Form("claw"),
    web_claw_max_steps: str = Form("6"),
    web_max_iterations: str = Form("8"),
    web_max_total_iterations: str = Form("16"),
    # Chapter writing
    min_chapter_chars: str = Form("3000"),
    max_chapter_chars: str = Form("0"),
    web_max_chapter_subrounds: str = Form("2"),
    web_chapters_per_iter: str = Form("1"),
    # Performance
    web_fast_mode: str = Form("1"),
    web_full_cycle_interval: str = Form("3"),
    web_eval_interval: str = Form("8"),
    # LLM params
    temperature: str = Form("0.7"),
    max_tokens: str = Form("8000"),
    llm_timeout_seconds: str = Form("0"),
    llm_max_retries: str = Form("1"),
    # Memory & context
    web_memory_only_mode: str = Form("1"),
    context_max_chars: str = Form("12000"),
    recent_context_items: str = Form("4"),
    # Advanced
    web_enable_evaluator: str = Form("0"),
    web_enable_rag: str = Form("0"),
    web_enable_static_kb: str = Form("0"),
    turning_point_enabled: str = Form("1"),
):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    language = _ui_language(request)

    def _flag(v: str) -> str:
        return "1" if str(v or "0").strip() in {"1", "true", "on", "yes"} else "0"

    def _int_clamp(v: str, lo: int, hi: int, default: int) -> str:
        try:
            return str(max(lo, min(hi, int(v or default))))
        except (ValueError, TypeError):
            return str(default)

    def _float_clamp(v: str, lo: float, hi: float, default: float) -> str:
        try:
            return f"{max(lo, min(hi, float(v or default))):.2f}"
        except (ValueError, TypeError):
            return str(default)

    new_env: Dict[str, str] = {
        "WEB_EXECUTION_MODE": (web_execution_mode or "claw").strip().lower(),
        "WEB_CLAW_MAX_STEPS": _int_clamp(web_claw_max_steps, 4, 200, 6),
        "WEB_MAX_ITERATIONS": _int_clamp(web_max_iterations, 1, 500, 8),
        "WEB_MAX_TOTAL_ITERATIONS": _int_clamp(web_max_total_iterations, 1, 1000, 16),
        "MIN_CHAPTER_CHARS": _int_clamp(min_chapter_chars, 300, 50000, 3000),
        "MAX_CHAPTER_CHARS": _int_clamp(max_chapter_chars, 0, 100000, 0),
        "WEB_MAX_CHAPTER_SUBROUNDS": _int_clamp(web_max_chapter_subrounds, 1, 10, 2),
        "WEB_CHAPTERS_PER_ITER": _int_clamp(web_chapters_per_iter, 1, 10, 1),
        "WEB_FAST_MODE": _flag(web_fast_mode),
        "WEB_FULL_CYCLE_INTERVAL": _int_clamp(web_full_cycle_interval, 0, 20, 3),
        "WEB_EVAL_INTERVAL": _int_clamp(web_eval_interval, 1, 50, 8),
        "TEMPERATURE": _float_clamp(temperature, 0.0, 2.0, 0.7),
        "MAX_TOKENS": _int_clamp(max_tokens, 1000, 32000, 8000),
        "LLM_TIMEOUT_SECONDS": _int_clamp(llm_timeout_seconds, 0, 3600, 0),
        "LLM_MAX_RETRIES": _int_clamp(llm_max_retries, 0, 10, 1),
        "WEB_MEMORY_ONLY_MODE": _flag(web_memory_only_mode),
        "CONTEXT_MAX_CHARS": _int_clamp(context_max_chars, 2000, 100000, 12000),
        "RECENT_CONTEXT_ITEMS": _int_clamp(recent_context_items, 1, 20, 4),
        "WEB_ENABLE_EVALUATOR": _flag(web_enable_evaluator),
        "WEB_ENABLE_RAG": _flag(web_enable_rag),
        "WEB_ENABLE_STATIC_KB": _flag(web_enable_static_kb),
        "TURNING_POINT_ENABLED": _flag(turning_point_enabled),
    }

    # Persist to .env file (creates or updates)
    env_path = BASE_DIR / ".env"
    existing_lines: List[str] = []
    written_keys: set = set()
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                existing_lines.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in new_env:
                existing_lines.append(f"{key}={new_env[key]}")
                written_keys.add(key)
            else:
                existing_lines.append(line)
    for key, value in new_env.items():
        if key not in written_keys:
            existing_lines.append(f"{key}={value}")
    try:
        env_path.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")
    except Exception:
        pass

    # Update os.environ so the current process picks up new values immediately
    for key, value in new_env.items():
        os.environ[key] = value

    # Update frozen settings object live (bypass frozen constraint via object.__setattr__)
    _settings_map = {
        "WEB_EXECUTION_MODE": ("execution_mode", str),
        "WEB_CLAW_MAX_STEPS": ("claw_max_steps", int),
        "WEB_MAX_ITERATIONS": ("max_iterations", int),
        "WEB_MAX_TOTAL_ITERATIONS": ("max_total_iterations", int),
        "WEB_FAST_MODE": ("fast_mode", lambda v: v == "1"),
        "WEB_FULL_CYCLE_INTERVAL": ("full_cycle_interval", int),
        "WEB_CHAPTERS_PER_ITER": ("chapters_per_iter", int),
        "WEB_MAX_CHAPTER_SUBROUNDS": ("max_chapter_subrounds", int),
        "WEB_EVAL_INTERVAL": ("eval_interval", int),
    }
    for env_key, (attr, converter) in _settings_map.items():
        if env_key in new_env:
            try:
                object.__setattr__(settings, attr, converter(new_env[env_key]))
            except Exception:
                pass

    msg = _ui_text(language, "✓ 设置已保存，下次生成任务时生效。", "✓ Settings saved. Takes effect on the next generation run.")
    return _redirect_with_notice("/console/env", message=msg)

@app.get("/console/status")
def console_status(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("console_status.html", _console_context(request, db, user, active_nav="status"))


@app.post("/ui-language")
def set_ui_language(request: Request, lang: str = Form(...), next: str = Form("/console/chat")):
    normalized = (lang or "").strip().lower()
    request.session["ui_language"] = normalized if normalized in {"zh", "en"} else "en"
    return _redirect(_safe_next_path(next, "/console/chat"))


@app.post("/api-keys")
def save_api_key(
    request: Request,
    provider: str = Form(...),
    api_key: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    if _modelless_mode_enabled():
        return _reject_when_modelless(request, path="/console/models")

    language = _ui_language(request)
    provider = provider.strip().lower()
    api_key = api_key.strip()
    provider_specs = _provider_specs_for_user(db, user.id)

    if provider not in provider_specs:
        return _redirect_with_notice("/console/models", error=_ui_text(language, "不支持的提供商", "Unsupported provider"))
    if len(api_key) < 12:
        return _redirect_with_notice("/console/models", error=_ui_text(language, "API Key 看起来太短了", "API key looks too short"))

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
    return _redirect_with_notice("/console/models", message=_ui_text(language, "API Key 已保存", "API key saved"))



@app.post("/providers")
def save_provider_config(
    request: Request,
    slug: str = Form(...),
    label: str = Form(""),
    base_url: str = Form(...),
    model: str = Form(...),
    wire_api: str = Form("chat"),
    db: Session = Depends(get_db),
):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    if _modelless_mode_enabled():
        return _reject_when_modelless(request, path="/console/models")

    language = _ui_language(request)
    norm_slug = normalize_slug(slug)
    norm_label = (label or "").strip()
    norm_base_url = (base_url or "").strip()
    norm_model = (model or "").strip()
    norm_wire_api = normalize_wire_api(wire_api)

    if not is_valid_slug(norm_slug):
        return _redirect_with_notice(
            "/console/models",
            error=_ui_text(language, "无效的 slug。请使用 2-32 位 a-z、0-9、_ 或 -", "Invalid slug. Use 2-32 chars (a-z, 0-9, _, -)"),
        )
    if not norm_base_url:
        return _redirect_with_notice("/console/models", error=_ui_text(language, "Base URL 不能为空", "Base URL cannot be empty"))
    if not norm_model:
        return _redirect_with_notice("/console/models", error=_ui_text(language, "模型名不能为空", "Model cannot be empty"))
    if not (norm_base_url.startswith("http://") or norm_base_url.startswith("https://")):
        return _redirect_with_notice(
            "/console/models",
            error=_ui_text(language, "Base URL 必须以 http:// 或 https:// 开头", "Base URL must start with http:// or https://"),
        )

    base_specs = get_provider_specs(settings)
    if norm_slug in base_specs:
        return _redirect_with_notice(
            "/console/models",
            error=_ui_text(language, "这个 provider slug 已被占用，请换一个", "This provider slug is reserved. Use another slug"),
        )

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
    return _redirect_with_notice("/console/models", message=_ui_text(language, "自定义提供商已保存", "Custom provider saved"))



@app.post("/providers/{slug}/delete")
def delete_provider_config(slug: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    if _modelless_mode_enabled():
        return _reject_when_modelless(request, path="/console/models")

    language = _ui_language(request)
    norm_slug = normalize_slug(slug)
    row = db.execute(
        select(ProviderConfig).where(
            ProviderConfig.user_id == user.id,
            ProviderConfig.slug == norm_slug,
        )
    ).scalar_one_or_none()
    if not row:
        return _redirect_with_notice("/console/models", error=_ui_text(language, "未找到自定义提供商", "Custom provider not found"))

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
    return _redirect_with_notice("/console/models", message=_ui_text(language, "自定义提供商已删除", "Custom provider deleted"))



@app.post("/idea-copilot/start")
def start_idea_copilot(
    request: Request,
    idea: str = Form(...),
    provider: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    if _modelless_mode_enabled():
        return _reject_when_modelless(request, path="/console/chat")

    idea = idea.strip()
    provider = provider.strip().lower()
    if not idea:
        return _redirect_with_notice("/console/chat", error="Idea cannot be empty")

    provider_specs = _provider_specs_for_user(db, user.id)
    spec = provider_specs.get(provider)
    if not spec:
        return _redirect_with_notice("/console/chat", error="Unsupported provider")

    try:
        api_key = _provider_api_key(db, user.id, provider)
    except ValueError as exc:
        return _redirect_with_notice("/console/chat", error=str(exc))

    source_language = detect_language(idea)
    state_payload = {
        "version": 2,
        "messages": [],
        "refined_idea": idea,
        "round": 0,
        "preferred_language": source_language,
        "source_language": source_language,
        "ui_language": source_language,
        "translation_mode": "follow_input",
    }
    session = IdeaCopilotSession(
        user_id=user.id,
        provider=provider,
        status="active",
        original_idea=idea,
        refined_idea=idea,
        conversation_json=dump_state(state_payload),
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
        fallback_lang = source_language if source_language in {"en", "zh"} else "en"
        turn = {
            "role": "assistant",
            "analysis": (
                f"The first ideation turn failed: {exc}"
                if fallback_lang == "en"
                else f"首轮创意协作失败：{exc}"
            ),
            "refined_idea": idea,
            "questions": [
                "What is the core conflict and what kind of writing help do you want first?"
                if fallback_lang == "en"
                else "这个故事的核心冲突是什么？你最希望我先帮助你完善哪一部分？"
            ],
            "readiness": 10,
            "ready_hint": (
                "Add more detail about premise, voice, and hard constraints."
                if fallback_lang == "en"
                else "请补充更多关于故事前提、叙事声音和硬性约束的细节。"
            ),
            "language": fallback_lang,
            "style_targets": [],
            "memory_targets": [],
        }

    state = append_assistant_turn(state, turn)
    session.conversation_json = dump_state(state)
    session.refined_idea = str(state.get("refined_idea") or idea)
    session.round_count = int(state.get("round", 0) or 0)
    session.readiness_score = int(turn.get("readiness", 0) or 0)
    db.commit()
    _remember_session_turn(session, state, turn=turn)
    return _redirect(f"/console/chat?session_id={session.id}")


@app.get("/idea-copilot/{session_id}")
def idea_copilot_detail(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea session not found")
    return _redirect(f"/console/chat?session_id={session.id}")


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
    if _modelless_mode_enabled():
        return _reject_when_modelless(request, path=f"/console/chat?session_id={session_id}")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea session not found")
    if session.status != "active":
        return _redirect_with_notice(f"/console/chat?session_id={session_id}", error="Session is not active")

    answer = reply.strip()
    if not answer:
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"ok": False, "error": "Reply cannot be empty"}, status_code=400)
        return _redirect_with_notice(f"/console/chat?session_id={session_id}", error="Reply cannot be empty")

    state = load_state(session.conversation_json)
    if state.get("reply_pending"):
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"ok": False, "error": "Previous reply is still processing"}, status_code=409)
        return _redirect_with_notice(f"/console/chat?session_id={session_id}", error="Previous reply is still processing")

    provider_specs = _provider_specs_for_user(db, user.id)
    spec = provider_specs.get(session.provider)
    if not spec:
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"ok": False, "error": "Provider is no longer available"}, status_code=400)
        return _redirect_with_notice(f"/console/chat?session_id={session_id}", error="Provider is no longer available")
    try:
        _provider_api_key(db, user.id, session.provider)
    except ValueError as exc:
        if request.headers.get("x-requested-with") == "fetch":
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return _redirect_with_notice(f"/console/chat?session_id={session_id}", error=str(exc))

    state = append_user_reply(state, answer)
    state["reply_pending"] = True
    state["reply_error"] = ""
    state["reply_started_at"] = datetime.now(timezone.utc).isoformat()
    session.conversation_json = dump_state(state)
    session.refined_idea = str(state.get("refined_idea") or session.refined_idea or session.original_idea)
    db.commit()
    _remember_session_turn(session, state, user_reply=answer)
    _start_idea_copilot_reply_worker(session_id)

    provider_label = spec.label if spec else session.provider.upper()
    payload = _idea_session_payload(session, state, provider_label)
    if request.headers.get("x-requested-with") == "fetch":
        return JSONResponse({"ok": True, **payload}, status_code=202)
    return _redirect(f"/console/chat?session_id={session_id}")


@app.get("/api/idea-copilot/{session_id}/state")
def idea_copilot_state(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea session not found")

    state = load_state(session.conversation_json)
    provider_specs = _provider_specs_for_user(db, user.id)
    provider_label = provider_specs.get(session.provider).label if provider_specs.get(session.provider) else session.provider.upper()
    return JSONResponse({"ok": True, **_idea_session_payload(session, state, provider_label)})


@app.post("/api/idea-copilot/{session_id}/brief")
async def idea_copilot_brief_edit(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Allow users to directly edit the refined_idea brief for a session."""
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    try:
        body = await request.json()
        new_brief = str(body.get("brief", "")).strip()
    except Exception:
        form = await request.form()
        new_brief = str(form.get("brief", "")).strip()

    if not new_brief:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="brief cannot be empty")

    session.refined_idea = new_brief
    # Also patch the conversation state so polls return updated brief
    state = load_state(session.conversation_json)
    state["refined_idea"] = new_brief
    session.conversation_json = dump_state(state)
    db.commit()
    return JSONResponse({"ok": True, "refined_idea": new_brief})


@app.post("/idea-copilot/{session_id}/confirm")
def idea_copilot_confirm(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    if _modelless_mode_enabled():
        return _reject_when_modelless(request, path=f"/console/chat?session_id={session_id}")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea session not found")
    if session.status != "active":
        if session.final_job_id:
            return _redirect(f"/console/chat?session_id={session_id}")
        return _redirect_with_notice(f"/console/chat?session_id={session_id}", error="Session is not active")

    try:
        _start_generation_from_idea_session(db, session, user.id)
    except ValueError as exc:
        return _redirect_with_notice(f"/console/chat?session_id={session_id}", error=str(exc))
    return _redirect_with_notice(
        f"/console/chat?session_id={session_id}",
        message=_ui_text(_ui_language(request), "NovelClaw 已进入创作执行模式。", "NovelClaw has entered creation mode."),
    )


@app.post("/idea-copilot/{session_id}/cancel")
def idea_copilot_cancel(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea session not found")

    canceled_run = False
    if session.final_job_id:
        job = db.get(GenerationJob, session.final_job_id)
        canceled_run = _cancel_generation_job(job, reason="[user] canceled via session close.")

    if session.status in {"active", "confirmed"}:
        session.status = "canceled"
    session.finished_at = datetime.now(timezone.utc)
    db.commit()
    return _redirect_with_notice(
        "/console/chat",
        message=_ui_text(
            _ui_language(request),
            "写作会话已结束，关联运行也已停止。" if canceled_run else "写作会话已结束。",
            "Writing session closed. The linked run was stopped." if canceled_run else "Writing session closed.",
        ),
    )


@app.post("/idea-copilot/{session_id}/delete")
def idea_copilot_delete(
    session_id: int,
    request: Request,
    next_path: str = Form("/console/sessions", alias="next"),
    db: Session = Depends(get_db),
):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea session not found")

    language = _ui_language(request)
    target_path = _safe_next_path(next_path, "/console/sessions")
    if session.final_job_id:
        job = db.get(GenerationJob, session.final_job_id)
        _cancel_generation_job(job, reason="[user] canceled via session delete.")
        _detach_job_from_sessions(db, session.final_job_id)
    db.delete(session)
    db.commit()
    return _redirect_with_notice(
        target_path,
        message=_ui_text(language, "写作会话已删除，关联运行已取消并解绑。", "Writing session deleted. The linked run was canceled and detached."),
    )


@app.post("/jobs")
def create_job(
    request: Request,
    idea: str = Form(...),
    provider: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")
    if _modelless_mode_enabled():
        return _reject_when_modelless(request, path="/console/chat")

    idea = idea.strip()
    provider = provider.strip().lower()
    provider_specs = _provider_specs_for_user(db, user.id)

    if not idea:
        return _redirect_with_notice("/console/chat", error="Idea cannot be empty")
    if provider not in provider_specs:
        return _redirect_with_notice("/console/chat", error="Unsupported provider")

    try:
        _provider_api_key(db, user.id, provider)
    except ValueError:
        return _redirect("/dashboard?error=Save+your+API+key+for+that+provider+first")

    job = _create_generation_job(db, user.id, provider, idea)
    _start_generation_worker(job.id)
    return _redirect_with_notice(
        "/console/chat",
        message=_ui_text(_ui_language(request), "Claw \u5df2\u5728\u5f53\u524d\u804a\u5929\u5de5\u4f5c\u53f0\u5f00\u59cb\u6267\u884c\u3002", "Claw has started in the current chat workspace."),
    )


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if _cancel_generation_job(job):
        db.commit()
        return _redirect_with_notice(
            "/console/chat",
            message=_ui_text(_ui_language(request), "Claw \u8fd0\u884c\u5df2\u53d6\u6d88\uff0c\u4f60\u53ef\u4ee5\u7ee7\u7eed\u5728\u5f53\u524d\u804a\u5929\u91cc\u4e0b\u8fbe\u65b0\u6307\u4ee4\u3002", "The Claw run was canceled. You can continue giving instructions in the current chat."),
        )

    return _redirect_with_notice(
        "/console/chat",
        message=_ui_text(_ui_language(request), "\u5f53\u524d\u6ca1\u6709\u53ef\u53d6\u6d88\u7684 Claw \u8fd0\u884c\u3002", "There is no cancelable Claw run right now."),
    )


@app.post("/jobs/{job_id}/delete")
def delete_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if job.status in {"queued", "running"}:
        return _redirect_with_notice(
            "/console/chat",
            error=_ui_text(_ui_language(request), "\u8fd0\u884c\u4e2d\u7684 Claw \u4efb\u52a1\u4e0d\u80fd\u76f4\u63a5\u5220\u9664\uff0c\u8bf7\u5148\u53d6\u6d88\u3002", "A running Claw task cannot be deleted directly. Cancel it first."),
        )

    run_id = (job.run_id or "").strip()
    run_dir = _resolve_run_dir(run_id) if run_id else None
    _detach_job_from_sessions(db, job.id)

    db.delete(job)
    db.commit()

    if run_dir and run_dir.exists():
        try:
            shutil.rmtree(run_dir, ignore_errors=True)
        except Exception:
            pass

    return _redirect_with_notice(
        "/console/chat",
        message=_ui_text(_ui_language(request), "Claw \u8fd0\u884c\u8bb0\u5f55\u5df2\u5220\u9664\u3002", "Claw run record deleted."),
    )


@app.get("/jobs/{job_id}")
def job_detail(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        return _redirect("/login")

    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    related_session = db.execute(
        select(IdeaCopilotSession)
        .where(IdeaCopilotSession.final_job_id == job.id)
        .order_by(IdeaCopilotSession.updated_at.desc())
    ).scalar_one_or_none()

    if related_session:
        return _redirect_with_notice(
            f"/console/chat?session_id={related_session.id}",
            message=_ui_text(_ui_language(request), "\u8fd9\u6b21 Claw \u8fd0\u884c\u5df2\u7ecf\u5e76\u5165\u5f53\u524d\u804a\u5929\u5de5\u4f5c\u53f0\u3002", "This Claw run is now embedded in the chat workspace."),
        )
    return _redirect_with_notice(
        "/console/chat",
        message=_ui_text(_ui_language(request), "\u8fd9\u6b21 Claw \u8fd0\u884c\u5df2\u7ecf\u5e76\u5165\u5f53\u524d\u804a\u5929\u5de5\u4f5c\u53f0\u3002", "This Claw run is now embedded in the chat workspace."),
    )


@app.get("/api/idea-copilot/{session_id}/live")
def idea_copilot_live(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    session = db.get(IdeaCopilotSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea session not found")

    if not session.final_job_id:
        return JSONResponse(
            {
                "session_id": session.id,
                "status": "idle",
                "run_id": "",
                "progress_log": "",
                "progress_log_raw": "",
                "updated_at": session.updated_at.isoformat() if session.updated_at else "",
                "error_message": "",
                "progress_snapshot": _default_progress_snapshot(_ui_language(request)),
            }
        )

    job = db.get(GenerationJob, session.final_job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claw run not found")

    worker_log_text = ""
    progress_log_text = ""
    run_dir: Optional[Path] = None
    if job.run_id:
        run_dir = _resolve_run_dir(job.run_id)
        worker_log_text = _tail_text(run_dir / "worker.log")
        progress_log_text = _tail_text(run_dir / "progress.log")
    try:
        progress_snapshot = _build_progress_snapshot(job, run_dir, worker_log_text, progress_log_text)
    except Exception:
        progress_snapshot = _default_progress_snapshot(_job_language(job))

    job_language = _job_language(job)
    progress_log_raw = progress_log_text
    progress_log_text = _render_progress_log(progress_log_text, language=job_language)

    return JSONResponse(
        {
            "session_id": session.id,
            "status": job.status,
            "run_id": job.run_id,
            "progress_log": progress_log_text,
            "progress_log_raw": progress_log_raw,
            "updated_at": job.updated_at.isoformat() if job.updated_at else "",
            "error_message": job.error_message or "",
            "progress_snapshot": progress_snapshot,
        }
    )

@app.get("/jobs/{job_id}/logs")
def job_logs(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

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
        progress_snapshot = _build_progress_snapshot(job, run_dir, worker_log_text, progress_log_text)
    except Exception:
        progress_snapshot = _default_progress_snapshot(_job_language(job))

    job_language = _job_language(job)
    progress_log_raw = progress_log_text
    progress_log_text = _render_progress_log(progress_log_text, language=job_language)

    return JSONResponse(
        {
            "job_id": job.id,
            "status": job.status,
            "run_id": job.run_id,
            "worker_log": worker_log_text,
            "progress_log": progress_log_text,
            "progress_log_raw": progress_log_raw,
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


@app.get("/api/runs/{run_id}/memory-banks")
def api_run_memory_banks(run_id: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if not _job_for_run_id(db, user.id, run_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    index = _load_editable_memory_index_for_run(run_id)
    language = _ui_language(request)
    return JSONResponse(
        {
            "run_id": run_id,
            "topic_hint": _memory_topic_hint(index),
            "groups": _build_memory_bank_groups_from_index(index, language),
        }
    )


@app.post("/api/runs/{run_id}/memory-banks/{bank}/entries")
async def api_add_memory_bank_entry(run_id: str, bank: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if bank not in MemorySystem.CLAW_BANKS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory bank not found")
    if not _job_for_run_id(db, user.id, run_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    body = await request.json()
    content = str(body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content cannot be empty")

    index = _load_editable_memory_index_for_run(run_id)
    topic = str(body.get("topic") or "").strip() or _memory_topic_hint(index)
    chapter_value = body.get("chapter")
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    kind = str(body.get("kind") or metadata.get("kind") or "").strip()
    source = str(body.get("source") or metadata.get("source") or "manual_workspace").strip() or "manual_workspace"
    timestamp = datetime.now().isoformat()
    entry = {
        "id": f"manual_{bank}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(index['claw'].get(bank, []))}",
        "bank": bank,
        "topic": topic,
        "content": content,
        "timestamp": timestamp,
        "metadata": {
            **metadata,
            "kind": kind or metadata.get("kind") or "manual_note",
            "source": source,
            "manual_edit": True,
        },
    }
    if chapter_value not in (None, ""):
        entry["metadata"]["chapter"] = chapter_value
    index["claw"].setdefault(bank, []).append(entry)
    _save_memory_index_for_run(run_id, index)

    language = _ui_language(request)
    return JSONResponse(
        {
            "ok": True,
            "run_id": run_id,
            "selected_bank": bank,
            "entry": _serialize_claw_entry(entry),
            "groups": _build_memory_bank_groups_from_index(index, language),
        }
    )


@app.post("/api/runs/{run_id}/memory-banks/{bank}/entries/{entry_id}")
async def api_update_memory_bank_entry(run_id: str, bank: str, entry_id: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if bank not in MemorySystem.CLAW_BANKS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory bank not found")
    if not _job_for_run_id(db, user.id, run_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    body = await request.json()
    content = str(body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content cannot be empty")

    index = _load_editable_memory_index_for_run(run_id)
    entries = index["claw"].setdefault(bank, [])
    target = next((item for item in entries if str(item.get("id") or "") == entry_id), None)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory entry not found")

    topic = str(body.get("topic") or "").strip()
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    target["content"] = content
    if topic:
        target["topic"] = topic
    target_metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
    target_metadata.update(metadata)
    target_metadata["manual_edit"] = True
    target_metadata["edited_at"] = datetime.now().isoformat()
    target_metadata["source"] = str(body.get("source") or target_metadata.get("source") or "manual_workspace").strip() or "manual_workspace"
    target["metadata"] = target_metadata
    _save_memory_index_for_run(run_id, index)

    language = _ui_language(request)
    return JSONResponse(
        {
            "ok": True,
            "run_id": run_id,
            "selected_bank": bank,
            "entry": _serialize_claw_entry(target),
            "groups": _build_memory_bank_groups_from_index(index, language),
        }
    )


@app.post("/api/runs/{run_id}/chapters/{chapter_no}/content")
async def api_update_chapter_content(run_id: str, chapter_no: int, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if not _job_for_run_id(db, user.id, run_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    body = await request.json()
    content_raw = body.get("content")
    content = str(content_raw if content_raw is not None else "")
    if not content.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content cannot be empty")

    run_dir = _resolve_run_dir(run_id)
    chapter_path = _latest_chapter_file(run_dir, chapter_no)
    if not chapter_path or not chapter_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter output not found")

    normalized = content.rstrip() + "\n"
    chapter_path.write_text(normalized, encoding="utf-8")
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    title = lines[0] if lines else chapter_path.name
    return JSONResponse(
        {
            "ok": True,
            "run_id": run_id,
            "chapter": {
                "chapter": int(chapter_no),
                "iteration": int(re.search(r"_iter_(\d+)_", chapter_path.name).group(1)) if re.search(r"_iter_(\d+)_", chapter_path.name) else 0,
                "filename": chapter_path.name,
                "title": title,
                "content": normalized.strip(),
            },
        }
    )


@app.post("/api/runs/{run_id}/outlines/{outline_id}")
async def api_update_outline_asset(run_id: str, outline_id: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if not _job_for_run_id(db, user.id, run_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    body = await request.json()
    content_raw = body.get("content")
    content = str(content_raw if content_raw is not None else "")
    if not content.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content cannot be empty")

    index = _load_editable_memory_index_for_run(run_id)
    target = _find_memory_bucket_item(index, "outlines", outline_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outline not found")

    title = str(body.get("title") or "").strip()
    structure = target.get("structure") if isinstance(target.get("structure"), dict) else {}
    if title:
        structure["title"] = title
    target["structure"] = structure
    target["content"] = content.strip()
    target["timestamp"] = datetime.now().isoformat()
    _save_memory_index_for_run(run_id, index)

    return JSONResponse(
        {
            "ok": True,
            "run_id": run_id,
            "outline": {
                "id": str(target.get("id") or ""),
                "kind": str(structure.get("kind") or "outline"),
                "chapter": structure.get("chapter"),
                "title": str(structure.get("title") or body.get("title") or "").strip(),
                "content": str(target.get("content") or "").strip(),
                "timestamp": str(target.get("timestamp") or ""),
                "source": str(structure.get("source") or ""),
            },
        }
    )


# ---------------------------------------------------------------------------
# OpenClaw ask_user IPC endpoints
# The claw worker subprocess writes claw_ask.json when it needs user input.
# The frontend polls /api/runs/{run_id}/pending-question and shows the question.
# When the user replies, POST /api/runs/{run_id}/answer writes claw_reply.json.
# The worker subprocess reads it and continues.
# ---------------------------------------------------------------------------

@app.get("/api/runs/{run_id}/pending-question")
def api_pending_question(run_id: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    run_dir = _resolve_run_dir(run_id)
    ask_path = run_dir / "claw_ask.json"
    if not ask_path.exists():
        return JSONResponse({"pending": False, "question": None})
    try:
        payload = json.loads(ask_path.read_text(encoding="utf-8"))
        return JSONResponse({"pending": True, "question": payload.get("question", ""), "ts": payload.get("ts", 0)})
    except Exception:
        return JSONResponse({"pending": False, "question": None})


@app.post("/api/runs/{run_id}/answer")
async def api_submit_answer(run_id: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if not _job_for_run_id(db, user.id, run_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    body = await request.json()
    answer = str(body.get("answer") or "").strip()
    if not answer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Answer cannot be empty")
    run_dir = _resolve_run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    reply_path = run_dir / "claw_reply.json"
    reply_path.write_text(
        json.dumps({"answer": answer, "ts": __import__("time").time()}, ensure_ascii=False),
        encoding="utf-8",
    )
    return JSONResponse({"ok": True})


@app.post("/api/runs/{run_id}/interrupt")
async def api_interrupt_run(run_id: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if not _job_for_run_id(db, user.id, run_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    body = await request.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")

    run_dir = _resolve_run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    interrupt_path = run_dir / "claw_interrupt.json"
    payload = {"messages": []}
    if interrupt_path.exists():
        try:
            existing = json.loads(interrupt_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and isinstance(existing.get("messages"), list):
                payload["messages"] = list(existing.get("messages") or [])
            elif isinstance(existing, dict):
                legacy_message = str(existing.get("message") or "").strip()
                if legacy_message:
                    payload["messages"].append(
                        {"message": legacy_message, "ts": float(existing.get("ts") or 0.0)}
                    )
            elif isinstance(existing, list):
                payload["messages"] = list(existing)
        except Exception:
            payload = {"messages": []}

    payload["messages"].append({"message": message, "ts": __import__("time").time()})
    interrupt_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return JSONResponse({"ok": True, "queued": len(payload["messages"])})


# ---------------------------------------------------------------------------
# Between-chapter IPC endpoints
# After each chapter the worker writes claw_chapter_complete.json.
# The frontend polls /api/runs/{run_id}/chapter-complete and shows a checkpoint
# card. The user can leave an instruction; POST /api/runs/{run_id}/chapter-message
# writes claw_chapter_msg.json which the worker reads before the next chapter.
# ---------------------------------------------------------------------------

@app.get("/api/runs/{run_id}/chapter-complete")
def api_chapter_complete(run_id: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    run_dir = _resolve_run_dir(run_id)
    complete_path = run_dir / "claw_chapter_complete.json"
    if not complete_path.exists():
        return JSONResponse({"pending": False})
    try:
        payload = json.loads(complete_path.read_text(encoding="utf-8"))
        return JSONResponse({"pending": True, **payload})
    except Exception:
        return JSONResponse({"pending": False})


@app.post("/api/runs/{run_id}/chapter-message")
async def api_chapter_message(run_id: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    body = await request.json()
    message = str(body.get("message") or "").strip()
    raw_updates = body.get("memory_updates") if isinstance(body.get("memory_updates"), list) else []
    memory_updates: List[Dict[str, object]] = []
    for item in raw_updates:
        if not isinstance(item, dict):
            continue
        bank = str(item.get("bank") or "").strip()
        content = str(item.get("content") or "").strip()
        if bank not in MemorySystem.CLAW_BANKS or not content:
            continue
        memory_updates.append(
            {
                "bank": bank,
                "content": content,
                "topic": str(item.get("topic") or "").strip(),
                "kind": str(item.get("kind") or "between_chapter_note").strip() or "between_chapter_note",
                "source": str(item.get("source") or "checkpoint_ui").strip() or "checkpoint_ui",
            }
        )
    run_dir = _resolve_run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    # Write instruction for the worker
    if message or memory_updates:
        (run_dir / "claw_chapter_msg.json").write_text(
            json.dumps({"message": message, "memory_updates": memory_updates, "ts": __import__("time").time()}, ensure_ascii=False),
            encoding="utf-8",
        )
    # Always clear the chapter-complete signal so the frontend hides the checkpoint card
    complete_path = run_dir / "claw_chapter_complete.json"
    try:
        complete_path.unlink(missing_ok=True)
    except Exception:
        pass
    return JSONResponse({"ok": True})

