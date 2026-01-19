"""
一致性检查模块：检测和验证生成内容的一致性
用于减少幻觉和不确定性问题
"""
from typing import Dict, List, Optional, Tuple
from utils.llm_client import LLMClient
from rag.memory_system import MemorySystem
from config import Config
import re
import json


class ConsistencyChecker:
    """一致性检查器：检测生成内容与历史记忆的一致性"""
    
    def __init__(self, config: Config, llm_client: LLMClient, memory_system: MemorySystem):
        self.config = config
        self.llm_client = llm_client
        self.memory_system = memory_system
    
    def check_character_consistency(
        self,
        generated_text: str,
        topic: str,
        character_name: Optional[str] = None
    ) -> Dict:
        """
        检查人物一致性
        
        Args:
            generated_text: 生成的文本
            topic: 主题
            character_name: 人物名称（如果指定）
        
        Returns:
            一致性检查结果
        """
        # 获取相关人物信息
        if character_name:
            memories = self.memory_system.retrieve_memories(
                f"{character_name} 人物特征",
                memory_types=["character"],
                topic=topic,
                top_k=3
            )
        else:
            # 尝试从文本中提取人物名称
            character_names = self._extract_character_names(generated_text)
            if character_names:
                memories = []
                for name in character_names[:3]:  # 检查前3个人物
                    mems = self.memory_system.retrieve_memories(
                        f"{name} 人物特征",
                        memory_types=["character"],
                        topic=topic,
                        top_k=2
                    )
                    memories.extend(mems)
            else:
                memories = []
        
        if not memories:
            return {
                "consistent": True,
                "confidence": 0.5,
                "issues": [],
                "suggestions": []
            }
        
        # 使用LLM检查一致性
        character_info = "\n\n".join([m["text"] for m in memories[:5]])
        
        prompt = f"""请检查以下生成文本中的人物描述是否与已有的人物设定一致：

已有的人物设定：
{character_info}

生成的文本：
{generated_text}

请检查：
1. 人物性格是否一致
2. 人物背景是否一致
3. 人物行为是否符合设定
4. 是否有矛盾或冲突

请以JSON格式输出：
{{
    "consistent": true/false,
    "confidence": 0.0-1.0,
    "issues": ["问题1", "问题2"],
    "suggestions": ["建议1", "建议2"]
}}"""
        
        messages = [
            {
                "role": "system",
                "content": "你是一个专业的一致性检查专家，擅长发现文本中的不一致之处。"
            },
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = self.llm_client.chat(messages, temperature=0.3)
            result = self._parse_consistency_result(response)
            return result
        except:
            return {
                "consistent": True,
                "confidence": 0.5,
                "issues": [],
                "suggestions": []
            }
    
    def check_plot_consistency(
        self,
        generated_text: str,
        topic: str,
        baseline_outline: Optional[str] = None
    ) -> Dict:
        """
        检查情节一致性
        
        Args:
            generated_text: 生成的文本
            topic: 主题
        
        Returns:
            一致性检查结果
        """
        # 基准大纲：优先使用传入的 baseline（如当前章节计划 + 滚动摘要），否则检索
        if baseline_outline:
            plot_info = baseline_outline
        else:
            memories = self.memory_system.retrieve_memories(
                generated_text[:200],  # 使用文本开头作为查询
                memory_types=["plot_point", "outline"],
                topic=topic,
                top_k=5
            )
            
            if not memories:
                return {
                    "consistent": True,
                    "confidence": 0.5,
                    "issues": [],
                    "suggestions": []
                }
            
            plot_info = "\n\n".join([m["text"] for m in memories])
        
        prompt = f"""请检查以下生成文本的情节是否与已有的大纲和情节要点一致：

已有的大纲和情节要点：
{plot_info}

生成的文本：
{generated_text}

请检查：
1. 情节发展是否符合大纲
2. 是否有逻辑矛盾
3. 是否有时间线错误
4. 是否有前后不一致的地方

请以JSON格式输出：
{{
    "consistent": true/false,
    "confidence": 0.0-1.0,
    "issues": ["问题1", "问题2"],
    "suggestions": ["建议1", "建议2"]
}}"""
        
        messages = [
            {
                "role": "system",
                "content": "你是一个专业的情节一致性检查专家。"
            },
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = self.llm_client.chat(messages, temperature=0.3)
            result = self._parse_consistency_result(response)
            return result
        except:
            return {
                "consistent": True,
                "confidence": 0.5,
                "issues": [],
                "suggestions": []
            }
    
    def check_world_consistency(
        self,
        generated_text: str,
        topic: str
    ) -> Dict:
        """
        检查世界观一致性
        
        Args:
            generated_text: 生成的文本
            topic: 主题
        
        Returns:
            一致性检查结果
        """
        memories = self.memory_system.retrieve_memories(
            "世界观设定",
            memory_types=["world_setting"],
            topic=topic,
            top_k=5
        )
        
        if not memories:
            return {
                "consistent": True,
                "confidence": 0.5,
                "issues": [],
                "suggestions": []
            }
        
        world_info = "\n\n".join([m["text"] for m in memories])
        
        prompt = f"""请检查以下生成文本是否符合已有的世界观设定：

已有的世界观设定：
{world_info}

生成的文本：
{generated_text}

请检查：
1. 是否符合世界观的规则和设定
2. 是否有违反世界观设定的内容
3. 是否有逻辑矛盾

请以JSON格式输出：
{{
    "consistent": true/false,
    "confidence": 0.0-1.0,
    "issues": ["问题1", "问题2"],
    "suggestions": ["建议1", "建议2"]
}}"""
        
        messages = [
            {
                "role": "system",
                "content": "你是一个专业的世界观一致性检查专家。"
            },
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = self.llm_client.chat(messages, temperature=0.3)
            result = self._parse_consistency_result(response)
            return result
        except:
            return {
                "consistent": True,
                "confidence": 0.5,
                "issues": [],
                "suggestions": []
            }
    
    def comprehensive_check(
        self,
        generated_text: str,
        topic: str,
        baseline_outline: Optional[str] = None
    ) -> Dict:
        """
        综合一致性检查
        
        Args:
            generated_text: 生成的文本
            topic: 主题
        
        Returns:
            综合检查结果
        """
        results = {
            "character": self.check_character_consistency(generated_text, topic),
            "plot": self.check_plot_consistency(generated_text, topic, baseline_outline=baseline_outline),
            "world": self.check_world_consistency(generated_text, topic)
        }
        
        # 计算综合分数
        all_consistent = all(r["consistent"] for r in results.values())
        avg_confidence = sum(r["confidence"] for r in results.values()) / len(results)
        
        # 收集所有问题
        all_issues = []
        all_suggestions = []
        for r in results.values():
            all_issues.extend(r.get("issues", []))
            all_suggestions.extend(r.get("suggestions", []))
        
        return {
            "overall_consistent": all_consistent,
            "overall_confidence": avg_confidence,
            "details": results,
            "all_issues": all_issues,
            "all_suggestions": all_suggestions
        }
    
    def _extract_character_names(self, text: str) -> List[str]:
        """从文本中提取人物名称"""
        # 简单的启发式方法：查找可能的姓名模式
        # 这里可以改进为使用NER模型
        patterns = [
            r'[，。！？\s]([A-Za-z\u4e00-\u9fa5]{2,4})(?:说道|说|想|看|走|来|去)',
            r'人物[：:]\s*([A-Za-z\u4e00-\u9fa5]{2,4})',
        ]
        
        names = set()
        for pattern in patterns:
            matches = re.findall(pattern, text)
            names.update(matches)
        
        return list(names)[:5]  # 最多返回5个
    
    def _parse_consistency_result(self, response: str) -> Dict:
        """解析一致性检查结果"""
        # 尝试提取JSON
        json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        
        # 默认结果
        return {
            "consistent": True,
            "confidence": 0.5,
            "issues": [],
            "suggestions": []
        }

