"""
实时修改系统：检测并调整相关内容，保持整体一致性
"""
from typing import Dict, List, Optional, Tuple
import json
from utils.llm_client import LLMClient
from rag.memory_system import MemorySystem
from rag.turning_point_tracker import TurningPointTracker
from config import Config


class RealtimeEditor:
    """实时修改系统：检测需要修改的部分并自动调整"""
    
    def __init__(
        self,
        config: Config,
        llm_client: LLMClient,
        memory_system: MemorySystem,
        turning_point_tracker: TurningPointTracker
    ):
        self.config = config
        self.llm_client = llm_client
        self.memory_system = memory_system
        self.turning_point_tracker = turning_point_tracker
        self.lang = getattr(config, "language", "zh").lower()

    def _is_en(self) -> bool:
        return str(self.lang).startswith("en")
    
    def detect_modification_needs(
        self,
        text: str,
        topic: str,
        consistency_result: Optional[Dict] = None,
        turning_point_notes: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        检测需要修改的部分
        
        Args:
            text: 生成的文本
            topic: 主题
            consistency_result: 一致性检查结果
        
        Returns:
            需要修改的部分列表
        """
        modifications = []
        
        # 1. 基于一致性检查结果
        if consistency_result:
            issues = consistency_result.get("all_issues", [])
            for issue in issues:
                modifications.append({
                    "type": "consistency_issue",
                    "issue": issue,
                    "priority": "high",
                    "suggestion": self._generate_modification_suggestion(issue, text)
                })
        
        # 2. 参考转折提示/问题，要求正文修正以对齐大纲
        if turning_point_notes:
            for note in turning_point_notes:
                modifications.append({
                    "type": "turning_point_issue",
                    "issue": note,
                    "priority": "high",
                    "suggestion": self._generate_modification_suggestion(note, text)
                })
        
        return modifications
    
    def apply_modifications(
        self,
        text: str,
        modifications: List[Dict],
        topic: str
    ) -> str:
        """
        应用修改
        
        Args:
            text: 原始文本
            modifications: 修改列表
            topic: 主题
        
        Returns:
            修改后的文本
        """
        if not modifications:
            return text
        
        # 按优先级排序
        modifications.sort(key=lambda x: {
            "high": 0,
            "medium": 1,
            "low": 2
        }.get(x.get("priority", "low"), 2))
        
        # 获取相关上下文
        context = self.memory_system.get_relevant_context(
            text[:200],
            topic,
            include_types=["character", "outline", "plot_point"]
        )
        
        # 构建修改提示
        mod_descriptions = []
        for i, mod in enumerate(modifications[:5], 1):  # 最多处理5个
            mod_descriptions.append(
                f"{i}. [{mod['type']}] {mod.get('issue', mod.get('suggestion', ''))}"
            )
        
        if self._is_en():
            prompt = f"""Adjust the text based on the modification suggestions:

Original text:
{text}

Relevant context:
{context}

Needed changes:
{chr(10).join(mod_descriptions)}

Please:
1) Keep overall style and structure.
2) Ensure consistency with outline/characters.
3) Smooth turning points; avoid abruptness.
4) Maintain coherence.

Output only the revised full text."""
            system_prompt = "You are a professional fiction editor; apply the requested changes and keep coherence."
        else:
            prompt = f"""请根据以下修改建议，调整文本：

原始文本：
{text}

相关上下文：
{context}

需要修改的地方：
{chr(10).join(mod_descriptions)}

请：
1. 保持文本的整体风格和结构
2. 确保修改后的内容符合大纲和人物设定
3. 使转折点更加自然，不突兀
4. 保持文本的连贯性

请直接输出修改后的完整文本，不需要说明修改了哪些地方。"""
            system_prompt = "你是一个专业的文本编辑专家，擅长根据反馈调整文本，保持整体一致性。"
        
        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {"role": "user", "content": prompt}
        ]
        
        try:
            modified_text = self.llm_client.chat(messages, temperature=0.5)
            return modified_text
        except:
            return text
    
    def update_related_parts(
        self,
        modified_text: str,
        topic: str,
        modification_type: str
    ):
        """
        更新相关部分（当修改了关键内容时）
        
        Args:
            modified_text: 修改后的文本
            topic: 主题
            modification_type: 修改类型
        """
        # 如果修改了人物，更新人物信息
        if "character" in modification_type.lower():
            # 重新提取人物信息并更新
            characters = self._extract_characters(modified_text)
            for char_name, char_info in characters.items():
                self.memory_system.store_character(
                    char_name, char_info, topic
                )
        
        # 如果修改了情节，更新情节要点
        if "plot" in modification_type.lower() or "turning_point" in modification_type.lower():
            # 重新检测转折点
            turning_points = self.turning_point_tracker.detect_turning_points(
                modified_text, topic
            )
            for tp in turning_points:
                self.turning_point_tracker.record_turning_point(
                    tp.get("type", "key_events"),
                    tp.get("content", {}),
                    topic
                )
    
    def _generate_modification_suggestion(self, issue: str, text: str) -> str:
        """生成修改建议"""
        # 简单的启发式方法，可以改进
        if "人物" in issue or "角色" in issue:
            return "请检查人物行为是否符合其性格设定，确保前后一致。"
        elif "情节" in issue or "逻辑" in issue:
            return "请检查情节发展是否符合逻辑，确保前后连贯。"
        elif "世界观" in issue:
            return "请检查内容是否符合世界观设定。"
        else:
            return f"请根据问题调整：{issue}"
    
    def _check_if_abrupt(
        self,
        turning_point: Dict,
        text: str,
        topic: str
    ) -> bool:
        """检查转折点是否突兀"""
        # 使用LLM判断
        prompt = f"""请判断以下转折点是否突兀：

文本：
{text}

转折点：
{json.dumps(turning_point, ensure_ascii=False)}

请判断转折点是否：
1. 缺乏铺垫
2. 过于突然
3. 不符合逻辑发展

请回答：是/否，并简要说明原因。"""
        
        messages = [
            {
                "role": "system",
                "content": "你是一个专业的故事分析专家。"
            },
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = self.llm_client.chat(messages, temperature=0.3)
            return "是" in response or "突兀" in response or "突然" in response
        except:
            return False
    
    def _smooth_turning_point(
        self,
        turning_point: Dict,
        text: str,
        topic: str
    ) -> str:
        """平滑转折点"""
        return f"请为转折点添加适当的铺垫，使其更加自然。转折点：{turning_point.get('content', {})}"
    
    def _is_character_change_reasonable(
        self,
        change: Dict,
        text: str,
        topic: str
    ) -> bool:
        """检查人物变化是否合理"""
        # 获取人物历史信息
        character_name = change.get("content", {}).get("character", "未知")
        characters = self.memory_system.get_characters_by_topic(topic)
        
        # 检查是否有足够的铺垫
        # 这里可以改进为更复杂的逻辑
        return True
    
    def _adjust_character_change(
        self,
        change: Dict,
        text: str,
        topic: str
    ) -> str:
        """调整人物变化"""
        return f"请为人物变化添加合理的铺垫和原因。变化：{change.get('content', {})}"
    
    def _extract_characters(self, text: str) -> Dict[str, str]:
        """从文本中提取人物信息"""
        # 简单的提取方法，可以改进
        import re
        characters = {}
        
        # 查找人物描述
        patterns = [
            r'([A-Za-z\u4e00-\u9fa5]{2,4})[，。！？\s]*(?:是|叫|名为|性格|特点)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if match not in characters:
                    characters[match] = ""
        
        return characters

