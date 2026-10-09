"""Bounded log reads and atomic publication of runtime artifacts."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


def tail_text(path: Path, max_chars: int = 12000) -> str:
    """Read only enough UTF-8 bytes for the requested tail, even for huge logs."""
    if max_chars <= 0:
        return ""
    byte_limit = max_chars * 4 + 3
    try:
        with Path(path).open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - byte_limit))
            data = stream.read(byte_limit)
        return data.decode("utf-8", errors="replace").replace("\r\n", "\n")[-max_chars:]
    except OSError:
        return ""


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Publish a complete file; an interrupted write leaves the previous file intact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def resolve_run_directory(run_id: str, root: Path, *legacy_roots: Path) -> Path:
    """Resolve a single run component without allowing paths outside either root."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id or ""):
        raise ValueError("Invalid run ID")
    candidates = []
    for base in (root, *legacy_roots):
        base = base.resolve()
        candidate = (base / run_id).resolve()
        if candidate.parent != base:
            raise ValueError("Run directory is outside the configured root")
        candidates.append(candidate)
    return next((path for path in candidates if path.exists()), candidates[0])
