# Local Multi-User Web Portal

This folder is a local-first deployment layer for `Long-Story-agent`.

It provides:
- Multi-user login/register
- Secure API key storage (encrypted at rest)
- Per-user generation jobs from a web UI
- Local SQLite by default (easy to run), upgradeable to PostgreSQL on server
- Job execution via isolated subprocess worker that calls the same backend pipeline
  (`Config + CompositiveExecutor`) as your project main flow

## 1) Install

Run in project root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -r local_web_portal\requirements.txt
```

Use `python -m pip` if your system has multiple Python versions:

```powershell
python -m pip install -r requirements.txt
python -m pip install -r local_web_portal\requirements.txt
```

## 2) Configure

```powershell
Copy-Item local_web_portal\.env.example local_web_portal\.env
```

You can leave `APP_SESSION_SECRET` and `APP_ENCRYPTION_KEY` empty for local testing.
The app will auto-create fallback secrets in `local_web_portal/data/`.

## 3) Start locally

```powershell
python -m uvicorn local_web_portal.app.main:app --host 127.0.0.1 --port 8010
```

During active development, you can add `--reload`. For long-running generation jobs, running without reload is more stable.

Open:

```text
http://127.0.0.1:8010
```

If your generation job fails with `torch/torchvision` import errors, your base project environment has a deep learning dependency mismatch.
The web UI still works, but generation needs your original project dependencies fixed first.

## 4) Server deployment (recommended)

Use HTTPS + reverse proxy (Nginx/Caddy). Minimal command:

```bash
uvicorn local_web_portal.app.main:app --host 0.0.0.0 --port 8010 --workers 2
```

Set real secrets in server environment:
- `APP_SESSION_SECRET`
- `APP_ENCRYPTION_KEY`
- `APP_HTTPS_ONLY=1`

For production scale, replace SQLite with PostgreSQL via `APP_DATABASE_URL`.
