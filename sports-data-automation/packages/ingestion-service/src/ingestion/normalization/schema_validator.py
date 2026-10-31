"""Schema validator for incoming sports data."""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
import jsonschema
from jsonschema import validate, ValidationError

logger = logging.getLogger(__name__)


class SchemaValidator:
    """Validates incoming data against JSON schemas."""

    def __init__(self, schema_registry_path: str):
        self.schema_registry_path = Path(schema_registry_path)
        self.schemas: Dict[str, Dict[str, Any]] = {}
        self.compiled_schemas: Dict[str, Any] = {}

    async def load_schemas(self):
        """Load all schemas from registry."""
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
        """Create default schemas if registry doesn't exist."""
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
        """Validate data against schema."""
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
        """Validate and return detailed results."""
        valid, errors = self.validate(schema_type, data)
        return {
            "valid": valid,
            "schema_type": schema_type,
            "errors": errors,
            "error_count": len(errors),
        }

    def get_schema(self, schema_type: str) -> Optional[Dict[str, Any]]:
        """Get raw schema by type."""
        return self.schemas.get(schema_type)

    def list_schemas(self) -> List[str]:
        """List available schema types."""
        return list(self.schemas.keys())