"""Main entry point for the ingestion service."""
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

# Global service instances
websocket_client: WebSocketClient | None = None
rest_poller: RESTPoller | None = None
schema_validator: SchemaValidator | None = None
canonical_transformer: CanonicalTransformer | None = None
deduplicator: Deduplicator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Metrics middleware
app.middleware("http")(metrics_middleware)

# Setup Prometheus metrics
setup_metrics(app)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
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
    """Prometheus metrics endpoint."""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/ingest/event")
async def ingest_event(request: Request):
    """Manual event ingestion endpoint."""
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
    """Handle incoming WebSocket odds message."""
    logger.debug(f"Received odds message: {message.get('eventId', 'unknown')}")
    await process_odds(message)


async def handle_event_message(message: dict):
    """Handle incoming REST event message."""
    logger.debug(f"Received event message: {message.get('id', 'unknown')}")
    await process_event(message)


async def handle_settlement_message(message: dict):
    """Handle incoming REST settlement message."""
    logger.debug(f"Received settlement message: {message.get('eventId', 'unknown')}")
    await process_settlement(message)


async def process_odds(data: dict) -> dict:
    """Process odds through validation, transformation, and deduplication."""
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
    """Process event through validation, transformation, and deduplication."""
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
    """Process settlement through validation, transformation, and deduplication."""
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
    """Forward processed data to n8n webhook."""
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
    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )