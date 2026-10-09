"""Supervise a worker without buffering its output in application memory."""

from __future__ import annotations

import subprocess
import os
import signal
import time
from pathlib import Path
from typing import Callable


def run_logged_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    cancel_requested: Callable[[], bool],
    is_running: Callable[[], bool] | None = None,
    timeout: float = 0,
    idle_timeout: float = 0,
    heartbeat: Callable[[], None] | None = None,
    heartbeat_interval: float = 15,
) -> int:
    """Wait for completion, cancellation or timeout, and always reap the child.

    Output goes directly to disk. Status checks are capped at once per second,
    independently of how much output the worker produces.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        try:
            log.write(f"[system] worker started pid={process.pid}\n".encode())
            started = last_output = time.monotonic()
            next_status_check = started
            next_heartbeat = started + max(1, heartbeat_interval)
            previous_size = log_path.stat().st_size
            while True:
                now = time.monotonic()
                if cancel_requested():
                    raise RuntimeError("Job canceled while worker was running.")
                if is_running is not None and now >= next_status_check:
                    if not is_running():
                        raise RuntimeError("Job canceled while worker was running.")
                    next_status_check = now + 1
                return_code = process.poll()
                if return_code is not None:
                    return return_code
                size = log_path.stat().st_size
                if size != previous_size:
                    last_output = now
                    previous_size = size
                if timeout > 0 and now - started >= timeout:
                    raise TimeoutError(f"Worker exceeded timeout: {timeout}s")
                if idle_timeout > 0 and now - last_output >= idle_timeout:
                    raise TimeoutError(f"Worker exceeded idle timeout: {idle_timeout}s")
                if heartbeat is not None and now >= next_heartbeat:
                    heartbeat()
                    next_heartbeat = now + max(1, heartbeat_interval)
                time.sleep(0.2)
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    # Windows venv launchers may own another python.exe process.
                    # Terminating only the launcher can leave generation running.
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        process.kill()
                    else:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.wait()
            log.write(f"[system] worker exited code={process.returncode}\n".encode())
