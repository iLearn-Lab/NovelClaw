param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8010,
  [switch]$Reload
)

$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

function Test-SupportedPythonVersion {
  param(
    [string]$VersionText
  )
  if (-not $VersionText) {
    return $false
  }
  $parts = $VersionText.Split(".")
  if ($parts.Length -lt 2) {
    return $false
  }
  $major = 0
  $minor = 0
  if (-not [int]::TryParse($parts[0], [ref]$major)) {
    return $false
  }
  if (-not [int]::TryParse($parts[1], [ref]$minor)) {
    return $false
  }
  return ($major -eq 3 -and $minor -ge 10)
}

function Get-PythonVersion {
  param(
    [string]$PythonExe
  )
  try {
    return (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
  } catch {
    return ""
  }
}

function Resolve-PythonExecutable {
  $currentPython = (Get-Command python -ErrorAction SilentlyContinue)
  if ($currentPython) {
    $currentVersion = Get-PythonVersion $currentPython.Source
    if (Test-SupportedPythonVersion $currentVersion) {
      return $currentPython.Source
    }
  }

  $projectPython = ""
  if (Test-Path ".venv") {
    $projectPython = Join-Path (Resolve-Path ".venv").Path "Scripts\python.exe"
  }
  if ($projectPython -and (Test-Path $projectPython)) {
    $projectVersion = Get-PythonVersion $projectPython
    if (Test-SupportedPythonVersion $projectVersion) {
      return $projectPython
    }
    throw @"
Found project virtual environment, but its Python version is unsupported: $projectVersion

Please recreate the environment manually:
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  python -m pip install --upgrade pip setuptools wheel
  python -m pip install -r requirements.txt
  python -m pip install -r local_web_portal\requirements.txt

If you have multiple Python versions installed, choose any Python 3.10+ interpreter explicitly before creating `.venv`.
"@
  }

  throw @"
No usable Python environment was found.

Prepare one manually, then rerun this launcher:
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  python -m pip install --upgrade pip setuptools wheel
  python -m pip install -r requirements.txt
  python -m pip install -r local_web_portal\requirements.txt

Supported Python: 3.10+
If you have multiple Python versions installed, use whichever Python 3.10+ interpreter you actually want for this project.
"@
}

function Assert-PythonModule {
  param(
    [string]$PythonExe,
    [string]$ModuleName,
    [string]$InstallHint
  )
  & $PythonExe -c "import $ModuleName" *> $null
  if ($LASTEXITCODE -ne 0) {
    throw @"
Missing Python module: $ModuleName

Install dependencies manually:
  python -m pip install -r requirements.txt
  python -m pip install -r local_web_portal\requirements.txt

$InstallHint
"@
  }
}

$pythonExe = Resolve-PythonExecutable
$pythonVersion = Get-PythonVersion $pythonExe
if (-not (Test-SupportedPythonVersion $pythonVersion)) {
  throw "Unsupported Python version: $pythonVersion. Use Python 3.10 or newer."
}

$env:EMBEDDING_MODEL = "none"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Assert-PythonModule -PythonExe $pythonExe -ModuleName "fastapi" -InstallHint "Expected package from local_web_portal/requirements.txt"
Assert-PythonModule -PythonExe $pythonExe -ModuleName "uvicorn" -InstallHint "Expected package from local_web_portal/requirements.txt"
Assert-PythonModule -PythonExe $pythonExe -ModuleName "sqlalchemy" -InstallHint "Expected package from local_web_portal/requirements.txt"

Write-Host "[check] Verifying FastAPI app import ..."
& $pythonExe -c "import importlib; m = importlib.import_module('local_web_portal.app.main'); assert getattr(m, 'app', None) is not None"
if ($LASTEXITCODE -ne 0) {
  throw @"
FastAPI app import failed.

Please verify:
  1. You are using the intended Python environment
  2. Dependencies are installed
  3. The repository files are complete
"@
}

$uvicornArgs = @(
  "-m", "uvicorn",
  "local_web_portal.app.main:app",
  "--host", $BindHost,
  "--port", [string]$Port
)
if ($Reload.IsPresent) {
  $uvicornArgs += "--reload"
}

Write-Host "[run] Using Python $pythonVersion at $pythonExe"
Write-Host "[run] Starting web portal on http://${BindHost}:$Port"
& $pythonExe @uvicornArgs
