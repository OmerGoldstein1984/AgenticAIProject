"""
packages/processing-engine/src/processing_engine/alerts/prompt_templates.py

FILE HEADER
-----------
Business problem this file solves:
    The LLM needs consistent, well-structured prompts (system instructions + few-shot
    examples + user input) to produce reliable LLMAlertResponse output. prompt_templates.py
    builds the system prompt and user prompt used by llm_client.py, including few-shot
    priming so the LLM learns the required schema and tone from examples rather than
    fine-tuning.

Where it sits in the flow:
    Support module under alerts/. Imported by llm_client.py (to build prompts for the
    Anthropic call) and by tests/demo scripts that want to inspect or version prompts.

What calls it / what it calls:
    Called by: llm_client, tests.
    Calls: sports_automation.types (AlertType, AlertSeverity, LLMAlertResponse,
    FewShotExample).

What breaks if removed:
    llm_client cannot build prompts; LLM alert generation produces unstructured or empty
    output and falls back to simulation.

Language conventions:
    Python 3.11+. build_system_prompt() -> str; build_user_prompt(request) -> str;
    format_few_shot(examples) -> str. Few-shot examples steer the LLM toward the required
    JSON schema and tone.
"""

import json
from typing import Any, Dict, List

from sports_automation.types import AlertType, AlertSeverity, LLMAlertRequest  # noqa: E402


def build_system_prompt() -> str:
    """Build the system prompt that primes the LLM for structured alert generation.

    WHAT: Returns a system-prompt string instructing the LLM to output a single JSON object
        matching the LLMAlertResponse schema (title, description, severity, confidence,
        suggested_action, metadata), to use the provided few-shot examples as style guides,
        and to choose severity from the allowed enum.
    WHY: A strong system prompt is the cheapest way to get reliable structured output without
        fine-tuning, and it documents the expected alert contract for auditors.
    OUTPUTS: system prompt string.
    """
    return (
        "You are an expert sportsbook operations alert generator. "
        "Convert raw anomaly data into a single structured JSON alert.\n\n"
        "Output exactly one JSON object with these fields:\n"
        "  - title: short human-readable alert headline (string)\n"
        "  - description: 1-3 sentence explanation of the anomaly and its business impact\n"
        "  - severity: one of 'info', 'warning', 'critical', 'page'\n"
        "  - confidence: float between 0 and 1 (how certain the anomaly is real)\n"
        "  - suggested_action: recommended next step for the operations team (string, optional)\n"
        "  - metadata: extra structured context as a dict (optional)\n\n"
        "Rules:\n"
        "  - Respond with valid JSON only, no markdown fences, no extra prose.\n"
        "  - Base severity on anomaly type and confidence: feed outage -> page/critical;\n"
        "    settlement discrepancy -> critical; odds anomaly -> warning; info otherwise.\n"
        "  - Never invent event IDs or dollar figures not present in the input.\n"
        "  - Keep titles under 120 characters; descriptions under 400 characters.\n"
    )


def build_user_prompt(request: LLMAlertRequest) -> str:
    """Build the user prompt that feeds the anomaly data and few-shot examples to the LLM.

    WHAT: Combines the anomaly type, event data summary, context, and few-shot examples into
        one user message that asks the LLM to produce an LLMAlertResponse JSON object.
    WHY: Structuring the user input consistently (data + examples + explicit output schema)
        improves LLM reliability and makes prompt versioning straightforward.
    INPUTS: request (LLMAlertRequest).
    OUTPUTS: user prompt string.
    """
    event_data = request.event_data
    if hasattr(event_data, "model_dump"):
        event_summary = event_data.model_dump()
    elif hasattr(event_data, "dict"):
        event_summary = event_data.dict()
    else:
        event_summary = {"data": str(event_data)}

    lines: List[str] = []
    lines.append(f"Anomaly type: {request.anomaly_type.value if hasattr(request.anomaly_type, 'value') else request.anomaly_type}")
    lines.append("")
    lines.append("Event data:")
    lines.append(json.dumps(event_summary, default=str, indent=2))
    lines.append("")
    lines.append("Context:")
    lines.append(json.dumps(request.context or {}, default=str, indent=2))
    lines.append("")

    if request.few_shot_examples:
        lines.append("Few-shot examples (input -> expected output):")
        for example in request.few_shot_examples:
            lines.append(format_few_shot(example))
            lines.append("")

    lines.append("Now generate the alert JSON for the event data above:")
    return "\n".join(lines)


def format_few_shot(example: Any) -> str:
    """Format one few-shot example as an input/output block.

    WHAT: Serializes a FewShotExample (or dict with input/output) into a compact
        'Input: ... / Expected output: ...' block.
    WHY: Few-shot examples are most effective when clearly delimited in the prompt.
    INPUTS: example (FewShotExample or dict).
    OUTPUTS: formatted string.
    """
    if hasattr(example, "model_dump"):
        data = example.model_dump()
    elif hasattr(example, "dict"):
        data = example.dict()
    else:
        data = dict(example)

    inp = data.get("input", {})
    out = data.get("output", {})
    if hasattr(out, "model_dump"):
        out = out.model_dump()
    elif hasattr(out, "dict"):
        out = out.dict()

    return (
        "Input: " + json.dumps(inp, default=str) + "\n"
        "Expected output: " + json.dumps(out, default=str)
    )


def build_fewshot_examples() -> List[Dict[str, Any]]:
    """Return a small default set of few-shot examples for alert generation.

    WHAT: Hard-coded examples covering odds_anomaly, settlement_discrepancy, and feed_outage,
        each mapping an input event to the desired LLMAlertResponse output.
    WHY: Provides ready-to-use few-shot priming so callers don't have to author examples from
        scratch; traders can extend them over time.
    OUTPUTS: list of dicts with input/output keys.
    """
    return [
        {
            "input": {
                "anomaly_type": "odds_anomaly",
                "event": {
                    "id": "evt_000001",
                    "home_team": "Red United",
                    "away_team": "Blue City",
                    "market_id": "match_winner",
                    "selection_id": "home",
                    "odds": 5.0,
                    "other_providers_odds": 2.1,
                },
                "context": {"deviation_percent": 138},
            },
            "output": {
                "title": "Odds anomaly detected",
                "description": "Home win odds of 5.0 deviate 138% from other providers (2.1). "
                "Verify the price before accepting bets.",
                "severity": "warning",
                "confidence": 0.9,
                "suggested_action": "Verify with other providers before accepting bets.",
                "metadata": {"deviation_percent": 138},
            },
        },
        {
            "input": {
                "anomaly_type": "settlement_discrepancy",
                "event": {
                    "id": "evt_000002",
                    "home_team": "Red United",
                    "away_team": "Blue City",
                    "status": "ended",
                    "score": {"home": 2, "away": 1},
                },
                "context": {"settled_outcome": "away_won", "expected_outcome": "home_won"},
            },
            "output": {
                "title": "Settlement discrepancy",
                "description": "Match ended 2-1 (home win) but selection was settled as away "
                "won. Review and reconcile before paying out.",
                "severity": "critical",
                "confidence": 0.98,
                "suggested_action": "Reconcile with the official result feed and adjust payouts.",
                "metadata": {"expected_outcome": "home_won", "settled_outcome": "away_won"},
            },
        },
    ]
