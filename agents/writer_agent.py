"""
正文写作 Agent
"""
from typing import Dict, Optional, List
from agents.base_agent import BaseAgent
from utils.llm_client import LLMClient
from rag.retriever import Retriever
from rag.memory_system import MemorySystem
from rag.static_knowledge_base import StaticKnowledgeBase
from config import Config


class WriterAgent(BaseAgent):
    """写作 Agent：基于已有设定撰写连续正文"""
    
    def __init__(
        self,
        config: Config,
        llm_client: LLMClient,
        retriever: Optional[Retriever] = None,
        memory_system: Optional[MemorySystem] = None,
        static_kb: Optional[StaticKnowledgeBase] = None
    ):
        system_prompt = """你是一名长篇小说写作专家，善于在既定人设、情节和世界观基础上撰写连贯的正文。
硬性约束：
1) 不得无凭无据乱写；如需引入新人物/设定/规则，必须先交代其来源、动机/用途、与现有设定的关联，并保持后续一致。
2) 衔接已有内容，避免突兀跳跃与重复；保持人物性格、语气、行为与设定一致。
3) 合理推进情节，埋下伏笔或展开冲突，段落流畅；保持统一风格，不输出提纲式列点。
4) 若遇信息不足，请延展已有线索，不要编造无依据的背景。
请用中文直接输出正文段落。"""
        
        super().__init__(
            name="写作Agent",
            role="writer",
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
        style_tags: Optional[List[str]] = None,
        target_length: Optional[int] = None
    ) -> Dict:
        """
        生成正文段落
        """
        # 为写作阶段放宽长度，单次目标 1000-2000 字区间
        per_chunk_hint = " 单次输出控制在约 1000-2000 字之间，保证信息量和连贯性。"
        if target_length:
            # 如果目标特别长，动态提升单次长度目标
            per_chunk_hint = f" 单次输出控制在约 {max(int(target_length/40), 1000)}-{max(int(target_length/20), 2000)} 字之间，保证信息量和连贯性。"
        
        messages = self._build_messages(
            prompt + per_chunk_hint,
            context,
            use_rag=True,
            topic=topic,
            use_memory=True,
            use_static_kb=True,
            genre=genre,
            style_tags=style_tags
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
            "type": "writer"
        }
