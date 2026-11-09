# Settlement Discrepancy

FILE HEADER
-----------
Business problem this file solves:
    On-call and data engineers need a deterministic runbook for settlement
    discrepancies: the platform's settled outcome (won/lost/void/half_won/
    half_lost) drifts from the official result, or reconciliation finds
    void/won/lost distribution drift. Without this runbook, responders cannot
    quickly pinpoint which event/market/selection drifted or whether a payout
    correction is required, a regulatory audit concern.
Where it sits in the flow:
    Part of the processing engine (settlement worker) and observability plane
    (docs/runbooks/). Covers the Settlement Worker n8n node (rule DSL), the
    daily reconciliation job, and the CanonicalEvent/SettlementResult/Alert/
    Discrepancy/ReconciliationReport types in types.py.
What calls it / what it calls:
    Referenced by: Alertmanager (warning/business receivers), Settlement
    Worker n8n node, daily reconciliation job, Sportsbook CRM (payout
    corrections). Calls: none (human-operated runbook).
What breaks if removed:
    Incident responders cannot trace discrepancies to root cause; incorrect
    payouts may go uncorrected; the 100% audit-trail-coverage KPI and
    regulatory reporting are at risk.
Language conventions:
    Markdown. H1 title, overview, markdown tables, --- separators, numbered
    sections, FILE HEADER block. Matches kpi-definitions.md style.
---

## Overview

The Settlement Worker auto-settles bets when an official result arrives, using
the settlement rule DSL. A settlement discrepancy occurs when the platform's
settled outcome drifts from the official result, or when the daily
reconciliation job finds void/won/lost distribution drift. This runbook covers
diagnosing and resolving settlement discrepancies and acting on reconciliation
findings.

---

### Alert metadata

| Attribute | Value |
|-----------|-------|
| **Title** | Settlement Discrepancy |
| **Severity** | Warning / Critical |
| **Triggering alert** | `SettlementDiscrepancy` (warning), `ReconciliationDrift` (critical if >100 discrepancies) |
| **Canonical alert type** | `AlertType.SETTLEMENT_DISCREPANCY`, `AlertType.RECONCILIATION_DRIFT` |
| **Alert severity enum** | `AlertSeverity.WARNING`, `AlertSeverity.CRITICAL` |
| **Receiver** | `warning` / `business` (Alertmanager) |
| **Runbook link** | docs/runbooks/settlement-discrepancy.md |

---

### Symptoms

- Settlement outcome mismatch vs the official result (void/won/lost drift)
- Reconciliation report shows discrepancies where `entity_type = "settlement"`
- Customer complaints about incorrect payouts
- `reconciliation_discrepancies_total` above threshold
- Settlement latency p95 rising (SLA breach)

---

### Likely causes

| Cause | Likelihood |
|-------|------------|
| Official result delayed or revised after settlement | High |
| Settlement rule DSL rule misfiring (wrong outcome) | Medium |
| Event status/score not yet `ENDED` when settlement ran | Medium |
| Provider settlement feed out of sync with the platform | Medium |
| Duplicate settlement processed (idempotency failure) | Low |

---

## 1. Diagnostic steps

1. Open the latest ReconciliationReport (daily reconciliation job output) and list discrepancies where `entity_type = "settlement"`.
2. For each discrepancy, compare `expected` vs `actual` outcome and identify the event_id/market_id/selection_id.
3. Check the official result source for the event (settlement feed batch API).
4. Review the Settlement Worker n8n node execution log and the rule that fired (rule id + priority).
5. Verify event status is `ENDED` and the score is populated in CanonicalEvent.
6. Check `SettlementResult.source` (official/manual/auto_reconciled) and `confidence`.

---

## 2. Resolution steps

1. If the official result was revised, void or correct the settlement and re-issue payout adjustments via the Sportsbook CRM.
2. If a rule misfired, correct the SettlementRule DSL and re-run settlement for affected events; bump the rule-set version.
3. If event status was premature, add a guard: only settle when `status == ENDED`; backfill missed settlements.
4. Auto-correct discrepancies where confidence is high; send low-confidence cases to the manual review queue.
5. Record every correction in the audit trail (100% audit-trail-coverage KPI).
6. Confirm the next reconciliation run shows zero critical discrepancies.

---

## 3. Escalation contacts

| Role | Contact | Channel |
|------|---------|---------|
| On-call engineer | oncall@sports-automation.local | PagerDuty / #oncall (Slack) |
| Data engineering | team@sports-automation.local | #alerts (Slack) |
| Compliance | business@sports-automation.local | #business-alerts (Slack) |

Escalate to Compliance if any customer payout is affected (regulatory audit requirement).

---

## 4. Prevention

- Run daily reconciliation with checksum comparison; alert on `reconciliation_discrepancies_total > 100`.
- Require event status `ENDED` before auto-settlement; default unmatched cases to `void` (never pay on an unknown match).
- Pin settlement rule-set versions; add contract tests for the rule DSL.
- Maintain 100% audit-trail coverage for every settlement decision.
- Monitor settlement latency p95; page if > 120s.

---

Document Version: 1.0  
Last Updated: 2026-11-09  
Review Cycle: Monthly
