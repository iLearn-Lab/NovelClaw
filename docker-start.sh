#!/bin/bash

# Docker quick start script for NovelClaw.

set -euo pipefail

echo "NovelClaw Docker Deployment Setup"
echo "================================="
echo ""

if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] Docker is not installed. Please install Docker first."
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "[ERROR] Docker Compose is not available. Install Docker Compose v2 or docker-compose."
    exit 1
fi

echo "[OK] Docker and Docker Compose are available"
echo ""

echo "Setting up environment files..."

if [ ! -f "apps/auth-portal/.env" ]; then
    cp .env.auth-portal.example apps/auth-portal/.env
    echo "[OK] Created apps/auth-portal/.env"
else
    echo "[SKIP] apps/auth-portal/.env already exists"
fi

if [ ! -f "apps/multiagent/.env" ]; then
    cp .env.multiagent.example apps/multiagent/.env
    echo "[OK] Created apps/multiagent/.env"
else
    echo "[SKIP] apps/multiagent/.env already exists"
fi

if [ ! -f "apps/novelclaw/.env" ]; then
    cp .env.novelclaw.example apps/novelclaw/.env
    echo "[OK] Created apps/novelclaw/.env"
else
    echo "[SKIP] apps/novelclaw/.env already exists"
fi

echo ""
echo "[INFO] API keys are not required to open /select-mode or enter the workspaces."
echo "       Add provider keys later in the UI, or edit the .env files before generation."

echo ""
echo "Creating data directories..."
mkdir -p apps/auth-portal/local_web_portal/data
mkdir -p apps/multiagent/local_web_portal/data
mkdir -p apps/multiagent/local_web_portal/runs
mkdir -p apps/novelclaw/local_web_portal/data
mkdir -p apps/novelclaw/local_web_portal/runs
echo "[OK] Data directories created"

echo ""
echo "Building Docker images..."
"${COMPOSE[@]}" build

echo ""
echo "Starting services..."
"${COMPOSE[@]}" up -d

echo ""
echo "Waiting for services to start..."
sleep 5

echo ""
echo "Service Status:"
"${COMPOSE[@]}" ps

echo ""
echo "NovelClaw is now running"
echo ""
echo "Access the application:"
echo "   Portal:      http://localhost:8010/select-mode"
echo "   MultiAgent:  http://localhost:8011/dashboard"
echo "   NovelClaw:   http://localhost:8012/dashboard"
echo ""
echo "Useful commands:"
echo "   View logs:        ${COMPOSE[*]} logs -f"
echo "   Stop services:    ${COMPOSE[*]} down"
echo "   Restart services: ${COMPOSE[*]} restart"
echo ""
