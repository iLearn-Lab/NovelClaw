from __future__ import annotations

import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest


def test_memory_writers_preserve_independent_edits(workspace, tmp_path):
    store = importlib.import_module("utils.memory_store")
    path = tmp_path / "memory_index.json"
    initial = store.MemoryIndex(
        {
            "claw": {
                "story_premise": [
                    {"id": "original", "content": "draft", "metadata": {}}
                ]
            }
        }
    )
    store.save_memory_index(path, initial)
    worker = store.load_memory_index(path)
    author = store.load_memory_index(path)
    author["claw"]["story_premise"][0]["content"] = "author correction"
    store.save_memory_index(path, author)
    worker["claw"]["story_premise"].append({"id": "next", "content": "new memory"})
    store.save_memory_index(path, worker)
    entries = json.loads(path.read_text())["claw"]["story_premise"]
    assert entries == [
        {"id": "original", "content": "author correction", "metadata": {}},
        {"id": "next", "content": "new memory"},
    ]


def test_concurrent_memory_appends_survive(workspace, tmp_path):
    store = importlib.import_module("utils.memory_store")
    path = tmp_path / "memory_index.json"
    gate = Barrier(6)

    def append(number):
        index = store.load_memory_index(path)
        index.setdefault("texts", []).append(
            {"id": str(number), "content": f"chapter {number}"}
        )
        gate.wait(timeout=5)
        store.save_memory_index(path, index)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(append, range(6)))
    assert {entry["id"] for entry in store.load_memory_index(path)["texts"]} == set(
        map(str, range(6))
    )


def test_corrupt_memory_is_not_overwritten(workspace, tmp_path):
    store = importlib.import_module("utils.memory_store")
    path = tmp_path / "memory_index.json"
    path.write_text("broken legacy data", encoding="utf-8")
    with pytest.raises(ValueError):
        store.save_memory_index(path, store.MemoryIndex({"texts": []}))
    assert path.read_text() == "broken legacy data"


def test_memory_system_instances_share_new_entries(workspace, tmp_path):
    if workspace.name != "novelclaw":
        pytest.skip("NovelClaw supports memory without a vector database")
    memory_type = importlib.import_module("rag.memory_system").MemorySystem
    config = SimpleNamespace(
        embedding_model="none",
        enable_rag=False,
        vector_db_path=str(tmp_path),
        memory_vector_db_path=str(tmp_path / "memory"),
    )
    first = memory_type(config)
    second = memory_type(config)
    first.store_claw_memory(
        "story_premise", "Author's revision", "Novel", store_vector=False
    )
    second.store_claw_memory(
        "story_premise", "New chapter context", "Novel", store_vector=False
    )
    loaded = memory_type(config)
    entries = loaded.memory_index["claw"]["story_premise"]
    assert {entry["content"] for entry in entries} == {
        "Author's revision",
        "New chapter context",
    }
