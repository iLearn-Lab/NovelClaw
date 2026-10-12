param([switch]$WithVectorDependencies)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venv = Join-Path $root ".venv-shared"

function Resolve-BootstrapPython {
  $candidates = @(
    @{ Name = "py"; Args = @("-3") },
    @{ Name = "python"; Args = @() },
    @{ Name = "python3"; Args = @() }
  )

  foreach ($candidate in $candidates) {
    $cmd = Get-Command $candidate.Name -ErrorAction SilentlyContinue
    if ($cmd) {
      return [pscustomobject]@{
        Command = $candidate.Name
        Args = $candidate.Args
      }
    }
  }

  throw "Python was not found in PATH. Please install Python 3.10+ and make sure `py`, `python`, or `python3` is available in the terminal."
}

$venvPython = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
  $bootstrapPython = Resolve-BootstrapPython
  & $bootstrapPython.Command @($bootstrapPython.Args + @("-m", "venv", $venv))
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to create shared virtual environment at $venv. Please verify that Python can create virtual environments on this machine."
  }
}

if (-not (Test-Path $venvPython)) {
  throw "Shared virtual environment was not created successfully: $venvPython"
}

$python = $venvPython

& $python -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) {
  throw "Failed to upgrade pip in shared virtual environment: $python"
}

& $python -m pip install -r (Join-Path $root "requirements-web.txt")
if ($LASTEXITCODE -ne 0) { throw "Failed to install web runtime dependencies." }

if ($WithVectorDependencies) {
  foreach ($app in @("multiagent", "novelclaw")) {
    & $python -m pip install -r (Join-Path $root "apps\$app\requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Failed to install vector dependencies for $app." }
  }
}

Write-Host "[ok] shared venv ready: $python"
