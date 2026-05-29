# Agent API

NovelClaw exposes a token-authenticated REST API for CLI agents and automation.
The API does not use browser sessions or CSRF tokens.

## Enable

Set an agent token in `apps/novelclaw/.env`:

```env
APP_AGENT_API_KEY=change-this-agent-api-key
WEB_MODELLESS_MODE=0
```

Then restart the NovelClaw service:

```bash
docker compose restart novelclaw
```

Use either header style:

```bash
X-API-Key: change-this-agent-api-key
Authorization: Bearer change-this-agent-api-key
```

## Provider Setup

List providers:

```bash
curl -H "X-API-Key: $APP_AGENT_API_KEY" \
  http://127.0.0.1:8012/api/v1/providers
```

Save a provider key:

```bash
curl -X POST http://127.0.0.1:8012/api/v1/providers/deepseek/api-key \
  -H "X-API-Key: $APP_AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_key":"sk-..."}'
```

Register an OpenAI-compatible local provider:

```bash
curl -X POST http://127.0.0.1:8012/api/v1/providers \
  -H "X-API-Key: $APP_AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "local_llm",
    "label": "Local LLM",
    "base_url": "http://host.docker.internal:1234/v1",
    "model": "local-model",
    "wire_api": "chat",
    "api_key": "local"
  }'
```

## Story Workflow

Create and start a story:

```bash
curl -X POST http://127.0.0.1:8012/api/v1/stories \
  -H "X-API-Key: $APP_AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "deepseek",
    "premise": "Write a long-form mystery about an archivist who discovers a living map.",
    "preferred_language": "en",
    "requested_chapters": 3,
    "start": true
  }'
```

Poll status:

```bash
curl -H "X-API-Key: $APP_AGENT_API_KEY" \
  http://127.0.0.1:8012/api/v1/stories/1
```

List chapters:

```bash
curl -H "X-API-Key: $APP_AGENT_API_KEY" \
  http://127.0.0.1:8012/api/v1/stories/1/chapters
```

Download the manuscript:

```bash
curl -L -H "X-API-Key: $APP_AGENT_API_KEY" \
  -o story_1.txt \
  http://127.0.0.1:8012/api/v1/stories/1/export
```

## Endpoints

- `GET /api/v1/health`
- `GET /api/v1/providers`
- `POST /api/v1/providers`
- `POST /api/v1/providers/{provider}/api-key`
- `POST /api/v1/stories`
- `GET /api/v1/stories/{story_id}`
- `POST /api/v1/stories/{story_id}/start`
- `POST /api/v1/stories/{story_id}/cancel`
- `GET /api/v1/stories/{story_id}/chapters`
- `GET /api/v1/stories/{story_id}/chapters/{chapter_no}`
- `GET /api/v1/stories/{story_id}/export`
