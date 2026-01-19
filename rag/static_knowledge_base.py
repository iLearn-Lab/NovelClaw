"""
外部静态知识库RAG：存储大量小说/创意文本数据
用于风格参考和减少幻觉
"""
from typing import Dict, List, Optional
from rag.retriever import Retriever
from rag.vector_store import VectorStore
from rag.document_processor import DocumentProcessor
from config import Config
import os
import json


class StaticKnowledgeBase:
    """外部静态知识库：存储大量小说和创意文本数据"""
    
    def __init__(self, config: Config):
        self.config = config
        
        # 创建专门的外部知识库向量存储
        self.knowledge_store = VectorStore(
            config,
            collection_name="static_knowledge_base",
            db_path=getattr(config, "static_vector_db_path", None)
        )
        self.document_processor = DocumentProcessor(config)
        
        # 知识库索引文件
        self.kb_index_path = os.path.join(
            getattr(config, "static_vector_db_path", config.vector_db_path),
            "static_kb_index.json"
        )
        self.kb_index = self._load_kb_index()
    
    def _load_kb_index(self) -> Dict:
        """加载知识库索引"""
        if os.path.exists(self.kb_index_path):
            try:
                with open(self.kb_index_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {
                    "novels": [],
                    "creative_texts": [],
                    "styles": [],
                    "plot_references": [],
                    "total_documents": 0
                }
        return {
            "novels": [],
            "creative_texts": [],
            "styles": [],
            "plot_references": [],
            "total_documents": 0
        }
    
    def _save_kb_index(self):
        """保存知识库索引"""
        os.makedirs(os.path.dirname(self.kb_index_path), exist_ok=True)
        with open(self.kb_index_path, "w", encoding="utf-8") as f:
            json.dump(self.kb_index, f, ensure_ascii=False, indent=2)
    
    def add_novel(
        self,
        novel_text: str,
        title: str,
        author: Optional[str] = None,
        genre: Optional[str] = None,
        style_tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        doc_id: Optional[str] = None,
    ):
        """
        添加小说到知识库
        
        Args:
            novel_text: 小说文本
            title: 小说标题
            author: 作者
            genre: 类型（科幻、奇幻等）
            style_tags: 风格标签（如：细腻、宏大、悬疑等）
            metadata: 额外元数据
        """
        # 处理文档
        processed_docs = self.document_processor.process_document(novel_text, doc_id=doc_id)
        max_chunks = getattr(self.config, "static_max_chunks_per_doc", 0) or 0
        if max_chunks > 0:
            processed_docs = processed_docs[:max_chunks]
        
        # 添加元数据
        base_meta = self._sanitize_metadata(metadata)
        for doc in processed_docs:
            doc["metadata"].update({
                "type": "novel",
                "title": title,
                "author": author or "unknown",
                "genre": genre or "unknown",
                "style_tags": ", ".join(style_tags) if style_tags else "",
                **base_meta
            })
        
        self.knowledge_store.add_documents(processed_docs)
        
        # 更新索引
        self.kb_index["novels"].append({
            "title": title,
            "author": author,
            "genre": genre,
            "style_tags": style_tags or [],
            "chunks": len(processed_docs)
        })
        self.kb_index["total_documents"] += len(processed_docs)
        self._save_kb_index()

    def _sanitize_metadata(self, meta: Optional[Dict]) -> Dict:
        """确保元数据值都是 Chroma 支持的标量类型"""
        safe = {}
        if not meta:
            return safe
        for k, v in meta.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                safe[k] = v
            elif isinstance(v, list):
                try:
                    safe[k] = ", ".join(str(x) for x in v)[:500]
                except Exception:
                    safe[k] = str(v)[:500]
            elif isinstance(v, dict):
                safe[k] = str(v)[:500]
            else:
                try:
                    safe[k] = str(v)[:500]
                except Exception:
                    pass
        return safe
    
    def add_creative_text(
        self,
        text: str,
        title: str,
        text_type: str = "creative",
        style_tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        doc_id: Optional[str] = None,
    ):
        """
        添加创意文本到知识库
        
        Args:
            text: 文本内容
            title: 标题
            text_type: 文本类型（creative, academic等）
            style_tags: 风格标签
            metadata: 额外元数据
        """
        processed_docs = self.document_processor.process_document(text, doc_id=doc_id)
        max_chunks = getattr(self.config, "static_max_chunks_per_doc", 0) or 0
        if max_chunks > 0:
            processed_docs = processed_docs[:max_chunks]
        
        for doc in processed_docs:
            doc["metadata"].update({
                "type": "creative_text",
                "title": title,
                "text_type": text_type,
                "style_tags": ", ".join(style_tags) if style_tags else "",
                **self._sanitize_metadata(metadata)
            })
        
        self.knowledge_store.add_documents(processed_docs)
        
        self.kb_index["creative_texts"].append({
            "title": title,
            "text_type": text_type,
            "style_tags": style_tags or [],
            "chunks": len(processed_docs)
        })
        self.kb_index["total_documents"] += len(processed_docs)
        self._save_kb_index()

    def add_plot_reference(
        self,
        plot_text: str,
        title: str,
        genre: Optional[str] = None,
        style_tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        doc_id: Optional[str] = None,
    ):
        """
        添加“情节参考”到知识库（与风格参考分开检索）。
        """
        processed_docs = self.document_processor.process_document(plot_text, doc_id=doc_id)
        max_chunks = getattr(self.config, "static_max_chunks_per_doc", 0) or 0
        if max_chunks > 0:
            processed_docs = processed_docs[:max_chunks]

        base_meta = self._sanitize_metadata(metadata)
        for doc in processed_docs:
            doc["metadata"].update({
                "type": "plot_reference",
                "title": title,
                "genre": genre or "unknown",
                "style_tags": ", ".join(style_tags) if style_tags else "",
                **base_meta,
            })

        self.knowledge_store.add_documents(processed_docs)
        self.kb_index.setdefault("plot_references", [])
        self.kb_index["plot_references"].append({
            "title": title,
            "genre": genre,
            "style_tags": style_tags or [],
            "chunks": len(processed_docs),
        })
        self.kb_index["total_documents"] += len(processed_docs)
        self._save_kb_index()
    
    def load_from_directory(self, directory_path: str, file_pattern: str = "*.txt"):
        """
        从目录批量加载文本文件
        
        Args:
            directory_path: 目录路径
            file_pattern: 文件匹配模式
        """
        import glob
        
        files = glob.glob(os.path.join(directory_path, file_pattern))
        
        for file_path in files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    text = f.read()
                
                title = os.path.basename(file_path).replace(".txt", "")
                self.add_creative_text(text, title)
                print(f"已加载: {title}")
            except Exception as e:
                print(f"加载文件失败 {file_path}: {e}")
    
    def retrieve_style_reference(
        self,
        query: str,
        genre: Optional[str] = None,
        style_tags: Optional[List[str]] = None,
        top_k: int = 5
    ) -> List[Dict]:
        """
        检索风格参考文本
        
        Args:
            query: 查询文本
            genre: 类型过滤
            style_tags: 风格标签过滤
            top_k: 返回数量
        
        Returns:
            相关文本列表
        """
        # 构建过滤条件（style_tags 以字符串存储，避免在 where 中使用 $in）
        filter_metadata = {"type": "novel"}
        if genre:
            filter_metadata["genre"] = genre
        
        # 获取查询向量
        query_embedding = self.document_processor.get_embeddings([query])[0]
        
        # 检索
        try:
            results = self.knowledge_store.search(
                query_embedding.tolist(),
                top_k=max(top_k, 10),
                filter_metadata=filter_metadata if filter_metadata else None
            )
            if style_tags:
                wanted = set(style_tags)
                filtered = []
                for r in results:
                    tags_str = (r.get("metadata", {}) or {}).get("style_tags", "") or ""
                    if any(t in tags_str for t in wanted):
                        filtered.append(r)
                return filtered[:top_k] if filtered else results[:top_k]
            return results[:top_k]
        except Exception as e:
            # 避免静态库索引损坏导致全流程崩溃；可通过重建向量库修复
            print(f"[StaticKB] ⚠️ 静态知识库检索失败，将跳过风格参考: {e}")
            return []

    def retrieve_plot_reference(
        self,
        query: str,
        genre: Optional[str] = None,
        style_tags: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[Dict]:
        """
        检索“情节参考”（通常是从语料中抽取/总结出的剧情节奏与桥段）。
        """
        filter_metadata = {"type": "plot_reference"}
        if genre:
            filter_metadata["genre"] = genre

        query_embedding = self.document_processor.get_embeddings([query])[0]
        try:
            results = self.knowledge_store.search(
                query_embedding.tolist(),
                top_k=max(top_k, 10),
                filter_metadata=filter_metadata,
            )
            if style_tags:
                wanted = set(style_tags)
                filtered = []
                for r in results:
                    tags_str = (r.get("metadata", {}) or {}).get("style_tags", "") or ""
                    if any(t in tags_str for t in wanted):
                        filtered.append(r)
                return filtered[:top_k] if filtered else results[:top_k]
            return results[:top_k]
        except Exception as e:
            print(f"[StaticKB] ?? 情节参考检索失败，将跳过: {e}")
            return []
    
    def get_style_context(
        self,
        query: str,
        genre: Optional[str] = None,
        style_tags: Optional[List[str]] = None,
        top_k: int = 5
    ) -> str:
        """
        获取风格上下文（用于生成时参考）
        
        Args:
            query: 查询文本
            genre: 类型
            style_tags: 风格标签
            top_k: 返回数量
        
        Returns:
            组合后的风格上下文
        """
        results = self.retrieve_style_reference(query, genre, style_tags, top_k)
        
        if not results:
            return ""
        
        context_parts = ["=== 风格参考（来自外部知识库）==="]
        
        for i, result in enumerate(results, 1):
            metadata = result.get("metadata", {})
            title = metadata.get("title", "未知")
            style_tags_val = metadata.get("style_tags", "")
            if isinstance(style_tags_val, str):
                style_tags_show = style_tags_val
            else:
                style_tags_show = ", ".join(style_tags_val) if style_tags_val else ""
            snippet = result.get("text", "")
            # 限制每段参考长度，避免撑爆上下文
            if len(snippet) > 900:
                snippet = snippet[:900] + "…"
            
            context_parts.append(
                f"\n[参考 {i}] 《{title}》"
                f"{' | 风格: ' + style_tags_show if style_tags_show else ''}\n"
                f"{snippet}"
            )
        
        context_parts.append(
            "\n请参考上述文本的风格、表达方式和叙事技巧，但不要直接复制内容。"
        )
        
        return "\n".join(context_parts)

    def get_plot_context(
        self,
        query: str,
        genre: Optional[str] = None,
        style_tags: Optional[List[str]] = None,
        top_k: int = 2,
    ) -> str:
        """
        获取“情节参考上下文”（用于 plot/writer 参考节奏与桥段）。
        """
        results = self.retrieve_plot_reference(query, genre, style_tags, top_k=top_k)
        if not results:
            return ""

        parts = ["=== 情节参考（来自外部语料总结/抽取）==="]
        for i, r in enumerate(results, 1):
            meta = r.get("metadata", {}) or {}
            title = meta.get("title", "未知")
            snippet = r.get("text", "")
            if len(snippet) > 700:
                snippet = snippet[:700] + "…"
            parts.append(f"\n[参考 {i}] {title}\n{snippet}")

        parts.append("\n请借鉴节奏、冲突推进与转场手法，不要复刻具体人物名/专有设定/原句。")
        return "\n".join(parts)
    
    def get_statistics(self) -> Dict:
        """获取知识库统计信息"""
        return {
            "total_novels": len(self.kb_index["novels"]),
            "total_creative_texts": len(self.kb_index["creative_texts"]),
            "total_plot_references": len(self.kb_index.get("plot_references", [])),
            "total_documents": self.kb_index["total_documents"],
            "collection_size": self.knowledge_store.get_collection_size()
        }

