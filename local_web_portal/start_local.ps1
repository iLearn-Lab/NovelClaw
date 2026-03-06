$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  python -m venv .venv
}

. .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -r local_web_portal\requirements.txt

if (-not (Test-Path "local_web_portal\.env")) {
  Copy-Item "local_web_portal\.env.example" "local_web_portal\.env"
}

# Default: no --reload for stability while long jobs run.
# If you are actively editing code/templates, append --reload manually.
python -m uvicorn local_web_portal.app.main:app --host 127.0.0.1 --port 8010
