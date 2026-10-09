# Development and verification

Use Python 3.10+ and Node.js 20+. The regression suite isolates databases, run
files and memory in temporary directories and never calls a cloud model.

```powershell
python -m venv .venv-shared
.\.venv-shared\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv-shared\Scripts\python.exe -m pytest -q
.\.venv-shared\Scripts\python.exe -m ruff check .
node --test tests/live_runtime.test.cjs
.\.venv-shared\Scripts\python.exe scripts/check-javascript.py
```

On Linux/macOS, use `.venv-shared/bin/python` in place of the Windows executable.
Development requirements cover the web regression suite. Install the application
requirements under `apps/` to use the full generation and vector retrieval stack.

## Browser checks

```powershell
.\.venv-shared\Scripts\python.exe -m playwright install chromium
.\.venv-shared\Scripts\python.exe scripts/browser-smoke.py
```

To use an already installed browser, pass `--channel chrome` or `--channel msedge`.
The script starts all three services on temporary local ports, checks the shared
session, visits the writing and model pages, checks keyboard/mobile navigation,
and verifies that a failed reply submission preserves the draft. It stops its
own processes on exit. Screenshots and logs go to ignored `test-results/`.

GitHub Actions runs the Python suite on Linux (3.10 and 3.12) and Windows (3.11),
JavaScript checks, Chromium smoke checks and Docker Compose validation.
These checks do not certify external provider availability or generated prose quality.

## Runtime behavior

- Generation jobs are claimed with a conditional database update. Repeated start
  requests cannot run the same job twice; terminal jobs cannot be resurrected.
- Workers write directly to their logs. Cancellation and deadlines always wait
  for the child process to exit. Database status is checked at most once a second.
- Log tails read at most `4 * max_chars + 3` bytes. Browser polling waits for the
  preceding request, backs off after failures, pauses when hidden/offline and
  stops when the run finishes.
- Manuscripts, result files and memory indexes use atomic replacement. Memory
  writers lock the index and merge changes since their snapshot, preserving
  independent edits from another writer. Conflicting updates to the same memory
  field use the last writer's value. Invalid existing indexes are preserved.
- Chapter edits can send `base_content` with `content`. If the saved chapter has
  changed, the endpoint returns HTTP 409; the editor retains the unsaved text.
- `APP_DATA_DIR` controls service data and generated local secrets. Relative
  paths resolve under the application directory. `APP_RUNS_DIR` defaults to
  `local_web_portal/runs`; reading old `runs/` directories is still supported.
- `VECTOR_DB_PATH` controls memory storage. Docker persists each workspace's
  default `vector_db/` directory. Mount your chosen path separately if you
  override it; copy existing container memory out before replacing an old container.

The public entry remains a shared preview workspace. It is not a replacement
for authentication and user isolation in an internet-facing multi-user deployment.

## Local startup

`START_LOCAL.bat` preserves existing `.env` files. To intentionally regenerate
local defaults, run `scripts/setup-local-env.ps1 -Overwrite` yourself.
Services start in the background and readiness is checked before success is
reported. Logs are in each service's `local_web_portal/data/logs/` directory.

Docker builds install requirements before copying application source, so source
and template edits reuse the dependency layer. All services share the image and
workspaces wait for the portal health check before starting.
