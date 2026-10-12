from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
from io import BytesIO
from pathlib import Path
from threading import Barrier
import uuid
import zipfile

import pytest


def test_exports_use_latest_edited_chapters(signed_in):
    run_id = "export_" + uuid.uuid4().hex
    folder = signed_in.main._resolve_run_dir(run_id)
    (folder / "chapters").mkdir(parents=True)
    (folder / "chapters/chapter_01_iter_1_final.txt").write_text(
        "Obsolete draft", encoding="utf-8"
    )
    (folder / "chapters/chapter_01_iter_2_final.txt").write_text(
        "Author revised chapter", encoding="utf-8"
    )
    output = folder / "output.txt"
    output.write_text("Stale compiled output", encoding="utf-8")
    with signed_in.db.SessionLocal() as db:
        job = signed_in.models.GenerationJob(
            user_id=signed_in.user_id,
            provider="deepseek",
            idea="Novel",
            status="succeeded",
            run_id=run_id,
            output_path=str(output),
        )
        db.add(job)
        db.commit()
        job_id = job.id
    downloaded = signed_in.client.get(f"/jobs/{job_id}/download/output")
    assert downloaded.status_code == 200 and downloaded.text == "Author revised chapter"
    archived = signed_in.client.get(f"/jobs/{job_id}/download/chapters")
    assert archived.status_code == 200
    with zipfile.ZipFile(BytesIO(archived.content)) as zipped:
        assert zipped.namelist() == ["chapter_01_iter_2_final.txt"]
        assert zipped.read(zipped.namelist()[0]) == b"Author revised chapter"
    assert not list(folder.glob(".download_*.zip"))


def test_metadata_poll_does_not_read_chapter_bodies(workspace, tmp_path, monkeypatch):
    folder = tmp_path / "chapters"
    folder.mkdir()
    for name in (
        "chapter_1_iter_1_final.txt",
        "chapter_01_iter_22_final.txt",
        "chapter_2_iter_1_final.txt",
    ):
        (folder / name).write_text("Chapter body", encoding="utf-8")

    def no_read(*args, **kwargs):
        pytest.fail("Metadata requests must not read manuscripts")

    monkeypatch.setattr(Path, "read_text", no_read)
    outputs = workspace.main._load_chapter_outputs(tmp_path, include_content=False)
    assert [(item["chapter"], item["iteration"]) for item in outputs] == [
        (1, 22),
        (2, 1),
    ]
    assert (
        workspace.main._latest_chapter_file(tmp_path, 1).name
        == "chapter_01_iter_22_final.txt"
    )


def test_two_editors_cannot_overwrite_each_other(workspace, tmp_path):
    io = importlib.import_module("utils.file_io")
    path = tmp_path / "chapter.txt"
    path.write_text("Original", encoding="utf-8")
    gate = Barrier(2)

    def edit(number):
        gate.wait(timeout=5)
        try:
            io.save_text_version(path, str(number), base_content="Original")
            return "saved"
        except io.ContentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, range(2))) == ["conflict", "saved"]


def test_length_limits_use_english_words_and_chinese_characters(workspace):
    metrics = importlib.import_module("utils.text_metrics")
    english = "Lin's long-lost map was here. She opened the door and left."
    assert metrics.text_length(english, "en") == 11
    assert metrics.text_length("灯塔里的地图", "zh") == 6
    assert metrics.text_length(metrics.truncate_text(english, 5, "en"), "en") <= 5
    chinese = "灯塔里的地图消失了。她沿着海岸寻找新的线索。"
    assert len(metrics.truncate_text(chinese, 8, "zh")) <= 8
