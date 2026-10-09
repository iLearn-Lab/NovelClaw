# Run NovelClaw Locally

`NovelClaw` is the main workspace in this bundle. `Portal` is the public entry layer, and `MultiAgent` is an optional faster ideation lane, but the primary local path is:

```text
http://127.0.0.1:8010/select-mode -> http://127.0.0.1:8012/dashboard
```

## Recommended Path

1. Start the local stack.
2. Open `http://127.0.0.1:8010/select-mode`.
3. Choose `NovelClaw`.
4. Open `/console/models` and save an API key for a provider.
5. Open `/console/chat` and start a writing session.
6. Use `/console/tasks` to inspect runs and `/console/manuscript/read`, `/console/storyboard`, and `/console/memory/banks` to review and continue the project.

## One-Click Start

```powershell
.\START_LOCAL.bat
```

This script will:

1. Stop old listeners on `8010`, `8011`, and `8012`.
2. Create missing local `.env` files, preserving existing settings.
3. Prepare the shared `.venv-shared`.
4. Start `Portal`, `MultiAgent`, and `NovelClaw` in the background and check readiness.

Service logs are saved in each app's `local_web_portal/data/logs/` directory.

## One-Click Stop

```powershell
.\STOP_LOCAL.bat
```

## Manual Startup

```powershell
.\scripts\setup-local-env.ps1
.\scripts\bootstrap-shared-venv.ps1
.\scripts\start-all-local.ps1 -UseSharedVenv
```

If the services are already running and you want to restart them:

```powershell
.\scripts\start-all-local.ps1 -UseSharedVenv -RestartExisting
```

## Local URLs

- `Portal`: `http://127.0.0.1:8010/select-mode`
- `MultiAgent`: `http://127.0.0.1:8011/dashboard`
- `NovelClaw`: `http://127.0.0.1:8012/dashboard`

## Working Inside Claw Mode

After entering the main NovelClaw workspace, the most useful pages are:

- `/console/models`
  Configure providers, models, and API keys.
- `/console/chat`
  Start or continue the main writing session.
- `/console/tasks`
  Review active and past runs, then open job detail pages.
- `/console/manuscript/read`
  Read and review chapter output.
- `/console/storyboard`
  Review outlines, plot beats, and chapter progress.
- `/console/memory/banks`
  Inspect and edit memory-bank content tied to the project.

## Notes

- Start from `8010/select-mode` first, even if NovelClaw is the main destination.
- The public release does not expose the old registration, login, password reset, or email verification flow.
- Local preview does not require Nginx by default.
- The local defaults set `EMBEDDING_MODEL=none` and `DISABLE_EMBEDDING_DOWNLOADS=1` to avoid heavy embedding downloads during preview.
