"""
Idea分析器：根据用户的idea自动推断风格、类型等
"""
from typing import Dict, List, Optional
from utils.llm_client import LLMClient
from config import Config
import json
import re


class IdeaAnalyzer:
    """Idea分析器：从用户输入的idea中提取风格、类型等信息"""
    
    def __init__(self, config: Config, llm_client: LLMClient):
        self.config = config
        self.llm_client = llm_client
    
    def analyze_idea(
        self,
        idea: str,
        language: str = "chinese"
    ) -> Dict:
        """
        分析用户的idea，自动推断风格、类型等
        
        Args:
            idea: 用户的创意想法
            language: 语言（chinese/english）
        
        Returns:
            分析结果，包含genre, style_tags, text_type等
        """
        prompt = f"""请分析以下创意想法，提取关键信息：

创意想法：
{idea}

请分析并提取：
1. 故事类型/流派（genre）：如科幻、奇幻、悬疑、历史、现代、都市等
2. 风格标签（style_tags）：如细腻、宏大、悬疑、幽默、严肃、浪漫等（最多5个）
3. 文本类型（text_type）：creative（创意写作）
4. 主题关键词（keywords）：提取3-5个关键词
5. 目标受众（target_audience）：如青少年、成人等
6. 语言风格（language_style）：如现代、古典、口语化等

请以JSON格式输出：
{{
    "genre": "科幻",
    "style_tags": ["细腻", "宏大", "悬疑"],
    "text_type": "creative",
    "keywords": ["AI", "未来", "觉醒"],
    "target_audience": "成人",
    "language_style": "现代",
    "suggested_length": 5000,
    "complexity": "medium"
}}"""
        
        messages = [
            {
                "role": "system",
                "content": "你是一个专业的创意分析专家，擅长从用户的创意想法中提取关键信息，包括类型、风格、主题等。"
            },
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = self.llm_client.chat(messages, temperature=0.3)
            result = self._parse_analysis(response)
            
            # 设置默认值
            if not result:
                result = {
                    "genre": "general",
                    "style_tags": ["细腻"],
                    "text_type": "creative",
                    "keywords": [],
                    "target_audience": "成人",
                    "language_style": "现代",
                    "suggested_length": 5000,
                    "complexity": "medium"
                }
            
            # 确保必要字段存在
            result.setdefault("genre", "general")
            result.setdefault("style_tags", ["细腻"])
            result.setdefault("text_type", "creative")
            result.setdefault("keywords", [])
            
            return result
            
        except Exception as e:
            print(f"分析idea失败: {e}")
            # 返回默认值
            return {
                "genre": "general",
                "style_tags": ["细腻"],
                "text_type": "creative",
                "keywords": [],
                "target_audience": "成人",
                "language_style": "现代",
                "suggested_length": 5000,
                "complexity": "medium"
            }
    
    def _parse_analysis(self, response: str) -> Dict:
        """解析分析结果"""
        json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        return {}
    
    def extract_topic_from_idea(self, idea: str) -> str:
        """
        从idea中提取主题（用于生成）
        
        Args:
            idea: 用户的创意想法
        
        Returns:
            提取的主题
        """
        # 如果idea很短，直接作为topic
        if len(idea) < 100:
            return idea
        
        # 否则提取关键部分
        prompt = f"""请从以下创意想法中提取一个简洁的主题（不超过50字）：

{idea}

请直接输出主题，不要其他说明。"""
        
        messages = [
            {
                "role": "system",
                "content": "你是一个专业的文本提取专家。"
            },
            {"role": "user", "content": prompt}
        ]
        
        try:
            topic = self.llm_client.chat(messages, temperature=0.3)
            return topic.strip()[:100]  # 限制长度
        except:
            return idea[:100]  # 如果失败，返回前100字

