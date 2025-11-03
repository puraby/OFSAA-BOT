# ---- Build stage ----
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps (add Oracle Instant Client only if you need thick mode)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Copy API source
COPY api/ /app/

# Expose FastAPI port
EXPOSE 8000

# Default envs (override in runtime)
ENV LOG_LEVEL=INFO \
    ALLOW_ORIGINS="*" \
    DEMO_MODE=1

# Healthcheck (optional)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

# Run
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]


# from repo root
docker build -t ofsaa-bot-api -f Dockerfile .
docker run --rm -p 8000:8000 --env-file .env.example ofsaa-bot-api


python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DEMO_MODE=1
uvicorn app:app --reload --port 8000


