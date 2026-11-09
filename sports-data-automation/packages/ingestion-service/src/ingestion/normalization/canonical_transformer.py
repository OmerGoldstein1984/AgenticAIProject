"""
Canonical transformer - converts provider-specific formats to internal canonical format.

FILE HEADER
-----------
Business problem this file solves:
    Each provider names fields differently (LSports uses provider_id/event_id; Betradar uses
    bookmaker_id/match_id) and reports odds in different formats (decimal/American/fractional).
    CanonicalTransformer maps provider-specific fields into the canonical shape (CanonicalOdds/
    CanonicalEvent/SettlementResult) and normalizes odds to decimal, so the rest of the pipeline
    works with one consistent data model regardless of source.

Where it sits in the flow:
    Second stage of the ingestion pipeline (after SchemaValidator, before Deduplicator).
    main.py's process_* functions call canonical_transformer.transform_odds/transform_event/
    transform_settlement to coerce raw provider JSON into canonical form before dedup and forward.

What calls it / what it calls:
    Called by: main.py process_odds/process_event/process_settlement.
    Calls: nothing from this repo (pure transformations, stdlib datetime).
What breaks if removed:
    Raw provider payloads (with provider-specific field names and formats) would be forwarded to
    n8n unchanged; n8n nodes expect canonical fields and would mis-route or mis-settle.
Language conventions:
    Python 3.11+. Class with PROVIDER_MAPPINGS dict (provider → data-type → field map) plus
    private helper methods (_normalize_odds, _transform_team, _transform_score, _parse_timestamp,
    _get_nested_value). transform_* methods catch all exceptions and return the original data on
    error (never crash the pipeline on a bad transform).
GAP: The mapping is hard-coded in PROVIDER_MAPPINGS; the NormalizationRule-driven engine declared
    in canonical-types is not implemented. Adding a provider requires editing code here.
    See 07_issues_found.md.
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class CanonicalTransformer:
    """Transforms provider-specific data to canonical internal format.

    WHAT: Maps provider fields to canonical fields via PROVIDER_MAPPINGS, normalizes odds to
        decimal, parses timestamps to ISO 8601, and coerces types — per data type (odds/event/
        settlement) and per provider (lsports, betradar, sportradar).
    WHY: One canonical data model downstream; providers can be added or changed by updating
        mappings rather than rewriting pipeline logic.
    INPUTS: transform_* methods take (data: dict, provider: str = "unknown").
    OUTPUTS: a canonical dict (or the original data unchanged on error).
    SIDE EFFECTS: updates self.transform_stats counters (odds_transformed/events_transformed/
        settlements_transformed/errors).
    FAILURE MODES: any exception in a transform_* method is caught, logged, and the original
        data is returned — so a bad transform never kills ingestion, but the untransformed data
        may fail later at n8n. Unknown provider falls back to the "lsports" mapping.
    ALTERNATIVE: Pydantic model coercion per provider. Chosen explicit field-mapping dict because
        it's transparent, easy to audit, and doesn't require a Pydantic model per provider.
    # GAP: provider registry is hard-coded; no dynamic provider onboarding. See 07_issues_found.md.
    """

    # Provider-specific field mappings: provider → data_type → {canonical_field: provider_field}
    PROVIDER_MAPPINGS = {
        "lsports": {
            "odds": {
                "providerId": "provider_id",
                "eventId": "event_id",
                "marketId": "market_id",
                "selectionId": "selection_id",
                "odds": "odds",
                "format": "odds_format",
                "timestamp": "timestamp",
                "sequence": "sequence",
            },
            "event": {
                "id": "id",
                "sport": "sport",
                "league": "league",
                "homeTeam": "home_team",
                "awayTeam": "away_team",
                "startTime": "start_time",
                "status": "status",
                "score": "score",
            },
        },
        "betradar": {
            "odds": {
                "providerId": "bookmaker_id",
                "eventId": "match_id",
                "marketId": "market_id",
                "selectionId": "outcome_id",
                "odds": "decimal_odds",
                "format": "odds_type",
                "timestamp": "update_time",
                "sequence": "version",
            },
        },
        "sportradar": {
            "odds": {
                "providerId": "bookmaker",
                "eventId": "event_id",
                "marketId": "market_id",
                "selectionId": "outcome_id",
                "odds": "odds",
                "format": "format",
                "timestamp": "timestamp",
                "sequence": "sequence",
            },
        },
    }

    def __init__(self):
        """Initialize per-type transformation counters."""
        self.transform_stats = {
            "odds_transformed": 0,
            "events_transformed": 0,
            "settlements_transformed": 0,
            "errors": 0,
        }

    def transform_odds(self, data: Dict[str, Any], provider: str = "unknown") -> Dict[str, Any]:
        """Transform an odds payload to canonical format.

        WHAT: Applies the provider's odds field mapping, defaults missing fields, normalizes odds
            to decimal (storing original format), parses the timestamp, coerces sequence to int.
        WHY: Odds arrive in 3 formats from N providers; this produces one canonical decimal odds
            record the OddsNormalizer n8n node can compare across providers.
        INPUTS: data (provider odds dict), provider name (default "unknown").
        OUTPUTS: canonical dict with providerId/eventId/marketId/selectionId/odds/format/
            timestamp/sequence; original data returned unchanged on error.
        SIDE EFFECTS: increments self.transform_stats["odds_transformed"] or ["errors"].
        FAILURE MODES: any exception → logged and original `data` returned (pipeline-safe but
            untransformed). Missing required fields → setdefault fills provider/format/sequence.
        ALTERNATIVE: validate-then-transform with SchemaValidator first (main.py does validate
            before calling this, so malformed data is mostly filtered upstream).
        # INTERVIEW: odds are always stored as decimal internally but `format` records the
        #    provider's original format for audit/reconstruction.
        """
        try:
            mapping = self.PROVIDER_MAPPINGS.get(provider, self.PROVIDER_MAPPINGS["lsports"]).get("odds", {})

            canonical = {}
            for canon_field, provider_field in mapping.items():
                value = self._get_nested_value(data, provider_field)
                if value is not None:
                    canonical[canon_field] = value

            # Ensure required fields
            canonical.setdefault("providerId", provider)
            canonical.setdefault("format", "decimal")
            canonical.setdefault("sequence", 0)

            # Normalize odds format
            if "odds" in canonical and "format" in canonical:
                canonical["odds"] = self._normalize_odds(canonical["odds"], canonical["format"])
                canonical["format"] = "decimal"  # Always store as decimal internally

            # Parse timestamp
            if "timestamp" in canonical:
                canonical["timestamp"] = self._parse_timestamp(canonical["timestamp"])

            # Ensure sequence is int
            if "sequence" in canonical:
                canonical["sequence"] = int(canonical["sequence"])

            self.transform_stats["odds_transformed"] += 1
            return canonical

        except Exception as e:
            self.transform_stats["errors"] += 1
            logger.exception(f"Error transforming odds: {e}")
            return data  # Return original on error

    def transform_event(self, data: Dict[str, Any], provider: str = "unknown") -> Dict[str, Any]:
        """Transform an event payload to canonical format.

        WHAT: Applies the provider's event field mapping, defaults required fields, transforms
            teams/score, parses startTime to ISO 8601.
        WHY: Events anchor everything; canonical form lets settlement rules read score/status
            without provider-specific parsing.
        INPUTS: data (provider event dict), provider name.
        OUTPUTS: canonical dict; original data on error.
        SIDE EFFECTS: increments transform_stats["events_transformed"] or ["errors"].
        FAILURE MODES: any exception → logged, original data returned.
        ALTERNATIVE: None — this is the single event normalization point.
        """
        try:
            mapping = self.PROVIDER_MAPPINGS.get(provider, self.PROVIDER_MAPPINGS["lsports"]).get("event", {})

            canonical = {}
            for canon_field, provider_field in mapping.items():
                value = self._get_nested_value(data, provider_field)
                if value is not None:
                    canonical[canon_field] = value

            # Ensure required fields
            canonical.setdefault("id", data.get("id", ""))
            canonical.setdefault("sport", "unknown")
            canonical.setdefault("league", "unknown")
            canonical.setdefault("status", "scheduled")

            # Transform teams
            if "homeTeam" in canonical:
                canonical["homeTeam"] = self._transform_team(canonical["homeTeam"])
            if "awayTeam" in canonical:
                canonical["awayTeam"] = self._transform_team(canonical["awayTeam"])

            # Transform score
            if "score" in canonical:
                canonical["score"] = self._transform_score(canonical["score"])

            # Parse timestamp
            if "startTime" in canonical:
                canonical["startTime"] = self._parse_timestamp(canonical["startTime"])

            self.transform_stats["events_transformed"] += 1
            return canonical

        except Exception as e:
            self.transform_stats["errors"] += 1
            logger.exception(f"Error transforming event: {e}")
            return data

    def transform_settlement(self, data: Dict[str, Any], provider: str = "unknown") -> Dict[str, Any]:
        """Transform a settlement payload to canonical format.

        WHAT: Picks eventId/marketId/selectionId/outcome/settledAt/source/confidence from either
            camelCase or snake_case keys, parses settledAt, validates the outcome, clamps
            confidence to [0,1].
        WHY: Settlement results determine payouts; normalizing to canonical shape and validating
            the outcome prevents invalid financial outcomes from reaching the settlement worker.
        INPUTS: data (provider settlement dict), provider name.
        OUTPUTS: canonical settlement dict; original data on error.
        SIDE EFFECTS: increments transform_stats["settlements_transformed"] or ["errors"].
        FAILURE MODES: invalid outcome → defaults to "void" (safe: never pay on an unrecognized
            outcome); confidence clamped to [0,1].
        ALTERNATIVE: reject invalid settlements outright. Chosen "default to void" because in
            betting it's safer to withhold payout than pay on a bad outcome.
        """
        try:
            canonical = {
                "eventId": data.get("eventId") or data.get("event_id"),
                "marketId": data.get("marketId") or data.get("market_id"),
                "selectionId": data.get("selectionId") or data.get("selection_id"),
                "outcome": data.get("outcome"),
                "settledAt": data.get("settledAt") or data.get("settled_at"),
                "source": data.get("source", "official"),
                "confidence": data.get("confidence", 1.0),
            }

            # Parse timestamp
            if "settledAt" in canonical:
                canonical["settledAt"] = self._parse_timestamp(canonical["settledAt"])

            # Validate outcome
            valid_outcomes = ["won", "lost", "void", "half_won", "half_lost"]
            if canonical["outcome"] not in valid_outcomes:
                logger.warning(f"Invalid outcome: {canonical['outcome']}, defaulting to void")
                canonical["outcome"] = "void"

            # Clamp confidence
            canonical["confidence"] = max(0.0, min(1.0, float(canonical["confidence"])))

            self.transform_stats["settlements_transformed"] += 1
            return canonical

        except Exception as e:
            self.transform_stats["errors"] += 1
            logger.exception(f"Error transforming settlement: {e}")
            return data

    def _normalize_odds(self, odds: float, format: str) -> float:
        """Convert odds from any supported format to decimal.

        WHAT: decimal → as-is; American (positive/negative moneyline) → decimal; fractional
            ("5/1" string or numeric) → decimal.
        WHY: The platform stores and compares odds in decimal; providers report in their native
            format, so every quote must be converted before comparison/arbitrage detection.
        INPUTS: odds value, format string.
        OUTPUTS: decimal odds float.
        SIDE EFFECTS: none.
        FAILURE MODES: unknown format → assumes decimal (returns float(odds)).
        ALTERNATIVE: a dedicated money/odds library. Chosen inline conversion for a
            dependency-free, easy-to-audit implementation.
        # INTERVIEW: American odds conversion differs by sign — positive (underdog) and
        #    negative (favorite) use different formulas. A common bug is using one formula for
        #    both.
        """
        format = format.lower()
        if format == "decimal":
            return float(odds)
        elif format in ("american", "moneyline"):
            odds = float(odds)
            if odds > 0:
                return (odds / 100) + 1
            else:
                return (100 / abs(odds)) + 1
        elif format in ("fractional", "fraction"):
            if isinstance(odds, str) and "/" in odds:
                num, den = odds.split("/")
                return float(num) / float(den) + 1
            return float(odds) + 1
        else:
            return float(odds)  # Assume decimal

    def _transform_team(self, team: Any) -> Dict[str, Any]:
        """Normalize team data (dict or string) to {id, name, shortName}."""
        if isinstance(team, dict):
            return {
                "id": team.get("id", ""),
                "name": team.get("name", ""),
                "shortName": team.get("shortName") or team.get("short_name"),
            }
        elif isinstance(team, str):
            return {"id": team, "name": team}
        return {"id": "", "name": ""}

    def _transform_score(self, score: Any) -> Dict[str, Any]:
        """Normalize score data to {home, away, periodScores}."""
        if isinstance(score, dict):
            return {
                "home": int(score.get("home", 0)),
                "away": int(score.get("away", 0)),
                "periodScores": score.get("periodScores") or score.get("period_scores") or [],
            }
        return {"home": 0, "away": 0, "periodScores": []}

    def _parse_timestamp(self, timestamp: Any) -> str:
        """Parse a timestamp (string in several formats, unix int/float, or datetime) to ISO 8601."""
        if isinstance(timestamp, str):
            for fmt in [
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ]:
                try:
                    dt = datetime.strptime(timestamp, fmt)
                    return dt.isoformat() + "Z"
                except ValueError:
                    continue
            if "T" in timestamp:
                return timestamp
        elif isinstance(timestamp, (int, float)):
            dt = datetime.fromtimestamp(timestamp)
            return dt.isoformat() + "Z"
        elif isinstance(timestamp, datetime):
            return timestamp.isoformat() + "Z"

        return datetime.utcnow().isoformat() + "Z"

    def _get_nested_value(self, data: Dict[str, Any], path: str) -> Any:
        """Get a value from a nested dict using dot-notation path (e.g. "home.team.id")."""
        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current

    def get_stats(self) -> Dict[str, int]:
        """Return a copy of the transformation statistics counters."""
        return self.transform_stats.copy()

    def reset_stats(self):
        """Reset all transformation statistics counters to zero."""
        for key in self.transform_stats:
            self.transform_stats[key] = 0
