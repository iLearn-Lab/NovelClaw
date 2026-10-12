"""Length units used consistently by chapter prompts, limits and scoring."""

import re

WORDS = re.compile(r"\w+(?:['’\-]\w+)*", re.UNICODE)


def text_length(text: str, language: str) -> int:
    return (
        len(WORDS.findall(text))
        if str(language).lower().startswith("en")
        else len(text)
    )


def truncate_text(text: str, limit: int, language: str) -> str:
    if limit <= 0:
        return ""
    if text_length(text, language) <= limit:
        return text
    if str(language).lower().startswith("en"):
        matches = list(WORDS.finditer(text))
        boundary = matches[limit - 1].end()
    else:
        boundary = limit
    start = int(boundary * 0.7)
    endings = [
        text.rfind(mark, start, boundary)
        for mark in ("。", "！", "？", ".", "!", "?", "\n")
    ]
    cut = max(endings)
    return text[: cut + 1 if cut >= start else boundary].rstrip()


def summarize_consistency(checks: list[dict]) -> dict:
    """Combine the chapter checks without sending an entire novel back to a model."""
    return {
        "overall_consistent": all(
            check.get("overall_consistent", True) for check in checks
        ),
        "overall_confidence": sum(
            float(check.get("overall_confidence", 0)) for check in checks
        )
        / max(1, len(checks)),
        "details": {"chapters": checks},
        "all_issues": [
            issue for check in checks for issue in check.get("all_issues", [])
        ],
        "all_suggestions": [
            suggestion
            for check in checks
            for suggestion in check.get("all_suggestions", [])
        ],
    }
