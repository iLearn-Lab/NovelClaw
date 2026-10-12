from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List
from utils.file_io import atomic_write_text


class WorkspaceToolAgent:
    """Safe local workspace tools for NovelClaw.

    This agent writes project artifacts inside the current run directory so
    OpenClaw can act on the local workspace instead of only producing prose.
    """

    def __init__(self, executor: Any):
        self.executor = executor
        self.memory = executor.memory_system
        self.llm_client = executor.llm_client
        self.config = executor.config

    @property
    def chapter_no(self) -> int:
        return int(getattr(self.executor, "chapter_counter", 0) or 0)

    def workspace_root(self) -> Path:
        root = Path(self.config.runs_dir) / str(self.config.run_id or "") / "workspace"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def inspect_workspace(self, state: Dict[str, Any]) -> Dict[str, Any]:
        root = self.workspace_root()
        chapter_dir = Path(self.config.runs_dir) / str(self.config.run_id or "") / "chapters"
        workspace_files = sorted(
            [str(path.relative_to(root)).replace("\\", "/") for path in root.rglob("*") if path.is_file()]
        )[:40]
        chapter_files = sorted([path.name for path in chapter_dir.glob("*.txt")])[:20] if chapter_dir.exists() else []
        memory = getattr(self.memory, "memory_index", {}) or {}
        counts = {
            "outlines": len(memory.get("outlines", []) or []),
            "characters": len(memory.get("characters", []) or []),
            "world_settings": len(memory.get("world_settings", []) or []),
            "plot_points": len(memory.get("plot_points", []) or []),
            "fact_cards": len(memory.get("fact_cards", []) or []),
            "texts": len(memory.get("texts", []) or []),
        }
        report = "\n".join(
            [
                f"topic={state.get('topic', '')}",
                f"chapter={self.chapter_no}",
                f"workspace_root={root}",
                f"workspace_files={len(workspace_files)}",
                f"chapter_files={len(chapter_files)}",
                "memory_counts=" + json.dumps(counts, ensure_ascii=False),
                "workspace_preview=",
                *(f"- {item}" for item in workspace_files[:12]),
                "chapter_preview=",
                *(f"- {item}" for item in chapter_files[:8]),
            ]
        ).strip()
        path = self._write_file(f"observations/chapter_{self.chapter_no:03d}_workspace_scan.md", report)
        self.memory.store_claw_memory(
            "tool_observations",
            report,
            str(state.get("topic") or "global"),
            metadata={"chapter": self.chapter_no, "path": str(path), "tool": "inspect_workspace"},
            store_vector=False,
        )
        return {"type": "workspace", "content": report, "path": str(path), "role": "tool"}

    def sync_storyboard(self, state: Dict[str, Any]) -> Dict[str, Any]:
        topic = str(state.get("topic") or "")
        planning_packet = self.executor._build_planning_packet(
            topic,
            self.chapter_no,
            current_goal=f"Sync storyboard for chapter {self.chapter_no}",
            support_results=state.get("support_results") or [],
        )
        outline = str(planning_packet.get("chapter_outline") or "").strip()
        title = str(planning_packet.get("chapter_title") or f"Chapter {self.chapter_no}").strip()
        candidate = state.get("best_candidate") or {}
        support_results = list(state.get("support_results") or [])
        support_lines = [
            f"- {item.get('type', 'support')}: {self.executor._safe_excerpt(item.get('content', ''), 180)}"
            for item in support_results[-6:]
            if str(item.get("content") or "").strip()
        ]
        history_lines = [
            f"- step {item.get('step')}: {item.get('action')} | {item.get('reason', '')}"
            for item in (state.get("history") or [])[-8:]
        ]
        content = "\n".join(
            [
                f"# {title}",
                "",
                f"- topic: {topic}",
                f"- chapter: {self.chapter_no}",
                f"- reward: {float(candidate.get('reward_score', 0.0) or 0.0):.3f}",
                f"- issues: {int(candidate.get('issues_count', 0) or 0)}",
                f"- length: {int(candidate.get('story_length', 0) or 0)}",
                "",
                "## Unified Planning Packet",
                planning_packet.get("packet_text") or "No planning packet yet.",
                "",
                "## Support Signals",
                *(support_lines or ["- none"]),
                "",
                "## Claw History",
                *(history_lines or ["- none"]),
                "",
                "## Candidate Excerpt",
                self.executor._safe_excerpt(candidate.get("story_text", "") or "", 1200) or "(none yet)",
            ]
        ).strip()
        path = self._write_file(f"storyboard/chapter_{self.chapter_no:03d}_brief.md", content)
        if outline:
            self.memory.store_outline(
                outline,
                topic,
                structure={"kind": "chapter_outline", "chapter": self.chapter_no, "title": title, "source": "sync_storyboard"},
            )
        self.memory.store_claw_memory(
            "chapter_briefs",
            content,
            topic,
            metadata={"chapter": self.chapter_no, "path": str(path), "tool": "sync_storyboard"},
            store_vector=False,
        )
        for bullet in self._outline_bullets(outline or planning_packet.get("packet_text") or content)[:5]:
            self.memory.store_plot_point(bullet, topic, position=f"chapter_{self.chapter_no}")
        return {"type": "storyboard_sync", "content": content, "path": str(path), "role": "tool"}

    def sync_characters(self, state: Dict[str, Any]) -> Dict[str, Any]:
        topic = str(state.get("topic") or "")
        candidate = str((state.get("best_candidate") or {}).get("story_text") or "")
        support_text = self._support_text(state)
        prompt = f"""
Extract the currently relevant characters for this writing task.
Return strict JSON only:
{{
  "characters": [
    {{"name": "", "role": "", "motivation": "", "conflict": "", "arc": ""}}
  ]
}}

Topic:
{topic}

Support context:
{support_text or '- none'}

Candidate excerpt:
{self.executor._safe_excerpt(candidate, 1600) or '(none yet)'}
""".strip()
        data = self._ask_json(prompt)
        characters = data.get("characters") if isinstance(data.get("characters"), list) else []
        rows: List[str] = [f"# Character State · Chapter {self.chapter_no}", ""]
        stored = 0
        for item in characters[:8]:
            name = str((item or {}).get("name") or "").strip()
            if not name:
                continue
            role = str((item or {}).get("role") or "").strip()
            motivation = str((item or {}).get("motivation") or "").strip()
            conflict = str((item or {}).get("conflict") or "").strip()
            arc = str((item or {}).get("arc") or "").strip()
            info = "\n".join([
                f"role: {role or '-'}",
                f"motivation: {motivation or '-'}",
                f"conflict: {conflict or '-'}",
                f"arc: {arc or '-'}",
            ])
            rows.extend([f"## {name}", info, ""])
            self.memory.store_character(
                name,
                info,
                topic,
                attributes={"role": role, "motivation": motivation, "conflict": conflict, "arc": arc, "chapter": self.chapter_no},
            )
            stored += 1
        if stored == 0:
            rows.append("No character update extracted yet.")
        content = "\n".join(rows).strip()
        path = self._write_file(f"characters/chapter_{self.chapter_no:03d}_characters.md", content)
        self.memory.store_claw_memory(
            "entity_state",
            content,
            topic,
            metadata={"chapter": self.chapter_no, "path": str(path), "tool": "sync_characters", "count": stored},
            store_vector=False,
        )
        return {"type": "character_sync", "content": content, "path": str(path), "role": "tool"}

    def sync_world(self, state: Dict[str, Any]) -> Dict[str, Any]:
        topic = str(state.get("topic") or "")
        candidate = str((state.get("best_candidate") or {}).get("story_text") or "")
        support_text = self._support_text(state)
        prompt = f"""
Extract reusable world rules and continuity facts for the current writing task.
Return strict JSON only:
{{
  "world_items": [
    {{"name": "", "rule": "", "fact": ""}}
  ],
  "fact_cards": ["fact 1", "fact 2"]
}}

Topic:
{topic}

Support context:
{support_text or '- none'}

Candidate excerpt:
{self.executor._safe_excerpt(candidate, 1600) or '(none yet)'}
""".strip()
        data = self._ask_json(prompt)
        world_items = data.get("world_items") if isinstance(data.get("world_items"), list) else []
        fact_cards = data.get("fact_cards") if isinstance(data.get("fact_cards"), list) else []
        rows: List[str] = [f"# World State · Chapter {self.chapter_no}", ""]
        stored_world = 0
        for item in world_items[:8]:
            name = str((item or {}).get("name") or "").strip() or f"world_item_{stored_world + 1}"
            rule = str((item or {}).get("rule") or "").strip()
            fact = str((item or {}).get("fact") or "").strip()
            body = "\n".join([f"rule: {rule or '-'}", f"fact: {fact or '-'}"])
            rows.extend([f"## {name}", body, ""])
            self.memory.store_world_setting(name, body, topic)
            if fact:
                self.memory.store_fact_card(fact, topic, card_type="world_rule", metadata={"chapter": self.chapter_no, "name": name})
            stored_world += 1
        for fact in fact_cards[:10]:
            fact_text = str(fact or "").strip()
            if not fact_text:
                continue
            rows.append(f"- {fact_text}")
            self.memory.store_fact_card(fact_text, topic, card_type="continuity", metadata={"chapter": self.chapter_no})
        if stored_world == 0 and not rows[-1:]:
            rows.append("No world update extracted yet.")
        content = "\n".join(rows).strip()
        path = self._write_file(f"world/chapter_{self.chapter_no:03d}_world.md", content)
        self.memory.store_claw_memory(
            "world_state",
            content,
            topic,
            metadata={"chapter": self.chapter_no, "path": str(path), "tool": "sync_world", "count": stored_world},
            store_vector=False,
        )
        return {"type": "world_sync", "content": content, "path": str(path), "role": "tool"}

    def _support_text(self, state: Dict[str, Any]) -> str:
        parts: List[str] = []
        for item in list(state.get("support_results") or [])[-6:]:
            item_type = str(item.get("type") or item.get("role") or "support")
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            parts.append(f"[{item_type}]\n{self.executor._safe_excerpt(content, 500)}")
        return "\n\n".join(parts)

    def _ask_json(self, prompt: str) -> Dict[str, Any]:
        try:
            raw = self.llm_client.chat(
                messages=[
                    {"role": "system", "content": "Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=900,
            )
        except Exception:
            return {}
        return self._parse_json_object(raw)

    def _parse_json_object(self, text: str) -> Dict[str, Any]:
        match = re.search(r"\{.*\}", str(text or ""), re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def _outline_bullets(self, text: str) -> List[str]:
        lines = [line.strip(" -*•\t") for line in str(text or "").splitlines()]
        return [line for line in lines if line][:8]

    def _write_file(self, relative_path: str, content: str) -> Path:
        root = self.workspace_root().resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Workspace artifacts must stay inside the current run")
        atomic_write_text(path, str(content or "").strip() + "\n")
        return path
