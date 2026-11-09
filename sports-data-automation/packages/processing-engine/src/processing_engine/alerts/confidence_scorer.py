"""
packages/processing-engine/src/processing_engine/alerts/confidence_scorer.py

FILE HEADER
-----------
Business problem this file solves:
    Before sending an alert to the LLM (or as a deterministic baseline), the platform needs a
    rule-based confidence score for each anomaly. confidence_scorer.py scores anomalies using
    observable signals (deviation magnitude, source agreement, event status, provider count)
    so the alert engine can route high-confidence alerts to auto-escalation and low-confidence
    ones to human review.

Where it sits in the flow:
    Support module under alerts/. Imported by processing_engine/__init__.py, the n8n
    alert-engine workflow, and human_review_queue.py. Consumed alongside LLM output to
    decide auto-escalate vs human-review routing.

What calls it / what it calls:
    Called by: alert-engine workflow, human_review_queue, tests.
    Calls: sports_automation.types (AlertType), stdlib only.

What breaks if removed:
    No rule-based baseline confidence; the alert engine cannot distinguish high-confidence
    auto-escalation candidates from low-confidence review candidates.

Language conventions:
    Python 3.11+. ConfidenceScorer.score(anomaly_type, event_data, context) -> float in [0,1].
    Deterministic, pure function of inputs; no network or randomness.

GAP: this is a rule-based baseline; the LLM's own confidence (shadow mode) is compared
    against it in AlertEvaluationResult but the comparison harness is not implemented here.
    See 07_issues_found.md.
"""

from typing import Any, Dict, Optional

from sports_automation.types import AlertType  # noqa: E402


class ConfidenceScorer:
    """Rule-based baseline confidence scorer for anomalies.

    WHAT: Scores an anomaly on a 0-1 scale using observable signals:
        - deviation magnitude (odds anomaly)
        - number of agreeing providers
        - event status (ended events are more certain)
        - presence/quality of context fields
    WHY: A deterministic baseline lets the platform route alerts without waiting on the LLM,
        and provides a shadow-mode comparison target for measuring LLM precision/recall.
    INPUTS: anomaly_type (AlertType), event_data (dict/CanonicalEvent/CanonicalOdds),
        context (dict).
    OUTPUTS: float confidence in [0, 1].
    SIDE EFFECTS: none (pure).
    FAILURE MODES: never raises; on unexpected input returns a conservative 0.5.
    ALTERNATIVE: a trained ML model. Chosen rule-based scoring for transparency and
        auditability — ops can explain exactly why an alert got its score.
    """

    def score(
        self,
        anomaly_type: AlertType,
        event_data: Any = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Score an anomaly's confidence on a 0-1 scale.

        WHAT: Combines anomaly-type-specific signals into a single confidence value.
        WHY: Drives auto-escalate vs human-review routing in the alert engine.
        INPUTS: anomaly_type, event_data, context.
        OUTPUTS: float in [0, 1].
        SIDE EFFECTS: none.
        FAILURE MODES: returns 0.5 (conservative) on any unexpected input.
        """
        context = context or {}

        try:
            base = self._base_score(anomaly_type)
            adjusted = self._apply_signals(base, anomaly_type, event_data, context)
            return max(0.0, min(1.0, adjusted))
        except Exception:  # pragma: no cover - defensive
            return 0.5

    def _base_score(self, anomaly_type: AlertType) -> float:
        """Prior belief per anomaly type (how reliably the signal indicates a real issue)."""
        priors = {
            AlertType.FEED_OUTAGE: 0.9,
            AlertType.SETTLEMENT_DISCREPANCY: 0.85,
            AlertType.RECONCILIATION_DRIFT: 0.8,
            AlertType.ODDS_ANOMALY: 0.7,
            AlertType.SUSPICIOUS_PATTERN: 0.6,
            AlertType.ARBITRAGE_DETECTED: 0.55,
        }
        return priors.get(anomaly_type, 0.5)

    def _apply_signals(
        self,
        base: float,
        anomaly_type: AlertType,
        event_data: Any,
        context: Dict[str, Any],
    ) -> float:
        """Adjust the base score up or down based on observable signals."""
        score = base

        # Odds deviation magnitude (odds anomaly / arbitrage)
        deviation = context.get("deviation_percent")
        if deviation is not None:
            try:
                dev = float(deviation)
                if anomaly_type == AlertType.ODDS_ANOMALY:
                    # Bigger deviation -> higher confidence it's a real anomaly
                    if dev >= 50:
                        score += 0.15
                    elif dev >= 20:
                        score += 0.08
                    elif dev < 5:
                        score -= 0.1
                elif anomaly_type == AlertType.ARBITRAGE_DETECTED:
                    if dev >= 5:
                        score += 0.1
            except (TypeError, ValueError):
                pass

        # Provider agreement: more agreeing providers -> higher confidence
        provider_count = context.get("provider_count")
        if provider_count is not None:
            try:
                pc = int(provider_count)
                if pc >= 3:
                    score += 0.05
                elif pc == 1:
                    score -= 0.1
            except (TypeError, ValueError):
                pass

        # Event status: ended events are more certain than scheduled/live
        status = self._get_field(event_data, context, "status")
        if status:
            status_str = str(status).lower()
            if status_str == "ended":
                score += 0.05
            elif status_str in ("scheduled", "live"):
                score -= 0.02

        # Explicit context confidence overrides/adjusts
        ctx_conf = context.get("confidence")
        if ctx_conf is not None:
            try:
                ctx_conf = float(ctx_conf)
                # Blend: trust the explicit signal moderately
                score = 0.6 * score + 0.4 * ctx_conf
            except (TypeError, ValueError):
                pass

        return score

    def _get_field(self, event_data: Any, context: Dict[str, Any], field: str) -> Any:
        """Read a field from event_data (object/dict) or context."""
        if context.get(field) is not None:
            return context[field]
        if event_data is None:
            return None
        if hasattr(event_data, field):
            return getattr(event_data, field)
        if isinstance(event_data, dict):
            return event_data.get(field)
        return None
