"""
创意评估 Agent
"""
from typing import Dict, Optional
from agents.base_agent import BaseAgent
from utils.llm_client import LLMClient
from rag.retriever import Retriever
from rag.memory_system import MemorySystem
from rag.static_knowledge_base import StaticKnowledgeBase
from config import Config
import json


class EvaluatorAgent(BaseAgent):
    """创意评估 Agent：对整体文本创意进行打分与改进建议"""

    def __init__(
        self,
        config: Config,
        llm_client: LLMClient,
        retriever: Optional[Retriever] = None,
        memory_system: Optional[MemorySystem] = None,
        static_kb: Optional[StaticKnowledgeBase] = None,
    ):
        lang = getattr(config, "language", "zh").lower()
        if lang.startswith("en"):
            system_prompt = """You are a professional creative-writing evaluator.
Responsibilities:
1. Evaluate novelty, coherence, and emotional consistency.
2. Check logical consistency and structural completeness.
3. Provide concrete improvement suggestions.
4. Give a quality score between 0 and 1.
Respond in English with a JSON report:
{
  "overall_score": 0-1,
  "coherence": 0-1,
  "novelty": 0-1,
  "logic": 0-1,
  "pacing": 0-1,
  "suggestions": ["suggestion1", "suggestion2", ...]
}"""
            name = "Evaluator Agent"
        else:
            system_prompt = """你是一个专业的创意评估专家。你的职责是：
1. 评估文本的新颖性、连贯性和情感连贯性
2. 检查文本的逻辑一致性和结构完整性
3. 提供具体的改进建议
4. 给出0-1之间的质量分数
请用中文回答，提供详细的评估报告和改进建议。评估结果请以JSON格式输出：
{
  "overall_score": 0-1,
  "coherence": 0-1,
  "novelty": 0-1,
  "logic": 0-1,
  "pacing": 0-1,
  "suggestions": ["建议1", "建议2", ...]
}"""
            name = "创意评估Agent"

        super().__init__(
            name=name,
            role="evaluator",
            system_prompt=system_prompt,
            config=config,
            llm_client=llm_client,
            retriever=retriever,
            memory_system=memory_system,
            static_kb=static_kb,
        )

    def generate(self, prompt: str, context: Optional[str] = None) -> Dict:
        """评估文本质量"""
        messages = self._build_messages(prompt, context, use_rag=False)

        response = self.llm_client.chat(
            messages=messages,
            temperature=max(0.1, self.config.temperature - 0.2),
        )

        self.add_to_history("user", prompt)
        self.add_to_history("assistant", response)

        try:
            data = json.loads(response)
        except Exception:
            data = {
                "overall_score": 0.6,
                "coherence": 0.6,
                "novelty": 0.6,
                "logic": 0.6,
                "pacing": 0.6,
                "suggestions": ["Refine transitions", "Tighten logic"],
            }

        return {
            "agent": self.name,
            "role": self.role,
            "content": response,
            "parsed": data,
            "type": "evaluation",
        }
