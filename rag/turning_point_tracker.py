"""
关键转折点追踪器：记录伏笔、人物变化等关键转折
确保符合大纲，支持后续提示/修改
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import json
import os
import re
from config import Config
from utils.llm_client import LLMClient
from rag.memory_system import MemorySystem


class TurningPointTracker:
    """关键转折点追踪器"""

    def __init__(self, config: Config, llm_client: LLMClient, memory_system: MemorySystem):
        self.config = config
        self.llm_client = llm_client
        self.memory_system = memory_system

    def detect_turning_points(
        self,
        text: str,
        topic: str,
        context: Optional[str] = None
    ) -> List[Dict]:
        """
        检测文本中的关键转折点，返回列表：[{type, content, topic}]
        """
        prompt = f"""请分析以下文本，识别关键转折点：

文本：
{text}

请识别：
1. 伏笔（foreshadowing）：为后续情节埋下的线索
2. 人物变化（character_change）：人物性格、状态、关系的重大变化
3. 情节转折（plot_twist）：情节的重大转折
4. 关键事件（key_event）：影响故事走向的重要事件

请以JSON格式输出：
{{
    "foreshadowing": [{{"content": "伏笔内容", "hint": "暗示什么", "position": "在文本中的位置"}}],
    "character_changes": [{{"character": "人物名称", "change": "变化描述", "reason": "变化原因"}}],
    "plot_twists": [{{"content": "转折内容", "impact": "影响"}}],
    "key_events": [{{"event": "事件描述", "significance": "重要性"}}]
}}"""

        messages = [
            {"role": "system", "content": "你是一个专业的故事分析专家，擅长识别文本中的关键转折点。"},
            {"role": "user", "content": prompt}
        ]

        try:
            response = self.llm_client.chat(messages, temperature=0.3)
            result = self._parse_turning_points(response)
            if result:
                return self._validate_against_outline(result, topic, context)
            return []
        except Exception as e:
            print(f"检测转折点失败: {e}")
            return []

    def record_turning_point(
        self,
        tp_type: str,
        content: Dict,
        topic: str,
        position: Optional[str] = None
    ) -> str:
        """
        记录转折点，统一写入 memory（turning_point_issue），并按类型附带额外存储。
        """
        tp_id = f"{tp_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        turning_point = {
            "id": tp_id,
            "type": tp_type,
            "content": content,
            "topic": topic,
            "position": position or "unknown",
            "timestamp": datetime.now().isoformat()
        }
        tp_text = self._format_turning_point(turning_point)
        try:
            self.memory_system.store_outline(
                f"转折点（{tp_type}）：{tp_text}",
                topic,
                structure={"kind": "turning_point_issue", "type": tp_type, "position": position or "", "id": tp_id}
            )
        except Exception:
            pass
        if tp_type == "foreshadowing":
            try:
                self.memory_system.store_plot_point(tp_text, topic, position)
            except Exception:
                pass
        elif tp_type == "character_change":
            character_name = content.get("character", "未知")
            try:
                self.memory_system.store_character(
                    character_name,
                    f"人物变化：{content.get('change', '')}\n原因：{content.get('reason', '')}",
                    topic
                )
            except Exception:
                pass
        return tp_id

    def check_outline_consistency(
        self,
        turning_points: List[Dict],
        topic: str
    ) -> Tuple[bool, List[str]]:
        """
        检查转折点是否符合大纲
        """
        outline = self.memory_system.get_outline_by_topic(topic)
        if not outline:
            return True, []
        outline_text = outline.get("content") or outline.get("structure", {}).get("content", "")
        tp_text = "\n".join([f"- {tp.get('type', '')}: {tp.get('content', {})}" for tp in turning_points])

        prompt = f"""请检查以下转折点是否符合大纲：

大纲：
{outline_text}

转折点：
{tp_text}

请以JSON格式输出：
{{
    "consistent": true/false,
    "issues": ["问题1", "问题2"],
    "suggestions": ["建议1", "建议2"]
}}"""
        messages = [
            {"role": "system", "content": "你是一个专业的大纲一致性检查专家。"},
            {"role": "user", "content": prompt}
        ]
        try:
            response = self.llm_client.chat(messages, temperature=0.3)
            result = self._parse_consistency_check(response)
            return result.get("consistent", True), result.get("issues", [])
        except Exception:
            return True, []

    def _validate_against_outline(
        self,
        turning_points: Dict,
        topic: str,
        context: Optional[str]
    ) -> List[Dict]:
        """
        将 JSON dict 转为列表并做一致性校验；不一致则写入 memory。
        """
        all_tps = []
        for tp_type, tps in turning_points.items():
            if isinstance(tps, list):
                for tp in tps:
                    all_tps.append({"type": tp_type, "content": tp, "topic": topic})

        consistent, issues = self.check_outline_consistency(all_tps, topic)
        if not consistent and issues:
            print(f"⚠️ 转折点不符合大纲: {', '.join(issues[:3])}")
            try:
                self.memory_system.store_outline(
                    "⚠️ 转折点不符合大纲：\n" + "\n".join(issues),
                    topic,
                    structure={"kind": "turning_point_issue", "type": "consistency"}
                )
            except Exception:
                pass
        return all_tps

    def _parse_turning_points(self, response: str) -> Dict:
        """解析转折点检测结果"""
        block = self._extract_json_object(response)
        try:
            return json.loads(block)
        except Exception:
            return {}

    def _parse_consistency_check(self, response: str) -> Dict:
        """解析一致性检查结果"""
        block = self._extract_json_object(response)
        try:
            return json.loads(block)
        except Exception:
            return {"consistent": True, "issues": []}

    def _format_turning_point(self, tp: Dict) -> str:
        """格式化转折点文本"""
        content = tp.get("content", {})
        if isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False)
        return str(content)

    def _extract_json_object(self, text: str) -> str:
        """提取第一个 JSON 对象片段"""
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            return m.group(0)
        return text
