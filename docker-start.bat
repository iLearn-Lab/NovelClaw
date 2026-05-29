@echo off
REM Docker Quick Start Script for NovelClaw (Windows)

echo ================================
echo NovelClaw Docker Deployment Setup
echo ================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running. Please start Docker Desktop first.
    pause
    exit /b 1
)

echo [OK] Docker is running
echo.

docker compose version >nul 2>&1
if not errorlevel 1 (
    set "COMPOSE=docker compose"
) else (
    docker-compose version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Docker Compose is not available. Install Docker Compose v2 or docker-compose.
        pause
        exit /b 1
    )
    set "COMPOSE=docker-compose"
)

echo [OK] Docker Compose command: %COMPOSE%
echo.

REM Setup environment files
echo Setting up environment files...

if not exist "apps\auth-portal\.env" (
    copy .env.auth-portal.example apps\auth-portal\.env >nul
    echo [OK] Created apps\auth-portal\.env
) else (
    echo [SKIP] apps\auth-portal\.env already exists
)

if not exist "apps\multiagent\.env" (
    copy .env.multiagent.example apps\multiagent\.env >nul
    echo [OK] Created apps\multiagent\.env
) else (
    echo [SKIP] apps\multiagent\.env already exists
)

if not exist "apps\novelclaw\.env" (
    copy .env.novelclaw.example apps\novelclaw\.env >nul
    echo [OK] Created apps\novelclaw\.env
) else (
    echo [SKIP] apps\novelclaw\.env already exists
)

echo.
echo [INFO] API keys are not required to open /select-mode or enter the workspaces.
echo        Add provider keys later in the UI, or edit the .env files before generation.

REM Create data directories
echo.
echo Creating data directories...
if not exist "apps\auth-portal\local_web_portal\data" mkdir apps\auth-portal\local_web_portal\data
if not exist "apps\multiagent\local_web_portal\data" mkdir apps\multiagent\local_web_portal\data
if not exist "apps\multiagent\local_web_portal\runs" mkdir apps\multiagent\local_web_portal\runs
if not exist "apps\novelclaw\local_web_portal\data" mkdir apps\novelclaw\local_web_portal\data
if not exist "apps\novelclaw\local_web_portal\runs" mkdir apps\novelclaw\local_web_portal\runs
echo [OK] Data directories created

REM Build and start services
echo.
echo Building Docker images...
%COMPOSE% build

echo.
echo Starting services...
%COMPOSE% up -d

echo.
echo Waiting for services to start...
timeout /t 5 /nobreak >nul

REM Check service status
echo.
echo Service Status:
%COMPOSE% ps

echo.
echo ================================
echo NovelClaw is now running!
echo ================================
echo.
echo Access the application:
echo    Auth Portal:  http://localhost:8010/select-mode
echo    MultiAgent:   http://localhost:8011/dashboard
echo    NovelClaw:    http://localhost:8012/dashboard
echo.
echo Useful commands:
echo    View logs:        %COMPOSE% logs -f
echo    Stop services:    %COMPOSE% down
echo    Restart services: %COMPOSE% restart
echo.
pause
