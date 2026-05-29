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

3. **Review the .env files**:
   - API keys are not required to open `/select-mode` or enter either workspace.
   - Add provider keys later in the UI, or edit `apps/novelclaw/.env` and `apps/multiagent/.env` before generation.
   - For production, set one shared `APP_SESSION_SECRET` for all three services.

4. **Build and start all services**:
   ```bash
   docker compose up -d
   ```

5. **Access the application**:
   - Auth Portal: http://localhost:8010/select-mode
   - MultiAgent: http://localhost:8011/dashboard
   - NovelClaw: http://localhost:8012/dashboard

The portal keeps the browser host you used. If you open `http://127.0.0.1:8010/select-mode`, workspace links will stay on `127.0.0.1`; if you open `localhost`, they will stay on `localhost`.

For CLI agents, set `APP_AGENT_API_KEY` in `apps/novelclaw/.env` and use the token API documented in [docs/AGENT_API.md](docs/AGENT_API.md).

### Docker Commands

**Start services**:
```bash
docker compose up -d
```

**Stop services**:
```bash
docker compose down
```

**View logs**:
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f novelclaw
docker compose logs -f multiagent
docker compose logs -f auth-portal
```

**Rebuild after code changes**:
```bash
docker compose up -d --build
```

**Restart a specific service**:
```bash
docker compose restart novelclaw
```

### Data Persistence

The following directories are mounted as volumes to persist data:
- `apps/auth-portal/local_web_portal/data` - Auth portal database
- `apps/multiagent/local_web_portal/data` - MultiAgent data
- `apps/multiagent/local_web_portal/runs` - MultiAgent runs and outputs
- `apps/novelclaw/local_web_portal/data` - NovelClaw database
- `apps/novelclaw/local_web_portal/runs` - Writing runs and outputs

### Troubleshooting

**Port conflicts**:
If ports 8010, 8011, or 8012 are already in use, edit `docker-compose.yml` to change the port mappings:
```yaml
ports:
  - "9010:8010"  # Change 9010 to your preferred port
```
If you change the host ports for MultiAgent or NovelClaw, set `APP_MULTIAGENT_PORT` or `APP_CLAW_PORT` before starting Compose so `/select-mode` points at the same ports:
```bash
APP_MULTIAGENT_PORT=9011 APP_CLAW_PORT=9012 docker compose up -d
```

**Permission issues**:
On Linux/Mac, you may need to adjust permissions:
```bash
chmod -R 755 apps/*/local_web_portal/data
chmod -R 755 apps/multiagent/local_web_portal/runs
chmod -R 755 apps/novelclaw/local_web_portal/runs
```

**View container status**:
```bash
docker compose ps
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
