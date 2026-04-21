# Docker Deployment Guide

## Quick Start with Docker

### Prerequisites
- Docker and Docker Compose installed
- Git (to clone the repository)

### Setup Steps

1. **Clone the repository** (if not already done):
   ```bash
   git clone https://github.com/iLearn-Lab/NovelClaw.git
   cd NovelClaw
   ```

2. **Configure environment variables**:
   ```bash
   # Copy example env files to actual .env files
   cp .env.auth-portal.example apps/auth-portal/.env
   cp .env.multiagent.example apps/multiagent/.env
   cp .env.novelclaw.example apps/novelclaw/.env
   ```

3. **Edit the .env files** with your API keys:
   - `apps/novelclaw/.env` - Add your OpenAI/Anthropic API keys
   - `apps/multiagent/.env` - Add your OpenAI/Anthropic API keys
   - `apps/auth-portal/.env` - Change the SECRET_KEY

4. **Build and start all services**:
   ```bash
   docker-compose up -d
   ```

5. **Access the application**:
   - Auth Portal: http://localhost:8010/select-mode
   - MultiAgent: http://localhost:8011/dashboard
   - NovelClaw: http://localhost:8012/dashboard

### Docker Commands

**Start services**:
```bash
docker-compose up -d
```

**Stop services**:
```bash
docker-compose down
```

**View logs**:
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f novelclaw
docker-compose logs -f multiagent
docker-compose logs -f auth-portal
```

**Rebuild after code changes**:
```bash
docker-compose up -d --build
```

**Restart a specific service**:
```bash
docker-compose restart novelclaw
```

### Data Persistence

The following directories are mounted as volumes to persist data:
- `apps/auth-portal/local_web_portal/data` - Auth portal database
- `apps/multiagent/local_web_portal/data` - MultiAgent data
- `apps/novelclaw/local_web_portal/data` - NovelClaw database
- `apps/novelclaw/local_web_portal/runs` - Writing runs and outputs

### Troubleshooting

**Port conflicts**:
If ports 8010, 8011, or 8012 are already in use, edit `docker-compose.yml` to change the port mappings:
```yaml
ports:
  - "9010:8010"  # Change 9010 to your preferred port
```

**Permission issues**:
On Linux/Mac, you may need to adjust permissions:
```bash
chmod -R 755 apps/*/local_web_portal/data
chmod -R 755 apps/novelclaw/local_web_portal/runs
```

**View container status**:
```bash
docker-compose ps
```

**Enter a container for debugging**:
```bash
docker exec -it novelclaw-workspace bash
```

### Production Deployment

For production deployment:
1. Use proper secrets management (not .env files)
2. Configure reverse proxy (nginx example in `infra/nginx/`)
3. Set up SSL/TLS certificates
4. Use external database instead of SQLite
5. Configure proper backup for data volumes
6. Set resource limits in docker-compose.yml

See [DEPLOYMENT.md](DEPLOYMENT.md) for more production deployment details.
