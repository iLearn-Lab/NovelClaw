"""
章节规划 Agent：基于全局大纲与已写章节摘要，给出当前章节的写作约束
"""
from typing import Dict, Optional, List
from agents.base_agent import BaseAgent
from utils.llm_client import LLMClient
from rag.retriever import Retriever
from rag.memory_system import MemorySystem
from rag.static_knowledge_base import StaticKnowledgeBase
from config import Config


class ChapterPlannerAgent(BaseAgent):
    """章节规划 Agent：产出当前章节标题、关键事件、必保/禁用元素"""

    def __init__(
        self,
        config: Config,
        llm_client: LLMClient,
        retriever: Optional[Retriever] = None,
        memory_system: Optional[MemorySystem] = None,
        static_kb: Optional[StaticKnowledgeBase] = None
    ):
        system_prompt = """你是一名长篇小说的章节规划师，职责：
1) 结合全局大纲、已写章节摘要、滚动摘要，为当前章节给出写作约束。
2) 输出结构化 JSON，包含：chapter_title、must_have（必须出现的事件/角色/设定）、forbid（禁止偏离的大纲点或错误元素）、target_length_hint（本章目标字数范围）。
3) 语言简洁，约束清晰，可直接作为写作提示；不要写正文。
"""
        super().__init__(
            name="章节规划Agent",
            role="chapter_planner",
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
        messages = self._build_messages(
            prompt, context,
            use_rag=True,
            topic=topic,
            use_memory=True,
            use_static_kb=True,
            genre=genre,
            style_tags=style_tags
        )
        response = self.llm_client.chat(
            messages=messages,
            temperature=self.config.temperature - 0.1  # 规划更稳健
        )

        self.add_to_history("user", prompt)
        self.add_to_history("assistant", response)

        return {
            "agent": self.name,
            "role": self.role,
            "content": response,
            "type": "chapter_plan"
        }
