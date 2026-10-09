"""Merge independent memory edits before atomically publishing an index."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from filelock import FileLock

from utils.file_io import atomic_write_text


class MemoryIndex(dict):
    def __init__(self, value, *, persisted=False):
        super().__init__(value)
        self.base = deepcopy(value) if persisted else {}


def load_memory_index(path: Path) -> MemoryIndex:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("Memory index must contain a JSON object")
    return MemoryIndex(value, persisted=True)


def _merge(base, edited, current):
    if edited == base:
        return deepcopy(current)
    if isinstance(edited, dict) and isinstance(current, dict):
        base = base if isinstance(base, dict) else {}
        merged = deepcopy(current)
        for key in base.keys() - edited.keys():
            merged.pop(key, None)
        for key, value in edited.items():
            if key not in base or value != base[key]:
                merged[key] = _merge(base.get(key), value, current.get(key))
        return merged
    if isinstance(edited, list) and isinstance(current, list):
        base = base if isinstance(base, list) else []
        if all(
            isinstance(item, dict) and item.get("id")
            for item in [*base, *edited, *current]
        ):
            original = {item["id"]: item for item in base}
            changes = {item["id"]: item for item in edited}
            removed = original.keys() - changes.keys()
            merged = {
                item["id"]: deepcopy(item)
                for item in current
                if item["id"] not in removed
            }
            for key, value in changes.items():
                if key not in original or value != original[key]:
                    merged[key] = _merge(original.get(key), value, merged.get(key))
            return list(merged.values())
    return deepcopy(edited)


def save_memory_index(path: Path, index: MemoryIndex) -> None:
    """Keep updates made since this reader loaded the index, including other processes.

    Concurrent changes to different fields or entries are merged. A conflicting
    change to the same field uses the value from the last writer.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=10):
        current = load_memory_index(path)  # Never overwrite an unreadable index.
        merged = _merge(index.base, dict(index), dict(current))
        atomic_write_text(path, json.dumps(merged, ensure_ascii=False, indent=2))
        index.clear()
        index.update(merged)
        index.base = deepcopy(merged)
