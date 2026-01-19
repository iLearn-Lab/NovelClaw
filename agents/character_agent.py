"""
人物塑造 Agent
"""
from typing import Dict, Optional, List
from agents.base_agent import BaseAgent
from utils.llm_client import LLMClient
from rag.retriever import Retriever
from rag.memory_system import MemorySystem
from rag.static_knowledge_base import StaticKnowledgeBase
from config import Config


class CharacterAgent(BaseAgent):
    """人物塑造 Agent：设计主要及次要人物特征"""
    
    def __init__(
        self,
        config: Config,
        llm_client: LLMClient,
        retriever: Optional[Retriever] = None,
        memory_system: Optional[MemorySystem] = None,
        static_kb: Optional[StaticKnowledgeBase] = None
    ):
        system_prompt = """你是一个专业的人物塑造专家。你的职责是：
1. 设计立体、有深度的人物角色
2. 塑造人物的性格、背景、动机和成长弧线
3. 确保人物行为符合其性格设定
4. 创造人物之间的复杂关系

请用中文回答，提供详细、生动的人物设计。"""
        
        super().__init__(
            name="人物塑造Agent",
            role="character_builder",
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
        生成人物设计
        
        Args:
            prompt: 提示（如人物要求、角色类型等）
            context: 上下文信息
            topic: 主题
            genre: 类型
            style_tags: 风格标签
        
        Returns:
            包含生成内容和元数据的字典
        """
        messages = self._build_messages(
            prompt, context,
            use_rag=True, topic=topic, use_memory=True,
            use_static_kb=True, genre=genre, style_tags=style_tags
        )
        
        response = self.llm_client.chat(
            messages=messages,
            temperature=self.config.temperature
        )
        
        # 记录对话
        self.add_to_history("user", prompt)
        self.add_to_history("assistant", response)
        
        return {
            "agent": self.name,
            "role": self.role,
            "content": response,
            "type": "character"
        }

