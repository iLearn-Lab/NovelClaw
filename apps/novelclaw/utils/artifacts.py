"""Find the latest chapter revisions before reading their contents."""

from pathlib import Path
import re

CHAPTER_NAME = re.compile(r"^chapter_(\d+)_iter_(\d+)_final\.txt$")


def latest_chapter_files(run_dir: Path) -> list[Path]:
    folder = (run_dir / "chapters").resolve()
    latest = {}
    for path in folder.glob("chapter_*_iter_*_final.txt"):
        match = CHAPTER_NAME.fullmatch(path.name)
        if not match or not path.is_file() or not path.resolve().is_relative_to(folder):
            continue
        chapter, iteration = map(int, match.groups())
        if chapter not in latest or iteration > latest[chapter][0]:
            latest[chapter] = (iteration, path)
    return [latest[number][1] for number in sorted(latest)]


def chapter_outputs(run_dir: Path, *, include_content: bool = True) -> list[dict]:
    result = []
    for path in latest_chapter_files(run_dir):
        chapter, iteration = map(int, CHAPTER_NAME.fullmatch(path.name).groups())
        item = {"chapter": chapter, "iteration": iteration, "filename": path.name}
        if include_content:
            try:
                item["content"] = path.read_text(
                    encoding="utf-8", errors="replace"
                ).strip()
            except FileNotFoundError:
                continue  # A run may be deleted while the page is being refreshed.
        result.append(item)
    return result
