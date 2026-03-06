"""
关键转折点追踪器：记录伏笔、人物变化等关键转折（中英双语）
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
        self.lang = getattr(config, "language", "zh").lower()

    def _is_en(self) -> bool:
        return str(self.lang).startswith("en")

    def detect_turning_points(
        self,
        text: str,
        topic: str,
        context: Optional[str] = None
    ) -> List[Dict]:
        """检测文本中的关键转折点，返回列表：[{type, content, topic}]"""
        if self._is_en():
            prompt = f"""Analyze the text and extract turning points.

Text:
{text}

Identify:
1) Foreshadowing (clues for later)
2) Character changes (state/relationship/personality shifts)
3) Plot twists (major reversals)
4) Key events (important to story direction)

Return JSON:
{{
    "foreshadowing": [{{"content": "...", "hint": "what it implies", "position": "where"}}],
    "character_changes": [{{"character": "...", "change": "...", "reason": "..."}}],
    "plot_twists": [{{"content": "...", "impact": "..."}}],
    "key_events": [{{"event": "...", "significance": "..."}}]
}}"""
            system_prompt = "You analyze plot structure and detect turning points."
        else:
            json_example = {
                "foreshadowing": [{"content": "伏笔内容", "hint": "暗示什么", "position": "在文本中的位置"}],
                "character_changes": [{"character": "人物名称", "change": "变化描述", "reason": "变化原因"}],
                "plot_twists": [{"content": "转折内容", "impact": "影响"}],
                "key_events": [{"event": "事件描述", "significance": "重要性"}],
            }
            prompt = f"""请分析以下文本，识别关键转折点：

文本：
{text}

请识别：
1. 伏笔（foreshadowing）：为后续情节埋下的线索
2. 人物变化（character_change）：人物性格、状态、关系的重大变化
3. 情节转折（plot_twist）：情节的重大转折
4. 关键事件（key_event）：影响故事走向的重要事件

请以JSON格式输出，示例如下："""
            prompt += "\n" + json.dumps(json_example, ensure_ascii=False, indent=2)
            system_prompt = "你是一个擅长剧情结构分析的助手。"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        try:
            raw = self.llm_client.chat(messages, temperature=0.3)
            return self._parse_turning_points(raw, topic)
        except Exception:
            return []

    def record_turning_point(self, tp_type: str, content: Dict, topic: str):
        """记录转折点到 memory"""
        self.memory_system.memory_index.setdefault("outlines", []).append({
            "type": "turning_point",
            "topic": topic,
            "content": content,
            "structure": {"kind": "turning_point", "tp_type": tp_type},
            "created_at": datetime.utcnow().isoformat()
        })

    def _parse_turning_points(self, raw: str, topic: str) -> List[Dict]:
        """解析转折点 JSON"""
        try:
            data = json.loads(self._extract_json(raw))
            result = []
            for tp_type in ["foreshadowing", "character_changes", "plot_twists", "key_events"]:
                for item in data.get(tp_type, []):
                    result.append({
                        "type": tp_type,
                        "content": item,
                        "topic": topic
                    })
            return result
        except Exception:
            return []

    def _extract_json(self, text: str) -> str:
        m = re.search(r'\{[\s\S]*\}', text)
        return m.group(0) if m else text
