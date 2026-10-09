"""
OpenClaw-style ReAct agent loop.

True OpenClaw pattern:
  1. LLM sees full context + tool definitions
  2. LLM autonomously calls tools (function calling)
  3. Tool result is fed back to LLM as a "tool" message
  4. LLM continues until it calls `finalize` — or until safety step limit
  5. `ask_user` tool lets LLM pause and talk to the user at any moment
  6. Step count is ONLY a safety limit, not the normal exit condition
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from capability_registry import enabled_claw_actions


# ---------------------------------------------------------------------------
# File-based IPC helpers for web mode ask_user
# ---------------------------------------------------------------------------

def _web_run_dir() -> Optional[Path]:
    """Return the run directory if we are in a web worker subprocess, else None."""
    run_id = os.environ.get("RUN_ID", "").strip()
    runs_dir = os.environ.get("APP_RUNS_DIR", "") or os.environ.get("RUNS_DIR", "runs")
    if not run_id:
        return None
    return Path(runs_dir) / run_id


def _ask_user_web(question: str, timeout: int = 90) -> str:
    """
    Web-mode ask_user via filesystem IPC.
    Writes claw_ask.json, waits for claw_reply.json (up to `timeout` seconds).
    Returns user's answer or "(no reply — timed out)" on timeout.
    """
    run_dir = _web_run_dir()
    if run_dir is None:
        return "(no reply — not in web mode)"
    ask_path = run_dir / "claw_ask.json"
    reply_path = run_dir / "claw_reply.json"
    # Clean up any stale reply
    try:
        reply_path.unlink(missing_ok=True)
    except Exception:
        pass
    # Write the question
    ask_path.write_text(
        json.dumps({"question": question, "ts": time.time()}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[OpenClaw] ask_user written to {ask_path}: {question[:120]}")
    # Poll for reply
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if reply_path.exists():
            try:
                payload = json.loads(reply_path.read_text(encoding="utf-8"))
                answer = str(payload.get("answer") or "").strip() or "(empty reply)"
                reply_path.unlink(missing_ok=True)
                ask_path.unlink(missing_ok=True)
                print(f"[OpenClaw] ask_user reply received: {answer[:120]}")
                return answer
            except Exception:
                pass
        time.sleep(0.8)
    # Timeout — clean up and continue
    try:
        ask_path.unlink(missing_ok=True)
    except Exception:
        pass
    print(f"[OpenClaw] ask_user timed out after {timeout}s")
    return "(no reply — timed out)"


# ---------------------------------------------------------------------------
# Tool schema — every capability the LLM can call
# ---------------------------------------------------------------------------

def _read_user_interrupts(clear: bool = False) -> List[str]:
    """Read queued mid-run user interrupts from the web worker run dir."""
    run_dir = _web_run_dir()
    if run_dir is None:
        return []
    interrupt_path = run_dir / "claw_interrupt.json"
    if not interrupt_path.exists():
        return []
    try:
        payload = json.loads(interrupt_path.read_text(encoding="utf-8"))
    except Exception:
        try:
            interrupt_path.unlink(missing_ok=True)
        except Exception:
            pass
        return []

    messages: List[str] = []
    if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
        raw_items = list(payload.get("messages") or [])
    elif isinstance(payload, list):
        raw_items = list(payload)
    elif isinstance(payload, dict):
        raw_items = [payload]
    else:
        raw_items = []

    for item in raw_items:
        if isinstance(item, dict):
            message = str(item.get("message") or "").strip()
        else:
            message = str(item or "").strip()
        if message:
            messages.append(message)

    if clear:
        try:
            interrupt_path.unlink(missing_ok=True)
        except Exception:
            pass
    return messages


def _drain_user_interrupts() -> List[str]:
    return _read_user_interrupts(clear=True)


def _has_pending_user_interrupt() -> bool:
    return bool(_read_user_interrupts(clear=False))


_TOOL_DEFS: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "inspect_workspace",
            "description": (
                "Inspect the current local run workspace: chapter files already written, "
                "memory assets, world/character snapshots. Call this first if you are unsure "
                "about existing state."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_strategy",
            "description": (
                "Generate the chapter execution strategy: core conflict, emotional arc, "
                "must-land plot beats, forbidden out-of-outline additions, and narrative focus."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "Specific aspect to emphasise (optional)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_context",
            "description": (
                "Pull the most relevant dynamic-memory context: recent facts, character states, "
                "world rules, and prior-chapter continuity. Call before drafting if memory is sparse."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enrich_character",
            "description": (
                "Strengthen character execution constraints for this chapter: active viewpoint, "
                "current motivations, resistance, relationship shifts, and dialogue/behavior bounds."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enrich_world",
            "description": (
                "Clarify worldbuilding and scene constraints: relevant rules, setting boundaries, "
                "facts that must not be violated, and explicit setting risks in the current draft."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_chapter",
            "description": (
                "Write the full prose draft for the current chapter, integrating all available "
                "support context and memory."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rewrite_chapter",
            "description": (
                "Revise the current chapter candidate to fix quality, pacing, length, or "
                "consistency issues identified in previous observations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "What to fix specifically (optional)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sync_storyboard",
            "description": "Write the current chapter brief and plan into local workspace storyboard files.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sync_characters",
            "description": "Extract current character state and write it into local files and character memory.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sync_world",
            "description": "Extract world rules and continuity facts into local workspace files and world memory.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Pause the loop and ask the human user a direct question. Use when you need "
                "a preference, clarification, or creative decision that only the author can make."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The specific question to ask the user.",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize",
            "description": (
                "Finalize this chapter. Call when you are satisfied with the current draft — "
                "the content quality, length, consistency, and emotional impact all meet the bar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of why the chapter is ready.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]

_ACTION_TO_TOOL = {t["function"]["name"]: t for t in _TOOL_DEFS}

_SYSTEM_PROMPT_ZH = """\
你是 OpenClaw 的章节写作 Agent。你的任务是为当前章节生成高质量正文。

你拥有以下工具，可以随时按需调用，顺序完全由你决定：
- inspect_workspace：检查本地工作区文件
- plot_strategy：生成章节执行策略（冲突、节奏、情节节点）
- retrieve_context：从动态记忆中召回相关事实和上下文
- enrich_character：强化人物约束（动机、关系、行为边界）
- enrich_world：强化世界观约束（规则、设定、风险）
- draft_chapter：生成章节正文草稿
- rewrite_chapter：基于问题修订当前草稿
- sync_storyboard：把章节简报同步到本地工作区
- sync_characters：把角色状态同步到本地文件
- sync_world：把世界设定同步到本地文件
- ask_user：暂停循环，直接问用户一个问题
- finalize：当你对当前草稿满意时，调用此工具结束循环

工作原则：
1. 你是唯一的决策者。不要等待外部指令，主动根据当前状态选择下一步。
2. 只要内容还不够好，就继续工作，不要过早 finalize。
3. 每次工具调用后，你会看到结果，根据结果决定下一步。
4. 若需要用户的创意决定，调用 ask_user，等用户回复后继续。
5. 调用 finalize 时必须说明理由。
"""

_SYSTEM_PROMPT_EN = """\
You are an OpenClaw chapter writing agent. Your goal is to produce a high-quality prose draft for the current chapter.

You have the following tools, callable in any order you decide:
- inspect_workspace: inspect local workspace files
- plot_strategy: generate chapter execution strategy (conflict, pacing, plot beats)
- retrieve_context: recall relevant facts and context from dynamic memory
- enrich_character: strengthen character constraints (motives, relationships, behavior)
- enrich_world: strengthen worldbuilding constraints (rules, setting, risks)
- draft_chapter: write the chapter prose draft
- rewrite_chapter: revise the current draft based on observed issues
- sync_storyboard: sync chapter brief to local workspace
- sync_characters: sync character state to local files
- sync_world: sync world state to local files
- ask_user: pause the loop and ask the human user a direct question
- finalize: call this when you are satisfied with the current draft

Principles:
1. You are the sole decision-maker. Act autonomously based on what you observe.
2. Keep working until the content is genuinely good — do not finalize prematurely.
3. After each tool call you will see the result; use it to decide your next action.
4. If you need a creative decision only the author can make, call ask_user.
5. When calling finalize, always explain why the chapter is ready.
"""


class OpenClawManager:
    """
    True OpenClaw / ReAct agent loop.

    The LLM sees all context + tool definitions, calls tools autonomously,
    observes results, and continues until it calls `finalize` or hits the
    safety step limit.  No fixed action sequence — the LLM decides everything.
    """

    def __init__(
        self,
        executor: Any,
        user_interaction_hook: Optional[Callable[[str], str]] = None,
    ):
        self.executor = executor
        self.config = executor.config
        self.llm_client = executor.llm_client
        self.memory = executor.memory_system
        self.enabled_actions = enabled_claw_actions(
            getattr(self.config, "enabled_capabilities", set())
        )
        # always include finalize
        self.enabled_actions.add("finalize")
        # always include ask_user
        self.enabled_actions.add("ask_user")
        self.user_interaction_hook: Optional[Callable[[str], str]] = user_interaction_hook

        # import workspace agent lazily to avoid circular imports
        from workflow.workspace_agent import WorkspaceToolAgent
        self.workspace_agent = WorkspaceToolAgent(executor)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_chapter_loop(
        self,
        *,
        topic: str,
        round_results: List[Dict],
        generated_content: List[Dict],
        genre: Optional[str],
        style_tags: Optional[List[str]],
        chapter_target: int,
        chapter_min_required: int,
        chapter_max_allowed: int,
    ) -> Dict[str, Any]:
        max_steps = max(4, int(getattr(self.config, "claw_max_steps", 20) or 20))
        is_en = str(getattr(self.executor, "lang", "zh")).lower().startswith("en")

        state: Dict[str, Any] = {
            "topic": topic,
            "genre": genre,
            "style_tags": style_tags,
            "chapter_target": chapter_target,
            "chapter_min_required": chapter_min_required,
            "chapter_max_allowed": chapter_max_allowed,
            "support_results": [],
            "best_candidate": None,
            "generated_content": generated_content,
            "step": 0,
        }

        # Store project seed in Claw memory
        self.memory.store_claw_memory(
            "task_briefs",
            (
                f"topic={topic}\nchapter={self.executor.chapter_counter}\n"
                f"target={chapter_min_required}-{chapter_max_allowed}\n"
                f"genre={genre or '-'}\nstyle_tags={', '.join(style_tags or []) or '-'}"
            ),
            topic,
            metadata={"chapter": self.executor.chapter_counter},
            store_vector=False,
        )

        # Seed support results from pre-run agents
        seeded_support = [
            r for r in round_results
            if r.get("content") and r.get("type") not in {"writer", "modified"}
        ]
        for item in seeded_support:
            state["support_results"].append(item)
            self._remember_support_result(topic, item)

        # Score any seed candidate
        seed_all = [r for r in round_results if r.get("content")]
        if seed_all:
            state["best_candidate"] = self.executor._score_chapter_candidate(
                topic=topic,
                round_results=seed_all,
                genre=genre,
                style_tags=style_tags,
                chapter_target=chapter_target,
                chapter_min_required=chapter_min_required,
                chapter_max_allowed=chapter_max_allowed,
            )

        self.executor._append_progress_event(
            "claw_loop_start",
            (
                f"mode=react, max_steps={max_steps}, "
                f"enabled_actions={','.join(sorted(self.enabled_actions)) or '-'}, "
                f"seed_results={len(seed_all)}, seed_support={len(seeded_support)}"
            ),
            self.executor.chapter_counter,
        )

        # Build initial ReAct message thread
        messages = self._build_initial_messages(state, is_en)

        # Inject seed observations so LLM knows what was already done
        for item in seeded_support:
            content = str(item.get("content") or "").strip()
            if content:
                messages.append({
                    "role": "system",
                    "content": f"[Pre-computed {item.get('type', 'support')}]:\n{self.executor._safe_excerpt(content, 600)}",
                })

        # Build enabled tools list
        tools = self._build_enabled_tools()

        print(
            f"\n{'=' * 60}\n"
            f"[OpenClaw] {'章节' if not is_en else 'Chapter'} {self.executor.chapter_counter} "
            f"— ReAct loop started (max {max_steps} steps)\n"
            f"{'=' * 60}"
        )

        # ----------------------------------------------------------------
        # True ReAct loop — LLM calls tools until it calls `finalize`
        # ----------------------------------------------------------------
        for step in range(1, max_steps + 1):
            state["step"] = step

            for interrupt_message in _drain_user_interrupts():
                messages.append(
                    {
                        "role": "user",
                        "content": f"[User interrupt]\n{interrupt_message}",
                    }
                )
                self.executor._append_progress_event(
                    "claw_user_interrupt",
                    f"step={step}, message={interrupt_message[:200]}",
                    self.executor.chapter_counter,
                )

            # Inject current candidate summary so LLM always knows the state
            candidate_summary = self._candidate_summary(state)
            loop_messages = list(messages) + [{
                "role": "user",
                "content": (
                    f"[Step {step}/{max_steps}] Current state:\n{candidate_summary}\n\n"
                    + ("下一步做什么？" if not is_en else "What is your next action?")
                ),
            }]

            response = self.llm_client.chat_with_tools(
                loop_messages,
                tools,
                temperature=0.3,
                max_tokens=800,
            )

            tool_calls = response.get("tool_calls") or []
            if not tool_calls:
                # LLM gave a plain-text response — treat as implicit finalize
                plain_text = response.get("content") or ""
                print(f"[OpenClaw] step={step} → text-reply (implicit finalize): {plain_text[:120]}")
                self.executor._append_progress_event(
                    "claw_decision",
                    f"step={step}, action=implicit_finalize, reason=no_tool_call",
                    self.executor.chapter_counter,
                )
                break

            tc = tool_calls[0]
            tool_name = tc["name"]
            tool_args = tc.get("args") or {}

            print(f"[OpenClaw] step={step} → tool={tool_name} args={json.dumps(tool_args, ensure_ascii=False)[:80]}")

            self.executor._append_progress_event(
                "claw_decision",
                f"step={step}, action={tool_name}, params={json.dumps(tool_args, ensure_ascii=False)[:200]}",
                self.executor.chapter_counter,
            )

            # Append assistant message with the tool call
            messages.append({
                "role": "assistant",
                "content": response.get("content") or None,
                "tool_calls": [{
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(tool_args, ensure_ascii=False),
                    },
                }],
            })

            # ---- finalize → exit loop ----
            if tool_name == "finalize":
                reason = tool_args.get("reason") or "-"
                print(f"[OpenClaw] finalize called: {reason}")
                self.executor._append_progress_event(
                    "claw_finalize_ready",
                    f"step={step}, reason={reason}",
                    self.executor.chapter_counter,
                )
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": "Chapter finalized."})
                break

            # ---- ask_user → file IPC (web) or hook/stdin (CLI) ----
            if tool_name == "ask_user":
                question = tool_args.get("question") or "?"
                print(f"\n[OpenClaw] 🤔 Agent asks: {question}")
                self.executor._append_progress_event(
                    "claw_ask_user",
                    f"step={step}, question={question[:200]}",
                    self.executor.chapter_counter,
                )
                if _web_run_dir() is not None:
                    # Web mode: use file-based IPC so the subprocess can
                    # pause and receive a reply from the web frontend.
                    user_answer = _ask_user_web(question, timeout=90)
                elif self.user_interaction_hook:
                    user_answer = self.user_interaction_hook(question)
                else:
                    try:
                        user_answer = input(f"  ↳ Your reply: ").strip() or "(skipped)"
                    except (EOFError, KeyboardInterrupt):
                        user_answer = "(skipped)"
                print(f"[OpenClaw] User replied: {user_answer[:120]}")
                self.executor._append_progress_event(
                    "claw_user_reply",
                    f"step={step}, answer={user_answer[:200]}",
                    self.executor.chapter_counter,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": f"User replied: {user_answer}",
                })
                continue

            # ---- execute tool ----
            if tool_name not in {"finalize", "ask_user"} and _has_pending_user_interrupt():
                tool_result_text = (
                    "[Interrupt pending]\n"
                    "A newer user interrupt arrived before this tool started, so the tool was deferred."
                )
                updated_candidate = None
                self.executor._append_progress_event(
                    "claw_interrupt_defer",
                    f"step={step}, action={tool_name}, phase=before_execute",
                    self.executor.chapter_counter,
                )
            else:
                tool_result_text, updated_candidate = self._execute_tool(tool_name, tool_args, state)

            if updated_candidate is not None:
                state["best_candidate"] = updated_candidate
                self._remember_candidate_snapshot(topic, updated_candidate, label=f"step{step}")

            self.executor._append_progress_event(
                "claw_action_result",
                f"step={step}, action={tool_name}, excerpt={self.executor._safe_excerpt(tool_result_text, 180)}",
                self.executor.chapter_counter,
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result_text,
            })

            # Early exit if quality already good (LLM may still choose to continue)
            if (
                state.get("best_candidate")
                and not self.executor._should_retry_chapter(
                    state["best_candidate"],
                    chapter_min_required,
                    chapter_max_allowed,
                )
            ):
                reward = float((state.get("best_candidate") or {}).get("reward_score", 0.0) or 0.0)
                print(f"[OpenClaw] Quality threshold met at step {step} (reward={reward:.3f}) — LLM may still choose to continue.")
                self.executor._append_progress_event(
                    "claw_quality_ok",
                    f"step={step}, reward={reward:.3f} — threshold met, LLM decides whether to finalize",
                    self.executor.chapter_counter,
                )

        # ---- Fallback if no draft yet ----
        if not state.get("best_candidate"):
            print("[OpenClaw] Safety fallback: no candidate yet, drafting now.")
            draft_result = self._run_draft(state)
            if _has_pending_user_interrupt():
                state["support_results"].append(draft_result)
                state["best_candidate"] = self._build_provisional_candidate(
                    state,
                    draft_result,
                    reason="interrupt_after_fallback_draft",
                )
            else:
                state["best_candidate"] = self._merge_candidate(state, draft_result)

        self._ensure_workspace_sync(state, tools)

        final = state["best_candidate"]
        self.executor._append_progress_event(
            "claw_loop_complete",
            (
                f"steps={state['step']}, "
                f"reward={float(final.get('reward_score', 0.0) or 0.0):.3f}, "
                f"issues={int(final.get('issues_count', 0) or 0)}, "
                f"length={int(final.get('story_length', 0) or 0)}"
            ),
            self.executor.chapter_counter,
        )
        print(
            f"[OpenClaw] Loop complete — steps={state['step']}, "
            f"reward={float(final.get('reward_score', 0.0) or 0.0):.3f}, "
            f"length={int(final.get('story_length', 0) or 0)} chars\n"
            f"{'=' * 60}\n"
        )
        return final

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    def _build_initial_messages(self, state: Dict[str, Any], is_en: bool) -> List[Dict]:
        planning_packet = self.executor._build_planning_packet(
            state["topic"],
            self.executor.chapter_counter,
            current_goal=f"Write chapter {self.executor.chapter_counter}",
            support_results=state.get("support_results") or [],
        )
        title = planning_packet.get("chapter_title") or self.executor._get_chapter_outline_title(
            state["topic"], self.executor.chapter_counter
        )
        system_prompt = _SYSTEM_PROMPT_EN if is_en else _SYSTEM_PROMPT_ZH
        if is_en:
            user_msg = (
                f"Chapter: {self.executor.chapter_counter}\n"
                f"Title: {title or 'Untitled'}\n"
                f"Topic: {state['topic']}\n"
                f"Target length: {state['chapter_min_required']}-{state['chapter_max_allowed']} chars\n"
                f"Genre: {state.get('genre') or '-'}\n"
                f"Style tags: {', '.join(state.get('style_tags') or []) or '-'}\n\n"
                f"Unified planning packet:\n{planning_packet.get('packet_text') or '(none available)'}\n\n"
                "Begin. Call tools in whatever order you judge best."
            )
        else:
            user_msg = (
                f"章节：第 {self.executor.chapter_counter} 章\n"
                f"标题：{title or '未命名'}\n"
                f"主题：{state['topic']}\n"
                f"目标字数：{state['chapter_min_required']}-{state['chapter_max_allowed']} 字\n"
                f"题材：{state.get('genre') or '-'}\n"
                f"风格标签：{', '.join(state.get('style_tags') or []) or '-'}\n\n"
                f"统一 planning packet：\n{planning_packet.get('packet_text') or '（暂无可用 planning packet）'}\n\n"
                "开始。按你认为最合适的顺序调用工具。"
            )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

    def _candidate_summary(self, state: Dict[str, Any]) -> str:
        candidate = state.get("best_candidate") or {}
        support = state.get("support_results") or []
        support_types = [str(s.get("type") or "?") for s in support[-6:]]
        story_text = str(candidate.get("story_text") or "")
        reward = float(candidate.get("reward_score", 0.0) or 0.0)
        issues = (candidate.get("consistency") or {}).get("all_issues", [])
        issue_text = "; ".join(str(i) for i in issues[:4]) if issues else "none"
        provisional_note = " | status=provisional_interrupt" if candidate.get("provisional") else ""
        if story_text:
            return (
                f"draft_length={len(story_text)} chars | "
                f"reward={reward:.3f} | issues={len(issues)} ({issue_text}){provisional_note} | "
                f"tools_used=[{', '.join(support_types)}] | "
                f"target={state['chapter_min_required']}-{state['chapter_max_allowed']}\n"
                f"Draft excerpt: {self.executor._safe_excerpt(story_text, 400)}"
            )
        return (
            f"No draft yet | tools_used=[{', '.join(support_types)}] | "
            f"target={state['chapter_min_required']}-{state['chapter_max_allowed']}"
        )

    def _build_provisional_candidate(
        self,
        state: Dict[str, Any],
        writer_result: Dict[str, Any],
        *,
        reason: str,
    ) -> Dict[str, Any]:
        story_text = str(
            (writer_result or {}).get("story_text")
            or (writer_result or {}).get("content")
            or ""
        ).strip()
        round_results = list(state.get("support_results") or [])
        if writer_result and (not round_results or round_results[-1] is not writer_result):
            round_results.append(writer_result)
        return {
            "story_text": story_text,
            "story_length": len(story_text),
            "round_results": round_results,
            "evaluation": {},
            "reward": {
                "total_reward": 0.0,
                "provisional": True,
                "reason": reason,
            },
            "reward_score": 0.0,
            "consistency": {
                "all_issues": [],
                "provisional": True,
                "reason": reason,
            },
            "issues_count": 0,
            "provisional": True,
            "provisional_reason": reason,
        }

    # ------------------------------------------------------------------
    # Tool execution — dispatches to sub-agents / workspace agent
    # ------------------------------------------------------------------

    def _build_enabled_tools(self) -> List[Dict]:
        return [
            t for t in _TOOL_DEFS
            if t["function"]["name"] in self.enabled_actions
            or t["function"]["name"] in {"finalize", "ask_user"}
        ]

    def _execute_tool(
        self, tool_name: str, tool_args: Dict[str, Any], state: Dict[str, Any]
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        """
        Execute the tool and return (result_text_for_llm, updated_candidate_or_None).
        """
        topic = state["topic"]
        genre = state.get("genre")
        style_tags = state.get("style_tags")
        updated_candidate = None

        if tool_name == "inspect_workspace":
            result = self.workspace_agent.inspect_workspace(state)
            state["support_results"].append(result)
            self._remember_support_result(topic, result)
            return self._result_to_text(result, tool_name), None

        if tool_name == "plot_strategy":
            result = self._run_plot_strategy(state)
            state["support_results"].append(result)
            self._remember_support_result(topic, result)
            return self._result_to_text(result, tool_name), None

        if tool_name == "retrieve_context":
            result = self._run_retrieval(state)
            state["support_results"].append(result)
            self._remember_support_result(topic, result)
            return self._result_to_text(result, tool_name), None

        if tool_name == "enrich_character":
            result = self._run_character_enrichment(state)
            state["support_results"].append(result)
            self._remember_support_result(topic, result)
            return self._result_to_text(result, tool_name), None

        if tool_name == "enrich_world":
            result = self._run_world_enrichment(state)
            state["support_results"].append(result)
            self._remember_support_result(topic, result)
            return self._result_to_text(result, tool_name), None

        if tool_name == "draft_chapter":
            draft = self._run_draft(state)
            state["support_results"].append(draft)
            if _has_pending_user_interrupt():
                updated_candidate = self._build_provisional_candidate(
                    state,
                    draft,
                    reason="interrupt_after_draft",
                )
                self.executor._append_progress_event(
                    "claw_interrupt_defer",
                    f"step={state.get('step', '?')}, action={tool_name}, phase=after_draft",
                    self.executor.chapter_counter,
                )
                return (
                    self._candidate_to_text(updated_candidate, "Draft captured; interrupt pending"),
                    updated_candidate,
                )
            updated_candidate = self._merge_candidate(state, draft)
            return self._candidate_to_text(updated_candidate, "Draft complete"), updated_candidate

        if tool_name == "rewrite_chapter":
            draft = self._run_rewrite(state)
            if _has_pending_user_interrupt():
                updated_candidate = self._build_provisional_candidate(
                    state,
                    draft,
                    reason="interrupt_after_rewrite",
                )
                self.executor._append_progress_event(
                    "claw_interrupt_defer",
                    f"step={state.get('step', '?')}, action={tool_name}, phase=after_rewrite",
                    self.executor.chapter_counter,
                )
                return (
                    self._candidate_to_text(updated_candidate, "Rewrite captured; interrupt pending"),
                    updated_candidate,
                )
            updated_candidate = self._merge_candidate(state, draft)
            return self._candidate_to_text(updated_candidate, "Rewrite complete"), updated_candidate

        if tool_name == "sync_storyboard":
            result = self.workspace_agent.sync_storyboard(state)
            state["support_results"].append(result)
            self._remember_support_result(topic, result)
            return self._result_to_text(result, tool_name), None

        if tool_name == "sync_characters":
            result = self.workspace_agent.sync_characters(state)
            state["support_results"].append(result)
            self._remember_support_result(topic, result)
            return self._result_to_text(result, tool_name), None

        if tool_name == "sync_world":
            result = self.workspace_agent.sync_world(state)
            state["support_results"].append(result)
            self._remember_support_result(topic, result)
            return self._result_to_text(result, tool_name), None

        return f"(unknown tool: {tool_name})", None

    def _result_to_text(self, result: Dict[str, Any], tool_name: str) -> str:
        content = str((result or {}).get("content") or "").strip()
        path = str((result or {}).get("path") or "").strip()
        excerpt = self.executor._safe_excerpt(content, 1200)
        if path:
            return f"[{tool_name} result — path={path}]\n{excerpt}"
        return f"[{tool_name} result]\n{excerpt}"

    def _candidate_to_text(self, candidate: Dict[str, Any], label: str) -> str:
        reward = float(candidate.get("reward_score", 0.0) or 0.0)
        issues = (candidate.get("consistency") or {}).get("all_issues", [])
        length = int(candidate.get("story_length", 0) or 0)
        issue_text = "; ".join(str(i) for i in issues[:4]) if issues else "none"
        excerpt = self.executor._safe_excerpt(str(candidate.get("story_text") or ""), 600)
        status = " | status=provisional_interrupt" if candidate.get("provisional") else ""
        return (
            f"[{label}] reward={reward:.3f} | length={length} chars | issues={len(issues)} ({issue_text}){status}\n"
            f"Excerpt:\n{excerpt}"
        )

    # ------------------------------------------------------------------
    # Sub-agent calls
    # ------------------------------------------------------------------

    def _run_plot_strategy(self, state: Dict[str, Any]) -> Dict[str, Any]:
        outline = self.executor._get_chapter_outline_text(state["topic"], self.executor.chapter_counter)
        prompt = self.executor._prompt(
            f"为第{self.executor.chapter_counter}章生成执行策略：\n"
            f"1) 核心冲突  2) 情绪推进  3) 必须落地的情节节点  4) 不可越界的新设定  5) 叙事重心\n\n"
            f"章节大纲：{outline or '无'}",
            f"Create execution strategy for chapter {self.executor.chapter_counter}:\n"
            f"1) Core conflict  2) Emotional arc  3) Must-land beats  "
            f"4) Forbidden additions  5) Narrative focus\n\nOutline: {outline or 'none'}",
        )
        return self.executor.agents["plot"].generate(
            prompt=prompt, context="", topic=state["topic"],
            genre=state.get("genre"), style_tags=state.get("style_tags"),
        )

    def _run_retrieval(self, state: Dict[str, Any]) -> Dict[str, Any]:
        outline = self.executor._get_chapter_outline_text(state["topic"], self.executor.chapter_counter)
        prompt = self.executor._prompt(
            f"检索与第{self.executor.chapter_counter}章最相关的信息：最近事实卡、人物状态、世界规则、上章衔接。\n"
            f"主题：{state['topic']}\n大纲：{outline or '无'}",
            f"Retrieve most relevant info for chapter {self.executor.chapter_counter}: "
            f"facts, character states, world rules, prior-chapter continuity.\n"
            f"Topic: {state['topic']}\nOutline: {outline or 'none'}",
        )
        return self.executor.agents["retrieval"].generate(
            prompt=prompt, context="", topic=state["topic"],
            genre=state.get("genre"), style_tags=state.get("style_tags"),
        )

    def _run_character_enrichment(self, state: Dict[str, Any]) -> Dict[str, Any]:
        outline = self.executor._get_chapter_outline_text(state["topic"], self.executor.chapter_counter)
        candidate_excerpt = self.executor._safe_excerpt(
            (state.get("best_candidate") or {}).get("story_text", ""), 600
        )
        prompt = self.executor._prompt(
            f"为第{self.executor.chapter_counter}章提炼人物执行约束：\n"
            f"1) 主视角人物  2) 当前动机/阻力/关系变化  3) 对话与行为约束  4) 候选稿中最需修的角色问题\n\n"
            f"大纲：{outline or '无'}\n候选稿：{candidate_excerpt}",
            f"Character constraints for chapter {self.executor.chapter_counter}:\n"
            f"1) Viewpoint  2) Motivations/resistance/relations  3) Dialogue/behavior bounds  "
            f"4) Biggest character issues\n\nOutline: {outline or 'none'}\nDraft: {candidate_excerpt}",
        )
        return self.executor.agents["character"].generate(
            prompt=prompt, context="", topic=state["topic"],
            genre=state.get("genre"), style_tags=state.get("style_tags"),
        )

    def _run_world_enrichment(self, state: Dict[str, Any]) -> Dict[str, Any]:
        outline = self.executor._get_chapter_outline_text(state["topic"], self.executor.chapter_counter)
        candidate_excerpt = self.executor._safe_excerpt(
            (state.get("best_candidate") or {}).get("story_text", ""), 600
        )
        prompt = self.executor._prompt(
            f"为第{self.executor.chapter_counter}章提炼世界观执行约束：\n"
            f"1) 本章涉及的规则/场景边界  2) 不能违背的世界信息  3) 候选稿的设定风险\n\n"
            f"大纲：{outline or '无'}\n候选稿：{candidate_excerpt}",
            f"Worldbuilding constraints for chapter {self.executor.chapter_counter}:\n"
            f"1) Rules/scene boundaries  2) Must-not-violate facts  3) Setting risks in draft\n\n"
            f"Outline: {outline or 'none'}\nDraft: {candidate_excerpt}",
        )
        return self.executor.agents["world"].generate(
            prompt=prompt, context="", topic=state["topic"],
            genre=state.get("genre"), style_tags=state.get("style_tags"),
        )

    def _run_draft(self, state: Dict[str, Any]) -> Dict[str, Any]:
        planning_packet = self.executor._build_planning_packet(
            state["topic"],
            self.executor.chapter_counter,
            current_goal=f"Draft chapter {self.executor.chapter_counter}",
            support_results=state.get("support_results") or [],
        )
        title = planning_packet.get("chapter_title") or self.executor._get_chapter_outline_title(
            state["topic"], self.executor.chapter_counter
        )
        packet_text = planning_packet.get("packet_text") or ""
        prompt = self.executor._prompt(
            f"请为第{self.executor.chapter_counter}章生成完整正文。\n"
            f"主题：{state['topic']}  标题：{title or '未命名'}\n"
            f"目标字数：{state['chapter_min_required']}-{state['chapter_max_allowed']}\n\n"
            f"统一 planning packet：\n{packet_text or '（请基于既有剧情自然推进）'}\n\n"
            "要求：只输出正文，不要标注、解释或提纲。",
            f"Write the full prose for chapter {self.executor.chapter_counter}.\n"
            f"Topic: {state['topic']}  Title: {title or 'Untitled'}\n"
            f"Target: {state['chapter_min_required']}-{state['chapter_max_allowed']} chars\n\n"
            f"Unified planning packet:\n{packet_text or '(advance naturally from established story)'}\n\n"
            "Output full prose only, with no bullets, labels, or explanations.",
        )
        return self.executor.agents["writer"].generate(
            prompt=prompt,
            context=packet_text,
            topic=state["topic"],
            genre=state.get("genre"),
            style_tags=state.get("style_tags"),
            target_length=state.get("chapter_target"),
            target_min_chars=state.get("chapter_min_required"),
            target_max_chars=state.get("chapter_max_allowed"),
        )

    def _planning_packet(self, state: Dict[str, Any], current_goal: str) -> Dict[str, Any]:
        return self.executor._build_planning_packet(
            state["topic"],
            self.executor.chapter_counter,
            current_goal=current_goal,
            support_results=state.get("support_results") or [],
        )

    def _run_plot_strategy(self, state: Dict[str, Any]) -> Dict[str, Any]:
        planning_packet = self._planning_packet(
            state,
            f"Generate tactical execution strategy for chapter {self.executor.chapter_counter}",
        )
        packet_text = planning_packet.get("packet_text") or ""
        prompt = self.executor._prompt(
            (
                f"请为第 {self.executor.chapter_counter} 章生成战术层执行策略。\n"
                "输出内容覆盖：核心冲突、情绪推进、必须落地的关键情节、不可越界的新设定、scene card 拆分建议。\n\n"
                f"统一 planning packet：\n{packet_text or '（暂无 planning packet，可基于现有上下文补全）'}"
            ),
            (
                f"Generate the tactical execution strategy for chapter {self.executor.chapter_counter}.\n"
                "Cover the core conflict, emotional progression, must-land beats, forbidden additions, and suggested scene-card breakdown.\n\n"
                f"Unified planning packet:\n{packet_text or '(no planning packet available yet)'}"
            ),
        )
        return self.executor.agents["plot"].generate(
            prompt=prompt,
            context=packet_text,
            topic=state["topic"],
            genre=state.get("genre"),
            style_tags=state.get("style_tags"),
        )

    def _run_retrieval(self, state: Dict[str, Any]) -> Dict[str, Any]:
        planning_packet = self._planning_packet(
            state,
            f"Retrieve continuity support for chapter {self.executor.chapter_counter}",
        )
        packet_text = planning_packet.get("packet_text") or ""
        prompt = self.executor._prompt(
            (
                f"请为第 {self.executor.chapter_counter} 章检索最相关的连续性上下文。\n"
                "重点召回：最近章节衔接、人物状态、关系变化、世界规则、硬性事实。\n\n"
                f"统一 planning packet：\n{packet_text or '（暂无 planning packet）'}"
            ),
            (
                f"Retrieve the most relevant continuity context for chapter {self.executor.chapter_counter}.\n"
                "Focus on prior-chapter carryover, character state, relationship shifts, world rules, and hard facts.\n\n"
                f"Unified planning packet:\n{packet_text or '(no planning packet available yet)'}"
            ),
        )
        return self.executor.agents["retrieval"].generate(
            prompt=prompt,
            context=packet_text,
            topic=state["topic"],
            genre=state.get("genre"),
            style_tags=state.get("style_tags"),
        )

    def _run_character_enrichment(self, state: Dict[str, Any]) -> Dict[str, Any]:
        planning_packet = self._planning_packet(
            state,
            f"Extract character execution constraints for chapter {self.executor.chapter_counter}",
        )
        packet_text = planning_packet.get("packet_text") or ""
        candidate_excerpt = self.executor._safe_excerpt(
            (state.get("best_candidate") or {}).get("story_text", ""),
            600,
        )
        prompt = self.executor._prompt(
            (
                f"请提炼第 {self.executor.chapter_counter} 章的人物执行约束。\n"
                "输出重点：当前主视角与人物功能、当前动机和阻力、关系变化、对话与行为边界、草稿中的人物问题。\n\n"
                f"统一 planning packet：\n{packet_text or '（暂无 planning packet）'}\n\n"
                f"候选草稿摘录：\n{candidate_excerpt or '（暂无草稿）'}"
            ),
            (
                f"Extract character execution constraints for chapter {self.executor.chapter_counter}.\n"
                "Focus on viewpoint/function, motivations and resistance, relationship shifts, dialogue/behavior bounds, and the main character issues in the draft.\n\n"
                f"Unified planning packet:\n{packet_text or '(no planning packet available yet)'}\n\n"
                f"Draft excerpt:\n{candidate_excerpt or '(no draft yet)'}"
            ),
        )
        return self.executor.agents["character"].generate(
            prompt=prompt,
            context=packet_text,
            topic=state["topic"],
            genre=state.get("genre"),
            style_tags=state.get("style_tags"),
        )

    def _run_world_enrichment(self, state: Dict[str, Any]) -> Dict[str, Any]:
        planning_packet = self._planning_packet(
            state,
            f"Extract world and continuity constraints for chapter {self.executor.chapter_counter}",
        )
        packet_text = planning_packet.get("packet_text") or ""
        candidate_excerpt = self.executor._safe_excerpt(
            (state.get("best_candidate") or {}).get("story_text", ""),
            600,
        )
        prompt = self.executor._prompt(
            (
                f"请提炼第 {self.executor.chapter_counter} 章的世界观与连续性约束。\n"
                "输出重点：规则与场景边界、不能违背的设定和事实、草稿中的世界观风险。\n\n"
                f"统一 planning packet：\n{packet_text or '（暂无 planning packet）'}\n\n"
                f"候选草稿摘录：\n{candidate_excerpt or '（暂无草稿）'}"
            ),
            (
                f"Extract worldbuilding and continuity constraints for chapter {self.executor.chapter_counter}.\n"
                "Focus on rules and scene boundaries, must-not-violate facts, and world/continuity risks in the draft.\n\n"
                f"Unified planning packet:\n{packet_text or '(no planning packet available yet)'}\n\n"
                f"Draft excerpt:\n{candidate_excerpt or '(no draft yet)'}"
            ),
        )
        return self.executor.agents["world"].generate(
            prompt=prompt,
            context=packet_text,
            topic=state["topic"],
            genre=state.get("genre"),
            style_tags=state.get("style_tags"),
        )

    def _run_draft(self, state: Dict[str, Any]) -> Dict[str, Any]:
        planning_packet = self._planning_packet(
            state,
            f"Draft chapter {self.executor.chapter_counter}",
        )
        title = planning_packet.get("chapter_title") or self.executor._get_chapter_outline_title(
            state["topic"],
            self.executor.chapter_counter,
        )
        packet_text = planning_packet.get("packet_text") or ""
        prompt = self.executor._prompt(
            (
                f"请写出第 {self.executor.chapter_counter} 章完整正文。\n"
                f"主题：{state['topic']}\n"
                f"标题：{title or '未命名'}\n"
                f"目标字数：{state['chapter_min_required']}-{state['chapter_max_allowed']}\n\n"
                f"统一 planning packet：\n{packet_text or '（请基于既有剧情自然推进）'}\n\n"
                "只输出正文，不要输出提纲、标签、解释或额外说明。"
            ),
            (
                f"Write the full prose for chapter {self.executor.chapter_counter}.\n"
                f"Topic: {state['topic']}\n"
                f"Title: {title or 'Untitled'}\n"
                f"Target: {state['chapter_min_required']}-{state['chapter_max_allowed']} chars\n\n"
                f"Unified planning packet:\n{packet_text or '(advance naturally from the established story)'}\n\n"
                "Output prose only. No bullets, labels, or explanations."
            ),
        )
        return self.executor.agents["writer"].generate(
            prompt=prompt,
            context=packet_text,
            topic=state["topic"],
            genre=state.get("genre"),
            style_tags=state.get("style_tags"),
            target_length=state.get("chapter_target"),
            target_min_chars=state.get("chapter_min_required"),
            target_max_chars=state.get("chapter_max_allowed"),
        )

    def _run_rewrite(self, state: Dict[str, Any]) -> Dict[str, Any]:
        best = state.get("best_candidate") or {}
        rewritten = self.executor._rewrite_chapter_with_feedback(
            topic=state["topic"],
            story_text=best.get("story_text", ""),
            generated_content=(state.get("generated_content") or []) + (state.get("support_results") or []),
            evaluation_result=best.get("evaluation", {}),
            consistency_result=best.get("consistency", {}),
            genre=state.get("genre"),
            style_tags=state.get("style_tags"),
            chapter_target=state.get("chapter_target"),
            chapter_min_required=state.get("chapter_min_required"),
            chapter_max_allowed=state.get("chapter_max_allowed"),
            subround=int(state.get("step", 1) or 1),
        )
        return rewritten[0]

    def _merge_candidate(self, state: Dict[str, Any], writer_result: Dict[str, Any]) -> Dict[str, Any]:
        support = list(state.get("support_results") or [])
        challenger = self.executor._score_chapter_candidate(
            topic=state["topic"],
            round_results=support + [writer_result],
            genre=state.get("genre"),
            style_tags=state.get("style_tags"),
            chapter_target=state.get("chapter_target"),
            chapter_min_required=state.get("chapter_min_required"),
            chapter_max_allowed=state.get("chapter_max_allowed"),
        )
        current = state.get("best_candidate")
        if not current:
            return challenger
        return self.executor._select_better_candidate(current, challenger)

    # ------------------------------------------------------------------
    # Memory helpers
    # ------------------------------------------------------------------

    def _remember_support_result(self, topic: str, result: Dict[str, Any]) -> None:
        result_type = str(result.get("type") or result.get("role") or "working_set")
        content = str(result.get("content") or "").strip()
        if not content:
            return
        bank_targets = {
            "plot": ["chapter_briefs", "scene_cards"],
            "character": ["entity_state", "relationship_state"],
            "world": ["world_state", "continuity_facts"],
            "retrieval": ["tool_observations", "working_set"],
            "workspace": ["tool_observations", "working_set"],
            "storyboard_sync": ["chapter_briefs", "working_set"],
            "character_sync": ["entity_state", "relationship_state"],
            "world_sync": ["world_state", "continuity_facts"],
        }.get(result_type, ["working_set"])
        for bank in bank_targets:
            self.memory.store_claw_memory(
                bank, content, topic,
                metadata={"chapter": self.executor.chapter_counter, "source_type": result_type},
                store_vector=True,
            )

    def _remember_candidate_snapshot(self, topic: str, candidate: Dict[str, Any], label: str) -> None:
        story_text = str(candidate.get("story_text") or "").strip()
        if not story_text:
            return
        summary = (
            f"label={label}\nchapter={self.executor.chapter_counter}\n"
            f"reward={float(candidate.get('reward_score', 0.0) or 0.0):.3f}\n"
            f"issues={int(candidate.get('issues_count', 0) or 0)}\n"
            f"excerpt={self.executor._safe_excerpt(story_text, 700)}"
        )
        self.memory.store_claw_memory(
            "working_set", summary, topic,
            metadata={"chapter": self.executor.chapter_counter, "label": label},
            store_vector=True,
        )
        self.memory.store_claw_memory(
            "revision_notes", summary, topic,
            metadata={"chapter": self.executor.chapter_counter, "label": label},
            store_vector=False,
        )

    def _support_context(self, results: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for item in results[-5:]:
            item_type = str(item.get("type") or item.get("role") or "support")
            content = str(item.get("content") or "").strip()
            if content:
                parts.append(f"【{item_type}】\n{self.executor._safe_excerpt(content, 800)}")
        return "\n\n".join(parts)

    def _ensure_workspace_sync(self, state: Dict[str, Any], tools: List[Dict]) -> None:
        topic = str(state.get("topic") or "")
        support_types = {item.get("type") for item in (state.get("support_results") or [])}
        enabled_tool_names = {t["function"]["name"] for t in tools}
        for result_type, action_name, handler in [
            ("storyboard_sync", "sync_storyboard", self.workspace_agent.sync_storyboard),
            ("character_sync", "sync_characters", self.workspace_agent.sync_characters),
            ("world_sync", "sync_world", self.workspace_agent.sync_world),
        ]:
            if result_type in support_types or action_name not in enabled_tool_names:
                continue
            result = handler(state)
            state["support_results"].append(result)
            self._remember_support_result(topic, result)
