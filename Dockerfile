# NovelClaw Docker Image
FROM python:3.10-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# Keep dependency installation cached when only source or templates change.
COPY apps/auth-portal/requirements.txt /app/apps/auth-portal/requirements.txt
COPY apps/multiagent/requirements.txt /app/apps/multiagent/requirements.txt
COPY apps/multiagent/local_web_portal/requirements.txt /app/apps/multiagent/local_web_portal/requirements.txt
COPY apps/novelclaw/requirements.txt /app/apps/novelclaw/requirements.txt
COPY apps/novelclaw/local_web_portal/requirements.txt /app/apps/novelclaw/local_web_portal/requirements.txt

# Install Python dependencies for all services
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

RUN pip install --no-cache-dir \
    -r /app/apps/auth-portal/requirements.txt \
    -r /app/apps/multiagent/requirements.txt \
    -r /app/apps/multiagent/local_web_portal/requirements.txt \
    -r /app/apps/novelclaw/requirements.txt \
    -r /app/apps/novelclaw/local_web_portal/requirements.txt

COPY apps/ /app/apps/
COPY scripts/ /app/scripts/
COPY infra/ /app/infra/

# Create data directories
RUN mkdir -p /app/apps/auth-portal/local_web_portal/data && \
    mkdir -p /app/apps/multiagent/local_web_portal/data && \
    mkdir -p /app/apps/multiagent/local_web_portal/runs && \
    mkdir -p /app/apps/novelclaw/local_web_portal/data && \
    mkdir -p /app/apps/novelclaw/local_web_portal/runs

# Expose ports
EXPOSE 8010 8011 8012

# Default command (can be overridden in docker-compose)
WORKDIR /app/apps/novelclaw
CMD ["python", "-m", "uvicorn", "local_web_portal.app.main:app", "--host", "0.0.0.0", "--port", "8012"]
