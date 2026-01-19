"""
创意评估 Agent
"""
from typing import Dict, Optional, List
from agents.base_agent import BaseAgent
from utils.llm_client import LLMClient
from rag.retriever import Retriever
from rag.memory_system import MemorySystem
from rag.static_knowledge_base import StaticKnowledgeBase
from config import Config
import json
import re


class EvaluatorAgent(BaseAgent):
    """创意评估 Agent：对整体文本创意进行打分与改进建议"""
    
    def __init__(
        self,
        config: Config,
        llm_client: LLMClient,
        retriever: Optional[Retriever] = None,
        memory_system: Optional[MemorySystem] = None,
        static_kb: Optional[StaticKnowledgeBase] = None
    ):
        system_prompt = """你是一个专业的创意评估专家。你的职责是：
1. 评估文本的新颖性、连贯性和情感连贯性
2. 检查文本的逻辑一致性和结构完整性
3. 提供具体的改进建议
4. 给出0-1之间的质量分数

请用中文回答，提供详细的评估报告和改进建议。评估结果请以JSON格式输出：
{
    "novelty_score": 0.0-1.0,
    "coherence_score": 0.0-1.0,
    "emotional_score": 0.0-1.0,
    "overall_score": 0.0-1.0,
    "suggestions": ["建议1", "建议2", ...]
}"""
        
        super().__init__(
            name="创意评估Agent",
            role="evaluator",
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
        评估文本质量
        
        Args:
            prompt: 要评估的文本内容
            context: 上下文信息（如评估标准等）
        
        Returns:
            包含评估结果和改进建议的字典
        """
        messages = self._build_messages(prompt, context, use_rag=False)
        
        response = self.llm_client.chat(
            messages=messages,
            temperature=0.3  # 评估需要更客观
        )
        
        # 解析评估结果
        evaluation_result = self._parse_evaluation(response)
        
        # 记录对话
        self.add_to_history("user", prompt)
        self.add_to_history("assistant", response)
        
        return {
            "agent": self.name,
            "role": self.role,
            "content": response,
            "evaluation": evaluation_result,
            "type": "evaluation"
        }
    
    def _parse_evaluation(self, response: str) -> Dict:
        """
        解析评估结果中的JSON
        
        Args:
            response: LLM 返回的文本
        
        Returns:
            解析后的评估结果字典
        """
        # 尝试提取JSON
        json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        
        # 如果无法解析JSON，尝试提取分数
        scores = {
            "novelty_score": 0.5,
            "coherence_score": 0.5,
            "emotional_score": 0.5,
            "overall_score": 0.5,
            "suggestions": []
        }
        
        # 尝试从文本中提取分数
        score_match = re.search(r'overall_score[:\s]+([\d.]+)', response, re.IGNORECASE)
        if score_match:
            try:
                scores["overall_score"] = float(score_match.group(1))
            except:
                pass
        
        return scores
    
    def evaluate_multiple(self, texts: List[Dict]) -> Dict:
        """
        评估多个文本片段
        
        Args:
            texts: 文本列表，每个元素包含 agent 和 content
        
        Returns:
            综合评估结果
        """
        combined_text = "\n\n".join([
            f"[{text.get('agent', 'Unknown')}]:\n{text.get('content', '')}"
            for text in texts
        ])
        
        prompt = f"请评估以下多个Agent生成的内容：\n\n{combined_text}"
        return self.generate(prompt)

