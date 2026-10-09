"""
记忆管理系统：存储和检索生成历史
用于减少幻觉和保持一致性
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import uuid4
import json
import os
import re
import shutil
from config import Config
from pathlib import Path
from utils.memory_store import MemoryIndex, load_memory_index, save_memory_index


class MemorySystem:
    CLAW_BANKS = (
        "session_profile",
        "language_profile",
        "user_preferences",
        "task_briefs",
        "story_premise",
        "style_guide",
        "chapter_briefs",
        "scene_cards",
        "entity_state",
        "relationship_state",
        "world_state",
        "continuity_facts",
        "tool_observations",
        "decision_log",
        "revision_notes",
        "working_set",
    )

    """记忆系统：管理生成历史，确保一致性"""
    
    def __init__(self, config: Config):
        self.config = config
        self.vector_memory_enabled = self._should_use_vector_memory()

        self.memory_store = None
        self.document_processor = None
        if self.vector_memory_enabled:
            from rag.vector_store import VectorStore
            from rag.document_processor import DocumentProcessor
            self.memory_store = VectorStore(
                config,
                collection_name="memory_collection",
                db_path=getattr(config, "memory_vector_db_path", None) or config.vector_db_path
            )
            self.document_processor = DocumentProcessor(config)
        self.memory_index_path = os.path.join(
            getattr(config, "memory_vector_db_path", config.vector_db_path),
            "memory_index.json"
        )

        legacy_index_path = os.path.join(config.vector_db_path, "memory_index.json")
        if not os.path.exists(self.memory_index_path) and os.path.exists(legacy_index_path):
            try:
                os.makedirs(os.path.dirname(self.memory_index_path), exist_ok=True)
                shutil.copy2(legacy_index_path, self.memory_index_path)
            except Exception:
                pass

        self.memory_index = self._load_memory_index()
        self._ensure_memory_schema()
        self._save_memory_index()

        if os.getenv("MIGRATE_LEGACY_MEMORY", "0") in {"1", "true", "True", "YES", "yes", "y"}:
            self._maybe_migrate_legacy_memory_collection()


    def _maybe_migrate_legacy_memory_collection(self):
        """
        将旧 vector_db_path 下的 memory_collection 迁移到 memory_vector_db_path。
        仅在新库为空时尝试；失败则静默跳过。
        """
        new_path = getattr(self.config, "memory_vector_db_path", None)
        if not new_path:
            return

        if not self.vector_memory_enabled or self.memory_store is None:
            return

        try:
            new_count = self.memory_store.get_collection_size()
        except Exception:
            new_count = 0
        if new_count and new_count > 0:
            return

        legacy_path = self.config.vector_db_path
        # legacy_path 与 new_path 相同则无需迁移
        try:
            if os.path.abspath(legacy_path) == os.path.abspath(new_path):
                return
        except Exception:
            return

        try:
            import chromadb
            from chromadb.config import Settings

            legacy_client = chromadb.PersistentClient(
                path=legacy_path,
                settings=Settings(anonymized_telemetry=False),
            )
            legacy_col = legacy_client.get_collection("memory_collection")

            # 读取总量（如果失败则保守尝试 get 一次）
            try:
                total = legacy_col.count()
            except Exception:
                total = 0

            if total <= 0:
                return

            batch_size = 200
            offset = 0
            while offset < total:
                res = legacy_col.get(
                    limit=batch_size,
                    offset=offset,
                    include=["documents", "metadatas", "embeddings"],
                )
                ids = res.get("ids") or []
                if not ids:
                    break

                self.memory_store.collection.add(
                    ids=ids,
                    documents=res.get("documents"),
                    metadatas=res.get("metadatas"),
                    embeddings=res.get("embeddings"),
                )
                offset += len(ids)

            print(f"[MemorySystem] 已从旧库迁移 memory_collection: {offset} 条 -> {new_path}")
        except Exception:
            return
    
    def _load_memory_index(self) -> Dict:
        """加载记忆索引"""
        if os.path.exists(self.memory_index_path):
            try:
                return load_memory_index(Path(self.memory_index_path))
            except:
                return MemoryIndex(self._empty_memory_index())
        return MemoryIndex(self._empty_memory_index())

    def _empty_memory_index(self) -> Dict[str, Any]:
        return {
            "schema_version": 2,
            "texts": [],
            "outlines": [],
            "characters": [],
            "world_settings": [],
            "plot_points": [],
            "fact_cards": [],
            "claw": {bank: [] for bank in self.CLAW_BANKS},
        }

    def _ensure_memory_schema(self) -> None:
        self.memory_index.setdefault("schema_version", 2)
        self.memory_index.setdefault("texts", [])
        self.memory_index.setdefault("outlines", [])
        self.memory_index.setdefault("characters", [])
        self.memory_index.setdefault("world_settings", [])
        self.memory_index.setdefault("plot_points", [])
        self.memory_index.setdefault("fact_cards", [])
        claw = self.memory_index.setdefault("claw", {})
        if not isinstance(claw, dict):
            claw = {}
            self.memory_index["claw"] = claw
        for bank in self.CLAW_BANKS:
            claw.setdefault(bank, [])
        for outline in self.memory_index.get("outlines", []):
            outline.setdefault("content", "")
    
    def _save_memory_index(self):
        """保存记忆索引"""
        os.makedirs(os.path.dirname(self.memory_index_path), exist_ok=True)
        save_memory_index(Path(self.memory_index_path), self.memory_index)

    def _should_use_vector_memory(self) -> bool:
        embed_name = str(getattr(self.config, "embedding_model", "") or "").strip().lower()
        if embed_name in {"", "none", "noop", "disable", "disabled"}:
            return False
        return bool(getattr(self.config, "enable_rag", False))

    def _is_en(self, language: Optional[str] = None) -> bool:
        lang = str(language or getattr(self.config, "language", "zh") or "zh").lower()
        return lang.startswith("en")

    def _lang_text(self, zh: str, en: str, language: Optional[str] = None) -> str:
        return en if self._is_en(language) else zh

    def store_claw_memory(
        self,
        bank: str,
        content: str,
        topic: str,
        metadata: Optional[Dict[str, Any]] = None,
        store_vector: bool = True,
    ) -> str:
        bank = bank if bank in self.CLAW_BANKS else "working_set"
        topic = str(topic or "global").strip() or "global"
        timestamp = datetime.now().isoformat()
        memory_id = f"claw_{bank}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index['claw'].get(bank, []))}" + "_" + uuid4().hex[:12]
        merged_metadata = {
            "type": "claw_memory",
            "bank": bank,
            "memory_id": memory_id,
            "topic": topic,
            "timestamp": timestamp,
            **(metadata or {}),
        }

        if store_vector and self.vector_memory_enabled and self.document_processor is not None and self.memory_store is not None and content.strip():
            processed_docs = self.document_processor.process_document(content)
            for doc in processed_docs:
                doc["metadata"].update(merged_metadata)
            self.memory_store.add_documents(processed_docs)

        self.memory_index["claw"].setdefault(bank, []).append(
            {
                "id": memory_id,
                "bank": bank,
                "topic": topic,
                "content": content,
                "timestamp": timestamp,
                "metadata": metadata or {},
            }
        )
        self._save_memory_index()
        return memory_id

    def _topic_matches(self, entry_topic: str, requested_topic: str) -> bool:
        entry_topic = str(entry_topic or "").strip()
        requested_topic = str(requested_topic or "").strip()
        if not requested_topic:
            return True
        if entry_topic == requested_topic:
            return True
        if entry_topic in {"*", "global"}:
            return True
        return requested_topic in entry_topic or entry_topic in requested_topic

    def _query_tokens(self, text: str) -> List[str]:
        raw = str(text or "").lower()
        return re.findall(r"[a-z0-9_]+|[一-鿿]", raw)

    def _searchable_entries(self, memory_types: Optional[List[str]] = None, topic: Optional[str] = None) -> List[Dict[str, Any]]:
        mapping = {
            "generated_text": "texts",
            "text": "texts",
            "outline": "outlines",
            "character": "characters",
            "world_setting": "world_settings",
            "plot_point": "plot_points",
            "fact_card": "fact_cards",
        }
        requested = set(memory_types) if memory_types else {"generated_text", "outline", "character", "world_setting", "plot_point", "fact_card"}
        entries: List[Dict[str, Any]] = []
        for memory_type in requested:
            bucket = mapping.get(memory_type)
            if not bucket:
                continue
            for item in self.memory_index.get(bucket, []):
                if topic and not self._topic_matches(item.get("topic", ""), topic):
                    continue
                metadata: Dict[str, Any] = {"type": memory_type, "topic": item.get("topic", "")}
                for key in ("name", "position", "card_type"):
                    if item.get(key):
                        metadata[key] = item.get(key)
                entries.append({
                    "text": str(item.get("content", "") or ""),
                    "metadata": metadata,
                    "timestamp": str(item.get("timestamp", "") or ""),
                })
        return entries

    def _lexical_search(self, query: str, memory_types: Optional[List[str]] = None, topic: Optional[str] = None, top_k: int = 5) -> List[Dict]:
        query_text = str(query or "").strip().lower()
        query_tokens = self._query_tokens(query_text)
        rows: List[Dict[str, Any]] = []
        for entry in self._searchable_entries(memory_types=memory_types, topic=topic):
            haystack = (entry.get("text", "") + "\n" + json.dumps(entry.get("metadata", {}), ensure_ascii=False)).lower()
            score = 0.0
            if query_text and query_text in haystack:
                score += 8.0
            if query_tokens:
                score += float(sum(1 for token in set(query_tokens) if token and token in haystack))
            if topic and entry.get("metadata", {}).get("topic") == topic:
                score += 1.5
            if score <= 0 and not query_text:
                score = 0.5
            if score > 0:
                rows.append({
                    "text": entry.get("text", ""),
                    "metadata": entry.get("metadata", {}),
                    "distance": 1.0 / (1.0 + score),
                    "score": score,
                    "timestamp": entry.get("timestamp", ""),
                })
        rows.sort(key=lambda item: (item.get("score", 0.0), item.get("timestamp", "")), reverse=True)
        trimmed = rows[: max(1, top_k)]
        for item in trimmed:
            item.pop("score", None)
            item.pop("timestamp", None)
        return trimmed

    def get_claw_memories(
        self,
        topic: str,
        banks: Optional[List[str]] = None,
        limit_per_bank: int = 5,
        metadata_filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        selected = [bank for bank in (banks or list(self.CLAW_BANKS)) if bank in self.CLAW_BANKS]
        claw = self.memory_index.get("claw", {})
        result: Dict[str, List[Dict[str, Any]]] = {}
        for bank in selected:
            entries = []
            for item in claw.get(bank, []):
                if not self._topic_matches(item.get("topic", ""), topic):
                    continue
                if metadata_filters:
                    meta = item.get("metadata") or {}
                    ok = True
                    for key, value in metadata_filters.items():
                        if meta.get(key) != value:
                            ok = False
                            break
                    if not ok:
                        continue
                entries.append(item)
            result[bank] = entries[-limit_per_bank:]
        return result

    def get_claw_memory_overview(self, topic: str) -> Dict[str, Any]:
        grouped = self.get_claw_memories(topic, limit_per_bank=50)
        counts = {bank: len(items) for bank, items in grouped.items()}
        latest = {bank: (items[-1] if items else None) for bank, items in grouped.items()}
        previews = {
            bank: [str(item.get("content") or "")[:180] for item in items[-3:]]
            for bank, items in grouped.items()
        }
        return {"counts": counts, "latest": latest, "previews": previews}

    def build_claw_packet(
        self,
        topic: str,
        current_goal: str = "",
        banks: Optional[List[str]] = None,
        limit_per_bank: int = 3,
    ) -> Dict[str, Any]:
        selected = banks or [
            "session_profile",
            "language_profile",
            "user_preferences",
            "task_briefs",
            "story_premise",
            "style_guide",
            "chapter_briefs",
            "scene_cards",
            "entity_state",
            "relationship_state",
            "world_state",
            "continuity_facts",
            "tool_observations",
            "decision_log",
            "revision_notes",
            "working_set",
        ]
        grouped = self.get_claw_memories(topic, banks=selected, limit_per_bank=limit_per_bank)
        counts = {bank: len(grouped.get(bank) or []) for bank in selected}
        return {
            "topic": topic,
            "goal": current_goal.strip(),
            "banks": selected,
            "counts": counts,
            "grouped": grouped,
        }

    def build_claw_context(
        self,
        topic: str,
        current_goal: str = "",
        banks: Optional[List[str]] = None,
        limit_per_bank: int = 3,
    ) -> str:
        packet = self.build_claw_packet(
            topic=topic,
            current_goal=current_goal,
            banks=banks,
            limit_per_bank=limit_per_bank,
        )
        parts: List[str] = []
        if packet.get("goal"):
            parts.append(f"=== CURRENT GOAL ===\n{packet['goal']}")
        for bank in packet["banks"]:
            entries = packet["grouped"].get(bank) or []
            if not entries:
                continue
            parts.append(f"=== {bank.upper()} ({len(entries)}) ===")
            for item in entries:
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                meta = item.get("metadata") or {}
                chapter = meta.get("chapter")
                prefix = f"[chapter={chapter}] " if chapter is not None else ""
                parts.append(prefix + content)
        return "\n\n".join(parts).strip()

    def store_chapter_claw_state(
        self,
        topic: str,
        chapter: int,
        *,
        title: str = "",
        outline_text: str = "",
        plan_text: str = "",
        summary_text: str = "",
        rolling_summary: str = "",
        fact_cards: Optional[List[str]] = None,
        story_text: str = "",
        evaluation_suggestions: Optional[List[str]] = None,
        consistency_issues: Optional[List[str]] = None,
        reward_score: Optional[float] = None,
        issues_count: Optional[int] = None,
    ) -> None:
        brief_parts = [f"chapter={chapter}"]
        if title:
            brief_parts.append(f"title={title}")
        if outline_text:
            brief_parts.append("[outline]")
            brief_parts.append(outline_text.strip())
        if plan_text:
            brief_parts.append("[plan]")
            brief_parts.append(plan_text.strip())
        if summary_text:
            brief_parts.append("[summary]")
            brief_parts.append(summary_text.strip())
        if len(brief_parts) > 1:
            self.store_claw_memory(
                "chapter_briefs",
                "\n".join(brief_parts),
                topic,
                metadata={"chapter": chapter},
                store_vector=True,
            )

        if rolling_summary:
            self.store_claw_memory(
                "working_set",
                f"chapter={chapter}\nkind=rolling_summary\n{rolling_summary.strip()}",
                topic,
                metadata={"chapter": chapter, "kind": "rolling_summary"},
                store_vector=False,
            )

        if story_text:
            excerpt = story_text.strip()
            if len(excerpt) > 1800:
                excerpt = excerpt[:1800].rstrip() + "..."
            snapshot_lines = [f"chapter={chapter}", "kind=story_snapshot"]
            if reward_score is not None:
                snapshot_lines.append(f"reward={float(reward_score):.3f}")
            if issues_count is not None:
                snapshot_lines.append(f"issues={int(issues_count)}")
            snapshot_lines.append(excerpt)
            self.store_claw_memory(
                "working_set",
                "\n".join(snapshot_lines),
                topic,
                metadata={"chapter": chapter, "kind": "story_snapshot"},
                store_vector=True,
            )

        for card in (fact_cards or [])[:8]:
            card_text = str(card or "").strip()
            if not card_text:
                continue
            self.store_claw_memory(
                "continuity_facts",
                card_text,
                topic,
                metadata={"chapter": chapter, "kind": "fact_card"},
                store_vector=True,
            )

        if consistency_issues:
            issue_lines = [f"chapter={chapter}", "kind=consistency_issues"]
            issue_lines.extend(f"- {str(item).strip()}" for item in consistency_issues[:8] if str(item).strip())
            if len(issue_lines) > 2:
                self.store_claw_memory(
                    "revision_notes",
                    "\n".join(issue_lines),
                    topic,
                    metadata={"chapter": chapter, "kind": "consistency_issues"},
                    store_vector=False,
                )

        if evaluation_suggestions:
            suggestion_lines = [f"chapter={chapter}", "kind=evaluator_suggestions"]
            suggestion_lines.extend(f"- {str(item).strip()}" for item in evaluation_suggestions[:8] if str(item).strip())
            if len(suggestion_lines) > 2:
                self.store_claw_memory(
                    "revision_notes",
                    "\n".join(suggestion_lines),
                    topic,
                    metadata={"chapter": chapter, "kind": "evaluator_suggestions"},
                    store_vector=False,
                )

    def store_generated_text(
        self,
        text: str,
        topic: str,
        metadata: Optional[Dict] = None,
        store_vector: bool = True,
        content_path: Optional[str] = None,
    ) -> str:
        memory_id = f"text_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index['texts'])}" + "_" + uuid4().hex[:12]

        if store_vector and self.vector_memory_enabled and self.document_processor is not None and self.memory_store is not None:
            processed_docs = self.document_processor.process_document(text)
            for doc in processed_docs:
                doc["metadata"].update({
                    "type": "generated_text",
                    "memory_id": memory_id,
                    "topic": topic,
                    "timestamp": datetime.now().isoformat(),
                    **(metadata or {}),
                })
            self.memory_store.add_documents(processed_docs)

        entry = {
            "id": memory_id,
            "topic": topic,
            "length": len(text),
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
            "content": text,
        }
        if content_path:
            entry["path"] = content_path
        self.memory_index["texts"].append(entry)
        self._save_memory_index()
        return memory_id

    def store_outline(
        self,
        outline: str,
        topic: str,
        structure: Optional[Dict] = None
    ) -> str:
        memory_id = f"outline_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index['outlines'])}" + "_" + uuid4().hex[:12]

        if self.vector_memory_enabled and self.document_processor is not None and self.memory_store is not None:
            processed_docs = self.document_processor.process_document(outline)
            for doc in processed_docs:
                doc["metadata"].update({
                    "type": "outline",
                    "memory_id": memory_id,
                    "topic": topic,
                    "timestamp": datetime.now().isoformat(),
                })
            self.memory_store.add_documents(processed_docs)

        self.memory_index["outlines"].append({
            "id": memory_id,
            "topic": topic,
            "content": outline,
            "structure": structure or {},
            "timestamp": datetime.now().isoformat(),
        })
        self._save_memory_index()
        return memory_id

    def store_character(
        self,
        character_name: str,
        character_info: str,
        topic: str,
        attributes: Optional[Dict] = None
    ) -> str:
        memory_id = f"character_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index['characters'])}" + "_" + uuid4().hex[:12]

        full_text = f"?????{character_name}\n\n{character_info}"
        if attributes:
            full_text += f"\n\n?????\n{json.dumps(attributes, ensure_ascii=False, indent=2)}"

        if self.vector_memory_enabled and self.document_processor is not None and self.memory_store is not None:
            processed_docs = self.document_processor.process_document(full_text)
            for doc in processed_docs:
                doc["metadata"].update({
                    "type": "character",
                    "memory_id": memory_id,
                    "character_name": character_name,
                    "topic": topic,
                    "timestamp": datetime.now().isoformat(),
                })
            self.memory_store.add_documents(processed_docs)

        self.memory_index["characters"].append({
            "id": memory_id,
            "name": character_name,
            "topic": topic,
            "attributes": attributes or {},
            "timestamp": datetime.now().isoformat(),
            "content": full_text,
        })
        self._save_memory_index()
        return memory_id

    def store_world_setting(
        self,
        setting_name: str,
        setting_info: str,
        topic: str
    ) -> str:
        memory_id = f"world_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index['world_settings'])}" + "_" + uuid4().hex[:12]

        full_text = f"??????{setting_name}\n\n{setting_info}"

        if self.vector_memory_enabled and self.document_processor is not None and self.memory_store is not None:
            processed_docs = self.document_processor.process_document(full_text)
            for doc in processed_docs:
                doc["metadata"].update({
                    "type": "world_setting",
                    "memory_id": memory_id,
                    "setting_name": setting_name,
                    "topic": topic,
                    "timestamp": datetime.now().isoformat(),
                })
            self.memory_store.add_documents(processed_docs)

        self.memory_index["world_settings"].append({
            "id": memory_id,
            "name": setting_name,
            "topic": topic,
            "timestamp": datetime.now().isoformat(),
            "content": full_text,
        })
        self._save_memory_index()
        return memory_id

    def store_plot_point(
        self,
        plot_point: str,
        topic: str,
        position: Optional[str] = None
    ) -> str:
        memory_id = f"plot_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index['plot_points'])}" + "_" + uuid4().hex[:12]

        if self.vector_memory_enabled and self.document_processor is not None and self.memory_store is not None:
            processed_docs = self.document_processor.process_document(plot_point)
            for doc in processed_docs:
                doc["metadata"].update({
                    "type": "plot_point",
                    "memory_id": memory_id,
                    "topic": topic,
                    "position": position or "unknown",
                    "timestamp": datetime.now().isoformat(),
                })
            self.memory_store.add_documents(processed_docs)

        self.memory_index["plot_points"].append({
            "id": memory_id,
            "topic": topic,
            "position": position or "unknown",
            "timestamp": datetime.now().isoformat(),
            "content": plot_point,
        })
        self._save_memory_index()
        return memory_id

    def store_fact_card(
        self,
        card_text: str,
        topic: str,
        card_type: str = "general",
        metadata: Optional[Dict] = None
    ) -> str:
        memory_id = f"fact_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index.get('fact_cards', []))}" + "_" + uuid4().hex[:12]

        if self.vector_memory_enabled and self.document_processor is not None and self.memory_store is not None:
            processed_docs = self.document_processor.process_document(card_text)
            for doc in processed_docs:
                doc["metadata"].update({
                    "type": "fact_card",
                    "memory_id": memory_id,
                    "topic": topic,
                    "card_type": card_type,
                    "timestamp": datetime.now().isoformat(),
                    **(metadata or {}),
                })
            self.memory_store.add_documents(processed_docs)

        self.memory_index.setdefault("fact_cards", []).append({
            "id": memory_id,
            "topic": topic,
            "card_type": card_type,
            "content": card_text,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        })
        self._save_memory_index()
        return memory_id

    def get_recent_outlines(
        self,
        topic: str,
        limit: int = 3,
        kind: Optional[str] = None
    ) -> List[Dict]:
        """获取最近的若干条大纲/摘要（按写入顺序）"""
        outlines = [o for o in self.memory_index.get("outlines", []) if o.get("topic") == topic]
        if kind is not None:
            outlines = [o for o in outlines if o.get("structure", {}).get("kind") == kind]
        return outlines[-limit:] if limit > 0 else outlines

    def get_recent_fact_cards(self, topic: str, limit: int = 10) -> List[Dict]:
        """获取最近的事实卡片（按写入顺序）"""
        cards = [c for c in self.memory_index.get("fact_cards", []) if c.get("topic") == topic]
        return cards[-limit:] if limit > 0 else cards
    
    def retrieve_memories(
        self,
        query: str,
        memory_types: Optional[List[str]] = None,
        topic: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict]:
        """
        ??????
        
        Args:
            query: ????
            memory_types: ???????["character", "outline", "text"]??
            topic: ????
            top_k: ????
        
        Returns:
            ??????
        """
        if not self.vector_memory_enabled or self.document_processor is None or self.memory_store is None:
            return self._lexical_search(query, memory_types=memory_types, topic=topic, top_k=top_k)

        filter_metadata = {}
        if memory_types:
            filter_metadata["type"] = {"": memory_types}
        if topic:
            filter_metadata["topic"] = topic

        try:
            query_embedding = self.document_processor.get_embeddings([query])[0]
            return self.memory_store.search(
                query_embedding.tolist(),
                top_k=top_k,
                filter_metadata=filter_metadata if filter_metadata else None
            )
        except Exception:
            return self._lexical_search(query, memory_types=memory_types, topic=topic, top_k=top_k)

    def get_characters_by_topic(self, topic: str) -> List[Dict]:
        """获取指定主题的所有人物"""
        return [
            char for char in self.memory_index["characters"]
            if char.get("topic") == topic
        ]
    
    def get_outline_by_topic(self, topic: str) -> Optional[Dict]:
        """获取指定主题的大纲（优先全局大纲）"""
        outlines = [
            outline for outline in self.memory_index["outlines"]
            if outline.get("topic") == topic
        ]
        if not outlines:
            return None
        global_outlines = [
            outline for outline in outlines
            if outline.get("structure", {}).get("kind") == "global_outline"
        ]
        if global_outlines:
            return global_outlines[-1]
        return outlines[-1]
    
    def get_relevant_context(
        self,
        query: str,
        topic: str,
        include_types: Optional[List[str]] = None,
        language: Optional[str] = None,
    ) -> str:
        """
        获取相关上下文（用于生成时参考）
        
        Args:
            query: 查询文本
            topic: 主题
            include_types: 包含的记忆类型
        
        Returns:
            组合后的上下文
        """
        if include_types is None:
            # 精简类型，聚焦大纲/情节/事实，减少噪声
            include_types = ["outline", "plot_point", "fact_card"]

        # 固定注入：滚动摘要 + 最近章节摘要 + 最近事实卡片（不依赖向量检索，保证召回）
        fixed_parts: List[str] = []
        rolling = self.get_recent_outlines(topic, limit=1, kind="rolling_summary")
        if rolling and rolling[-1].get("content"):
            fixed_parts.append(self._lang_text("=== 滚动摘要（全局进度）===", "=== Rolling Summary (Global Progress) ===", language))
            fixed_parts.append(rolling[-1]["content"])

        recent_chapters = self.get_recent_outlines(topic, limit=2, kind="chapter_summary")
        if recent_chapters:
            fixed_parts.append(self._lang_text("=== 最近章节摘要 ===", "=== Recent Chapter Summaries ===", language))
            for ch in recent_chapters:
                if ch.get("content"):
                    fixed_parts.append(ch["content"])

        recent_cards = self.get_recent_fact_cards(topic, limit=6)
        if recent_cards:
            fixed_parts.append(self._lang_text("=== 关键事实卡片（最近）===", "=== Recent Key Fact Cards ===", language))
            for card in recent_cards:
                if card.get("content"):
                    fixed_parts.append(card["content"])

        claw_context = self.build_claw_context(
            topic=topic,
            current_goal=(query or "")[:180],
            banks=[
                "task_briefs",
                "story_premise",
                "style_guide",
                "chapter_briefs",
                "entity_state",
                "relationship_state",
                "world_state",
                "continuity_facts",
                "revision_notes",
                "working_set",
            ],
            limit_per_bank=1,
        )
        if claw_context:
            fixed_parts.append(self._lang_text("=== Claw 工作记忆 ===", "=== Claw Working Memory ===", language))
            fixed_parts.append(claw_context)
        
        # 检索相关记忆
        memories = self.retrieve_memories(
            query,
            memory_types=include_types,
            topic=topic,
            top_k=10
        )
        
        # 按类型分组
        context_parts: List[str] = []
        if fixed_parts:
            context_parts.append("\n".join(fixed_parts))
        
        # 人物信息
        characters = [m for m in memories if m.get("metadata", {}).get("type") == "character"]
        if characters:
            context_parts.append(self._lang_text("=== 相关人物信息 ===", "=== Relevant Character Information ===", language))
            seen_names = set()
            for char in characters:
                name = char.get("metadata", {}).get("character_name", self._lang_text("未知", "Unknown", language))
                if name not in seen_names:
                    context_parts.append(f"\n{char['text']}")
                    seen_names.add(name)

        # 大纲信息
        outlines = [m for m in memories if m.get("metadata", {}).get("type") == "outline"]
        if outlines:
            context_parts.append(self._lang_text("\n=== 文本大纲 ===", "\n=== Story Outlines ===", language))
            for outline in outlines[:2]:  # 只取前2个
                context_parts.append(f"\n{outline['text']}")

        # 世界观设定
        world_settings = [m for m in memories if m.get("metadata", {}).get("type") == "world_setting"]
        if world_settings:
            context_parts.append(self._lang_text("\n=== 世界观设定 ===", "\n=== Worldbuilding Notes ===", language))
            for setting in world_settings[:2]:
                context_parts.append(f"\n{setting['text']}")

        # 情节要点
        plot_points = [m for m in memories if m.get("metadata", {}).get("type") == "plot_point"]
        if plot_points:
            context_parts.append(self._lang_text("\n=== 相关情节要点 ===", "\n=== Relevant Plot Beats ===", language))
            for plot in plot_points[:3]:
                context_parts.append(f"\n{plot['text']}")

        # 事实卡片
        fact_cards = [m for m in memories if m.get("metadata", {}).get("type") == "fact_card"]
        if fact_cards:
            context_parts.append(self._lang_text("\n=== 相关事实卡片 ===", "\n=== Relevant Fact Cards ===", language))
            for card in fact_cards[:5]:
                context_parts.append(f"\n{card['text']}")
        
        return "\n".join(context_parts) if context_parts else ""
