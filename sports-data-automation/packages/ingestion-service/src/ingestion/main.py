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

What calls it / what it calls:
    Called by: uvicorn (docker-compose / CMD); tests (import app).
    Calls: ingestion.config.get_settings; providers.websocket_client.WebSocketClient;
    providers.rest_poller.RESTPoller; normalization.schema_validator.SchemaValidator;
    normalization.canonical_transformer.CanonicalTransformer; idempotency.deduplicator.Deduplicator;
    ingestion.metrics (setup_metrics, metrics_middleware); n8n webhook via httpx.
What breaks if removed:
    The entire ingestion service — no validation, normalization, dedup, or forwarding to n8n.
    This is the single entry point; nothing else substitutes for it.
Language conventions:
    Python 3.11+. FastAPI with lifespan context manager, async/await throughout, httpx for
    outbound webhooks, logging via stdlib. Prometheus metrics exposed at /metrics.
GAP: forward_to_n8n swallows exceptions ("In production, send to dead letter queue") — a
    n8n outage silently drops data. See 07_issues_found.md. Also, metrics.py's metrics_middleware
    uses await in a non-async function (syntax error) — see 07_issues_found.md.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import logging
import os

from ingestion.config import get_settings
from ingestion.providers.websocket_client import WebSocketClient
from ingestion.providers.rest_poller import RESTPoller
from ingestion.normalization.schema_validator import SchemaValidator
from ingestion.normalization.canonical_transformer import CanonicalTransformer
from ingestion.idempotency.deduplicator import Deduplicator
from ingestion.metrics import setup_metrics, metrics_middleware

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
    global websocket_client, rest_poller, schema_validator, canonical_transformer, deduplicator

    settings = get_settings()

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

    # WebSocket client for live odds
    websocket_client = WebSocketClient(
        url=settings.odds_feed_ws_url,
        on_message=handle_odds_message,
        reconnect_interval=settings.ws_reconnect_interval,
    )
    await websocket_client.connect()

    # REST pollers for event and settlement feeds
    rest_poller = RESTPoller(
        endpoints=settings.rest_endpoints,
        poll_interval=settings.rest_poll_interval,
        on_event=handle_event_message,
        on_settlement=handle_settlement_message,
    )
    await rest_poller.start()

    logger.info("Ingestion service started")

    yield

    # Cleanup
    logger.info("Shutting down ingestion service...")
    if websocket_client:
        await websocket_client.disconnect()
    if rest_poller:
        await rest_poller.stop()
    if deduplicator:
        await deduplicator.disconnect()
    logger.info("Ingestion service stopped")


app = FastAPI(
    title="Sports Data Ingestion Service",
    description="Normalizes, validates, and deduplicates sports data feeds",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow cross-origin calls (dev-friendly; tighten origins in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Metrics middleware (records HTTP request count + duration for every request)
app.middleware("http")(metrics_middleware)

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


@app.post("/ingest/event")
async def ingest_event(request: Request):
    """Manual event ingestion endpoint (used for demos / testing)."""
    try:
        data = await request.json()
        result = await process_event(data)
        return {"status": "accepted", "result": result}
    except Exception as e:
        logger.exception("Error ingesting event")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/ingest/odds")
async def ingest_odds(request: Request):
    """Manual odds ingestion endpoint."""
    try:
        data = await request.json()
        result = await process_odds(data)
        return {"status": "accepted", "result": result}
    except Exception as e:
        logger.exception("Error ingesting odds")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/ingest/settlement")
async def ingest_settlement(request: Request):
    """Manual settlement ingestion endpoint."""
    try:
        data = await request.json()
        result = await process_settlement(data)
        return {"status": "accepted", "result": result}
    except Exception as e:
        logger.exception("Error ingesting settlement")
        return JSONResponse(status_code=500, content={"error": str(e)})


async def handle_odds_message(message: dict):
    """Callback invoked by WebSocketClient for each incoming odds message."""
    logger.debug(f"Received odds message: {message.get('eventId', 'unknown')}")
    await process_odds(message)


async def handle_event_message(message: dict):
    """Callback invoked by RESTPoller for each fetched event."""
    logger.debug(f"Received event message: {message.get('id', 'unknown')}")
    await process_event(message)


async def handle_settlement_message(message: dict):
    """Callback invoked by RESTPoller for each fetched settlement."""
    logger.debug(f"Received settlement message: {message.get('eventId', 'unknown')}")
    await process_settlement(message)


async def process_odds(data: dict) -> dict:
    """Run one odds item through validate → transform → deduplicate → forward.

    WHAT: Validates against the "odds" schema, transforms to canonical odds, dedups on
        odds:{providerId}:{eventId}:{sequence}, then forwards to n8n. Returns a status dict.
    WHY: This is the core per-item pipeline for the highest-volume feed. Each stage is a gate:
        invalid data is rejected, duplicates are dropped, only clean canonical odds reach n8n.
    INPUTS: data (raw provider odds dict).
    OUTPUTS: dict with status in {"processed","rejected","duplicate"} plus eventId/reason/errors.
    SIDE EFFECTS: writes to Redis (dedup), calls schema_validator/canonical_transformer,
        forwards an HTTP webhook to n8n.
    FAILURE MODES: n8n forward failure is logged and swallowed (data dropped — see GAP).
    ALTERNATIVE: enqueue to a reliable queue (Redis Streams/Kafka) instead of a direct webhook,
        so a n8n outage doesn't lose data. Chosen direct webhook for simplicity in this project.
    # GAP: forward_to_n8n catches all exceptions and just logs — no dead-letter queue, no retry.
    #    A n8n outage loses odds. See 07_issues_found.md.
    # BUSINESS: odds feed every 500ms-2s; losing a price update means a stale market and
    #    potential trading loss.
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

    # Deduplicate
    if deduplicator:
        is_duplicate = await deduplicator.check_and_store(
            f"odds:{canonical.get('providerId')}:{canonical.get('eventId')}:{canonical.get('sequence')}"
        )
        if is_duplicate:
            return {"status": "duplicate", "eventId": canonical.get('eventId')}

    # Forward to n8n webhook
    await forward_to_n8n("odds", canonical)

    return {"status": "processed", "eventId": canonical.get('eventId')}


async def process_event(data: dict) -> dict:
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

    # Deduplicate
    if deduplicator:
        is_duplicate = await deduplicator.check_and_store(
            f"event:{canonical.get('id')}:{canonical.get('sequence', 0)}"
        )
        if is_duplicate:
            return {"status": "duplicate", "eventId": canonical.get('id')}

    # Forward to n8n webhook
    await forward_to_n8n("event", canonical)

    return {"status": "processed", "eventId": canonical.get('id')}


async def process_settlement(data: dict) -> dict:
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

    # Deduplicate
    if deduplicator:
        is_duplicate = await deduplicator.check_and_store(
            f"settlement:{canonical.get('eventId')}:{canonical.get('marketId')}:{canonical.get('selectionId')}"
        )
        if is_duplicate:
            return {"status": "duplicate", "eventId": canonical.get('eventId')}

    # Forward to n8n webhook
    await forward_to_n8n("settlement", canonical)

    return {"status": "processed", "eventId": canonical.get('eventId')}


async def forward_to_n8n(data_type: str, data: dict):
    """POST the canonical payload to the n8n webhook for this data type.

    WHAT: httpx.AsyncClient POST to {n8n_webhook_url}/{data_type} with a 10s timeout.
    WHY: n8n is the orchestration layer — once data is validated/normalized/deduped here, it's
        handed to n8n for event routing, odds normalization, settlement, and alerting.
    INPUTS: data_type ("odds"|"event"|"settlement"), data (canonical dict).
    OUTPUTS: None.
    SIDE EFFECTS: makes an outbound HTTP request to n8n.
    FAILURE MODES: any exception (n8n down, timeout, DNS) is caught, logged, and swallowed —
        data is silently dropped (see GAP).
    ALTERNATIVE: push to Redis Streams with a dead-letter queue and retry, so n8n outages
        don't lose data. Chosen direct webhook for simplicity.
    # GAP: no dead-letter queue or retry — a n8n outage loses every event forwarded in that
    #    window. See 07_issues_found.md.
    """
    settings = get_settings()
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.n8n_webhook_url}/{data_type}",
                json=data,
                headers={"Content-Type": "application/json"},
            )
    except Exception as e:
        logger.error(f"Failed to forward to n8n: {e}")
        # In production, send to dead letter queue


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
