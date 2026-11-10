"""n8n webhook forwarding with retry, dead-letter queue, and trace propagation.

FILE HEADER
-----------
Business problem this file solves:
    Forwarding validated, normalized, deduplicated payloads to the n8n orchestration layer
    must be reliable: a n8n outage must not lose data, and every forwarded request carries
    the trace ID for distributed tracing. This module handles HTTP forwarding with
    exponential-backoff retry and a Redis dead-letter queue, plus an operational retry
    endpoint for recovering DLQ items after an outage.

Where it sits in the flow:
    The N8nForwarder is constructed in ingestion.main lifespan() with the DLQ Redis client
    and called by process_odds/process_event/process_settlement after dedup. The /dlq/retry
    endpoint delegates to it for operational recovery.

What calls it / what it calls:
    Called by: ingestion.main (process_* pipeline, /dlq/retry endpoint).
    Calls: ingestion.config.get_settings, ingestion.tracing.trace_id_header, httpx, redis.

What breaks if removed:
    n8n forwarding — validated data would not reach the orchestration layer, and there would
    be no retry/DLQ safety net for n8n outages.

Language conventions:
    Python 3.11+. async/await throughout, httpx for outbound webhooks, logging via stdlib.
    Fail-open: if the DLQ Redis client is unavailable, errors are logged and data is dropped
    rather than crashing.
"""
import asyncio
import json
import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, status

from ingestion.config import get_settings
from ingestion.tracing import trace_id_header

logger = logging.getLogger(__name__)


class N8nForwarder:
    """POST canonical payloads to n8n with retry, DLQ fail-open, and trace ID propagation.

    WHAT: Retries failed forwards with exponential backoff up to n8n_max_retries attempts,
        then writes to the Redis DLQ (dlq:n8n:{data_type}) on exhaustion. Provides a retry
        method to reprocess DLQ items after an outage.
    WHY: A n8n outage must not lose data; every forwarded request carries the trace ID so
        n8n and downstream services can continue the distributed trace.
    """

    def __init__(self, dlq_redis: Optional[Any] = None):
        self.dlq_redis = dlq_redis
        self.settings = get_settings()

    async def forward_to_n8n(
        self, data_type: str, data: Dict[str, Any], trace_id: Optional[str] = None
    ) -> None:
        """POST the canonical payload to the n8n webhook for this data type.

        Retries with exponential backoff up to n8n_max_retries attempts. On total failure,
        writes the payload to the dead-letter queue instead of silently dropping data.
        """
        headers = {"Content-Type": "application/json"}
        headers.update(trace_id_header(trace_id))

        last_error = None
        for attempt in range(self.settings.n8n_max_retries):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        f"{self.settings.n8n_webhook_url}/{data_type}",
                        json=data,
                        headers=headers,
                    )
                return  # success
            except Exception as e:
                last_error = e
                if attempt < self.settings.n8n_max_retries - 1:
                    await asyncio.sleep(self.settings.n8n_retry_backoff * (2 ** attempt))

        # All retries exhausted — dead letter queue
        await self._write_to_dlq(data_type, data, last_error)

    async def _write_to_dlq(
        self, data_type: str, data: Dict[str, Any], error: Exception
    ) -> None:
        """Write a failed forward to the DLQ Redis list (fail-open: log if unavailable)."""
        if self.dlq_redis is None:
            logger.error(f"DLQ unavailable, dropping {data_type}: {error}")
            return
        try:
            key = f"{self.settings.dlq_redis_key_prefix}{data_type}"
            payload = json.dumps(
                {"data": data, "error": str(error), "data_type": data_type}
            )
            await self.dlq_redis.rpush(key, payload)
            logger.warning(
                f"Wrote {data_type} to DLQ {key} after retries exhausted: {error}"
            )
        except Exception as e:
            logger.error(f"Failed to write to DLQ for {data_type}: {e}")

    async def retry_dlq(self, data_type: str) -> Dict[str, Any]:
        """Reprocess items from the dead-letter queue for a given data type.

        WHAT: Pops items from dlq:n8n:{data_type} and re-forwards each to n8n. Successfully
            reprocessed items are consumed; a failing item is put back and the retry stops
            (poison-message protection).
        WHY: Provides an operational escape hatch to recover data after a n8n outage.
        INPUTS: data_type (query param, e.g. "odds"|"event"|"settlement").
        OUTPUTS: {status, reprocessed, data_type}.
        SIDE EFFECTS: pops from Redis DLQ, re-forwards to n8n, may re-push on failure.
        FAILURE MODES: DLQ unavailable -> 503.
        """
        if self.dlq_redis is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DLQ unavailable"
            )
        key = f"{self.settings.dlq_redis_key_prefix}{data_type}"
        reprocessed = 0
        max_items = 100
        while reprocessed < max_items:
            raw = await self.dlq_redis.lpop(key)
            if raw is None:
                break
            try:
                payload = json.loads(raw)
                item_data = (
                    payload.get("data", payload)
                    if isinstance(payload, dict)
                    else raw
                )
                await self.forward_to_n8n(
                    data_type,
                    item_data,
                    item_data.get("trace_id") if isinstance(item_data, dict) else None,
                )
                reprocessed += 1
            except Exception as e:
                # Put it back and stop — don't loop forever on a poison message
                await self.dlq_redis.rpush(key, raw)
                logger.error(f"DLQ retry failed for {data_type}: {e}")
                break
        return {"status": "ok", "reprocessed": reprocessed, "data_type": data_type}
