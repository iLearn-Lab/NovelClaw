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
`requirements-web.txt` includes the complete default writing runtime: web services,
model clients and structured memory. The development requirements add testing tools.
Vector retrieval and local embedding models are optional; install application
requirements under `apps/` or pass `-WithVectorDependencies` to a bootstrap script.

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

The generation test runs the real SDK and worker processes against a local HTTP
provider fixture, including briefs larger than Windows' command-line limit:

```powershell
.\.venv-shared\Scripts\python.exe scripts/generation-smoke.py
```

Both workspaces are exercised over Chat Completions and Responses. This checks
chapter publication, memory persistence and final manuscript assembly; fixture
text is deterministic and is not a literary quality evaluation.

GitHub Actions runs the Python suite on Linux (3.10 and 3.12) and Windows (3.11),
JavaScript checks, Chromium smoke checks and a full Docker image build. The Docker
job executes both packaged workers over both protocols, starts all three services
and verifies the shared session. The default image uses Python 3.12 and excludes
embedding dependencies. Include them with `docker build --build-arg INSTALL_VECTOR_DEPS=true .`.
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
- Final output is assembled from published chapters. It is never shortened by a
  second whole-book model rewrite. Downloads stream the latest chapter revisions,
  including manual edits; ZIP archives are private to each request and cleaned up.
- English chapter limits count words; Chinese limits count characters. Prompts,
  length enforcement and reward scoring use the same units.
- Running workers refresh memory before each writing step. Concurrent session
  confirmation produces one job, and a late reply cannot overwrite a newer brief
  or restart a canceled session.
- `APP_DATA_DIR` controls service data and generated local secrets. Relative
  paths resolve under the application directory. `APP_RUNS_DIR` defaults to
  `local_web_portal/runs`; reading old `runs/` directories is still supported.
- `VECTOR_DB_PATH` controls memory storage. Docker persists each workspace's
  default `vector_db/` directory. Mount your chosen path separately if you
  override it; copy existing container memory out before replacing an old container.

## Model protocol handling

Responses requests preserve message roles, function call IDs, tool outputs and
reasoning items. Optional reasoning is controlled by `MODEL_REASONING_EFFORT`;
there is no forced reasoning setting for ordinary models. Invalid model output is
reported rather than treated as an empty success. Authentication, rate-limit and
server failures use SDK retries and remain visible to the caller. Text fallback
is used only when a provider explicitly rejects function tools.

The implementation follows the [official OpenAI function calling documentation](https://developers.openai.com/api/docs/guides/function-calling):
Responses tools have flattened schemas, call outputs use `function_call_output`
with `call_id`, and reasoning items are retained between turns. The writing loop
requests `parallel_tool_calls=false` because actions run in sequence.

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
