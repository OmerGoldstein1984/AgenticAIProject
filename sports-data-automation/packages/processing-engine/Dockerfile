# Dockerfile for Processing Engine
# =================================
# FILE HEADER
# -----------
# Business problem this file solves:
#   The processing engine (Python business logic: settlement rule engine, LLM alert client,
#   reconciliation job) needs a reproducible, minimal, secure container image that installs
#   Python dependencies, copies source, runs as a non-root user, and stays alive so `docker
#   compose up` shows it as a running service. The n8n workflows and demo scripts invoke its
#   modules directly; this image exists to make `docker compose build processing-engine`
#   succeed and to provide a Python runtime for one-off reconciliation/settlement jobs.
#
# Where it sits in the flow:
#   Build layer for the processing-engine service in docker-compose.yml.
#
# What calls it / what it calls:
#   Called by: docker-compose (processing-engine service, build context
#   ./packages/processing-engine). Calls: docker build (FROM python:3.11-slim, pip install,
#   copy source).
#
# What breaks if removed:
#   No container image for the processing engine; `docker compose build` fails on the
#   processing-engine service and the stack cannot start.
#
# Language conventions:
#   Dockerfile. Multi-concern single stage: Python deps → source → non-root user (appuser,
#   uid 1000) → keep-alive CMD.
#
# # GAP: `pip install -e ".[dev]"` installs dev tools into the image (bloat); a production
#    image would split runtime/dev. See 07_issues_found.md.
# # NOTE: canonical-types (sports_automation.types) is imported at runtime via sys.path in
#    settlement/models.py; keep the monorepo layout intact so the path resolves.

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

# Keep the container alive so `docker compose up` lists it as running. The processing
# engine is a library invoked by n8n workflows and demo scripts rather than a long-running
# server; this CMD prevents the container from exiting immediately.
CMD ["sh", "-c", "echo 'processing-engine ready'; sleep infinity"]
