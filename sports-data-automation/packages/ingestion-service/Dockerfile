# Dockerfile for Ingestion Service
# ================================
# FILE HEADER
# -----------
# Business problem this file solves:
#   The ingestion service (Python/FastAPI) needs a reproducible, minimal, secure container image
#   that installs system deps (gcc, libpq-dev for psycopg/asyncpg), Python dependencies, copies
#   source, runs as a non-root user, and exposes port 8000 — so `docker compose build` yields a
#   production-like image that runs identically in dev, CI, and prod.
#
# Where it sits in the flow:
#   Build layer for the ingestion-service service in docker-compose.yml.
#
# What calls it / what it calls:
#   Called by: docker-compose (ingestion-service service, build context ./packages/ingestion-service).
#   Calls: docker build (FROM python:3.11-slim, pip install, apt-get).
#
# What breaks if removed:
#   No container image for the ingestion service; the stack can't run it.
#
# Language conventions:
#   Dockerfile. Multi-concern single stage: system deps → Python deps → source → non-root user
#   (appuser, uid 1000) → EXPOSE 8000 → CMD uvicorn.
#
# # INTERVIEW: running as non-root (appuser) is a production security practice; the CMD matches
#    docker-compose's command override (uvicorn with --reload in dev).
# # GAP: `pip install -e ".[dev]"`` installs dev tools (pytest, mypy, ruff) into the image,
#    bloating it; a production image would split runtime/dev. See 07_issues_found.md.
#

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# Copy source code
COPY src/ ./src/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Run
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]