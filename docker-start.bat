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
echo [IMPORTANT] Please edit the .env files and add your API keys:
echo    - apps\novelclaw\.env
echo    - apps\multiagent\.env
echo    - apps\auth-portal\.env
echo.
pause

REM Create data directories
echo.
echo Creating data directories...
if not exist "apps\auth-portal\local_web_portal\data" mkdir apps\auth-portal\local_web_portal\data
if not exist "apps\multiagent\local_web_portal\data" mkdir apps\multiagent\local_web_portal\data
if not exist "apps\novelclaw\local_web_portal\data" mkdir apps\novelclaw\local_web_portal\data
if not exist "apps\novelclaw\local_web_portal\runs" mkdir apps\novelclaw\local_web_portal\runs
echo [OK] Data directories created

REM Build and start services
echo.
echo Building Docker images...
docker-compose build

echo.
echo Starting services...
docker-compose up -d

echo.
echo Waiting for services to start...
timeout /t 5 /nobreak >nul

REM Check service status
echo.
echo Service Status:
docker-compose ps

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
echo    View logs:        docker-compose logs -f
echo    Stop services:    docker-compose down
echo    Restart services: docker-compose restart
echo.
pause
