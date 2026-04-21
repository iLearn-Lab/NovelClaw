# NovelClaw Docker Image
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy all application code
COPY apps/ /app/apps/
COPY scripts/ /app/scripts/
COPY infra/ /app/infra/

# Install Python dependencies for all services
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install auth-portal dependencies
RUN pip install --no-cache-dir -r /app/apps/auth-portal/requirements.txt

# Install multiagent dependencies
RUN pip install --no-cache-dir -r /app/apps/multiagent/requirements.txt && \
    pip install --no-cache-dir -r /app/apps/multiagent/local_web_portal/requirements.txt

# Install novelclaw dependencies
RUN pip install --no-cache-dir -r /app/apps/novelclaw/requirements.txt && \
    pip install --no-cache-dir -r /app/apps/novelclaw/local_web_portal/requirements.txt

# Create data directories
RUN mkdir -p /app/apps/auth-portal/local_web_portal/data && \
    mkdir -p /app/apps/multiagent/local_web_portal/data && \
    mkdir -p /app/apps/novelclaw/local_web_portal/data && \
    mkdir -p /app/apps/novelclaw/local_web_portal/runs

# Expose ports
EXPOSE 8010 8011 8012

# Default command (can be overridden in docker-compose)
CMD ["python", "-m", "uvicorn", "local_web_portal.app.main:app", "--host", "0.0.0.0", "--port", "8012"]
