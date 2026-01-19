"""
数据检索 Agent
"""
from typing import Dict, Optional, List
from agents.base_agent import BaseAgent
from utils.llm_client import LLMClient
from rag.retriever import Retriever
from rag.memory_system import MemorySystem
from rag.static_knowledge_base import StaticKnowledgeBase
from config import Config


class RetrievalAgent(BaseAgent):
    """数据检索 Agent：检索相关历史、文化和技术背景信息"""
    
    def __init__(
        self,
        config: Config,
        llm_client: LLMClient,
        retriever: Retriever,  # 这个Agent必须有retriever
        memory_system: Optional[MemorySystem] = None,
        static_kb: Optional[StaticKnowledgeBase] = None
    ):
        system_prompt = """你是一个专业的信息检索和整合专家。你的职责是：
1. 根据需求检索相关的历史、文化、技术背景信息
2. 整合检索到的信息，提供准确、有用的背景知识
3. 确保信息的准确性和相关性
4. 为其他Agent提供信息支持

请用中文回答，提供清晰、有条理的信息整合。"""
        
        super().__init__(
            name="数据检索Agent",
            role="retrieval",
            system_prompt=system_prompt,
            config=config,
            llm_client=llm_client,
            retriever=retriever,
            memory_system=memory_system,
            static_kb=static_kb
        )
    
    def generate(
        self,
        prompt: str,
        context: Optional[str] = None,
        topic: Optional[str] = None,
        genre: Optional[str] = None,
        style_tags: Optional[List[str]] = None
    ) -> Dict:
        """
        检索并整合相关信息
        
        Args:
            prompt: 检索需求
            context: 上下文信息
        
        Returns:
            包含检索结果和整合信息的字典
        """
        # 使用RAG检索
        retrieved_docs = self.retriever.retrieve(prompt, top_k=5)
        
        if not retrieved_docs:
            return {
                "agent": self.name,
                "role": self.role,
                "content": "未找到相关信息。",
                "retrieved_docs": [],
                "type": "retrieval"
            }
        
        # 整合检索到的信息
        retrieved_text = "\n\n".join([
            f"[来源 {i+1}]: {doc['text']}"
            for i, doc in enumerate(retrieved_docs)
        ])
        
        # 使用LLM整合信息
        integration_prompt = f"""基于以下检索到的信息，请整合并总结相关内容：

检索到的信息：
{retrieved_text}

检索需求：{prompt}

请提供清晰、有条理的整合结果。"""
        
        messages = self._build_messages(integration_prompt, context, use_rag=False)
        
        response = self.llm_client.chat(
            messages=messages,
            temperature=0.5  # 信息整合需要准确性
        )
        
        # 记录对话
        self.add_to_history("user", prompt)
        self.add_to_history("assistant", response)
        
        return {
            "agent": self.name,
            "role": self.role,
            "content": response,
            "retrieved_docs": retrieved_docs,
            "type": "retrieval"
        }
    
    def add_knowledge(self, text: str, metadata: Optional[Dict] = None):
        """
        添加知识到知识库
        
        Args:
            text: 知识文本
            metadata: 元数据
        """
        if self.retriever:
            self.retriever.add_knowledge(text, metadata)

