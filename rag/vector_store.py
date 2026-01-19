"""
向量数据库模块：使用 ChromaDB 存储和检索文档
"""
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Optional
import os
from config import Config


class VectorStore:
    """向量数据库管理器"""
    
    def __init__(self, config: Config, collection_name: str = "documents", db_path: Optional[str] = None):
        self.config = config
        self.collection_name = collection_name
        self.db_path = db_path or config.vector_db_path
        
        # 创建 ChromaDB 客户端
        os.makedirs(self.db_path, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=self.db_path,
            settings=Settings(anonymized_telemetry=False)
        )
        
        # 获取或创建集合
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
    
    def add_documents(self, documents: List[Dict]):
        """
        添加文档到向量数据库
        
        Args:
            documents: 文档列表，每个文档包含 text 和 embedding
        """
        if not documents:
            return
        
        ids = [doc["id"] for doc in documents]
        texts = [doc["text"] for doc in documents]
        embeddings = [doc["embedding"] for doc in documents]
        metadatas = [doc.get("metadata", {}) for doc in documents]
        
        payload = dict(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
        # 优先使用 upsert，便于重复导入同一批数据时“覆盖/跳过”而不是炸掉
        upsert = getattr(self.collection, "upsert", None)
        if callable(upsert):
            upsert(**payload)
        else:
            self.collection.add(**payload)
    
    def search(
        self,
        query_embedding: List[float],
        top_k: Optional[int] = None,
        filter_metadata: Optional[Dict] = None
    ) -> List[Dict]:
        """
        搜索相似文档
        
        Args:
            query_embedding: 查询向量
            top_k: 返回的文档数量
            filter_metadata: 元数据过滤条件
        
        Returns:
            相似文档列表，包含 text, metadata, distance
        """
        top_k = top_k or self.config.top_k
        
        # Chroma 要求 where 顶层只接受一个操作符；如果同时有多个字段，改成 $and 组合
        where = None
        if filter_metadata:
            if "$and" in filter_metadata or "$or" in filter_metadata:
                where = filter_metadata
            elif len(filter_metadata.keys()) > 1:
                where = {"$and": [{k: v} for k, v in filter_metadata.items()]}
            else:
                where = filter_metadata

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where
        )
        
        # 格式化结果
        formatted_results = []
        if results["ids"] and len(results["ids"][0]) > 0:
            for i in range(len(results["ids"][0])):
                formatted_results.append({
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if "distances" in results else None
                })
        
        return formatted_results
    
    def delete_collection(self):
        """删除集合"""
        self.client.delete_collection(name=self.collection_name)
    
    def get_collection_size(self) -> int:
        """获取集合中的文档数量"""
        return self.collection.count()

