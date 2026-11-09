"""
Schema validator for incoming sports data.

FILE HEADER
-----------
Business problem this file solves:
    Providers change field names, drop required fields, or send malformed JSON without warning.
    SchemaValidator validates every incoming odds/event/settlement payload against a JSON Schema
    (Draft 7) before it is transformed or forwarded, so malformed data is rejected early with a
    clear error path rather than corrupting downstream settlement and analytics.

Where it sits in the flow:
    First stage of the ingestion pipeline (before CanonicalTransformer and Deduplicator).
    main.py's process_* functions call schema_validator.validate(schema_type, data) and reject
    with status "rejected"/"validation_failed" when it returns invalid.

What calls it / what it calls:
    Called by: main.py process_odds/process_event/process_settlement.
    Calls: the jsonschema library (Draft7Validator); reads schema .json files from the registry
        directory on disk (or auto-creates default schemas).
What breaks if removed:
    Invalid provider payloads flow straight into transformation/settlement; a single bad field
    could produce wrong payouts or crash downstream code. No contract enforcement between
    providers and the platform.
Language conventions:
    Python 3.11+. jsonschema library (Draft7Validator). Schemas loaded from
    ./schemas/{odds,event,settlement}.json, auto-created on disk if missing.
GAP: The schema registry directory (./schemas) doesn't exist in the repo, so schemas are always
    auto-created in memory and written to disk at runtime — there's no versioned, reviewed
    schema source of truth. See 07_issues_found.md.
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
import jsonschema
from jsonschema import validate, ValidationError

logger = logging.getLogger(__name__)


class SchemaValidator:
    """Validates incoming data against JSON schemas.

    WHAT: Loads JSON schemas (odds/event/settlement) from a registry directory, pre-compiles
        them into Draft7Validator instances, and exposes validate(schema_type, data) returning
        (bool, list of error strings).
    WHY: Centralized, versionable contract enforcement — providers must conform to the canonical
        schema before their data enters the platform.
    INPUTS (constructor): schema_registry_path (directory of *.json schema files).
        validate(schema_type, data): schema_type in {"odds","event","settlement"} and the data dict.
    OUTPUTS: validate returns (valid: bool, errors: List[str]).
    SIDE EFFECTS: load_schemas reads files from disk and (when auto-creating) writes default
        schemas to disk; mutates self.schemas / self.compiled_schemas.
    FAILURE MODES: registry missing → warns and auto-creates defaults (degrades gracefully).
        A malformed schema file → logged error, that schema skipped (not a crash).
        Unknown schema_type → returns (True, []) — allows through (permissive default).
    ALTERNATIVE: Pydantic models for validation. Chosen JSON Schema because schemas are stored
        as files, can be versioned independently of code, and the same schema files could be
        shared with the TypeScript side.
    # GAP: unknown schema_type is permissive (allows through) — a typo in schema_type would let
    #    unvalidated data pass. See 07_issues_found.md.
    """

    def __init__(self, schema_registry_path: str):
        """Point the validator at a directory of *.json schema files."""
        self.schema_registry_path = Path(schema_registry_path)
        self.schemas: Dict[str, Dict[str, Any]] = {}
        self.compiled_schemas: Dict[str, Any] = {}

    async def load_schemas(self):
        """Load all *.json schemas from the registry; auto-create defaults if the dir is missing."""
        if not self.schema_registry_path.exists():
            logger.warning(f"Schema registry not found: {self.schema_registry_path}")
            await self._create_default_schemas()
            return

        for schema_file in self.schema_registry_path.glob("*.json"):
            try:
                with open(schema_file) as f:
                    schema = json.load(f)
                schema_type = schema_file.stem
                self.schemas[schema_type] = schema
                # Pre-compile for performance
                self.compiled_schemas[schema_type] = jsonschema.Draft7Validator(schema)
                logger.info(f"Loaded schema: {schema_type}")
            except Exception as e:
                logger.error(f"Failed to load schema {schema_file}: {e}")

        logger.info(f"Loaded {len(self.schemas)} schemas")

    async def _create_default_schemas(self):
        """Create default schemas if the registry doesn't exist, writing them to disk."""
        self.schema_registry_path.mkdir(parents=True, exist_ok=True)

        # Odds schema
        odds_schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Odds Feed",
            "type": "object",
            "required": ["providerId", "eventId", "marketId", "selectionId", "odds", "format", "timestamp", "sequence"],
            "properties": {
                "providerId": {"type": "string", "minLength": 1},
                "eventId": {"type": "string", "minLength": 1},
                "marketId": {"type": "string", "minLength": 1},
                "selectionId": {"type": "string", "minLength": 1},
                "odds": {"type": "number", "minimum": 1.01, "maximum": 10000},
                "format": {"type": "string", "enum": ["decimal", "american", "fractional"]},
                "timestamp": {"type": "string", "format": "date-time"},
                "sequence": {"type": "integer", "minimum": 0},
                "metadata": {"type": "object"},
            },
        }

        # Event schema
        event_schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Event Feed",
            "type": "object",
            "required": ["id", "sport", "league", "homeTeam", "awayTeam", "startTime", "status"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "sport": {"type": "string", "minLength": 1},
                "league": {"type": "string", "minLength": 1},
                "homeTeam": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "shortName": {"type": "string"},
                    },
                },
                "awayTeam": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "shortName": {"type": "string"},
                    },
                },
                "startTime": {"type": "string", "format": "date-time"},
                "status": {"type": "string", "enum": ["scheduled", "live", "half_time", "ended", "cancelled", "postponed", "abandoned"]},
                "score": {
                    "type": "object",
                    "properties": {
                        "home": {"type": "integer", "minimum": 0},
                        "away": {"type": "integer", "minimum": 0},
                        "periodScores": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "period": {"type": "string"},
                                    "home": {"type": "integer"},
                                    "away": {"type": "integer"},
                                },
                            },
                        },
                    },
                },
                "metadata": {"type": "object"},
            },
        }

        # Settlement schema
        settlement_schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Settlement Feed",
            "type": "object",
            "required": ["eventId", "marketId", "selectionId", "outcome", "settledAt", "source"],
            "properties": {
                "eventId": {"type": "string", "minLength": 1},
                "marketId": {"type": "string", "minLength": 1},
                "selectionId": {"type": "string", "minLength": 1},
                "outcome": {"type": "string", "enum": ["won", "lost", "void", "half_won", "half_lost"]},
                "settledAt": {"type": "string", "format": "date-time"},
                "source": {"type": "string", "enum": ["official", "manual", "auto_reconciled"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        }

        schemas = {
            "odds": odds_schema,
            "event": event_schema,
            "settlement": settlement_schema,
        }

        for name, schema in schemas.items():
            self.schemas[name] = schema
            self.compiled_schemas[name] = jsonschema.Draft7Validator(schema)
            # Save to disk
            schema_file = self.schema_registry_path / f"{name}.json"
            with open(schema_file, "w") as f:
                json.dump(schema, f, indent=2)
            logger.info(f"Created default schema: {name}")

    def validate(self, schema_type: str, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate data against the compiled schema for schema_type.

        WHAT: Iterates validator.iter_errors(data) and returns (True, []) if valid or
            (False, [error strings]) listing each validation failure with its JSON path.
        WHY: Gives a structured accept/reject decision plus human-readable error paths for
            logging and metrics (events_validated_total{result=valid|invalid}).
        INPUTS: schema_type ("odds"|"event"|"settlement"), data dict.
        OUTPUTS: (bool, List[str]) — valid flag and list of "path: message" error strings.
        SIDE EFFECTS: none (pure validation).
        FAILURE MODES: unknown schema_type → returns (True, []) permissively (see GAP).
        ALTERNATIVE: raise on first error. Chosen iter_errors to collect ALL validation problems
            at once so the operator sees every issue, not just the first.
        # INTERVIEW: Draft7Validator is pre-compiled once at load, so validate() is fast per
        #    event — important because odds arrive every 500ms-2s from multiple providers.
        """
        if schema_type not in self.compiled_schemas:
            logger.warning(f"No schema for type: {schema_type}")
            return True, []  # Allow if no schema

        validator = self.compiled_schemas[schema_type]
        errors = []

        for error in validator.iter_errors(data):
            error_path = ".".join(str(p) for p in error.path) if error.path else "root"
            errors.append(f"{error_path}: {error.message}")

        return len(errors) == 0, errors

    def validate_with_details(self, schema_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and return a detailed result dict (valid, schema_type, errors, error_count)."""
        valid, errors = self.validate(schema_type, data)
        return {
            "valid": valid,
            "schema_type": schema_type,
            "errors": errors,
            "error_count": len(errors),
        }

    def get_schema(self, schema_type: str) -> Optional[Dict[str, Any]]:
        """Get the raw (uncompiled) schema dict by type."""
        return self.schemas.get(schema_type)

    def list_schemas(self) -> List[str]:
        """List available schema type names."""
        return list(self.schemas.keys())
