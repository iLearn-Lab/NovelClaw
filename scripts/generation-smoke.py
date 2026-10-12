"""Run real generation workers against a deterministic local model server."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from provider_server import completion, provider_server, response

STORY = "\n\n".join(
    f"Lin counted the lighthouse signals for the {number}th time. The keeper had left a mark beside the tide chart. Following it, she found another piece of the missing map and carried it safely back through the storm."
    for number in range(1, 26)
)


def fixture_reply(path, body, number):
    if number > 80:
        return 400, {"error": {"message": "Smoke test exceeded its request budget"}}
    history = body.get("messages", body.get("input", []))
    prompt = "\n".join(
        str(item.get("content", "")) for item in history if isinstance(item, dict)
    ).lower()
    if body.get("tools"):
        has_draft = any(
            item.get("role") == "tool" or item.get("type") == "function_call_output"
            for item in history
        )
        name = "finalize" if has_draft else "draft_chapter"
        arguments = json.dumps(
            {"reason": "The chapter is complete."} if has_draft else {}
        )
        if path.endswith("/responses"):
            return 200, response(
                output=[
                    {
                        "type": "function_call",
                        "id": f"fc_{number}",
                        "call_id": f"call_{number}",
                        "name": name,
                        "arguments": arguments,
                        "status": "completed",
                    }
                ]
            )
        return 200, completion(
            "",
            [
                {
                    "id": f"call_{number}",
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ],
        )
    if "creative-analysis expert" in prompt:
        text = json.dumps(
            {
                "genre": "mystery",
                "style_tags": ["suspenseful"],
                "text_type": "creative",
                "keywords": ["lighthouse"],
                "suggested_length": 800,
                "complexity": "simple",
            }
        )
    elif "output only the topic" in prompt:
        text = "The Lighthouse Map"
    elif "chapter-level outlines as a json array" in prompt:
        text = json.dumps(
            [
                {
                    "chapter": 1,
                    "title": "The Lighthouse Map",
                    "content": "Lin finds the missing map and resolves the lighthouse mystery.",
                }
            ]
        )
    elif (
        "expert long-form fiction writer" in prompt
        or "creative writing" in prompt
        or "fiction writer" in prompt
    ):
        text = STORY
    elif "json" in prompt:
        text = json.dumps(
            {
                "consistent": True,
                "confidence": 1.0,
                "issues": [],
                "suggestions": [],
                "all_issues": [],
                "complexity": "simple",
                "required_agents": ["writer"],
                "rag_required": False,
                "estimated_iterations": 1,
                "quality_score": 0.9,
                "summary": "Lin found the map.",
                "facts": [],
                "characters": [],
                "turning_points": [],
            }
        )
    else:
        text = "Book: The Lighthouse Map\nChapter 1: The signal\nLin finds a map inside the lighthouse and resolves the mystery."
    return 200, response(text) if path.endswith("/responses") else completion(text)


def run_smoke(service: str, wire: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="novelclaw-generation-") as temporary:
        state = Path(temporary)
        run_id = "smoke_run"
        result_path = state / "worker_result.json"
        brief = state / "input.txt"
        # Large enough to exceed Windows' command-line limit; passed as a UTF-8 file.
        brief.write_text(
            "Write one chapter about Lin finding a map in a lighthouse.\n"
            + "Keep continuity with the established lighthouse setting.\n" * 800,
            encoding="utf-8",
        )
        with provider_server(fixture_reply) as (url, requests):
            env = os.environ.copy()
            env.update(
                {
                    "LLM_PROVIDER": "test",
                    "LLM_API_KEY": "test-only-key",
                    "LLM_BASE_URL": url,
                    "MODEL_NAME": "test-model",
                    "WIRE_API": wire,
                    "LANGUAGE": "en",
                    "APP_DATA_DIR": str(state / "data"),
                    "APP_RUNS_DIR": str(state / "runs"),
                    "RUNS_DIR": str(state / "runs"),
                    "RUN_ID": run_id,
                    "VECTOR_DB_PATH": str(state / "vector_db"),
                    "MEMORY_VECTOR_DB_PATH": str(state / "vector_db" / "memory"),
                    "MEMORY_RESET_EACH_RUN": "1",
                    "EMBEDDING_MODEL": "none",
                    "ENABLE_RAG": "0",
                    "ENABLE_STATIC_KB": "0",
                    "ENABLE_EVALUATOR": "0",
                    "MEMORY_ONLY_MODE": "1",
                    "TURNING_POINT_ENABLED": "0",
                    "FAST_MODE": "1",
                    "MAX_TOTAL_ITERATIONS": "1",
                    "MAX_ITERATIONS": "1",
                    "CLAW_MAX_STEPS": "3",
                    "MAX_CHAPTER_SUBROUNDS": "1",
                    "MIN_CHAPTER_CHARS": "300",
                    "MAX_CHAPTER_CHARS": "8000",
                    "MAX_TOKENS": "12000",
                    "LLM_TIMEOUT_SECONDS": "5",
                    "LLM_MAX_RETRIES": "0",
                    "PYTHONUTF8": "1",
                    "EN_SEGMENTS": "1",
                    "WORKFLOW_MODE": "chaptered",
                    "DISABLE_EMBEDDING_DOWNLOADS": "1",
                }
            )
            worker = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "local_web_portal.worker_process",
                    "--idea-file",
                    str(brief),
                    "--output-json",
                    str(result_path),
                ],
                cwd=ROOT / "apps" / service,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=45,
            )
        assert result_path.exists(), worker.stderr[-5000:]
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        assert worker.returncode == 0 and payload["ok"], (
            payload.get("traceback") or worker.stdout[-5000:]
        )
        result = payload["result"]
        assert result["chapters_written"] == 1, {"chapters": result["chapters_written"]}
        assert len(result["final_text"]) > 200, {
            "output": result["final_text"],
            "log": worker.stdout[-3000:],
        }
        chapters = list((state / "runs" / run_id / "chapters").glob("*_final.txt"))
        assert len(chapters) == 1 and len(chapters[0].read_text(encoding="utf-8")) > 200
        assert (
            result["final_text"].strip()
            == chapters[0].read_text(encoding="utf-8").strip()
        )
        memory = json.loads(
            (
                state / "vector_db" / "memory" / f"run_{run_id}" / "memory_index.json"
            ).read_text(encoding="utf-8")
        )
        assert memory["texts"] and memory["outlines"]
        assert all(
            item["path"]
            == ("/v1/responses" if wire == "responses" else "/v1/chat/completions")
            for item in requests
        )
        return {
            "service": service,
            "wire": wire,
            "requests": len(requests),
            "chapters": len(chapters),
            "output_chars": len(result["final_text"]),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service", choices=["novelclaw", "multiagent", "both"], default="both"
    )
    parser.add_argument("--wire", choices=["chat", "responses", "both"], default="both")
    args = parser.parse_args()
    services = ["novelclaw", "multiagent"] if args.service == "both" else [args.service]
    protocols = ["chat", "responses"] if args.wire == "both" else [args.wire]
    for service in services:
        for wire in protocols:
            print(json.dumps(run_smoke(service, wire)))
