"""
packages/ingestion-service/src/ingestion/tracing.py

FILE HEADER
-----------
Business problem this file solves:
    Distributed tracing needs a single place to generate trace IDs, propagate them across
    service boundaries (ingestion -> n8n -> processing-engine), and record simple spans so
    operators can correlate a single event's journey through the pipeline. Without it, an
    anomaly detected at settlement time cannot be traced back to the originating provider
    feed, making debugging and root-cause analysis slow.

Where it sits in the flow:
    Leaf utility module imported by ingestion-service main.py (to generate/inject trace IDs
    into forwarded payloads) and by processing-engine modules (to extract/propagate trace IDs
    from incoming payloads). Imports only stdlib (uuid, contextvars).

What calls it / what it calls:
    Called by: ingestion.main (process_* / forward_to_n8n), processing_engine settlement,
    alerts, reconciliation modules.
    Calls: nothing from this repo (only uuid, contextvars, stdlib).

What breaks if removed:
    No trace ID generation or propagation; every service generates its own unrelated IDs and
    cross-service correlation becomes impossible.

Language conventions:
    Python 3.11+. Trace IDs are UUID4 strings. Propagated as the "X-Trace-ID" HTTP header
    and as a "trace_id" field in JSON payloads. A contextvar holds the current trace ID for
    the duration of a request so span recording can attach it without threading it through
    every function signature.

GAP: OpenTelemetry integration is not wired here — this is a lightweight stdlib-based
    tracer that satisfies trace ID generation + header/JSON propagation. Swap in OpenTelemetry
    later by replacing generate_trace_id() / get_current_trace_id() with OTel equivalents.
"""

import contextvars
import uuid
from typing import Optional

# Header name used when propagating trace IDs across HTTP boundaries (ingestion -> n8n).
TRACE_ID_HEADER = "X-Trace-ID"

# Contextvar holding the trace ID for the current request/task. Defaults to None so code
# running outside a request (e.g. background workers) degrades gracefully.
_current_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_trace_id", default=None
)


def generate_trace_id() -> str:
    """Generate a new trace ID (UUID4).

    WHAT: Returns a fresh UUID4 string to use as a distributed trace ID.
    WHY: UUID4 is collision-resistant, URL-safe, and requires no coordination between
        services — each service can generate trace IDs independently.
    OUTPUTS: a UUID4 hex string (e.g. "a1b2c3d4-e5f6-7890-abcd-ef1234567890").
    """
    return str(uuid.uuid4())


def get_current_trace_id() -> Optional[str]:
    """Return the trace ID for the current request context, if any.

    WHAT: Reads the contextvar set by set_current_trace_id().
    WHY: Lets span recorders and log formatters attach the current trace ID without
        threading it through every function call.
    OUTPUTS: the current trace ID string, or None if not set.
    """
    return _current_trace_id.get()


def set_current_trace_id(trace_id: Optional[str]) -> None:
    """Set the trace ID for the current request context.

    WHAT: Stores trace_id in the contextvar for the current async context.
    WHY: Called at request ingress (e.g. from an X-Trace-ID header or a generated ID) so
        downstream code can read it via get_current_trace_id().
    INPUTS: trace_id (str or None).
    """
    _current_trace_id.set(trace_id)


def extract_trace_id_from_headers(headers: dict) -> Optional[str]:
    """Extract a trace ID from an HTTP headers dict.

    WHAT: Reads the X-Trace-ID header (case-insensitive) from a headers mapping.
    WHY: When ingestion receives a request from an upstream service (or n8n calls back into
        ingestion), the trace ID arrives as a header and must be extracted to continue the
        trace.
    INPUTS: headers (dict-like, str keys).
    OUTPUTS: the trace ID string, or None if the header is absent.
    """
    for key, value in headers.items():
        if key.lower() == TRACE_ID_HEADER.lower() and value:
            return value
    return None


def trace_id_header(trace_id: Optional[str]) -> dict:
    """Build an HTTP headers dict containing the X-Trace-ID header.

    WHAT: Returns {"X-Trace-ID": <trace_id>} if trace_id is set, otherwise {}.
    WHY: Used by forward_to_n8n to inject the trace ID into outbound webhook requests so
        n8n and downstream services can continue the trace.
    INPUTS: trace_id (str or None).
    OUTPUTS: headers dict.
    """
    if trace_id:
        return {TRACE_ID_HEADER: trace_id}
    return {}


def new_trace_context(trace_id: Optional[str] = None) -> str:
    """Generate (or accept) a trace ID, set it in the current context, and return it.

    WHAT: If trace_id is None, generates a new UUID4; either way, sets it as the current
        trace ID via set_current_trace_id() and returns it.
    WHY: Convenience entry point for request ingress — generates a fresh trace ID for each
        new top-level request, or adopts an incoming one.
    INPUTS: trace_id (optional str) — an incoming trace ID to adopt, or None to generate.
    OUTPUTS: the trace ID string in use for the current context.
    """
    tid = trace_id or generate_trace_id()
    set_current_trace_id(tid)
    return tid
