"""Main entry point for the ingestion service.

FILE HEADER
-----------
Business problem this file solves:
    The ingestion service is the gateway between raw provider feeds (WebSocket odds, REST
    events/settlements) and the downstream n8n orchestration layer. It must accept data from
    multiple providers, validate it, normalize it to the canonical schema, deduplicate it, and
    forward it to n8n — all while emitting metrics, staying up under load, and never losing or
    duplicating data. main.py wires all of that together as a FastAPI application.

Where it sits in the flow:
    The central INGESTION SERVICE (stage 2 of the pipeline, after mock providers, before n8n).
    lifespan() constructs and starts SchemaValidator, CanonicalTransformer, Deduplicator,
    WebSocketClient, and RESTPoller; HTTP endpoints /ingest/{event,odds,settlement} allow
    manual injection; process_* functions run validate → transform → deduplicate → forward.
    n8n forwarding (retry + dead-letter queue + trace ID propagation) is delegated to
    ingestion.n8n_forwarder.N8nForwarder.

What calls it / what it calls:
    Called by: uvicorn (docker-compose / CMD); tests (import app).
    Calls: ingestion.config.get_settings; providers.websocket_client.WebSocketClient;
    providers.rest_poller.RESTPoller; normalization.schema_validator.SchemaValidator;
    normalization.canonical_transformer.CanonicalTransformer; idempotency.deduplicator.Deduplicator;
    ingestion.metrics (setup_metrics, metrics_middleware); ingestion.n8n_forwarder (n8n webhook
    forwarding with retry + DLQ).
What breaks if removed:
    The entire ingestion service — no validation, normalization, dedup, or forwarding to n8n.
    This is the single entry point; nothing else substitutes for it.
Language conventions:
    Python 3.11+. FastAPI with lifespan context manager, async/await throughout, httpx for
    outbound webhooks (via n8n_forwarder), logging via stdlib. Prometheus metrics exposed at
    /metrics.
GAP: metrics.py's metrics_middleware uses await in a non-async function (syntax error) — see
    07_issues_found.md.
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Depends, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
import redis.asyncio as redis
import uvicorn

from ingestion.config import get_settings
from ingestion.n8n_forwarder import N8nForwarder
from ingestion.providers.registry import ProviderRegistry
from ingestion.providers.websocket_client import WebSocketClient
from ingestion.providers.rest_poller import RESTPoller
from ingestion.normalization.schema_validator import SchemaValidator
from ingestion.normalization.canonical_transformer import CanonicalTransformer
from ingestion.idempotency.deduplicator import Deduplicator
from ingestion.metrics import setup_metrics, metrics_middleware
from ingestion.security import RateLimiter, SecurityHeadersMiddleware, rate_limit_middleware, log_auth_failure
from ingestion.tracing import extract_trace_id_from_headers, new_trace_context, trace_id_header

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global service instances — set in lifespan(), read by process_* functions
websocket_client: WebSocketClient | None = None
rest_poller: RESTPoller | None = None
schema_validator: SchemaValidator | None = None
canonical_transformer: CanonicalTransformer | None = None
deduplicator: Deduplicator | None = None
n8n_forwarder: Optional[N8nForwarder] = None
rate_limiter: Optional[RateLimiter] = None

# API key header for /ingest/* authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(request: Request, api_key: str | None = Security(api_key_header)):
    """Require X-API-Key on /ingest/* endpoints when ingestion_api_key is configured.

    Health and metrics endpoints remain unauthenticated. If no API key is configured
    (empty setting), the check is skipped (fail-open/dev-friendly). Failed attempts
    are recorded in the security audit log.
    """
    settings = get_settings()
    if not settings.ingestion_api_key:
        return
    if api_key is None or api_key != settings.ingestion_api_key:
        log_auth_failure(api_key, request.url.path, reason="missing_or_invalid_api_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager: startup → yield → shutdown.

    WHAT: On startup, reads settings, constructs SchemaValidator (loads schemas),
        CanonicalTransformer, Deduplicator (connects to Redis), WebSocketClient (connects to the
        odds feed), and RESTPoller (starts polling event/settlement endpoints). On shutdown,
        disconnects them in reverse order.
    WHY: FastAPI lifespan guarantees resources are initialized before the app accepts traffic
        and released cleanly on `docker compose down`/reload.
    INPUTS: app (the FastAPI instance).
    OUTPUTS: yields control to the app; nothing returned.
    SIDE EFFECTS: sets the module-level global service instances; opens Redis, WebSocket, and
        HTTP-poller connections.
    FAILURE MODES: if Redis is down, Deduplicator.connect() re-raises and lifespan aborts
        startup (fail-fast — better than accepting traffic with no dedup).
    ALTERNATIVE: initialize each component lazily on first request. Chosen eager startup so
        configuration errors surface immediately at deploy time, not mid-traffic.
    # INTERVIEW: lifespan is the modern FastAPI replacement for @app.on_event("startup") /
    #    ("shutdown"); it guarantees setup/teardown pairing.
    """
    global websocket_client, rest_poller, schema_validator, canonical_transformer, deduplicator, n8n_forwarder

    settings = get_settings()

    # Rate limiter for write endpoints (/ingest/*, /dlq/*). None when disabled.
    global rate_limiter
    if settings.rate_limit_enabled:
        rate_limiter = RateLimiter(
            requests_per_minute=settings.rate_limit_requests_per_minute,
            burst=settings.rate_limit_burst,
            anonymous_requests_per_minute=settings.rate_limit_anonymous_per_minute,
            anonymous_burst=settings.rate_limit_anonymous_burst,
        )
        logger.info(
            "Rate limiter enabled: %d rpm/%d burst (auth), %d rpm/%d burst (anonymous)",
            settings.rate_limit_requests_per_minute,
            settings.rate_limit_burst,
            settings.rate_limit_anonymous_per_minute,
            settings.rate_limit_anonymous_burst,
        )
    else:
        rate_limiter = None
        logger.info("Rate limiter disabled")

    # Initialize services
    logger.info("Initializing ingestion service...")

    # Schema validator
    schema_validator = SchemaValidator(settings.schema_registry_path)
    await schema_validator.load_schemas()

    # Canonical transformer
    canonical_transformer = CanonicalTransformer()

    # Deduplicator
    deduplicator = Deduplicator(
        redis_url=settings.redis_url,
        ttl_seconds=settings.deduplication_ttl_seconds,
    )
    await deduplicator.connect()

    # Provider registry (replaces hard-coded rest_endpoints / odds_feed_ws_url).
    # Falls back to Settings.rest_endpoints if the registry is disabled or fails to load.
    registry: ProviderRegistry | None = None
    if settings.provider_registry_enabled:
        try:
            registry = ProviderRegistry(
                config_path=settings.providers_config_path,
                enabled=True,
            )
            await registry.start(
                on_event=handle_event_message,
                on_settlement=handle_settlement_message,
                on_message=handle_odds_message,
                poll_interval=settings.rest_poll_interval,
                reconnect_interval=settings.ws_reconnect_interval,
            )
            websocket_clients = registry.get_websocket_clients()
            websocket_client = websocket_clients[0] if websocket_clients else None
            rest_pollers = registry.get_rest_pollers()
            rest_poller = rest_pollers[0] if rest_pollers else None
        except Exception as e:
            logger.error(f"Provider registry failed, falling back to rest_endpoints: {e}")
            registry = None

    if registry is None:
        # WebSocket client for live odds (fallback)
        websocket_client = WebSocketClient(
            url=settings.odds_feed_ws_url,
            on_message=handle_odds_message,
            reconnect_interval=settings.ws_reconnect_interval,
        )
        await websocket_client.connect()

        # REST pollers for event and settlement feeds (fallback)
        rest_poller = RESTPoller(
            endpoints=settings.rest_endpoints,
            poll_interval=settings.rest_poll_interval,
            on_event=handle_event_message,
            on_settlement=handle_settlement_message,
        )
        await rest_poller.start()

    # DLQ Redis client + n8n forwarder (dead letter queue for failed n8n forwards — fail-open)
    try:
        dlq_redis = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        await dlq_redis.ping()
        n8n_forwarder = N8nForwarder(dlq_redis=dlq_redis)
        logger.info(f"DLQ Redis connected: {settings.redis_url}")
    except Exception as e:
        logger.error(f"Failed to connect DLQ Redis: {e}")
        n8n_forwarder = N8nForwarder(dlq_redis=None)

    logger.info("Ingestion service started")

    yield

    # Cleanup
    logger.info("Shutting down ingestion service...")
    if registry:
        await registry.stop()
    else:
        if websocket_client:
            await websocket_client.disconnect()
        if rest_poller:
            await rest_poller.stop()
    if deduplicator:
        await deduplicator.disconnect()
    if n8n_forwarder and n8n_forwarder.dlq_redis:
        await n8n_forwarder.dlq_redis.close()
    logger.info("Ingestion service stopped")


app = FastAPI(
    title="Sports Data Ingestion Service",
    description="Normalizes, validates, and deduplicates sports data feeds",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allowed origins from settings (tightened from ["*"]); regex covers localhost dev ports
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Metrics middleware (records HTTP request count + duration for every request)
app.middleware("http")(metrics_middleware)

# Security response headers on every response (CORS already configured above).
app.add_middleware(
    SecurityHeadersMiddleware,
    enabled=settings.security_headers_enabled,
    hsts_enabled=settings.hsts_enabled,
    hsts_max_age=settings.hsts_max_age,
)

# Rate limiting + request body size guard on write endpoints (/ingest/*, /dlq/*).
@app.middleware("http")
async def security_request_middleware(request: Request, call_next):
    return await rate_limit_middleware(
        request,
        call_next,
        rate_limiter,
        enabled=settings.rate_limit_enabled,
        max_body_size=settings.max_request_body_size,
    )

# Setup Prometheus metrics endpoint at /metrics
setup_metrics(app)


@app.get("/health")
async def health_check():
    """Health check endpoint reporting whether each sub-service is connected/running."""
    return {
        "status": "healthy",
        "services": {
            "websocket": websocket_client.is_connected if websocket_client else False,
            "rest_poller": rest_poller.is_running if rest_poller else False,
            "redis": deduplicator.is_connected if deduplicator else False,
        },
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint (scraped by Prometheus)."""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/ingest/event", dependencies=[Depends(verify_api_key)])
async def ingest_event(request: Request):
    """Manual event ingestion endpoint (used for demos / testing)."""
    try:
        data = await request.json()
        trace_id = extract_trace_id_from_headers(request.headers) or new_trace_context()
        result = await process_event(data, trace_id)
        return {"status": "accepted", "result": result, "trace_id": trace_id}
    except Exception as e:
        logger.exception("Error ingesting event")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/ingest/odds", dependencies=[Depends(verify_api_key)])
async def ingest_odds(request: Request):
    """Manual odds ingestion endpoint."""
    try:
        data = await request.json()
        trace_id = extract_trace_id_from_headers(request.headers) or new_trace_context()
        result = await process_odds(data, trace_id)
        return {"status": "accepted", "result": result, "trace_id": trace_id}
    except Exception as e:
        logger.exception("Error ingesting odds")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/ingest/settlement", dependencies=[Depends(verify_api_key)])
async def ingest_settlement(request: Request):
    """Manual settlement ingestion endpoint."""
    try:
        data = await request.json()
        trace_id = extract_trace_id_from_headers(request.headers) or new_trace_context()
        result = await process_settlement(data, trace_id)
        return {"status": "accepted", "result": result, "trace_id": trace_id}
    except Exception as e:
        logger.exception("Error ingesting settlement")
        return JSONResponse(status_code=500, content={"error": str(e)})


async def handle_odds_message(message: dict):
    """Callback invoked by WebSocketClient for each incoming odds message."""
    logger.debug(f"Received odds message: {message.get('eventId', 'unknown')}")
    trace_id = new_trace_context()
    await process_odds(message, trace_id)


async def handle_event_message(message: dict):
    """Callback invoked by RESTPoller for each fetched event."""
    logger.debug(f"Received event message: {message.get('id', 'unknown')}")
    trace_id = new_trace_context()
    await process_event(message, trace_id)


async def handle_settlement_message(message: dict):
    """Callback invoked by RESTPoller for each fetched settlement."""
    logger.debug(f"Received settlement message: {message.get('eventId', 'unknown')}")
    trace_id = new_trace_context()
    await process_settlement(message, trace_id)


async def process_odds(data: dict, trace_id: Optional[str] = None) -> dict:
    """Run one odds item through validate → transform → deduplicate → forward.

    WHAT: Validates against the "odds" schema, transforms to canonical odds, dedups on
        odds:{providerId}:{eventId}:{sequence}, then forwards to n8n. Returns a status dict.
    WHY: This is the core per-item pipeline for the highest-volume feed. Each stage is a gate:
        invalid data is rejected, duplicates are dropped, only clean canonical odds reach n8n.
    INPUTS: data (raw provider odds dict), trace_id (optional distributed trace ID).
    OUTPUTS: dict with status in {"processed","rejected","duplicate"} plus eventId/reason/errors/trace_id.
    SIDE EFFECTS: writes to Redis (dedup), calls schema_validator/canonical_transformer,
        forwards an HTTP webhook to n8n with X-Trace-ID header.
    FAILURE MODES: n8n forward failure is retried then DLQ'd (no silent drop).
    ALTERNATIVE: enqueue to a reliable queue (Redis Streams/Kafka) instead of a direct webhook,
        so a n8n outage doesn't lose data. Chosen direct webhook with DLQ for this project.
    """
    settings = get_settings()

    # Validate
    if schema_validator:
        valid, errors = schema_validator.validate("odds", data)
        if not valid:
            return {"status": "rejected", "reason": "validation_failed", "errors": errors}

    # Transform to canonical format
    if canonical_transformer:
        canonical = canonical_transformer.transform_odds(data)
    else:
        canonical = data

    # Inject trace ID into canonical payload for end-to-end propagation
    canonical["trace_id"] = trace_id

    # Deduplicate
    if deduplicator:
        is_duplicate = await deduplicator.check_and_store(
            f"odds:{canonical.get('providerId')}:{canonical.get('eventId')}:{canonical.get('sequence')}"
        )
        if is_duplicate:
            return {"status": "duplicate", "eventId": canonical.get('eventId'), "trace_id": trace_id}

    # Forward to n8n webhook
    await n8n_forwarder.forward_to_n8n("odds", canonical, trace_id)

    return {"status": "processed", "eventId": canonical.get('eventId'), "trace_id": trace_id}


async def process_event(data: dict, trace_id: Optional[str] = None) -> dict:
    """Run one event item through validate → transform → deduplicate → forward."""
    settings = get_settings()

    # Validate
    if schema_validator:
        valid, errors = schema_validator.validate("event", data)
        if not valid:
            return {"status": "rejected", "reason": "validation_failed", "errors": errors}

    # Transform to canonical format
    if canonical_transformer:
        canonical = canonical_transformer.transform_event(data)
    else:
        canonical = data

    # Inject trace ID into canonical payload for end-to-end propagation
    canonical["trace_id"] = trace_id

    # Deduplicate
    if deduplicator:
        is_duplicate = await deduplicator.check_and_store(
            f"event:{canonical.get('id')}:{canonical.get('sequence', 0)}"
        )
        if is_duplicate:
            return {"status": "duplicate", "eventId": canonical.get('id'), "trace_id": trace_id}

    # Forward to n8n webhook
    await n8n_forwarder.forward_to_n8n("event", canonical, trace_id)

    return {"status": "processed", "eventId": canonical.get('id'), "trace_id": trace_id}


async def process_settlement(data: dict, trace_id: Optional[str] = None) -> dict:
    """Run one settlement item through validate → transform → deduplicate → forward."""
    settings = get_settings()

    # Validate
    if schema_validator:
        valid, errors = schema_validator.validate("settlement", data)
        if not valid:
            return {"status": "rejected", "reason": "validation_failed", "errors": errors}

    # Transform to canonical format
    if canonical_transformer:
        canonical = canonical_transformer.transform_settlement(data)
    else:
        canonical = data

    # Inject trace ID into canonical payload for end-to-end propagation
    canonical["trace_id"] = trace_id

    # Deduplicate
    if deduplicator:
        is_duplicate = await deduplicator.check_and_store(
            f"settlement:{canonical.get('eventId')}:{canonical.get('marketId')}:{canonical.get('selectionId')}"
        )
        if is_duplicate:
            return {"status": "duplicate", "eventId": canonical.get('eventId'), "trace_id": trace_id}

    # Forward to n8n webhook
    await n8n_forwarder.forward_to_n8n("settlement", canonical, trace_id)

    return {"status": "processed", "eventId": canonical.get('eventId'), "trace_id": trace_id}


@app.post("/dlq/retry")
async def retry_dlq(data_type: str):
    """Reprocess items from the dead-letter queue for a given data type.

    WHAT: POST /dlq/retry?data_type=odds pops items from dlq:n8n:{data_type} and re-forwards
        each to n8n. Successfully reprocessed items are consumed; a failing item is put back
        and the retry stops (poison-message protection).
    WHY: Provides an operational escape hatch to recover data after a n8n outage.
    INPUTS: data_type (query param, e.g. "odds"|"event"|"settlement").
    OUTPUTS: {status, reprocessed, data_type}.
    SIDE EFFECTS: pops from Redis DLQ, re-forwards to n8n, may re-push on failure.
    FAILURE MODES: DLQ unavailable -> 503.
    """
    return await n8n_forwarder.retry_dlq(data_type)


if __name__ == "__main__":
    """Allow `python -m ingestion.main` or `python src/main.py` to run the service directly."""
    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
