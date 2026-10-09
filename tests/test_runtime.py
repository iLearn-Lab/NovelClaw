from __future__ import annotations

import importlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest


def test_tail_is_bounded_and_preserves_unicode(workspace, tmp_path, monkeypatch):
    io = importlib.import_module("utils.file_io")
    path = tmp_path / "large.log"
    suffix = "末尾章节🙂\n" * 50
    path.write_bytes(b"x" * 2_000_000 + suffix.encode())
    original = type(path).open
    amounts = []

    class Tracked:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def __getattr__(self, key):
            return getattr(self.stream, key)

        def read(self, amount=-1):
            amounts.append(amount)
            assert 0 <= amount <= 403
            return self.stream.read(amount)

    monkeypatch.setattr(
        type(path), "open", lambda self, *a, **kw: Tracked(original(self, *a, **kw))
    )
    assert io.tail_text(path, 100) == suffix[-100:]
    assert io.tail_text(path, 0) == ""
    assert io.tail_text(tmp_path / "missing", 100) == ""
    assert amounts == [403]


def test_failed_write_preserves_previous_artifact(workspace, tmp_path, monkeypatch):
    io = importlib.import_module("utils.file_io")
    path = tmp_path / "chapter.txt"
    path.write_text("原稿", encoding="utf-8")

    def fail_replace(*args):
        raise OSError("simulated disk error")

    monkeypatch.setattr(io.os, "replace", fail_replace)
    with pytest.raises(OSError):
        io.atomic_write_text(path, "新稿")
    assert path.read_text(encoding="utf-8") == "原稿"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "run_id", ["../other", "..\\other", "/tmp", "C:\\data", "", ".", ".."]
)
def test_run_paths_stay_in_workspace(workspace, run_id):
    io = importlib.import_module("utils.file_io")
    with pytest.raises(ValueError):
        io.resolve_run_directory(
            run_id, workspace.temp / "runs", workspace.temp / "legacy"
        )


@pytest.mark.parametrize("stop_reason", ["cancel", "timeout", "status_error"])
def test_stopped_worker_is_reaped(workspace, tmp_path, monkeypatch, stop_reason):
    supervisor = importlib.import_module("utils.processes")
    original = supervisor.subprocess.Popen
    children = []

    def start(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    def check():
        if stop_reason == "status_error":
            raise RuntimeError("database unavailable")
        return True

    monkeypatch.setattr(supervisor.subprocess, "Popen", start)
    with pytest.raises((RuntimeError, TimeoutError)):
        supervisor.run_logged_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            env=os.environ.copy(),
            log_path=tmp_path / "worker.log",
            cancel_requested=lambda: stop_reason == "cancel",
            is_running=check,
            timeout=0.1 if stop_reason == "timeout" else 0,
        )
    assert children and children[0].poll() is not None


def test_worker_output_is_available_and_exit_code_preserved(workspace, tmp_path):
    supervisor = importlib.import_module("utils.processes")
    path = tmp_path / "worker.log"
    code = supervisor.run_logged_process(
        [sys.executable, "-c", "print('chapter ready'); raise SystemExit(7)"],
        cwd=tmp_path,
        env=os.environ.copy(),
        log_path=path,
        cancel_requested=lambda: False,
    )
    assert code == 7
    assert "chapter ready" in path.read_text()


def test_cancel_stops_worker_descendants(workspace, tmp_path):
    supervisor = importlib.import_module("utils.processes")
    ready = tmp_path / "ready"
    survived = tmp_path / "survived"
    child = f"from pathlib import Path; import time; Path({str(ready)!r}).touch(); time.sleep(1); Path({str(survived)!r}).touch()"
    parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)"
    with pytest.raises(RuntimeError, match="canceled"):
        supervisor.run_logged_process(
            [sys.executable, "-c", parent],
            cwd=tmp_path,
            env=os.environ.copy(),
            log_path=tmp_path / "worker.log",
            cancel_requested=ready.exists,
            timeout=5,
        )
    assert ready.exists()
    time.sleep(1.2)
    assert not survived.exists(), "A descendant kept running after cancellation"


def test_job_claim_is_atomic_and_only_runs_once(signed_in, monkeypatch):
    runner = importlib.import_module("local_web_portal.app.job_runner")
    security = importlib.import_module("local_web_portal.app.security")
    with signed_in.db.SessionLocal() as db:
        db.add(
            signed_in.models.ApiCredential(
                user_id=signed_in.user_id,
                provider="deepseek",
                encrypted_key=security.encrypt_api_key("fake-test-key"),
            )
        )
        job = signed_in.models.GenerationJob(
            user_id=signed_in.user_id, provider="deepseek", idea="test", status="queued"
        )
        db.add(job)
        db.commit()
        job_id = job.id
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return {"ok": True, "result": {"final_text": "A chapter."}}

    monkeypatch.setattr(runner, "_run_worker_subprocess", run)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(runner.run_generation_job, [job_id] * 4))
    assert len(calls) == 1
    with signed_in.db.SessionLocal() as db:
        assert db.get(signed_in.models.GenerationJob, job_id).status == "succeeded"


@pytest.mark.parametrize("status", ["canceled", "succeeded", "failed", "running"])
def test_existing_job_is_not_restarted(signed_in, monkeypatch, status):
    runner = importlib.import_module("local_web_portal.app.job_runner")
    with signed_in.db.SessionLocal() as db:
        job = signed_in.models.GenerationJob(
            user_id=signed_in.user_id, provider="deepseek", idea="test", status=status
        )
        db.add(job)
        db.commit()
        job_id = job.id
    monkeypatch.setattr(
        runner, "_run_worker_subprocess", lambda *a, **kw: pytest.fail("must not run")
    )
    runner.run_generation_job(job_id)
    with signed_in.db.SessionLocal() as db:
        assert db.get(signed_in.models.GenerationJob, job_id).status == status


def test_cancellation_during_artifact_save_wins(signed_in, monkeypatch):
    runner = importlib.import_module("local_web_portal.app.job_runner")
    security = importlib.import_module("local_web_portal.app.security")
    with signed_in.db.SessionLocal() as db:
        db.add(
            signed_in.models.ApiCredential(
                user_id=signed_in.user_id,
                provider="deepseek",
                encrypted_key=security.encrypt_api_key("fake-test-key"),
            )
        )
        job = signed_in.models.GenerationJob(
            user_id=signed_in.user_id, provider="deepseek", idea="test", status="queued"
        )
        db.add(job)
        db.commit()
        job_id = job.id

    def save(*args):
        with signed_in.db.SessionLocal() as db:
            db.get(signed_in.models.GenerationJob, job_id).status = "canceled"
            db.commit()
        return "saved-output.txt", "excerpt"

    monkeypatch.setattr(
        runner,
        "_run_worker_subprocess",
        lambda *a, **kw: {"ok": True, "result": {"final_text": "chapter"}},
    )
    monkeypatch.setattr(runner, "_save_job_artifacts", save)
    runner.run_generation_job(job_id)
    with signed_in.db.SessionLocal() as db:
        assert db.get(signed_in.models.GenerationJob, job_id).status == "canceled"
