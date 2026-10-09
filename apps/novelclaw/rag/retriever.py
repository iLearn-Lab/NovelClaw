"""
检索器模块：整合向量数据库和文档处理。
当 RAG 关闭时退化为空实现，避免加载 embedding 模型。
"""

from typing import Dict, List, Optional

from config import Config


class Retriever:
    """RAG 检索器。"""

    def __init__(self, config: Config, collection_name: str = "documents"):
        self.config = config
        self.enabled = bool(getattr(config, "enable_rag", False))
        self.collection_name = collection_name
        self.vector_store = None
        self.document_processor = None

        if self.enabled:
            from rag.vector_store import VectorStore
            from rag.document_processor import DocumentProcessor
            db_path = getattr(config, "knowledge_vector_db_path", None) or config.vector_db_path
            self.vector_store = VectorStore(config, collection_name, db_path=db_path)
            self.document_processor = DocumentProcessor(config)

    def add_knowledge(self, text: str, metadata: Optional[Dict] = None):
        if not self.enabled or self.document_processor is None or self.vector_store is None:
            return
        if not str(text or "").strip():
            return

        processed_docs = self.document_processor.process_document(text)
        if metadata:
            for doc in processed_docs:
                doc["metadata"].update(metadata)
        self.vector_store.add_documents(processed_docs)

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_metadata: Optional[Dict] = None,
    ) -> List[Dict]:
        if not self.enabled or self.document_processor is None or self.vector_store is None:
            return []
        if not str(query or "").strip():
            return []

        query_embedding = self.document_processor.get_embeddings([query])[0]
        return self.vector_store.search(
            query_embedding.tolist(),
            top_k=top_k,
            filter_metadata=filter_metadata,
        )

    def retrieve_with_context(
        self,
        query: str,
        context: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> str:
        if not self.enabled:
            return context or ""

        retrieved_docs = self.retrieve(query, top_k=top_k)
        context_parts = []
        if context:
            context_parts.append(f"额外上下文：\n{context}\n")

        if retrieved_docs:
            context_parts.append("检索到的相关信息：\n")
            for i, doc in enumerate(retrieved_docs, 1):
                context_parts.append(f"[{i}] {doc['text']}\n")

        return "\n".join(context_parts)

    def clear_knowledge_base(self):
        from rag.vector_store import VectorStore
        if not self.enabled or self.vector_store is None:
            return
        self.vector_store.delete_collection()
        db_path = getattr(self.config, "knowledge_vector_db_path", None) or self.config.vector_db_path
        self.vector_store = VectorStore(self.config, self.collection_name, db_path=db_path)
