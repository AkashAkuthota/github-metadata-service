# Multi-stage build — keeps the final image lean.
FROM python:3.11-slim AS base

WORKDIR /app

# System deps needed to compile asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies before copying source so that the layer
# is cached as long as pyproject.toml hasn't changed.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

# Copy application source
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY app/ ./app/

# Run as a non-root user — standard security practice for containers.
# The user is created here so the /app directory (owned by root during
# build) is readable, and all runtime writes go to files the app owns.
RUN adduser --disabled-password --gecos "" appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
