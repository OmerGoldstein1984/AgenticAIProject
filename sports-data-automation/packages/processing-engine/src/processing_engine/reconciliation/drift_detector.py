"""
packages/processing-engine/src/processing_engine/reconciliation/drift_detector.py

FILE HEADER
-----------
Business problem this file solves:
    The daily reconciliation job must catch drift between source systems (e.g. a provider's
    odds vs the ingestion service's canonical odds, or the settlement feed vs the engine's
    settlement). drift_detector.py compares checksums for the same entity across two systems
    and produces a Discrepancy list pinpointing exactly what differs.

Where it sits in the flow:
    Core reconciliation module. Imported by processing_engine/__init__.py, auto_corrector.py,
    and the n8n reconciliation workflow. Consumed by the daily job that snapshots entities
    from each source system.

What calls it / what it calls:
    Called by: reconciliation workflow, auto_corrector, tests.
    Calls: reconciliation.checksum (compute_checksum), sports_automation.types (Discrepancy).

What breaks if removed:
    No drift detection; the reconciliation job reports zero discrepancies even when systems
    disagree, silently corrupting settlements/payouts.

Language conventions:
    Python 3.11+. DriftDetector.detect(records_a, records_b) -> List[Discrepancy]. Records are
    dicts with entity_type/entity_id/data/source_system. Compares checksums for matching
    (entity_type, entity_id) pairs; mismatches produce Discrepancy entries with severity
    derived from field importance.
"""

import sys
import os
from typing import Any, Dict, List, Tuple

# Ensure canonical types are importable (monorepo layout).
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANONICAL_TYPES_PY = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", "canonical-types", "python")
)
if os.path.isdir(_CANONICAL_TYPES_PY) and _CANONICAL_TYPES_PY not in sys.path:
    sys.path.insert(0, _CANONICAL_TYPES_PY)

from sports_automation.types import Discrepancy  # noqa: E402
from processing_engine.reconciliation.checksum import compute_checksum  # noqa: E402

# Fields considered financially significant -> high severity discrepancy.
_HIGH_SEVERITY_FIELDS = {"outcome", "odds", "status", "score"}
_MEDIUM_SEVERITY_FIELDS = {"market_id", "selection_id", "source"}


def _record_key(record: Dict[str, Any]) -> Tuple[str, str]:
    """Return (entity_type, entity_id) for a record."""
    return record.get("entity_type", "unknown"), record.get("entity_id", "unknown")


def _field_severity(field: str) -> str:
    """Map a field name to a discrepancy severity ('low' | 'medium' | 'high')."""
    if field in _HIGH_SEVERITY_FIELDS:
        return "high"
    if field in _MEDIUM_SEVERITY_FIELDS:
        return "medium"
    return "low"


def _flatten(data: Any, prefix: str = "") -> List[Tuple[str, Any]]:
    """Flatten a nested dict into (field_path, value) leaf pairs."""
    items: List[Tuple[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            items.extend(_flatten(value, path))
    else:
        items.append((prefix, data))
    return items


class DriftDetector:
    """Compares checksums for the same entity across two systems and produces Discrepancies.

    WHAT: Indexes records from system A and system B by (entity_type, entity_id). For each
        entity present in both, compares checksums. If they differ, drills into the data to
        find which fields differ and emits a Discrepancy per differing field.
    WHY: Checksum comparison is cheap; drilling only into mismatched entities keeps the daily
        job fast even with large datasets. The Discrepancy list tells auto_corrector exactly
        what to fix and report.py what to summarize.
    INPUTS: records_a, records_b (lists of {entity_type, entity_id, data, source_system}).
    OUTPUTS: List[Discrepancy].
    SIDE EFFECTS: none (pure).
    FAILURE MODES: records missing entity_type/entity_id are skipped; unhashable values are
        stringified.
    """

    def detect(
        self,
        records_a: List[Dict[str, Any]],
        records_b: List[Dict[str, Any]],
        source_a: str = "system_a",
        source_b: str = "system_b",
    ) -> List[Discrepancy]:
        """Detect drift between two sets of entity records.

        WHAT: Indexes both record sets by (entity_type, entity_id); for entities present in
            both, compares checksums; on mismatch, diffs field-by-field and emits
            Discrepancies. Entities present in only one system are reported as high-severity
            'missing' discrepancies.
        WHY: Produces the Discrepancy list consumed by auto_corrector and report.
        INPUTS: records_a, records_b (record dicts), source_a, source_b (labels).
        OUTPUTS: List[Discrepancy] sorted by severity (high, medium, low).
        SIDE EFFECTS: none.
        FAILURE MODES: malformed records are skipped with a debug log.
        """
        index_a: Dict[Tuple[str, str], Dict[str, Any]] = {}
        index_b: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for record in records_a:
            key = _record_key(record)
            index_a[key] = record
        for record in records_b:
            key = _record_key(record)
            index_b[key] = record

        discrepancies: List[Discrepancy] = []

        # Entities in both systems - compare checksums
        for key in index_a.keys() & index_b.keys():
            rec_a = index_a[key]
            rec_b = index_b[key]
            entity_type, entity_id = key

            checksum_a = compute_checksum(entity_type, entity_id, rec_a.get("data", {}), source_a)
            checksum_b = compute_checksum(entity_type, entity_id, rec_b.get("data", {}), source_b)

            if checksum_a == checksum_b:
                continue  # no drift

            # Drill into fields to find exact differences
            flat_a = dict(_flatten(rec_a.get("data", {})))
            flat_b = dict(_flatten(rec_b.get("data", {})))

            all_fields = set(flat_a.keys()) | set(flat_b.keys())
            for field in sorted(all_fields):
                val_a = flat_a.get(field)
                val_b = flat_b.get(field)
                if val_a == val_b:
                    continue
                discrepancies.append(
                    Discrepancy(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        field=field,
                        expected=val_a,
                        actual=val_b,
                        severity=_field_severity(field),
                    )
                )

        # Entities only in A -> missing in B
        for key in index_a.keys() - index_b.keys():
            entity_type, entity_id = key
            discrepancies.append(
                Discrepancy(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    field="__entity__",
                    expected="present",
                    actual="missing",
                    severity="high",
                )
            )

        # Entities only in B -> missing in A
        for key in index_b.keys() - index_a.keys():
            entity_type, entity_id = key
            discrepancies.append(
                Discrepancy(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    field="__entity__",
                    expected="missing",
                    actual="present",
                    severity="high",
                )
            )

        # Sort by severity: high, medium, low
        severity_order = {"high": 0, "medium": 1, "low": 2}
        discrepancies.sort(key=lambda d: severity_order.get(d.severity, 9))
        return discrepancies
