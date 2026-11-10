"""
tests/test_ingestion.py

FILE HEADER
-----------
Business problem this file solves:
    The ingestion service validates, transforms, deduplicates, and forwards every provider
    payload. These unit tests lock in the behavior of SchemaValidator, CanonicalTransformer,
    Deduplicator, and the process_odds/process_event/process_settlement pipeline so that
    regressions in validation, normalization, or idempotency are caught immediately.

Where it sits in the flow:
    Unit tests for packages/ingestion-service/src/ingestion/ modules (schema_validator,
    canonical_transformer, deduplicator) and the process_* pipeline in main.py.

What calls it / what it calls:
    pytest. Imports ingestion.schema_validator, ingestion.canonical_transformer,
    ingestion.idempotency.deduplicator, ingestion.main. Uses fixtures from conftest.py.

Language conventions:
    Python 3.11+. pytest-asyncio (async tests). Arrange-act-assert. Input is validated at
    the system boundary: invalid inputs are rejected, not silently passed.
"""

from __future__ import annotations

import asyncio

import pytest

from ingestion.idempotency.deduplicator import Deduplicator
from ingestion.main import process_event, process_odds, process_settlement
from ingestion.normalization.canonical_transformer import CanonicalTransformer
from ingestion.normalization.schema_validator import SchemaValidator


# ---------------------------------------------------------------------------
# SchemaValidator
# ---------------------------------------------------------------------------


@pytest.fixture
def validator(tmp_path):
    v = SchemaValidator(str(tmp_path / "schemas"))
    asyncio.run(v.load_schemas())
    return v


def test_validate_valid_odds(validator):
    valid, errors = validator.validate(
        "odds",
        {
            "providerId": "lsports",
            "eventId": "evt_1",
            "marketId": "match_winner",
            "selectionId": "home",
            "odds": 2.10,
            "format": "decimal",
            "timestamp": "2026-11-09T14:30:00Z",
            "sequence": 7,
        },
    )
    assert valid is True
    assert errors == []


def test_validate_missing_required_field(validator):
    valid, errors = validator.validate(
        "odds",
        {
            "eventId": "evt_1",
            "marketId": "match_winner",
            # providerId missing
            "selectionId": "home",
            "odds": 2.10,
            "format": "decimal",
            "timestamp": "2026-11-09T14:30:00Z",
            "sequence": 7,
        },
    )
    assert valid is False
    assert any("providerId" in e for e in errors)


def test_validate_odds_below_minimum(validator):
    valid, errors = validator.validate(
        "odds",
        {
            "providerId": "lsports",
            "eventId": "evt_1",
            "marketId": "match_winner",
            "selectionId": "home",
            "odds": 0.50,  # below minimum 1.01
            "format": "decimal",
            "timestamp": "2026-11-09T14:30:00Z",
            "sequence": 7,
        },
    )
    assert valid is False


def test_validate_invalid_format_rejected(validator):
    valid, errors = validator.validate(
        "odds",
        {
            "providerId": "lsports",
            "eventId": "evt_1",
            "marketId": "match_winner",
            "selectionId": "home",
            "odds": 2.10,
            "format": "bogus",
            "timestamp": "2026-11-09T14:30:00Z",
            "sequence": 7,
        },
    )
    assert valid is False


def test_validate_unknown_schema_type_is_permissive(validator):
    # Undocumented schema types allow data through (documented GAP in schema_validator.py)
    valid, errors = validator.validate("not_a_schema", {"foo": "bar"})
    assert valid is True
    assert errors == []


def test_validate_with_details_shape(validator):
    result = validator.validate_with_details("odds", {"providerId": "x"})
    assert set(result) == {"valid", "schema_type", "errors", "error_count"}
    assert result["valid"] is False
    assert result["schema_type"] == "odds"
    assert result["error_count"] == len(result["errors"])


def test_list_schemas(validator):
    assert set(validator.list_schemas()) == {"odds", "event", "settlement"}


# ---------------------------------------------------------------------------
# CanonicalTransformer
# ---------------------------------------------------------------------------


@pytest.fixture
def transformer():
    return CanonicalTransformer()


def test_transform_odds_maps_lsports_fields(transformer, sample_provider_odds):
    canonical = transformer.transform_odds(sample_provider_odds, provider="lsports")
    assert canonical["providerId"] == "lsports"
    assert canonical["eventId"] == "evt_1001"
    assert canonical["marketId"] == "match_winner"
    assert canonical["selectionId"] == "home"
    assert canonical["odds"] == 2.10
    assert canonical["format"] == "decimal"
    assert canonical["sequence"] == 7


def test_transform_odds_normalizes_american_positive(transformer):
    canonical = transformer.transform_odds(
        {
            "provider_id": "lsports",
            "event_id": "evt_1",
            "market_id": "m",
            "selection_id": "s",
            "odds": 150,
            "odds_format": "american",
            "timestamp": "2026-11-09T14:30:00Z",
            "sequence": 1,
        },
        provider="lsports",
    )
    assert canonical["odds"] == pytest.approx(2.50)
    assert canonical["format"] == "decimal"


def test_transform_odds_normalizes_american_negative(transformer):
    canonical = transformer.transform_odds(
        {
            "provider_id": "lsports",
            "event_id": "evt_1",
            "market_id": "m",
            "selection_id": "s",
            "odds": -200,
            "odds_format": "american",
            "timestamp": "2026-11-09T14:30:00Z",
            "sequence": 1,
        },
        provider="lsports",
    )
    assert canonical["odds"] == pytest.approx(1.50)
    assert canonical["format"] == "decimal"


def test_transform_odds_normalizes_fractional(transformer):
    canonical = transformer.transform_odds(
        {
            "provider_id": "lsports",
            "event_id": "evt_1",
            "market_id": "m",
            "selection_id": "s",
            "odds": "5/1",
            "odds_format": "fractional",
            "timestamp": "2026-11-09T14:30:00Z",
            "sequence": 1,
        },
        provider="lsports",
    )
    assert canonical["odds"] == pytest.approx(6.00)
    assert canonical["format"] == "decimal"


def test_transform_odds_missing_fields_defaulted(transformer):
    canonical = transformer.transform_odds({"odds": 2.10}, provider="lsports")
    assert canonical["providerId"] == "lsports"
    assert canonical["format"] == "decimal"
    assert canonical["sequence"] == 0
    # Missing fields are not fabricated.
    assert "eventId" not in canonical


def test_transform_odds_unknown_provider_falls_back_to_lsports(
    transformer, sample_provider_odds
):
    canonical = transformer.transform_odds(sample_provider_odds, provider="nonexistent")
    assert canonical["providerId"] == "lsports"
    assert canonical["eventId"] == "evt_1001"


def test_transform_event_maps_fields(transformer, sample_provider_event):
    canonical = transformer.transform_event(sample_provider_event, provider="lsports")
    assert canonical["id"] == "evt_1001"
    assert canonical["sport"] == "football"
    assert canonical["league"] == "Premier League"
    assert canonical["homeTeam"]["id"] == "team_home"
    assert canonical["homeTeam"]["name"] == "Red United"
    assert canonical["awayTeam"]["name"] == "Blue City"
    assert canonical["status"] == "scheduled"
    assert canonical["score"]["home"] == 0


def test_transform_settlement_valid(transformer, sample_provider_settlement):
    canonical = transformer.transform_settlement(sample_provider_settlement, provider="lsports")
    assert canonical["eventId"] == "evt_1001"
    assert canonical["outcome"] == "won"
    assert canonical["source"] == "official"
    assert canonical["confidence"] == 1.0


def test_transform_settlement_invalid_outcome_defaults_to_void(transformer):
    canonical = transformer.transform_settlement(
        {"outcome": "nonsense", "confidence": 1.0}, provider="lsports"
    )
    assert canonical["outcome"] == "void"


def test_transform_settlement_confidence_clamped_to_0_1(transformer):
    low = transformer.transform_settlement({"confidence": -0.5}, provider="lsports")
    assert low["confidence"] == 0.0
    high = transformer.transform_settlement({"confidence": 1.5}, provider="lsports")
    assert high["confidence"] == 1.0


def test_transform_stats_tracking(transformer):
    before = transformer.get_stats()
    transformer.transform_odds({"odds": 2.0}, provider="lsports")
    after = transformer.get_stats()
    assert after["odds_transformed"] == before["odds_transformed"] + 1
    transformer.reset_stats()
    assert transformer.get_stats()["odds_transformed"] == 0


# ---------------------------------------------------------------------------
# Deduplicator contract semantics
# ---------------------------------------------------------------------------


def test_deduplicator_first_seen_is_new(fake_deduplicator):
    assert asyncio.run(fake_deduplicator.check_and_store("odds:lsports:evt_1:7")) is False


def test_deduplicator_second_seen_is_duplicate(fake_deduplicator):
    asyncio.run(fake_deduplicator.check_and_store("odds:lsports:evt_1:7"))
    assert asyncio.run(fake_deduplicator.check_and_store("odds:lsports:evt_1:7")) is True


def test_deduplicator_different_keys_independent(fake_deduplicator):
    assert asyncio.run(fake_deduplicator.check_and_store("key_a")) is False
    assert asyncio.run(fake_deduplicator.check_and_store("key_b")) is False
    assert asyncio.run(fake_deduplicator.check_and_store("key_a")) is True


# ---------------------------------------------------------------------------
# process_odds / process_event / process_settlement pipeline
# ---------------------------------------------------------------------------
#
# Note on data shape: process_* validates the raw input against the canonical (camelCase)
# schema *before* transforming. So rejection tests use canonical-format data, while the
# transform/dedup/forward acceptance tests monkeypatch schema_validator.validate to pass and
# feed provider-format (lsports snake_case) input that the transformer understands.


@pytest.fixture
def wired_main(monkeypatch, fake_deduplicator, forward_spy, tmp_path):
    """Wire main.py globals with test doubles and monkeypatch forward_to_n8n.

    Schema validation is left real by default. Acceptance tests monkeypatch
    schema_validator.validate to (True, []) when they want to exercise the
    transform/dedup/forward path with provider-format input.
    """
    import ingestion.main as main
    from ingestion.n8n_forwarder import N8nForwarder

    validator = SchemaValidator(str(tmp_path / "schemas"))
    asyncio.run(validator.load_schemas())
    main.schema_validator = validator
    main.canonical_transformer = CanonicalTransformer()
    main.deduplicator = fake_deduplicator
    main.n8n_forwarder = N8nForwarder(dlq_redis=None)
    monkeypatch.setattr(main.n8n_forwarder, "forward_to_n8n", forward_spy)
    return main, forward_spy


@pytest.mark.asyncio
async def test_process_odds_valid_returns_processed(
    wired_main, sample_provider_odds, monkeypatch
):
    main, spy = wired_main
    monkeypatch.setattr(main.schema_validator, "validate", lambda st, data: (True, []))
    result = await main.process_odds(sample_provider_odds)
    assert result["status"] == "processed"
    assert result["eventId"] == "evt_1001"
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == "odds"


@pytest.mark.asyncio
async def test_process_odds_invalid_returns_rejected(wired_main, sample_canonical_odds):
    main, spy = wired_main
    invalid = dict(sample_canonical_odds)
    invalid["odds"] = 0.5  # below schema minimum 1.01
    result = await main.process_odds(invalid)
    assert result["status"] == "rejected"
    assert result["reason"] == "validation_failed"
    assert len(spy.calls) == 0


@pytest.mark.asyncio
async def test_process_odds_duplicate_skips_forwarding(
    wired_main, sample_provider_odds, monkeypatch
):
    main, spy = wired_main
    monkeypatch.setattr(main.schema_validator, "validate", lambda st, data: (True, []))
    await main.process_odds(sample_provider_odds)
    result = await main.process_odds(sample_provider_odds)
    assert result["status"] == "duplicate"
    assert len(spy.calls) == 1  # forwarded only once


@pytest.mark.asyncio
async def test_process_event_valid(wired_main, sample_provider_event, monkeypatch):
    main, spy = wired_main
    monkeypatch.setattr(main.schema_validator, "validate", lambda st, data: (True, []))
    result = await main.process_event(sample_provider_event)
    assert result["status"] == "processed"
    assert result["eventId"] == "evt_1001"


@pytest.mark.asyncio
async def test_process_settlement_valid(
    wired_main, sample_provider_settlement, monkeypatch
):
    main, spy = wired_main
    monkeypatch.setattr(main.schema_validator, "validate", lambda st, data: (True, []))
    result = await main.process_settlement(sample_provider_settlement)
    assert result["status"] == "processed"
    assert result["eventId"] == "evt_1001"
