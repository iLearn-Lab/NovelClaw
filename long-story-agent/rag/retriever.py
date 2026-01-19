"""
检索器模块：整合向量数据库和文档处理
"""
from typing import List, Dict, Optional
from rag.vector_store import VectorStore
from rag.document_processor import DocumentProcessor
from config import Config


class Retriever:
    """RAG 检索器"""
    
    def __init__(self, config: Config, collection_name: str = "documents"):
        self.config = config
        db_path = getattr(config, "knowledge_vector_db_path", None) or config.vector_db_path
        self.vector_store = VectorStore(config, collection_name, db_path=db_path)
        self.document_processor = DocumentProcessor(config)
    
    def add_knowledge(self, text: str, metadata: Optional[Dict] = None):
        """
        添加知识到知识库
        
        Args:
            text: 知识文本
            metadata: 元数据
        """
        processed_docs = self.document_processor.process_document(text)
        
        # 添加元数据
        if metadata:
            for doc in processed_docs:
                doc["metadata"].update(metadata)
        
        self.vector_store.add_documents(processed_docs)
    
    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_metadata: Optional[Dict] = None
    ) -> List[Dict]:
        """
        检索相关文档
        
        Args:
            query: 查询文本
            top_k: 返回的文档数量
            filter_metadata: 元数据过滤条件
        
        Returns:
            相关文档列表
        """
        # 获取查询的嵌入向量
        query_embedding = self.document_processor.get_embeddings([query])[0]
        
        # 在向量数据库中搜索
        results = self.vector_store.search(
            query_embedding.tolist(),
            top_k=top_k,
            filter_metadata=filter_metadata
        )
        
        return results
    
    def retrieve_with_context(
        self,
        query: str,
        context: Optional[str] = None,
        top_k: Optional[int] = None
    ) -> str:
        """
        检索并组合上下文
        
        Args:
            query: 查询文本
            context: 额外上下文
            top_k: 返回的文档数量
        
        Returns:
            组合后的上下文文本
        """
        retrieved_docs = self.retrieve(query, top_k=top_k)
        
        # 组合检索到的文档
        context_parts = []
        if context:
            context_parts.append(f"额外上下文：\n{context}\n")
        
        if retrieved_docs:
            context_parts.append("检索到的相关信息：\n")
            for i, doc in enumerate(retrieved_docs, 1):
                context_parts.append(f"[{i}] {doc['text']}\n")
        
        return "\n".join(context_parts)
    
    def clear_knowledge_base(self):
        """清空知识库"""
        self.vector_store.delete_collection()
        db_path = getattr(self.config, "knowledge_vector_db_path", None) or self.config.vector_db_path
        self.vector_store = VectorStore(self.config, self.vector_store.collection_name, db_path=db_path)

