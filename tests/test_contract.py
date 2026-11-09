"""
tests/test_contract.py

FILE HEADER
-----------
Business problem this file solves:
    packages/canonical-types/src/types.ts (TypeScript) and
    packages/canonical-types/python/sports_automation/types.py (Python) are manual mirrors:
    no codegen keeps them in sync. A field added to one side but not the other silently breaks
    the TS<->Python contract between the Python ingestion service and the TypeScript n8n nodes.
    This contract test parses both files and asserts that every shared data model has identical
    field sets (modulo snake_case <-> camelCase naming), so contract drift is caught in CI.

Where it sits in the flow:
    tests/test_contract.py — stands between the TypeScript and Python canonical-type
    definitions; fails when the two diverge.

What calls it / what it calls:
    pytest. Reads types.ts and types.py as text; parses interfaces and Pydantic models.
    No runtime imports of the packages required.

Language conventions:
    Python 3.11+. pytest.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
TS_PATH = (
    _REPO_ROOT
    / "sports-data-automation"
    / "packages"
    / "canonical-types"
    / "src"
    / "types.ts"
)
PY_PATH = (
    _REPO_ROOT
    / "sports-data-automation"
    / "packages"
    / "canonical-types"
    / "python"
    / "sports_automation"
    / "types.py"
)

# Python (snake_case) model -> TypeScript (camelCase) interface that must stay in sync.
MODEL_MAP = {
    "Team": "Team",
    "PeriodScore": "PeriodScore",
    "Score": "Score",
    "CanonicalEvent": "CanonicalEvent",
    "CanonicalOdds": "CanonicalOdds",
    "SettlementResult": "SettlementResult",
    "Alert": "Alert",
    "Discrepancy": "Discrepancy",
    "ReconciliationReport": "ReconciliationReport",
    "IngestionMetrics": "IngestionMetrics",
    "AuthConfig": "AuthConfig",
    "RateLimitConfig": "RateLimitConfig",
    "ProviderConfig": "ProviderConfig",
    "NormalizationRule": "NormalizationRule",
    "WorkflowError": "WorkflowError",
    "WorkflowExecution": "WorkflowExecution",
    "RuleCondition": "RuleCondition",
    "SettlementRule": "SettlementRule",
    "SettlementRuleSet": "SettlementRuleSet",
    "FewShotExample": "FewShotExample",
    "LLMAlertRequest": "LLMAlertRequest",
    "LLMAlertResponse": "LLMAlertResponse",
    "AlertEvaluationResult": "AlertEvaluationResult",
    "ReconciliationJob": "ReconciliationJob",
    "ChecksumRecord": "ChecksumRecord",
}


def to_camel(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def parse_ts_interfaces(text: str) -> dict[str, set[str]]:
    interfaces: dict[str, set[str]] = {}
    for m in re.finditer(
        r"export\s+interface\s+([A-Za-z_]\w*)\s*\{([^}]*)\}", text, re.DOTALL
    ):
        name = m.group(1)
        body = m.group(2)
        fields = set()
        for line in body.splitlines():
            fm = re.match(r"\s*([A-Za-z_]\w*)\??\s*:", line)
            if fm:
                fields.add(fm.group(1))
        interfaces[name] = fields
    return interfaces


def parse_py_models(text: str) -> dict[str, set[str]]:
    models: dict[str, set[str]] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"class ([A-Za-z_]\w*)\(BaseModel\):", lines[i])
        if m:
            name = m.group(1)
            fields = set()
            j = i + 1
            while j < len(lines):
                line = lines[j]
                stripped = line.strip()
                if stripped and not line.startswith((" ", "\t")):
                    break  # top-level statement ends the class body
                fm = re.match(r"\s{4}([A-Za-z_]\w*)\s*:", line)
                if fm:
                    field_name = fm.group(1)
                    # Skip docstring section headers (ALL CAPS words like WHAT/WHY/EXAMPLE);
                    # real Pydantic fields are snake_case.
                    if not field_name.isupper():
                        fields.add(field_name)
                j += 1
            models[name] = fields
            i = j
        else:
            i += 1
    return models


@pytest.fixture
def ts_interfaces():
    return parse_ts_interfaces(TS_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def py_models():
    return parse_py_models(PY_PATH.read_text(encoding="utf-8"))


def test_files_exist():
    assert TS_PATH.is_file(), f"missing {TS_PATH}"
    assert PY_PATH.is_file(), f"missing {PY_PATH}"


def test_every_model_exists_on_both_sides(ts_interfaces, py_models):
    for py_name, ts_name in MODEL_MAP.items():
        assert py_name in py_models, f"Python model {py_name} missing from types.py"
        assert ts_name in ts_interfaces, f"TS interface {ts_name} missing from types.ts"


@pytest.mark.parametrize("py_name", sorted(MODEL_MAP))
def test_ts_and_python_fields_align(py_name, ts_interfaces, py_models):
    ts_name = MODEL_MAP[py_name]
    py_fields = {to_camel(f) for f in py_models.get(py_name, set())}
    ts_fields = set(ts_interfaces.get(ts_name, set()))
    missing_in_ts = py_fields - ts_fields
    missing_in_py = ts_fields - py_fields
    assert not missing_in_ts, (
        f"{py_name}: fields present in Python but missing in TypeScript: "
        f"{sorted(missing_in_ts)}"
    )
    assert not missing_in_py, (
        f"{py_name}: fields present in TypeScript but missing in Python: "
        f"{sorted(missing_in_py)}"
    )
