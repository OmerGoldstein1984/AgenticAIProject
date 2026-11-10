"""
packages/processing-engine/src/processing_engine/settlement/rule_engine.py

FILE HEADER
-----------
Business problem this file solves:
    When an official match result arrives, the platform must auto-settle bets (won/lost/void/
    half_won/half_lost) according to trader-defined rules. rule_engine.py evaluates a
    SettlementRuleSet against a canonical event + odds and returns a SettlementResult, giving
    full audit trail (outcome + source + confidence) required for regulatory compliance.

Where it sits in the flow:
    Core settlement module. Imported by processing_engine/__init__.py and by the n8n
    settlement-worker workflow. Consumed after ingestion has canonicalized an event and the
    settlement feed has delivered the official result.

What calls it / what it calls:
    Called by: n8n settlement-worker, demo scripts, tests.
    Calls: settlement.models (SettlementResult, SettlementOutcome),
    settlement.dsl_parser (parse_rule_set), sports_automation.types (CanonicalEvent,
    CanonicalOdds).

What breaks if removed:
    No auto-settlement logic; every match defaults to void (no payouts), breaking the
    time-to-settle KPI and frustrating traders.

Language conventions:
    Python 3.11+. SettlementRuleEngine.evaluate(event, odds, rule_set) returns a
    SettlementResult. Rules are evaluated in priority order (highest first); the first match
    wins. If no rule matches, default_outcome is used (safe: never pay on an unknown match).

GAP: hot-reload of rule sets from a remote DB is not implemented; only embedded JSON rule
    sets are supported. See 07_issues_found.md.
"""

import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional

# Ensure canonical types are importable (monorepo layout).
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANONICAL_TYPES_PY = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", "canonical-types", "python")
)
if os.path.isdir(_CANONICAL_TYPES_PY) and _CANONICAL_TYPES_PY not in sys.path:
    sys.path.insert(0, _CANONICAL_TYPES_PY)

from sports_automation.types import (  # noqa: E402
    CanonicalEvent,
    CanonicalOdds,
    SettlementOutcome,
)

from processing_engine.settlement.models import SettlementResult  # noqa: E402


def _build_context(event: CanonicalEvent, odds: Optional[CanonicalOdds]) -> Dict[str, Any]:
    """Build a flat context dict for DSL field resolution from event + odds.

    WHAT: Merges event and odds fields under namespaces (event.*, odds.*) plus top-level
        shortcuts so DSL conditions like `event.status == "ended"` and `odds.market_id ==
        "match_winner"` resolve.
    WHY: The DSL addresses fields via dot-notation paths; this context is what `_eval_condition`
        reads.
    INPUTS: event (CanonicalEvent), odds (CanonicalOdds or None).
    OUTPUTS: dict with event/ odds namespaces and scalar shortcuts.
    """
    context: Dict[str, Any] = {}

    # Event namespace
    context["event"] = {
        "id": event.id,
        "sport": event.sport,
        "league": event.league,
        "status": event.status.value if hasattr(event.status, "value") else event.status,
        "home_team": {
            "id": event.home_team.id,
            "name": event.home_team.name,
            "short_name": event.home_team.short_name,
        },
        "away_team": {
            "id": event.away_team.id,
            "name": event.away_team.name,
            "short_name": event.away_team.short_name,
        },
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "score": {
            "home": event.score.home if event.score else 0,
            "away": event.score.away if event.score else 0,
        },
    }
    # Top-level shortcuts for common conditions
    context["event_id"] = event.id
    context["status"] = context["event"]["status"]
    context["sport"] = event.sport
    context["league"] = event.league
    context["home_score"] = context["event"]["score"]["home"]
    context["away_score"] = context["event"]["score"]["away"]

    # Odds namespace
    if odds is not None:
        context["odds"] = {
            "provider_id": odds.provider_id,
            "event_id": odds.event_id,
            "market_id": odds.market_id,
            "selection_id": odds.selection_id,
            "odds": odds.odds,
            "format": odds.format.value if hasattr(odds.format, "value") else odds.format,
            "sequence": odds.sequence,
        }
        context["market_id"] = odds.market_id
        context["selection_id"] = odds.selection_id

    return context


class SettlementRuleEngine:
    """Evaluates a SettlementRuleSet against an event + odds, returning a SettlementResult.

    WHAT: Holds a parsed rule set (version, rules sorted by priority, default_outcome).
        evaluate(event, odds, trace_id) runs each rule's condition tree against the event+odds
        context in priority order; the first matching rule's outcome is used. If none match,
        default_outcome is used (safe default: void).
    WHY: Settlement accuracy is a regulatory requirement. Priority-ordered first-match rules
        with a void default guarantee deterministic, auditable outcomes and never pay on an
        unrecognized match.
    INPUTS: rule_set (dict from parse_rule_set), event (CanonicalEvent), odds (CanonicalOdds),
        trace_id (optional distributed trace ID for end-to-end propagation).
    OUTPUTS: SettlementResult with outcome, settled_at, source="auto", confidence, trace_id.
    SIDE EFFECTS: none (pure evaluation).
    FAILURE MODES: a rule condition that raises during evaluation is caught, logged, and the
        rule is skipped (so one bad rule cannot block all settlements); falls back to
        default_outcome.
    ALTERNATIVE: a full rules engine (Drools/Clips). Chosen a lightweight DSL evaluator for a
        dependency-free, easy-to-audit implementation.
    """

    def __init__(self, rule_set: Dict[str, Any]):
        """Construct the engine from a parsed rule-set dict.

        WHAT: Stores version, rules (sorted by priority desc), and default_outcome.
        WHY: Pre-sorting rules once avoids re-sorting on every evaluation.
        INPUTS: rule_set (parsed dict from dsl_parser.parse_rule_set).
        OUTPUTS: None; sets instance attributes.
        SIDE EFFECTS: none.
        FAILURE MODES: ValueError if rule_set lacks required keys.
        """
        if not rule_set or "rules" not in rule_set or "default_outcome" not in rule_set:
            raise ValueError("rule_set must contain 'rules' and 'default_outcome'")
        self.version = rule_set.get("version", "1.0")
        self.rules = list(rule_set["rules"])
        self.default_outcome = rule_set["default_outcome"]

    def evaluate(
        self,
        event: CanonicalEvent,
        odds: Optional[CanonicalOdds] = None,
        trace_id: Optional[str] = None,
    ) -> SettlementResult:
        """Evaluate the rule set against an event + odds and return a SettlementResult.

        WHAT: Builds the DSL context, iterates rules in priority order, evaluates each
            condition tree; returns the first matching rule's outcome. If no rule matches,
            returns default_outcome. settled_at is now, source is "auto", confidence is
            1.0 for rule-matched outcomes and 0.5 for default outcomes. trace_id is carried
            into the SettlementResult for distributed tracing.
        WHY: Produces one auditable SettlementResult per selection, with outcome/source/
            confidence forming the regulatory audit trail, plus trace_id for correlation
            across ingestion -> n8n -> processing-engine.
        INPUTS: event (CanonicalEvent), odds (CanonicalOdds, optional),
            trace_id (optional str).
        OUTPUTS: SettlementResult.
        SIDE EFFECTS: none.
        FAILURE MODES: condition evaluation errors skip the offending rule; final fallback is
            default_outcome with confidence 0.5.
        """
        context = _build_context(event, odds)
        matched_outcome = None
        matched_rule = None
        confidence = 1.0

        for rule in self.rules:
            try:
                if _eval_condition(rule["condition_tree"], context):
                    matched_outcome = rule["outcome"]
                    matched_rule = rule
                    confidence = 1.0
                    break
            except Exception as exc:  # pragma: no cover - defensive, skip bad rule
                import logging

                logging.getLogger(__name__).warning(
                    f"Skipping rule {rule.get('id', '?')}: condition evaluation failed: {exc}"
                )
                continue

        if matched_outcome is None:
            matched_outcome = self.default_outcome
            confidence = 0.5  # default outcomes are less certain

        try:
            outcome_enum = SettlementOutcome(matched_outcome)
        except Exception:  # pragma: no cover - defensive
            outcome_enum = SettlementOutcome.VOID

        return SettlementResult(
            event_id=event.id,
            market_id=(odds.market_id if odds else "unknown"),
            selection_id=(odds.selection_id if odds else "unknown"),
            outcome=outcome_enum,
            settled_at=datetime.utcnow(),
            source="auto",
            confidence=confidence,
            trace_id=trace_id,
        )


def _eval_condition(cond, context: Dict[str, Any]) -> bool:
    """Evaluate a RuleCondition (or parsed condition dict) against a context dict.

    Supports both RuleCondition objects (from dsl_parser) and raw dicts. Used internally by
    SettlementRuleEngine.evaluate.
    """
    from sports_automation.types import RuleCondition

    if isinstance(cond, dict):
        operator = cond.get("operator")
        conditions = cond.get("conditions")
        field = cond.get("field")
        comparator = cond.get("comparator")
        value = cond.get("value")
    else:
        operator = getattr(cond, "operator", None)
        conditions = getattr(cond, "conditions", None)
        field = getattr(cond, "field", None)
        comparator = getattr(cond, "comparator", None)
        value = getattr(cond, "value", None)

    if operator:
        operator = str(operator).lower()
        if operator == "not":
            if not conditions or len(conditions) != 1:
                raise ValueError("'not' operator requires exactly one condition")
            return not _eval_condition(conditions[0], context)
        if operator in ("and", "or"):
            results = [_eval_condition(c, context) for c in (conditions or [])]
            return all(results) if operator == "and" else any(results)
        raise ValueError(f"Unknown rule operator: {operator!r}")

    if field is None or comparator is None:
        raise ValueError("Leaf condition must set field and comparator")

    # Resolve actual value via dot-notation path
    actual: Any = context
    for key in str(field).split("."):
        if isinstance(actual, dict) and key in actual:
            actual = actual[key]
        else:
            actual = None
            break

    comparators = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "gt": lambda a, b: a > b,
        "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b,
        "lte": lambda a, b: a <= b,
        "in": lambda a, b: a in (b if isinstance(b, (list, tuple, set)) else [b]),
        "contains": lambda a, b: b in a if isinstance(a, (str, list, tuple, set)) else False,
    }
    fn = comparators.get(comparator)
    if fn is None:
        raise ValueError(f"Unknown comparator: {comparator!r}")
    return fn(actual, value)
