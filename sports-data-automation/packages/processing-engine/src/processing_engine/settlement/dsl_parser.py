"""
packages/processing-engine/src/processing_engine/settlement/dsl_parser.py

FILE HEADER
-----------
Business problem this file solves:
    Settlement business logic must be expressible declaratively (as JSON) so traders can change
    void/won/lost conditions without a code deploy. dsl_parser.py parses a rule JSON document
    (a SettlementRuleSet or a list of SettlementRule dicts) into a RuleCondition tree that the
    rule engine can evaluate against an event + odds.

Where it sits in the flow:
    Leaf module under settlement/. Imported by rule_engine.py (to build RuleCondition trees
    from JSON) and by processing_engine/__init__.py. Consumers feed rule JSON produced by the
    n8n settlement-worker or stored in a rule DB.

What calls it / what it calls:
    Called by: rule_engine, tests, demo scripts.
    Calls: sports_automation.types.RuleCondition (canonical), stdlib only otherwise.

What breaks if removed:
    Rule JSON cannot be converted into an evaluatable condition tree; the settlement worker
    falls back to default_outcome for every match (never auto-settles).

Language conventions:
    Python 3.11+. Pure functions; raises ValueError on malformed rule JSON so invalid rules
    never silently produce wrong settlements. Comparators supported: eq, ne, gt, gte, lt, lte,
    in, contains. Operators supported: and, or, not.

GAP: hot-reload of rule sets from a remote DB is declared in the n8n node but not implemented;
    only embedded/JSON rule sets parse here. See 07_issues_found.md.
"""

import os
import sys
from typing import Any, Dict, List, Optional

# Ensure canonical types (RuleCondition) are importable (monorepo layout).
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANONICAL_TYPES_PY = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", "canonical-types", "python")
)
if os.path.isdir(_CANONICAL_TYPES_PY) and _CANONICAL_TYPES_PY not in sys.path:
    sys.path.insert(0, _CANONICAL_TYPES_PY)

from sports_automation.types import RuleCondition  # noqa: E402

# Comparators supported by the DSL, mapped to Python evaluation callables.
_COMPARATORS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "in": lambda a, b: a in (b if isinstance(b, (list, tuple, set)) else [b]),
    "contains": lambda a, b: b in a if isinstance(a, (str, list, tuple, set)) else False,
}

# Logical operators supported by the DSL.
_OPERATORS = {"and", "or", "not"}


def _get_nested(data: Dict[str, Any], field: str) -> Any:
    """Resolve a dot-notation field path (e.g. "event.status") against a nested dict."""
    keys = field.split(".")
    current: Any = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _eval_condition(cond: RuleCondition, context: Dict[str, Any]) -> bool:
    """Evaluate a single RuleCondition against a context dict.

    Leaf conditions compare context[field] against value using comparator.
    Compound conditions (and/or/not) recurse over sub-conditions.
    """
    if cond.operator:
        operator = cond.operator.lower()
        if operator not in _OPERATORS:
            raise ValueError(f"Unknown rule operator: {cond.operator!r}")
        sub_conditions = cond.conditions or []
        if operator == "not":
            if len(sub_conditions) != 1:
                raise ValueError("'not' operator requires exactly one condition")
            return not _eval_condition(sub_conditions[0], context)
        results = [_eval_condition(c, context) for c in sub_conditions]
        if operator == "and":
            return all(results)
        if operator == "or":
            return any(results)
        return False  # unreachable

    # Leaf condition
    if cond.field is None or cond.comparator is None:
        raise ValueError("Leaf RuleCondition must set field and comparator")
    comparator_fn = _COMPARATORS.get(cond.comparator)
    if comparator_fn is None:
        raise ValueError(f"Unknown comparator: {cond.comparator!r}")
    actual = _get_nested(context, cond.field)
    return comparator_fn(actual, cond.value)


def parse_rule_condition(raw: Dict[str, Any]) -> RuleCondition:
    """Parse one raw rule-condition dict into a RuleCondition (recursively).

    WHAT: Validates that a raw dict has either an operator (compound) or field+comparator
        (leaf), then recurses into sub-conditions for compound nodes.
    WHY: Rule JSON from traders / n8n must be strictly validated before evaluation so a
        malformed rule never produces a wrong financial outcome.
    INPUTS: raw (dict with operator/conditions or field/comparator/value).
    OUTPUTS: a RuleCondition instance.
    SIDE EFFECTS: none.
    FAILURE MODES: raises ValueError on malformed input (missing operator/field, unknown
        comparator, 'not' with != 1 sub-condition).
    """
    operator = raw.get("operator")
    conditions = raw.get("conditions")
    field = raw.get("field")
    comparator = raw.get("comparator")
    value = raw.get("value")

    if operator:
        if operator not in _OPERATORS:
            raise ValueError(f"Unknown rule operator: {operator!r}")
        if conditions is None:
            raise ValueError(f"Operator '{operator}' requires a 'conditions' list")
        parsed_conditions = [parse_rule_condition(c) for c in conditions]
        return RuleCondition(operator=operator, conditions=parsed_conditions)

    # Leaf condition
    if field is None or comparator is None:
        raise ValueError("Leaf rule condition must set 'field' and 'comparator'")
    if comparator not in _COMPARATORS:
        raise ValueError(f"Unknown comparator: {comparator!r}")
    return RuleCondition(field=field, comparator=comparator, value=value)


def parse_rule_set(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a raw settlement rule-set dict into a validated structure.

    WHAT: Takes a raw dict (version, rules: [{id,name,condition,outcome,priority,...}],
        default_outcome) and returns a dict with the same fields plus a parsed
        `condition_tree` (list of RuleCondition) per rule and a validated default_outcome.
    WHY: Separates parsing/validation from evaluation. The rule engine consumes the parsed
        structure; parse errors surface here, not mid-settlement.
    INPUTS: raw (dict with version/rules/default_outcome keys).
    OUTPUTS: dict {version, rules: [{id,name,condition,outcome,priority,condition_tree}],
        default_outcome}.
    SIDE EFFECTS: none.
    FAILURE MODES: raises ValueError if version/default_outcome/rules are missing, if a rule
        lacks id/outcome/priority, if an outcome is not a valid SettlementOutcome, or if a
        condition fails to parse.
    """
    if not isinstance(raw, dict):
        raise ValueError("Rule set must be a JSON object")

    version = raw.get("version")
    rules_raw = raw.get("rules")
    default_outcome = raw.get("default_outcome")

    if not version:
        raise ValueError("Rule set requires a 'version' string")
    if rules_raw is None:
        raise ValueError("Rule set requires a 'rules' list")
    if not isinstance(rules_raw, list):
        raise ValueError("'rules' must be a list")
    if not default_outcome:
        raise ValueError("Rule set requires a 'default_outcome'")

    # Validate default_outcome is a known settlement outcome.
    try:
        from sports_automation.types import SettlementOutcome  # noqa: E402

        SettlementOutcome(default_outcome)
    except Exception:
        raise ValueError(f"Invalid default_outcome: {default_outcome!r}")

    parsed_rules = []
    for idx, rule_raw in enumerate(rules_raw):
        if not isinstance(rule_raw, dict):
            raise ValueError(f"Rule at index {idx} must be an object")
        rule_id = rule_raw.get("id")
        name = rule_raw.get("name")
        outcome = rule_raw.get("outcome")
        priority = rule_raw.get("priority")
        condition_raw = rule_raw.get("condition")

        if not rule_id:
            raise ValueError(f"Rule at index {idx} requires an 'id'")
        if not name:
            raise ValueError(f"Rule '{rule_id}' requires a 'name'")
        if not outcome:
            raise ValueError(f"Rule '{rule_id}' requires an 'outcome'")
        try:
            from sports_automation.types import SettlementOutcome  # noqa: E402

            SettlementOutcome(outcome)
        except Exception:
            raise ValueError(f"Rule '{rule_id}' has invalid outcome: {outcome!r}")
        if not isinstance(priority, int):
            raise ValueError(f"Rule '{rule_id}' requires an integer 'priority'")
        if condition_raw is None:
            raise ValueError(f"Rule '{rule_id}' requires a 'condition'")

        condition_tree = parse_rule_condition(condition_raw)

        parsed_rules.append(
            {
                "id": rule_id,
                "name": name,
                "condition": condition_raw,
                "condition_tree": condition_tree,
                "outcome": outcome,
                "priority": priority,
                "metadata": rule_raw.get("metadata") or {},
            }
        )

    # Sort by priority descending so highest priority evaluates first.
    parsed_rules.sort(key=lambda r: r["priority"], reverse=True)

    return {
        "version": version,
        "rules": parsed_rules,
        "default_outcome": default_outcome,
    }
