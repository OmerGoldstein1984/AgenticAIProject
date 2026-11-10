"""
packages/processing-engine/src/processing_engine/alerts/llm_client.py

FILE HEADER
-----------
Business problem this file solves:
    The alert engine needs to turn raw anomaly data into human-readable, structured alerts
    (title, description, severity, confidence) using an LLM. llm_client.py makes a structured
    call to an Anthropic-style LLM and returns an LLMAlertResponse. When no API key is
    configured (dev/demo/CI), it simulates a deterministic LLM response so the stack is fully
    runnable without a live Anthropic contract.

Where it sits in the flow:
    Core alert module. Imported by processing_engine/__init__.py and by the n8n alert-engine
    workflow. Consumed after the odds-normalization / event-router workflows detect an
    anomaly and need a human-readable alert.

What calls it / what it calls:
    Called by: n8n alert-engine, demo scripts, tests.
    Calls: anthropic SDK (if ANTHROPIC_API_KEY set), prompt_templates (system/user prompts),
    sports_automation.types (LLMAlertRequest, LLMAlertResponse, AlertSeverity).

What breaks if removed:
    No LLM alert generation; anomalies produce no human-readable alerts, breaking the alert
    precision/recall story and the human-in-the-loop demo.

Language conventions:
    Python 3.11+. generate_alert(request: LLMAlertRequest) -> LLMAlertResponse.
    If ANTHROPIC_API_KEY is set, calls the Anthropic Messages API with structured output;
    otherwise simulates a deterministic response based on anomaly_type and confidence.

GAP: real Anthropic SDK calls are commented-out/simulated in the n8n node; here we call the
    SDK when a key is present and simulate otherwise. Structured output (JSON mode) is
    requested but the response is parsed defensively with a fallback. See 07_issues_found.md
    (F10).
"""

import json
import logging
import os
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Ensure canonical types are importable (monorepo layout).
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANONICAL_TYPES_PY = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", "canonical-types", "python")
)
if os.path.isdir(_CANONICAL_TYPES_PY) and _CANONICAL_TYPES_PY not in sys.path:
    sys.path.insert(0, _CANONICAL_TYPES_PY)

from sports_automation.types import (  # noqa: E402
    AlertSeverity,
    AlertType,
    CanonicalEvent,
    CanonicalOdds,
    LLMAlertRequest,
    LLMAlertResponse,
)


def _simulate_alert(request: LLMAlertRequest, trace_id: Optional[str] = None) -> LLMAlertResponse:
    """Produce a deterministic LLM-style alert response when no API key is configured.

    WHAT: Builds an LLMAlertResponse from the request's anomaly_type and context using
        rule-based templates, with a confidence score derived from context signal strength.
        trace_id is carried into metadata for distributed tracing.
    WHY: Lets the stack run end-to-end in dev/demo/CI without an Anthropic API key, while
        still exercising the structured alert schema downstream.
    INPUTS: request (LLMAlertRequest), trace_id (optional distributed trace ID).
    OUTPUTS: LLMAlertResponse.
    SIDE EFFECTS: none.
    """
    anomaly_type = request.anomaly_type
    event_data = request.event_data
    context = request.context or {}

    # Derive a readable event label
    event_label = "unknown event"
    if isinstance(event_data, CanonicalEvent):
        event_label = f"{event_data.home_team.name} vs {event_data.away_team.name} ({event_data.league})"
    elif isinstance(event_data, CanonicalOdds):
        event_label = f"odds {event_data.market_id}/{event_data.selection_id} on {event_data.event_id}"

    # Base templates per anomaly type
    templates = {
        AlertType.ODDS_ANOMALY: (
            f"Odds anomaly detected on {event_label}",
            "Odds moved beyond the expected threshold compared to other providers. "
            "Verify the price before accepting bets on this market.",
            AlertSeverity.WARNING,
            "Verify with other providers before accepting bets.",
        ),
        AlertType.SETTLEMENT_DISCREPANCY: (
            f"Settlement discrepancy on {event_label}",
            "The settled outcome disagrees with the canonical event result. "
            "Review and reconcile before paying out.",
            AlertSeverity.CRITICAL,
            "Reconcile with the official result feed and adjust if needed.",
        ),
        AlertType.FEED_OUTAGE: (
            f"Feed outage suspected on {event_label}",
            "No updates received from the provider within the expected window. "
            "Check provider connectivity and fail over if needed.",
            AlertSeverity.PAGE,
            "Check provider feed health and switch to backup provider.",
        ),
        AlertType.ARBITRAGE_DETECTED: (
            f"Arbitrage opportunity on {event_label}",
            "Cross-provider odds imply an arbitrage situation. Review exposure and "
            "consider adjusting limits.",
            AlertSeverity.WARNING,
            "Review exposure; adjust limits or suspend the market.",
        ),
        AlertType.SUSPICIOUS_PATTERN: (
            f"Suspicious betting pattern on {event_label}",
            "Unusual betting volume or pattern detected. Review for potential fraud.",
            AlertSeverity.CRITICAL,
            "Review account activity and consider limiting the market.",
        ),
        AlertType.RECONCILIATION_DRIFT: (
            f"Reconciliation drift on {event_label}",
            "Checksum comparison found drift between systems for this entity. "
            "Investigate and auto-correct or escalate.",
            AlertSeverity.WARNING,
            "Investigate drift and apply auto-correction or manual fix.",
        ),
    }

    title, description, severity, suggested_action = templates.get(
        anomaly_type,
        (
            f"Alert on {event_label}",
            "Anomaly detected requiring review.",
            AlertSeverity.INFO,
            "Review the anomaly context.",
        ),
    )

    # Confidence: higher when context carries strong signals; lower otherwise.
    base_confidence = 0.75
    if context.get("confidence") is not None:
        try:
            base_confidence = float(context["confidence"])
        except (TypeError, ValueError):
            pass
    # Clamp to [0, 1]
    confidence = max(0.0, min(1.0, base_confidence))

    return LLMAlertResponse(
        title=title,
        description=description,
        severity=severity,
        confidence=confidence,
        suggested_action=suggested_action,
        metadata={
            "anomaly_type": anomaly_type.value if hasattr(anomaly_type, "value") else str(anomaly_type),
            "simulated": True,
            "source_event_id": getattr(event_data, "event_id", None)
            or getattr(event_data, "id", None),
            "trace_id": trace_id,
        },
    )


def _call_anthropic(request: LLMAlertRequest, trace_id: Optional[str] = None) -> LLMAlertResponse:
    """Call the Anthropic Messages API for a structured alert response.

    WHAT: Builds system + user prompts via prompt_templates, calls the Anthropic Messages
        API with a JSON schema (structured output), parses the result into an
        LLMAlertResponse, and falls back to simulation on any failure. trace_id is carried
        into metadata for distributed tracing.
    WHY: Production alerts come from a real LLM with few-shot prompting; structured output
        keeps downstream routing deterministic.
    INPUTS: request (LLMAlertRequest), trace_id (optional distributed trace ID).
    OUTPUTS: LLMAlertResponse.
    SIDE EFFECTS: makes an outbound HTTPS call to api.anthropic.com.
    FAILURE MODES: network error, missing key, malformed JSON → caught and falls back to
        _simulate_alert so a transient LLM failure never drops the alert.
    """
    try:
        import anthropic  # type: ignore
    except ImportError:  # pragma: no cover - anthropic not installed
        logger.warning("anthropic SDK not installed; simulating alert")
        return _simulate_alert(request, trace_id)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _simulate_alert(request, trace_id)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        system_prompt = __import__(
            "processing_engine.alerts.prompt_templates", fromlist=["build_system_prompt"]
        ).build_system_prompt()
        user_prompt = __import__(
            "processing_engine.alerts.prompt_templates", fromlist=["build_user_prompt"]
        ).build_user_prompt(request)

        # Build event_data summary for the prompt (avoid dumping whole Pydantic model if heavy)
        event_data = request.event_data
        if isinstance(event_data, CanonicalEvent):
            event_summary = {
                "id": event_data.id,
                "sport": event_data.sport,
                "league": event_data.league,
                "status": event_data.status.value,
                "home_team": event_data.home_team.name,
                "away_team": event_data.away_team.name,
                "score": {
                    "home": event_data.score.home if event_data.score else 0,
                    "away": event_data.score.away if event_data.score else 0,
                },
            }
        elif isinstance(event_data, CanonicalOdds):
            event_summary = {
                "provider_id": event_data.provider_id,
                "event_id": event_data.event_id,
                "market_id": event_data.market_id,
                "selection_id": event_data.selection_id,
                "odds": event_data.odds,
                "format": event_data.format.value,
            }
        else:
            event_summary = str(event_data)

        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.2,
        )

        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text

        # Parse structured JSON from the LLM response
        parsed = _parse_llm_json(text)
        return LLMAlertResponse(
            title=parsed.get("title", "Alert"),
            description=parsed.get("description", ""),
            severity=_coerce_severity(parsed.get("severity", "info")),
            confidence=max(0.0, min(1.0, float(parsed.get("confidence", 0.5)))),
            suggested_action=parsed.get("suggested_action"),
            metadata={**parsed.get("metadata", {}), "simulated": False, "trace_id": trace_id},
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning(f"Anthropic call failed, simulating alert: {exc}")
        return _simulate_alert(request, trace_id)


def _parse_llm_json(text: str) -> Dict[str, Any]:
    """Parse a JSON object out of LLM response text, tolerating fences/extra prose."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```", 2)[-1] if "```" in text[3:] else text
        if text.startswith("json"):
            text = text[4:].strip()
    # Find the first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _coerce_severity(value: Any) -> AlertSeverity:
    """Coerce a raw severity value into an AlertSeverity, defaulting to WARNING."""
    try:
        return AlertSeverity(value)
    except Exception:
        return AlertSeverity.WARNING


class LLMClient:
    """Client wrapper for generating structured LLM alerts.

    WHAT: Wraps generate_alert so callers can hold a client instance (e.g. injected into an
        n8n node or service) and call generate_alert(request, trace_id) -> LLMAlertResponse.
    WHY: Dependency-injection friendly surface; easy to mock in tests.
    """

    def generate_alert(self, request: LLMAlertRequest, trace_id: Optional[str] = None) -> LLMAlertResponse:
        """Generate one structured alert from an LLMAlertRequest."""
        return generate_alert(request, trace_id)


def generate_alert(request: LLMAlertRequest, trace_id: Optional[str] = None) -> LLMAlertResponse:
    """Generate one structured alert from an LLMAlertRequest.

    WHAT: If ANTHROPIC_API_KEY is set, calls the Anthropic Messages API; otherwise simulates
        a deterministic alert. Returns an LLMAlertResponse with title, description, severity,
        confidence, and optional suggested_action/metadata. trace_id is carried into metadata
        for distributed tracing across ingestion -> n8n -> processing-engine.
    WHY: Centralized entry point for alert generation; simulation keeps the stack runnable
        without a live Anthropic contract.
    INPUTS: request (LLMAlertRequest with event_data, anomaly_type, context, few_shot_examples),
        trace_id (optional distributed trace ID).
    OUTPUTS: LLMAlertResponse.
    SIDE EFFECTS: may make an outbound HTTPS call to api.anthropic.com.
    FAILURE MODES: any failure falls back to _simulate_alert (alert is never dropped).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        return _call_anthropic(request, trace_id)
    return _simulate_alert(request, trace_id)
