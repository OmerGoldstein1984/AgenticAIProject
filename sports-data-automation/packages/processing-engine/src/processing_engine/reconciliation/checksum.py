"""
packages/processing-engine/src/processing_engine/reconciliation/checksum.py

FILE HEADER
-----------
Business problem this file solves:
    Reconciliation needs a lightweight way to compare an entity across systems without
    transferring full payloads. checksum.py computes a stable SHA-256 fingerprint of an
    entity (event, odds, or settlement) so two systems can compare checksums and detect
    drift efficiently.

Where it sits in the flow:
    Core reconciliation module. Imported by processing_engine/__init__.py,
    drift_detector.py, and demo scripts. Consumed by the daily reconciliation job that
    snapshots entities from each source system and compares fingerprints.

What calls it / what it calls:
    Called by: drift_detector, report, tests.
    Calls: hashlib, json, stdlib only.

What breaks if removed:
    No checksum fingerprints; drift detection must diff full payloads (expensive) or cannot
    run at all.

Language conventions:
    Python 3.11+. compute_checksum(entity_type, entity_id, data, source_system) -> str.
    Stable serialization (sort_keys=True, canonical field ordering) so the same entity always
    yields the same checksum regardless of key order in the source dict.
"""

import hashlib
import json
from typing import Any, Dict


def _canonical_payload(entity_type: str, entity_id: str, data: Dict[str, Any]) -> str:
    """Build a stable, sorted JSON string for an entity.

    WHAT: Combines entity_type, entity_id, and data into one dict with sorted keys and
        deterministic separators, then serializes to JSON.
    WHY: Sorting keys and using fixed separators makes the fingerprint independent of key
        order and whitespace, so the same logical entity produces the same checksum across
        systems and over time.
    INPUTS: entity_type, entity_id, data.
    OUTPUTS: canonical JSON string.
    SIDE EFFECTS: none.
    """
    payload = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "data": data,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_checksum(
    entity_type: str,
    entity_id: str,
    data: Dict[str, Any],
    source_system: str,
) -> str:
    """Compute a SHA-256 checksum fingerprint of one entity in one source system.

    WHAT: Serializes entity_type/entity_id/data to canonical JSON and returns its hex
        SHA-256 digest. source_system is recorded for provenance but is not part of the
        digest (so the same entity in two systems yields comparable checksums only when the
        data matches).
    WHY: Comparing checksums across systems is how reconciliation finds drift without
        transferring full payloads — cheap and audit-friendly.
    INPUTS: entity_type ('event'|'odds'|'settlement'), entity_id, data (dict),
        source_system (str).
    OUTPUTS: hex SHA-256 checksum string.
    SIDE EFFECTS: none (pure).
    FAILURE MODES: none (default=str handles non-serializable values).
    ALTERNATIVE: HMAC with a shared secret for tamper-evidence. Chosen plain SHA-256 for
        simplicity; drift detection, not integrity protection, is the goal here.
    """
    canonical = _canonical_payload(entity_type, entity_id, data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
