from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import traceback
from pathlib import Path
from utils.file_io import atomic_write_text


class _SafeTextStream:
    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        try:
            return self._stream.write(data)
        except (BrokenPipeError, OSError):
            return 0

    def flush(self):
        try:
            self._stream.flush()
        except (BrokenPipeError, OSError):
            return None

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _ensure_utf8_stdio() -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            continue
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or isinstance(stream, _SafeTextStream):
            continue
        setattr(sys, stream_name, _SafeTextStream(stream))


def _default_initial_knowledge(language: str) -> str:
    if str(language or "").lower().startswith("en"):
        return """
        Long-form fiction guidance:
        1. Keep the world model explicit and stable.
        2. Give characters clear motives, pressure, and growth.
        3. Land conflict, escalation, and payoff in each chapter.
        4. Protect continuity across facts, tone, and causal logic.
        """
    return """
    科幻小说创作要点：
    1. 世界观设定要完整，包括科技水平、社会结构、时间背景
    2. 人物要有深度，动机要清晰
    3. 情节要有冲突和高潮
    4. 保持逻辑一致性
    """


def run_worker(idea: str, output_json: str) -> int:
    _ensure_utf8_stdio()
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = os.getenv("RUN_ID", "").strip() or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    payload: dict = {
        "ok": False,
        "run_id": run_id,
        "result": {},
        "error": "",
        "traceback": "",
    }

    try:
        if not idea.strip():
            raise ValueError("The writing brief cannot be empty")
        from config import Config
        from workflow.executor import CompositiveExecutor

        config = Config(require_api_key=True)
        config.execution_mode = "claw"
        config.workflow_mode = "unfixed"
        # Keep run id stable between web job and worker payload, even on failure.
        config.run_id = run_id
        # 仅启用动态 memory（禁用静态 RAG / 静态知识库）
        config.memory_only_mode = True
        config.enable_rag = False
        config.enable_static_kb = False
        config.embedding_model = "none"

        if config.memory_reset_each_run:
            config.memory_vector_db_path = os.path.join(
                config.vector_db_path,
                "memory",
                f"run_{config.run_id}",
            )

        executor = CompositiveExecutor(config)
        initial_knowledge = _default_initial_knowledge(config.language)

        result = executor.generate_long_text(
            idea=idea,
            initial_knowledge=initial_knowledge,
            auto_analyze=True,
        )
        if not str(result.get("final_text") or "").strip():
            raise ValueError("Generation finished without manuscript text")
        payload["ok"] = True
        payload["result"] = result
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        payload["traceback"] = traceback.format_exc()

    atomic_write_text(output_path, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["ok"] else 1


def main() -> int:
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Run Long-Story generation in isolated worker process.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--idea", help="User story idea.")
    source.add_argument("--idea-file", type=Path, help="UTF-8 story brief file.")
    parser.add_argument("--output-json", required=True, help="Path for worker output JSON.")
    args = parser.parse_args()
    idea = args.idea_file.read_text(encoding="utf-8-sig") if args.idea_file else args.idea
    return run_worker(idea=idea, output_json=args.output_json)


if __name__ == "__main__":
    raise SystemExit(main())
