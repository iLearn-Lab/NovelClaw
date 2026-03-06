from __future__ import annotations

import argparse
import datetime
import json
import os
import traceback
from pathlib import Path


def run_worker(idea: str, output_json: str) -> int:
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
        from config import Config
        from workflow.executor import CompositiveExecutor

        config = Config(require_api_key=True)
        # Keep run id stable between web job and worker payload, even on failure.
        config.run_id = run_id
        # 仅启用动态 memory（禁用静态 RAG / 静态知识库）
        config.memory_only_mode = True
        config.enable_rag = False
        config.enable_static_kb = False

        if config.memory_reset_each_run:
            config.memory_vector_db_path = os.path.join(
                config.vector_db_path,
                "memory",
                f"run_{config.run_id}",
            )

        executor = CompositiveExecutor(config)
        initial_knowledge = """
        科幻小说创作要点：
        1. 世界观设定要完整，包括科技水平、社会结构、时间背景
        2. 人物要有深度，动机要清晰
        3. 情节要有冲突和高潮
        4. 保持逻辑一致性
        """

        result = executor.generate_long_text(
            idea=idea,
            initial_knowledge=initial_knowledge,
            auto_analyze=True,
        )
        payload["ok"] = True
        payload["result"] = result
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        payload["traceback"] = traceback.format_exc()

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Long-Story generation in isolated worker process.")
    parser.add_argument("--idea", required=True, help="User story idea.")
    parser.add_argument("--output-json", required=True, help="Path for worker output JSON.")
    args = parser.parse_args()
    return run_worker(idea=args.idea, output_json=args.output_json)


if __name__ == "__main__":
    raise SystemExit(main())
