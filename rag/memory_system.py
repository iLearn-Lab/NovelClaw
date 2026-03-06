"""
记忆管理系统：存储和检索生成历史
用于减少幻觉和保持一致性
"""
from typing import Dict, List, Optional
from datetime import datetime
import json
import os
import shutil
from rag.vector_store import VectorStore
from rag.document_processor import DocumentProcessor
from config import Config


class MemorySystem:
    """记忆系统：管理生成历史，确保一致性"""
    
    def __init__(self, config: Config):
        self.config = config
        
        # 创建专门的记忆向量数据库（独立子目录，避免其它 collection 索引损坏连带影响）
        self.memory_store = VectorStore(
            config,
            collection_name="memory_collection",
            db_path=getattr(config, "memory_vector_db_path", None) or config.vector_db_path
        )
        self.document_processor = DocumentProcessor(config)
        
        # 记忆索引文件（存储结构化信息）
        self.memory_index_path = os.path.join(
            getattr(config, "memory_vector_db_path", config.vector_db_path),
            "memory_index.json"
        )

        # 兼容迁移：如果旧路径存在索引，而新路径不存在，则复制一份，避免“看不到历史”
        legacy_index_path = os.path.join(config.vector_db_path, "memory_index.json")
        if not os.path.exists(self.memory_index_path) and os.path.exists(legacy_index_path):
            try:
                os.makedirs(os.path.dirname(self.memory_index_path), exist_ok=True)
                shutil.copy2(legacy_index_path, self.memory_index_path)
            except Exception:
                pass

        self.memory_index = self._load_memory_index()
        # 向后兼容：确保新增字段存在
        self.memory_index.setdefault("fact_cards", [])
        for outline in self.memory_index.get("outlines", []):
            outline.setdefault("content", "")
        # 确保索引文件存在（即便为空）
        self._save_memory_index()

        # 兼容迁移（可选）：旧库 -> 新库
        # 默认不自动迁移，避免在某些机器/索引状态下卡住；如需迁移请设置：MIGRATE_LEGACY_MEMORY=1
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
                with open(self.memory_index_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {
                    "texts": [],
                    "outlines": [],
                    "characters": [],
                    "world_settings": [],
                    "plot_points": [],
                    "fact_cards": []
                }
        return {
            "texts": [],
            "outlines": [],
            "characters": [],
            "world_settings": [],
            "plot_points": [],
            "fact_cards": []
        }
    
    def _save_memory_index(self):
        """保存记忆索引"""
        os.makedirs(os.path.dirname(self.memory_index_path), exist_ok=True)
        with open(self.memory_index_path, "w", encoding="utf-8") as f:
            json.dump(self.memory_index, f, ensure_ascii=False, indent=2)
    
    def store_generated_text(
        self,
        text: str,
        topic: str,
        metadata: Optional[Dict] = None,
        store_vector: bool = True,
        content_path: Optional[str] = None
    ) -> str:
        """
        存储生成的文本
        
        Args:
            text: 生成的文本
            topic: 主题
            metadata: 额外元数据
        
        Returns:
            存储ID
        """
        memory_id = f"text_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index['texts'])}"
        
        # 添加到向量数据库（可选，允许仅索引而不写向量）
        if store_vector:
            processed_docs = self.document_processor.process_document(text)
            for doc in processed_docs:
                doc["metadata"].update({
                    "type": "generated_text",
                    "memory_id": memory_id,
                    "topic": topic,
                    "timestamp": datetime.now().isoformat(),
                    **(metadata or {})
                })
            
            self.memory_store.add_documents(processed_docs)
        
        # 添加到索引
        entry = {
            "id": memory_id,
            "topic": topic,
            "length": len(text),
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
            "content": text
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
        """
        存储文本大纲
        
        Args:
            outline: 大纲文本
            topic: 主题
            structure: 结构信息（章节、段落等）
        
        Returns:
            存储ID
        """
        memory_id = f"outline_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index['outlines'])}"
        
        # 添加到向量数据库
        processed_docs = self.document_processor.process_document(outline)
        for doc in processed_docs:
            doc["metadata"].update({
                "type": "outline",
                "memory_id": memory_id,
                "topic": topic,
                "timestamp": datetime.now().isoformat()
            })
        
        self.memory_store.add_documents(processed_docs)
        
        # 添加到索引
        self.memory_index["outlines"].append({
            "id": memory_id,
            "topic": topic,
            "content": outline,
            "structure": structure or {},
            "timestamp": datetime.now().isoformat()
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
        """
        存储人物特征
        
        Args:
            character_name: 人物名称
            character_info: 人物信息描述
            topic: 主题
            attributes: 人物属性（性格、背景等）
        
        Returns:
            存储ID
        """
        memory_id = f"character_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index['characters'])}"
        
        # 构建完整的人物描述
        full_text = f"人物名称：{character_name}\n\n{character_info}"
        if attributes:
            full_text += f"\n\n人物属性：\n{json.dumps(attributes, ensure_ascii=False, indent=2)}"
        
        # 添加到向量数据库
        processed_docs = self.document_processor.process_document(full_text)
        for doc in processed_docs:
            doc["metadata"].update({
                "type": "character",
                "memory_id": memory_id,
                "character_name": character_name,
                "topic": topic,
                "timestamp": datetime.now().isoformat()
            })
        
        self.memory_store.add_documents(processed_docs)
        
        # 添加到索引
        self.memory_index["characters"].append({
            "id": memory_id,
            "name": character_name,
            "topic": topic,
            "attributes": attributes or {},
            "timestamp": datetime.now().isoformat(),
            "content": full_text
        })
        self._save_memory_index()
        
        return memory_id
    
    def store_world_setting(
        self,
        setting_name: str,
        setting_info: str,
        topic: str
    ) -> str:
        """
        存储世界观设定
        
        Args:
            setting_name: 设定名称
            setting_info: 设定信息
            topic: 主题
        
        Returns:
            存储ID
        """
        memory_id = f"world_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index['world_settings'])}"
        
        full_text = f"世界观设定：{setting_name}\n\n{setting_info}"
        
        processed_docs = self.document_processor.process_document(full_text)
        for doc in processed_docs:
            doc["metadata"].update({
                "type": "world_setting",
                "memory_id": memory_id,
                "setting_name": setting_name,
                "topic": topic,
                "timestamp": datetime.now().isoformat()
            })
        
        self.memory_store.add_documents(processed_docs)
        
        self.memory_index["world_settings"].append({
            "id": memory_id,
            "name": setting_name,
            "topic": topic,
            "timestamp": datetime.now().isoformat(),
            "content": full_text
        })
        self._save_memory_index()
        
        return memory_id
    
    def store_plot_point(
        self,
        plot_point: str,
        topic: str,
        position: Optional[str] = None
    ) -> str:
        """
        存储情节要点
        
        Args:
            plot_point: 情节要点
            topic: 主题
            position: 在故事中的位置（开头、中间、结尾等）
        
        Returns:
            存储ID
        """
        memory_id = f"plot_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index['plot_points'])}"
        
        processed_docs = self.document_processor.process_document(plot_point)
        for doc in processed_docs:
            doc["metadata"].update({
                "type": "plot_point",
                "memory_id": memory_id,
                "topic": topic,
                "position": position or "unknown",
                "timestamp": datetime.now().isoformat()
            })
        
        self.memory_store.add_documents(processed_docs)
        
        self.memory_index["plot_points"].append({
            "id": memory_id,
            "topic": topic,
            "position": position or "unknown",
            "timestamp": datetime.now().isoformat(),
            "content": plot_point
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
        """
        存储事实卡片（关键设定/时间线/人物关系/伏笔清单等短文本）
        """
        memory_id = f"fact_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.memory_index.get('fact_cards', []))}"

        processed_docs = self.document_processor.process_document(card_text)
        for doc in processed_docs:
            doc["metadata"].update({
                "type": "fact_card",
                "memory_id": memory_id,
                "topic": topic,
                "card_type": card_type,
                "timestamp": datetime.now().isoformat(),
                **(metadata or {})
            })

        self.memory_store.add_documents(processed_docs)

        self.memory_index.setdefault("fact_cards", []).append({
            "id": memory_id,
            "topic": topic,
            "card_type": card_type,
            "content": card_text,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
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
        检索相关记忆
        
        Args:
            query: 查询文本
            memory_types: 记忆类型列表（["character", "outline", "text"]等）
            topic: 主题过滤
            top_k: 返回数量
        
        Returns:
            相关记忆列表
        """
        # 构建过滤条件
        filter_metadata = {}
        if memory_types:
            filter_metadata["type"] = {"$in": memory_types}
        if topic:
            filter_metadata["topic"] = topic
        
        # 获取查询向量
        query_embedding = self.document_processor.get_embeddings([query])[0]
        
        # 检索
        results = self.memory_store.search(
            query_embedding.tolist(),
            top_k=top_k,
            filter_metadata=filter_metadata if filter_metadata else None
        )
        
        return results
    
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
        include_types: Optional[List[str]] = None
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
            fixed_parts.append("=== 滚动摘要（全局进度）===")
            fixed_parts.append(rolling[-1]["content"])

        recent_chapters = self.get_recent_outlines(topic, limit=2, kind="chapter_summary")
        if recent_chapters:
            fixed_parts.append("=== 最近章节摘要 ===")
            for ch in recent_chapters:
                if ch.get("content"):
                    fixed_parts.append(ch["content"])

        recent_cards = self.get_recent_fact_cards(topic, limit=6)
        if recent_cards:
            fixed_parts.append("=== 关键事实卡片（最近）===")
            for card in recent_cards:
                if card.get("content"):
                    fixed_parts.append(card["content"])
        
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
            context_parts.append("=== 相关人物信息 ===")
            seen_names = set()
            for char in characters:
                name = char.get("metadata", {}).get("character_name", "未知")
                if name not in seen_names:
                    context_parts.append(f"\n{char['text']}")
                    seen_names.add(name)
        
        # 大纲信息
        outlines = [m for m in memories if m.get("metadata", {}).get("type") == "outline"]
        if outlines:
            context_parts.append("\n=== 文本大纲 ===")
            for outline in outlines[:2]:  # 只取前2个
                context_parts.append(f"\n{outline['text']}")
        
        # 世界观设定
        world_settings = [m for m in memories if m.get("metadata", {}).get("type") == "world_setting"]
        if world_settings:
            context_parts.append("\n=== 世界观设定 ===")
            for setting in world_settings[:2]:
                context_parts.append(f"\n{setting['text']}")
        
        # 情节要点
        plot_points = [m for m in memories if m.get("metadata", {}).get("type") == "plot_point"]
        if plot_points:
            context_parts.append("\n=== 相关情节要点 ===")
            for plot in plot_points[:3]:
                context_parts.append(f"\n{plot['text']}")

        # 事实卡片
        fact_cards = [m for m in memories if m.get("metadata", {}).get("type") == "fact_card"]
        if fact_cards:
            context_parts.append("\n=== 相关事实卡片 ===")
            for card in fact_cards[:5]:
                context_parts.append(f"\n{card['text']}")
        
        return "\n".join(context_parts) if context_parts else ""

