import os
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# ensure repo root on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=ROOT / ".env", override=False, encoding="utf-8-sig")

from config import Config
from workflow.executor import CompositiveExecutor
from utils.llm_client import LLMClient
from agents.judge_agent import JudgeAgent


def load_jsonl_at_index(path: Path, idx: int) -> Dict[str, Any]:
    """Stream-read jsonl and return the row at idx (0-based) to avoid loading huge files into memory."""
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            if i == idx:
                return json.loads(line)
    raise IndexError(f"index {idx} out of range")


def append_jsonl(path: Path, obj: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def main(
    dataset_path: str,
    index: int,
    workflow_mode: str = "unfixed",
    outline_free: bool = False,
    en_segments: int = None,
    en_segment_words: int = None,
    do_judge: bool = True,
    run_id: str = "",
):
    # Load reference (streamed to avoid OOM)
    ref = load_jsonl_at_index(Path(dataset_path), index)
    premise = ref.get("prompt") or ref["messages"][0]["content"]
    ref_story = ref["messages"][1]["content"]

    # Configure env defaults
    os.environ.setdefault("LANGUAGE", "en")
    os.environ.setdefault("WORKFLOW_MODE", workflow_mode)
    os.environ.setdefault("OUTLINE_FREE", "1" if outline_free else "0")
    # 初始配置（用于读取默认段数/长度）
    cfg = Config()
    if en_segments is None:
        en_segments = getattr(cfg, "en_segments", 3)
    if en_segment_words is None:
        en_segment_words = getattr(cfg, "en_segment_words", 1200)

    os.environ.setdefault("EN_SEGMENTS", str(en_segments))
    os.environ.setdefault("EN_SEGMENT_WORDS", str(en_segment_words))

    if not run_id:
        cfg.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    else:
        cfg.run_id = run_id

    executor = CompositiveExecutor(cfg)
    print(f"[Gen] index={index}, premise len={len(premise)}")
    result = executor.generate_long_text(
        idea=premise,
        auto_analyze=True
    )

    candidate_text = result.get("final_text", "")
    run_dir = Path(cfg.runs_dir) / cfg.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Save generation artifacts
    (run_dir / "candidate.txt").write_text(candidate_text, encoding="utf-8")
    (run_dir / "round_results.json").write_text(json.dumps(result.get("round_results", []), ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "metadata.json").write_text(json.dumps({
        "index": index,
        "prompt": premise,
        "mode": workflow_mode,
        "outline_free": outline_free,
        "en_segments": en_segments,
        "en_segment_words": en_segment_words,
        "run_id": cfg.run_id,
        "length": len(candidate_text),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Save candidate jsonl (for batch judge later)
    append_jsonl(run_dir / "candidate.jsonl", {
        "index": index,
        "prompt": premise,
        "candidate": candidate_text,
        "run_id": cfg.run_id
    })

    judgment = None
    if do_judge:
        llm = LLMClient(cfg)
        judge = JudgeAgent(cfg, llm)
        judge_prompt = (
            "Reference story:\n"
            f"{ref_story}\n\n"
            "Candidate story:\n"
            f"{candidate_text}\n\n"
            "Evaluate which is better for the same premise. "
            "Score both on Relevance, Coherence, Empathy, Surprise, Creativity, Complexity (0-10 each) and pick a winner."
        )
        judgment = judge.generate(judge_prompt)
        append_jsonl(run_dir / "judgment.jsonl", {
            "index": index,
            "prompt": premise,
            "judgment": judgment["content"],
            "run_id": cfg.run_id
        })
        print(f"[Judge] done for index={index}")

    print(f"[Saved] {run_dir}")
    return {
        "run_id": cfg.run_id,
        "candidate_path": str(run_dir / "candidate.txt"),
        "judge": judgment["content"] if judgment else None
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate candidate story and judge vs reference for a selected index.")
    parser.add_argument("--dataset", required=True, help="Path to reference jsonl (e.g., sft_premise.jsonl)")
    parser.add_argument("--index", type=int, required=True, help="Row index (0-based)")
    parser.add_argument("--workflow_mode", default="unfixed", help="unfixed or chaptered")
    parser.add_argument("--outline_free", action="store_true", help="Skip global outline")
    parser.add_argument("--en_segments", type=int, default=4, help="Segments for English unfixed mode")
    parser.add_argument("--en_segment_words", type=int, default=1800, help="Words per segment")
    parser.add_argument("--no_judge", action="store_true", help="Skip judge scoring")
    parser.add_argument("--run_id", default="", help="Optional run id")
    args = parser.parse_args()
    main(
        dataset_path=args.dataset,
        index=args.index,
        workflow_mode=args.workflow_mode,
        outline_free=args.outline_free,
        en_segments=args.en_segments,
        en_segment_words=args.en_segment_words,
        do_judge=not args.no_judge,
        run_id=args.run_id,
    )
