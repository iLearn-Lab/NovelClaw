#!/bin/bash

# Docker Quick Start Script for NovelClaw

set -e

echo "🐳 NovelClaw Docker Deployment Setup"
echo "===================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

echo "✅ Docker and Docker Compose are installed"
echo ""

# Setup environment files
echo "📝 Setting up environment files..."

if [ ! -f "apps/auth-portal/.env" ]; then
    cp .env.auth-portal.example apps/auth-portal/.env
    echo "✅ Created apps/auth-portal/.env"
else
    echo "⚠️  apps/auth-portal/.env already exists, skipping"
fi

if [ ! -f "apps/multiagent/.env" ]; then
    cp .env.multiagent.example apps/multiagent/.env
    echo "✅ Created apps/multiagent/.env"
else
    echo "⚠️  apps/multiagent/.env already exists, skipping"
fi

if [ ! -f "apps/novelclaw/.env" ]; then
    cp .env.novelclaw.example apps/novelclaw/.env
    echo "✅ Created apps/novelclaw/.env"
else
    echo "⚠️  apps/novelclaw/.env already exists, skipping"
fi

echo ""
echo "⚠️  IMPORTANT: Please edit the .env files and add your API keys:"
echo "   - apps/novelclaw/.env"
echo "   - apps/multiagent/.env"
echo "   - apps/auth-portal/.env"
echo ""
read -p "Press Enter after you've configured the .env files..."

# Create data directories
echo ""
echo "📁 Creating data directories..."
mkdir -p apps/auth-portal/local_web_portal/data
mkdir -p apps/multiagent/local_web_portal/data
mkdir -p apps/novelclaw/local_web_portal/data
mkdir -p apps/novelclaw/local_web_portal/runs
echo "✅ Data directories created"

# Build and start services
echo ""
echo "🔨 Building Docker images..."
docker-compose build

echo ""
echo "🚀 Starting services..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to start..."
sleep 5

# Check service status
echo ""
echo "📊 Service Status:"
docker-compose ps

echo ""
echo "✅ NovelClaw is now running!"
echo ""
echo "🌐 Access the application:"
echo "   Auth Portal:  http://localhost:8010/select-mode"
echo "   MultiAgent:   http://localhost:8011/dashboard"
echo "   NovelClaw:    http://localhost:8012/dashboard"
echo ""
echo "📝 Useful commands:"
echo "   View logs:        docker-compose logs -f"
echo "   Stop services:    docker-compose down"
echo "   Restart services: docker-compose restart"
echo ""
