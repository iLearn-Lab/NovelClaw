param(
  [switch]$OverwriteEnv,
  [switch]$RestoreState,
  [switch]$WithVectorDependencies
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($RestoreState.IsPresent) {
  & (Join-Path $PSScriptRoot "restore-server-state.ps1") -Force
}

& (Join-Path $PSScriptRoot "setup-local-env.ps1") -Overwrite:$OverwriteEnv

function Ensure-Venv([string]$AppRoot, [string[]]$RequirementFiles) {
  Push-Location $AppRoot
  try {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
      python -m venv .venv
      if ($LASTEXITCODE -ne 0) { throw "Failed to create environment: $AppRoot" }
    }
    $python = (Resolve-Path ".venv\Scripts\python.exe").Path
    & $python -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { throw "Failed to prepare pip: $AppRoot" }
    foreach ($req in $RequirementFiles) {
      & $python -m pip install -r $req
      if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed: $req" }
    }
  } finally {
    Pop-Location
  }
}

Ensure-Venv -AppRoot (Join-Path $root "apps\auth-portal") -RequirementFiles @("requirements.txt")
$writingRequirements = @((Join-Path $root "requirements-web.txt"))
if ($WithVectorDependencies) { $writingRequirements += "requirements.txt" }
Ensure-Venv -AppRoot (Join-Path $root "apps\multiagent") -RequirementFiles $writingRequirements
Ensure-Venv -AppRoot (Join-Path $root "apps\novelclaw") -RequirementFiles $writingRequirements

Write-Host ""
Write-Host "Bootstrap finished."
Write-Host "Next step:"
Write-Host "  .\scripts\start-all-local.ps1"
