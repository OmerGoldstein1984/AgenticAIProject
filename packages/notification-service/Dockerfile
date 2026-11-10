# Dockerfile for Notification Service
# ===================================
# FILE HEADER
# -----------
# Business problem this file solves:
#   The notification service (multi-channel: email, Slack, SMS, push) needs a reproducible,
#   minimal, secure container image that installs Python dependencies, copies source, runs as a
#   non-root user, and stays alive so `docker compose up` lists it as a running service.
#
# Where it sits in the flow:
#   Build layer for the notification-service service in docker-compose.yml.
#
# What calls it / what it calls:
#   Called by: docker build (build context ./packages/notification-service). Calls: docker build
#   (FROM python:3.11-slim, pip install, copy source).
#
# What breaks if removed:
#   No container image for the notification service; the stack cannot deliver notifications.
#
# Language conventions:
#   Dockerfile. Single stage: Python deps -> source -> non-root user (appuser, uid 1000)
#   -> keep-alive CMD.
#
# # GAP: `pip install -e ".[dev]"` installs dev tools into the image (bloat); a production
#    image would split runtime/dev. See 07_issues_found.md.

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# Copy source code
COPY src/ ./src/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Keep the container alive so `docker compose up` lists it as running.
CMD ["sh", "-c", "echo 'notification-service ready'; sleep infinity"]
