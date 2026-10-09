@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Stopping old local services...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\stop-all-local.ps1"
if errorlevel 1 goto :fail

echo.
echo [2/4] Preparing local env files...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\setup-local-env.ps1"
if errorlevel 1 goto :fail

echo.
echo [3/4] Preparing shared virtual environment...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\bootstrap-shared-venv.ps1"
if errorlevel 1 goto :fail

echo.
echo [4/4] Starting Portal, MultiAgent, and NovelClaw...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\start-all-local.ps1" -UseSharedVenv
if errorlevel 1 goto :fail

echo.
echo Local services are launching.
echo Auth Portal : http://127.0.0.1:8010/select-mode
echo MultiAgent  : http://127.0.0.1:8011/dashboard
echo NovelClaw   : http://127.0.0.1:8012/dashboard
echo.
pause
exit /b 0

:fail
echo.
echo Failed to start local services.
pause
exit /b 1
