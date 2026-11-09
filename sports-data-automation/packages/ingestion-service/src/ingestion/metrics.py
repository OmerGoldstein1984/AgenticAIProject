"""
Prometheus metrics for ingestion service.

FILE HEADER
-----------
Business problem this file solves:
    You can't operate what you can't measure. The ingestion service needs to expose throughput,
    latency, error-rate, and connection metrics so Prometheus can scrape them, Grafana can
    dashboard them, and Alertmanager can page on SLA breaches (latency p95, validation error
    rate, duplicate rate). metrics.py defines all Prometheus counters/histograms/gauges plus a
    middleware that instruments every HTTP request.

Where it sits in the flow:
    Observability sidecar of the ingestion service. main.py calls setup_metrics(app) to register
    the /metrics endpoint and the metrics_middleware, and process_*/forward_to_n8n call the
    record_* helpers to instrument pipeline stages.

What calls it / what it calls:
    Called by: main.py (setup_metrics, metrics_middleware, record_* helpers).
    Calls: prometheus_client (Counter, Histogram, Gauge, Summary, CollectorRegistry, generate_latest),
    starlette BaseHTTPMiddleware, stdlib time/logging.
What breaks if removed:
    No Prometheus metrics at all — no dashboards, no alerts, no SLA visibility. The service
    runs blind.
Language conventions:
    Python 3.11+. prometheus_client with a custom CollectorRegistry (so this service's metrics
    don't collide with others). Histogram buckets tuned for sub-second to seconds latency.
BUG (pre-existing, NOT fixed): metrics_middleware() is declared `def` (not `async def`) but uses
    `await call_next(request)` — a SyntaxError ("await outside async function") that prevents the
    module from being imported, and therefore breaks the whole ingestion service. Recorded in
    07_issues_found.md; left as-is per the no-code-change rule.
"""
from prometheus_client import Counter, Histogram, Gauge, Summary, CollectorRegistry, generate_latest
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import time
import logging

logger = logging.getLogger(__name__)

# Create custom registry (avoids colliding with other services' default-registry metrics)
registry = CollectorRegistry()

# HTTP metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
    registry=registry,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    registry=registry,
)

# Ingestion metrics
events_received_total = Counter(
    "events_received_total",
    "Total events received",
    ["source", "type"],
    registry=registry,
)

events_validated_total = Counter(
    "events_validated_total",
    "Total events validated",
    ["type", "result"],
    registry=registry,
)

events_deduplicated_total = Counter(
    "events_deduplicated_total",
    "Total events deduplicated",
    ["type", "result"],
    registry=registry,
)

events_forwarded_total = Counter(
    "events_forwarded_total",
    "Total events forwarded to n8n",
    ["type", "result"],
    registry=registry,
)

processing_latency_seconds = Histogram(
    "processing_latency_seconds",
    "End-to-end processing latency",
    ["type"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=registry,
)

provider_latency_seconds = Histogram(
    "provider_latency_seconds",
    "Latency from provider to ingestion",
    ["provider", "type"],
    registry=registry,
)

active_connections = Gauge(
    "active_connections",
    "Active WebSocket connections",
    ["provider"],
    registry=registry,
)

queue_depth = Gauge(
    "queue_depth",
    "Current queue depth",
    ["queue"],
    registry=registry,
)

# n8n webhook metrics
n8n_webhook_latency_seconds = Histogram(
    "n8n_webhook_latency_seconds",
    "n8n webhook call latency",
    ["endpoint"],
    registry=registry,
)

n8n_webhook_errors_total = Counter(
    "n8n_webhook_errors_total",
    "n8n webhook errors",
    ["endpoint", "error_type"],
    registry=registry,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to collect HTTP request count and duration for every request."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        response = await call_next(request)

        duration = time.time() - start_time
        method = request.method
        endpoint = request.url.path
        status = response.status_code

        http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status=status,
        ).inc()

        http_request_duration_seconds.labels(
            method=method,
            endpoint=endpoint,
        ).observe(duration)

        return response


def metrics_middleware(request: Request, call_next):
    """Function-based middleware for metrics (alternative to the class-based one).

    # BUG: declared `def` (not `async def`) but uses `await call_next(request)` — a SyntaxError
    # ("'await' outside async function"). This prevents metrics.py from being imported, which
    # breaks `from ingestion.metrics import setup_metrics, metrics_middleware` in main.py and
    # therefore the entire ingestion service. Left unfixed per the no-code-change rule; see
    # 07_issues_found.md. To fix: change `def metrics_middleware` to `async def metrics_middleware`.
    """
    start_time = time.time()

    response = await call_next(request)

    duration = time.time() - start_time
    method = request.method
    endpoint = request.url.path
    status = response.status_code

    http_requests_total.labels(
        method=method,
        endpoint=endpoint,
        status=status,
    ).inc()

    http_request_duration_seconds.labels(
        method=method,
        endpoint=endpoint,
    ).observe(duration)

    return response


def setup_metrics(app):
    """Register the /metrics endpoint and the class-based MetricsMiddleware on the app."""
    @app.get("/metrics")
    async def metrics():
        return Response(
            content=generate_latest(registry),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    # Add middleware
    app.add_middleware(MetricsMiddleware)


def record_event_received(source: str, event_type: str):
    events_received_total.labels(source=source, type=event_type).inc()


def record_event_validated(event_type: str, valid: bool):
    events_validated_total.labels(type=event_type, result="valid" if valid else "invalid").inc()


def record_event_deduplicated(event_type: str, is_duplicate: bool):
    events_deduplicated_total.labels(
        type=event_type,
        result="duplicate" if is_duplicate else "new",
    ).inc()


def record_event_forwarded(event_type: str, success: bool):
    events_forwarded_total.labels(
        type=event_type,
        result="success" if success else "failed",
    ).inc()


def record_processing_latency(event_type: str, latency_seconds: float):
    processing_latency_seconds.labels(type=event_type).observe(latency_seconds)


def record_provider_latency(provider: str, event_type: str, latency_seconds: float):
    provider_latency_seconds.labels(provider=provider, type=event_type).observe(latency_seconds)


def set_active_connections(provider: str, count: int):
    active_connections.labels(provider=provider).set(count)


def set_queue_depth(queue: str, depth: int):
    queue_depth.labels(queue=queue).set(depth)


def record_n8n_webhook_latency(endpoint: str, latency_seconds: float):
    n8n_webhook_latency_seconds.labels(endpoint=endpoint).observe(latency_seconds)


def record_n8n_webhook_error(endpoint: str, error_type: str):
    n8n_webhook_errors_total.labels(endpoint=endpoint, error_type=error_type).inc()
