"""Canonical transformer - converts provider-specific formats to internal canonical format."""
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class CanonicalTransformer:
    """Transforms provider-specific data to canonical internal format."""

    # Provider-specific field mappings
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
        self.transform_stats = {
            "odds_transformed": 0,
            "events_transformed": 0,
            "settlements_transformed": 0,
            "errors": 0,
        }

    def transform_odds(self, data: Dict[str, Any], provider: str = "unknown") -> Dict[str, Any]:
        """Transform odds to canonical format."""
        try:
            # Get provider mapping
            mapping = self.PROVIDER_MAPPINGS.get(provider, self.PROVIDER_MAPPINGS["lsports"]).get("odds", {})

            # Apply field mapping
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
        """Transform event to canonical format."""
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
        """Transform settlement to canonical format."""
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
        """Convert odds to decimal format."""
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
            # Handle string format "5/1" or numeric
            if isinstance(odds, str) and "/" in odds:
                num, den = odds.split("/")
                return float(num) / float(den) + 1
            return float(odds) + 1
        else:
            return float(odds)  # Assume decimal

    def _transform_team(self, team: Any) -> Dict[str, Any]:
        """Transform team data to canonical format."""
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
        """Transform score to canonical format."""
        if isinstance(score, dict):
            return {
                "home": int(score.get("home", 0)),
                "away": int(score.get("away", 0)),
                "periodScores": score.get("periodScores") or score.get("period_scores") or [],
            }
        return {"home": 0, "away": 0, "periodScores": []}

    def _parse_timestamp(self, timestamp: Any) -> str:
        """Parse timestamp to ISO 8601 format."""
        if isinstance(timestamp, str):
            # Try various formats
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
            # If already ISO format, return as-is
            if "T" in timestamp:
                return timestamp
        elif isinstance(timestamp, (int, float)):
            # Unix timestamp
            dt = datetime.fromtimestamp(timestamp)
            return dt.isoformat() + "Z"
        elif isinstance(timestamp, datetime):
            return timestamp.isoformat() + "Z"

        return datetime.utcnow().isoformat() + "Z"

    def _get_nested_value(self, data: Dict[str, Any], path: str) -> Any:
        """Get value from nested dict using dot notation."""
        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current

    def get_stats(self) -> Dict[str, int]:
        """Get transformation statistics."""
        return self.transform_stats.copy()

    def reset_stats(self):
        """Reset transformation statistics."""
        for key in self.transform_stats:
            self.transform_stats[key] = 0