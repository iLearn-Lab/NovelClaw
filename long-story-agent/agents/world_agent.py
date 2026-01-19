"""
世界观构建 Agent
"""
from typing import Dict, Optional, List
from agents.base_agent import BaseAgent
from utils.llm_client import LLMClient
from rag.retriever import Retriever
from rag.memory_system import MemorySystem
from rag.static_knowledge_base import StaticKnowledgeBase
from config import Config


class WorldAgent(BaseAgent):
    """世界观构建 Agent：构建故事背景、环境设定"""
    
    def __init__(
        self,
        config: Config,
        llm_client: LLMClient,
        retriever: Optional[Retriever] = None,
        memory_system: Optional[MemorySystem] = None,
        static_kb: Optional[StaticKnowledgeBase] = None
    ):
        system_prompt = """你是一个专业的世界观构建专家。你的职责是：
1. 构建完整、一致的世界观设定
2. 设计故事发生的背景、环境、时代
3. 建立世界的规则、文化和历史
4. 确保世界观与情节、人物相协调

请用中文回答，提供详细、有深度的世界观设计。"""
        
        super().__init__(
            name="世界观构建Agent",
            role="world_builder",
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
        生成世界观设计
        
        Args:
            prompt: 提示（如世界观类型、设定要求等）
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
            temperature=self.config.temperature + 0.1  # 世界观需要更多创意
        )
        
        # 记录对话
        self.add_to_history("user", prompt)
        self.add_to_history("assistant", response)
        
        return {
            "agent": self.name,
            "role": self.role,
            "content": response,
            "type": "world"
        }

