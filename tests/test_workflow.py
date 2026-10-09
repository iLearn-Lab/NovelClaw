from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("language", ["zh", "en"])
def test_agent_prompts_keep_roles_and_chapter_constraints(workspace, language):
    executor_type = importlib.import_module("workflow.executor").CompositiveExecutor
    executor = executor_type.__new__(executor_type)
    executor.lang = language
    executor.main_characters = ["Lin"]
    executor.chapter_counter = 3
    executor.memory_system = SimpleNamespace(
        get_outline_by_topic=lambda _: {"content": "The city is underwater."},
        get_characters_by_topic=lambda _: [{"name": "Lin"}],
    )
    executor._get_chapter_outline_text = lambda *args: "Find the lost key."
    executor._get_chapter_outline_title = lambda *args: "The gate"
    executor._get_recent_turning_point_notes = lambda *args, **kw: [
        "The ally betrays Lin."
    ]
    prompts = {
        name: executor._build_agent_prompt(name, "City", "Previous chapter", 2400)
        for name in ("plot", "character", "world", "writer")
    }
    assert len(set(prompts.values())) == 4
    assert all("Lin" in value and "underwater" in value for value in prompts.values())
    assert "2400" in prompts["writer"] and "lost key" in prompts["writer"]
    assert "The gate" in prompts["writer"] and "betrays" in prompts["writer"]
    assert ("动机" if language == "zh" else "motivations") in prompts["character"]


def test_disabled_novelclaw_retrieval_needs_no_embedding_packages(workspace):
    if workspace.name != "novelclaw":
        pytest.skip("NovelClaw supports a disabled retriever")
    retriever = importlib.import_module("rag.retriever").Retriever(
        SimpleNamespace(enable_rag=False)
    )
    assert retriever.retrieve("test") == []
