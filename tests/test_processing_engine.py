"""
tests/test_processing_engine.py

FILE HEADER
-----------
Business problem this file solves:
    The processing engine settles bets via a rule DSL, computes checksums for drift
    detection, and detects reconciliation drift. These unit tests lock in settlement rule
    evaluation (priority ordering, default-to-void safety), DSL parsing, checksum computation,
    and drift detection so financial outcomes cannot silently change.

Where it sits in the flow:
    Unit tests for packages/processing-engine/ (rule_engine, dsl_parser, checksum,
    drift_detector) using the real implementation now delivered by the coder agent.

What calls it / what it calls:
    pytest. Imports processing_engine.settlement.rule_engine, processing_engine.settlement.
    dsl_parser, processing_engine.reconciliation.checksum, processing_engine.reconciliation.
    drift_detector, and sports_automation.types (CanonicalEvent, CanonicalOdds, ...).

Language conventions:
    Python 3.11+. pytest.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from processing_engine.settlement.dsl_parser import parse_rule_set
from processing_engine.settlement.rule_engine import SettlementRuleEngine
from processing_engine.reconciliation.checksum import compute_checksum
from processing_engine.reconciliation.drift_detector import DriftDetector
from sports_automation.types import (
    CanonicalEvent,
    CanonicalOdds,
    Discrepancy,
    EventStatus,
    OddsFormat,
    Score,
    SettlementOutcome,
    Team,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ended_event():
    """A canonical ended football event with a home win (2-1)."""
    return CanonicalEvent(
        id="evt_1",
        sport="football",
        league="Premier League",
        home_team=Team(id="team_home", name="Red United", short_name="RED"),
        away_team=Team(id="team_away", name="Blue City", short_name="BLU"),
        start_time=datetime(2026, 11, 10, 15, 0),
        status=EventStatus.ENDED,
        score=Score(home=2, away=1),
    )


@pytest.fixture
def live_event():
    """A canonical live event (not yet settled)."""
    return CanonicalEvent(
        id="evt_2",
        sport="football",
        league="Premier League",
        home_team=Team(id="team_home", name="Red United"),
        away_team=Team(id="team_away", name="Blue City"),
        start_time=datetime(2026, 11, 10, 15, 0),
        status=EventStatus.LIVE,
        score=Score(home=0, away=0),
    )


@pytest.fixture
def home_win_odds():
    """Canonical odds for the home selection of evt_1."""
    return CanonicalOdds(
        provider_id="lsports",
        event_id="evt_1",
        market_id="match_winner",
        selection_id="home",
        odds=2.10,
        format=OddsFormat.DECIMAL,
        timestamp=datetime(2026, 11, 9, 14, 30),
        sequence=7,
    )


# ---------------------------------------------------------------------------
# DSL parsing (dsl_parser)
# ---------------------------------------------------------------------------


def test_parse_rule_set_valid_structure():
    raw = {
        "version": "1.0",
        "default_outcome": "void",
        "rules": [
            {
                "id": "r1",
                "name": "high",
                "outcome": "won",
                "priority": 10,
                "condition": {"field": "event.status", "comparator": "eq", "value": "ended"},
            },
            {
                "id": "r2",
                "name": "low",
                "outcome": "lost",
                "priority": 1,
                "condition": {"field": "event.status", "comparator": "eq", "value": "ended"},
            },
        ],
    }
    parsed = parse_rule_set(raw)
    assert parsed["version"] == "1.0"
    assert parsed["default_outcome"] == "void"
    assert len(parsed["rules"]) == 2
    # Rules sorted by priority descending (highest first).
    assert parsed["rules"][0]["id"] == "r1"
    assert parsed["rules"][0]["priority"] == 10
    assert parsed["rules"][1]["id"] == "r2"
    assert parsed["rules"][1]["priority"] == 1
    # Each parsed rule carries a condition_tree RuleCondition.
    assert parsed["rules"][0]["condition_tree"].field == "event.status"


def test_parse_rule_set_invalid_default_outcome_raises():
    raw = {
        "version": "1.0",
        "default_outcome": "not_an_outcome",
        "rules": [],
    }
    with pytest.raises(ValueError):
        parse_rule_set(raw)


def test_parse_rule_set_missing_required_raises():
    with pytest.raises(ValueError):
        parse_rule_set({"version": "1.0"})  # no rules / default_outcome


# ---------------------------------------------------------------------------
# Settlement rule engine (rule_engine)
# ---------------------------------------------------------------------------


def _rule_set(rules, default_outcome="void", version="1.0"):
    return parse_rule_set({"version": version, "default_outcome": default_outcome, "rules": rules})


def test_rule_engine_first_matching_rule_wins_by_priority(ended_event, home_win_odds):
    rules = [
        {
            "id": "r_low",
            "name": "low priority",
            "outcome": "lost",
            "priority": 1,
            "condition": {"field": "event.status", "comparator": "eq", "value": "ended"},
        },
        {
            "id": "r_high",
            "name": "high priority",
            "outcome": "won",
            "priority": 9,
            "condition": {"field": "event.status", "comparator": "eq", "value": "ended"},
        },
    ]
    engine = SettlementRuleEngine(_rule_set(rules))
    result = engine.evaluate(ended_event, home_win_odds)
    assert result.outcome == SettlementOutcome.WON
    assert result.source == "auto"
    assert result.confidence == 1.0


def test_rule_engine_defaults_to_void_when_no_rule_matches(live_event, home_win_odds):
    rules = [
        {
            "id": "r1",
            "name": "only-ended",
            "outcome": "won",
            "priority": 5,
            "condition": {"field": "event.status", "comparator": "eq", "value": "ended"},
        },
    ]
    engine = SettlementRuleEngine(_rule_set(rules, default_outcome="void"))
    result = engine.evaluate(live_event, home_win_odds)
    # No rule matches (status is live, not ended) -> default outcome void, lower confidence.
    assert result.outcome == SettlementOutcome.VOID
    assert result.confidence == 0.5
    assert result.source == "auto"


def test_rule_engine_dot_notation_field_resolution(ended_event, home_win_odds):
    # Condition on a nested field path: event.score.home > 1 (home won 2-1).
    rules = [
        {
            "id": "r1",
            "name": "home leads",
            "outcome": "won",
            "priority": 5,
            "condition": {"field": "event.score.home", "comparator": "gt", "value": 1},
        },
    ]
    engine = SettlementRuleEngine(_rule_set(rules))
    result = engine.evaluate(ended_event, home_win_odds)
    assert result.outcome == SettlementOutcome.WON


def test_rule_engine_without_odds(ended_event):
    rules = [
        {
            "id": "r1",
            "name": "ended",
            "outcome": "won",
            "priority": 5,
            "condition": {"field": "event.status", "comparator": "eq", "value": "ended"},
        },
    ]
    engine = SettlementRuleEngine(_rule_set(rules))
    result = engine.evaluate(ended_event)  # odds=None
    assert result.outcome == SettlementOutcome.WON
    assert result.market_id == "unknown"
    assert result.selection_id == "unknown"


def test_rule_engine_compound_and_condition(ended_event, home_win_odds):
    rules = [
        {
            "id": "r1",
            "name": "ended and home leads",
            "outcome": "won",
            "priority": 5,
            "condition": {
                "operator": "and",
                "conditions": [
                    {"field": "event.status", "comparator": "eq", "value": "ended"},
                    {"field": "event.score.home", "comparator": "gt", "value": 1},
                ],
            },
        },
    ]
    engine = SettlementRuleEngine(_rule_set(rules))
    result = engine.evaluate(ended_event, home_win_odds)
    assert result.outcome == SettlementOutcome.WON


# ---------------------------------------------------------------------------
# Checksum (reconciliation/checksum)
# ---------------------------------------------------------------------------


def test_compute_checksum_deterministic():
    data = {"outcome": "won", "status": "ended"}
    assert compute_checksum("event", "evt_1", data, "system_a") == compute_checksum(
        "event", "evt_1", data, "system_a"
    )


def test_compute_checksum_sensitive_to_data():
    base = {"outcome": "won"}
    assert compute_checksum("event", "evt_1", base, "system_a") != compute_checksum(
        "event", "evt_1", {**base, "outcome": "void"}, "system_a"
    )


def test_compute_checksum_includes_entity_id():
    data = {"outcome": "won"}
    assert compute_checksum("event", "evt_1", data, "system_a") != compute_checksum(
        "event", "evt_2", data, "system_a"
    )


# ---------------------------------------------------------------------------
# Drift detection (reconciliation/drift_detector)
# ---------------------------------------------------------------------------


def test_drift_detector_reports_field_change():
    detector = DriftDetector()
    records_a = [
        {
            "entity_type": "event",
            "entity_id": "e1",
            "data": {"outcome": "won", "status": "ended"},
            "source_system": "system_a",
        }
    ]
    records_b = [
        {
            "entity_type": "event",
            "entity_id": "e1",
            "data": {"outcome": "void", "status": "ended"},
            "source_system": "system_b",
        }
    ]
    diffs = detector.detect(records_a, records_b)
    assert len(diffs) == 1
    assert diffs[0].field == "outcome"
    assert diffs[0].expected == "won"
    assert diffs[0].actual == "void"
    assert diffs[0].severity == "high"  # outcome is financially significant
    assert isinstance(diffs[0], Discrepancy)


def test_drift_detector_no_drift_when_checksums_match():
    detector = DriftDetector()
    data = {"outcome": "won", "status": "ended"}
    records_a = [
        {"entity_type": "event", "entity_id": "e1", "data": dict(data), "source_system": "system_a"}
    ]
    records_b = [
        {"entity_type": "event", "entity_id": "e1", "data": dict(data), "source_system": "system_b"}
    ]
    assert detector.detect(records_a, records_b) == []


def test_drift_detector_missing_entity_is_high_severity():
    detector = DriftDetector()
    records_a = [
        {"entity_type": "event", "entity_id": "e1", "data": {"outcome": "won"}, "source_system": "system_a"}
    ]
    records_b = []
    diffs = detector.detect(records_a, records_b)
    assert len(diffs) == 1
    assert diffs[0].field == "__entity__"
    assert diffs[0].severity == "high"


def test_drift_detector_sorted_by_severity():
    detector = DriftDetector()
    # Two differing fields: low-severity 'league' and high-severity 'outcome'.
    records_a = [
        {
            "entity_type": "event",
            "entity_id": "e1",
            "data": {"outcome": "won", "league": "PL"},
            "source_system": "system_a",
        }
    ]
    records_b = [
        {
            "entity_type": "event",
            "entity_id": "e1",
            "data": {"outcome": "void", "league": "BL"},
            "source_system": "system_b",
        }
    ]
    diffs = detector.detect(records_a, records_b)
    assert diffs[0].severity == "high"
    assert diffs[0].field == "outcome"
    assert diffs[1].severity == "low"
    assert diffs[1].field == "league"
