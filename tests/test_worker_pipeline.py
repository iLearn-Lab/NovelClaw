from pathlib import Path
import runpy

import pytest

SMOKE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/generation-smoke.py")
)


@pytest.mark.parametrize("app", ["novelclaw", "multiagent"])
@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_full_worker_writes_chapter_and_memory(app, wire):
    result = SMOKE["run_smoke"](app, wire)
    assert result["chapters"] == 1 and result["requests"] > 2
