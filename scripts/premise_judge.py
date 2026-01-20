import json
import sys
from pathlib import Path
from typing import List, Dict

# ensure repo root on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=ROOT / ".env", override=False, encoding="utf-8-sig")

from config import Config
from utils.llm_client import LLMClient
from agents.judge_agent import JudgeAgent


def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(
    dataset_path: str,
    candidate_path: str,
    output_path: str = "runs/judge_results.jsonl",
    language: str = "en"
):
    dataset = load_jsonl(Path(dataset_path))
    candidates = load_jsonl(Path(candidate_path))
    assert len(dataset) == len(candidates), "dataset and candidate length mismatch"

    cfg = Config()
    cfg.language = language
    llm = LLMClient(cfg)
    judge = JudgeAgent(cfg, llm)

    out_lines = []
    for i, (ref, cand) in enumerate(zip(dataset, candidates)):
        ref_story = ref["messages"][1]["content"]
        cand_story = cand.get("candidate") or cand.get("content") or ""
        prompt = (
            "Reference story:\n"
            f"{ref_story}\n\n"
            "Candidate story:\n"
            f"{cand_story}\n\n"
            "Evaluate which is better for the same premise. "
            "Score both on Relevance, Coherence, Empathy, Surprise, Creativity, Complexity (0-10 each) and pick a winner."
        )
        res = judge.generate(prompt)
        out_lines.append(json.dumps({
            "index": i,
            "prompt": ref.get("prompt"),
            "judgment": res["content"]
        }, ensure_ascii=False))
        print(f"Scored {i}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(out_lines), encoding="utf-8")
    print(f"Saved judgments to {output_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Judge candidate stories against reference stories on 6 dimensions.")
    parser.add_argument("--dataset", required=True, help="Path to reference jsonl (e.g., sft_premise.jsonl)")
    parser.add_argument("--candidate", required=True, help="Path to candidate jsonl with field 'candidate' or 'content'")
    parser.add_argument("--output", default="runs/judge_results.jsonl", help="Output jsonl path")
    parser.add_argument("--language", default="en", help="Language code (en/zh)")
    args = parser.parse_args()
    main(args.dataset, args.candidate, args.output, args.language)
