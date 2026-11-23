FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent ./agent
COPY api ./api
COPY tools ./tools

# Fetch the model files LiveKit needs at build time so the first call is not slow.
# Not fatal if it fails: they are downloaded on first use instead.
RUN python -m agent.agent download-files || true

# The command comes from docker-compose.yml (one image runs both the web page and the agent).
