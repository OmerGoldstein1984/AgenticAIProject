# Alert Engine Down

FILE HEADER
-----------
Business problem this file solves:
    On-call engineers need a deterministic, step-by-step runbook for the
    "Alert Engine Down" incident: the LLM-based alert generator stops producing
    alerts, no alerts fire, and the alert queue backs up. Without this runbook,
    responders waste time guessing which service is broken and how to restore
    alerting, increasing Mean Time to Recovery (MTTR) and risking missed
    customer-impacting anomalies.
Where it sits in the flow:
    Part of the observability & control plane (docs/runbooks/). Linked from
    Alertmanager annotations (runbook_url) on page/critical alerts. Covers the
    n8n Alert Engine workflow (LLM alert generator) and its relationship to the
    ingestion service /health endpoint and Redis queue backend.
What calls it / what it calls:
    Referenced by: Alertmanager (alertmanager.yml pager receiver), n8n Alert
    Engine workflow, ingestion service. Calls: none (human-operated runbook).
What breaks if removed:
    Incident responders have no documented procedure; MTTR for alert-engine
    failures increases and critical alerts (odds anomaly, settlement
    discrepancy, feed outage) may be missed during an outage.
Language conventions:
    Markdown. H1 title, overview, markdown tables, --- separators, numbered
    sections, FILE HEADER block. Matches kpi-definitions.md style.
---

## Overview

The Alert Engine (n8n Alert Engine workflow, backed by the LLM alert
generator) is the platform's anomaly-detection and alerting layer. When it
fails, no alerts fire, the alert queue backs up, and on-call loses visibility
into odds anomalies, settlement discrepancies, feed outages, and other
critical events. This runbook provides the deterministic diagnostic and
resolution steps to restore alerting and bound MTTR.

---

### Alert metadata

| Attribute | Value |
|-----------|-------|
| **Title** | Alert Engine Down |
| **Severity** | Page / Critical |
| **Triggering alert** | `AlertEngineDown` (page), `AlertQueueDepthHigh` (warning) |
| **Canonical alert type** | N/A (infrastructure alert; see `AlertType` in types.py) |
| **Alert severity enum** | `AlertSeverity.PAGE`, `AlertSeverity.CRITICAL` |
| **Receiver** | `pager` (Alertmanager) |
| **Runbook link** | docs/runbooks/alert-engine-down.md |

---

### Symptoms

- No alerts firing in Alertmanager/Grafana despite known anomalies
- Alert queue depth rising in Redis/n8n (messages accumulating)
- LLM Alert Generator node returning errors or timeouts in the n8n execution log
- `GET /health` reporting the alert engine sub-service as disconnected
- Ingestion metrics showing `events_forwarded_total` rising but no alerts generated

---

### Likely causes

| Cause | Likelihood |
|-------|------------|
| LLM provider (Anthropic) API down or rate-limited | High |
| n8n Alert Engine workflow paused or errored | High |
| Redis connection lost (queue/dedup backend) | Medium |
| LLM prompt/schema version mismatch producing unparsable output | Medium |
| Ingestion service unable to forward to n8n webhook | Low |

---

## 1. Diagnostic steps

1. Open Alertmanager and confirm no active alerts; verify the `pager` receiver is reachable.
2. Open the n8n Alert Engine workflow execution log; inspect the LLM Alert Generator node for errors/timeouts.
3. Call `GET /health` on the ingestion service; verify `websocket`, `rest_poller`, and `redis` are all `true`.
4. Inspect the Redis `queue_depth` gauge to confirm a queue backup.
5. Review the Prometheus metric `n8n_webhook_errors_total` for forwarding failures to n8n.
6. Check the LLM provider status page and validate the API key.

---

## 2. Resolution steps

1. If the LLM provider API is down, fail over to the rule-based alert baseline (shadow mode) until the provider recovers.
2. If the n8n Alert Engine workflow is paused, resume it in the n8n UI and re-execute failed executions from the dead-letter queue.
3. If Redis is disconnected, restart the ingestion service (lifespan reconnects Redis) and verify `redis` returns `true` on `/health`.
4. If prompt/schema mismatch, roll the prompt version back to the last known-good version and redeploy the Alert Engine node.
5. Clear the alert queue backup by replaying queued messages through the Alert Engine.
6. Confirm alerts resume firing; send a test alert end-to-end to validate.

---

## 3. Escalation contacts

| Role | Contact | Channel |
|------|---------|---------|
| On-call engineer | oncall@sports-automation.local | PagerDuty / #oncall (Slack) |
| Platform engineering | team@sports-automation.local | Email / #alerts (Slack) |
| AI solutions engineering | business@sports-automation.local | #business-alerts (Slack) |

Escalate to Platform Engineering if not resolved within 15 minutes (critical SLA).

---

## 4. Prevention

- Enable LLM provider health checks and synthetic alert probes every 5 minutes.
- Run the Alert Engine in shadow mode against a rule-based baseline to detect drift early.
- Pin prompt and schema versions; add contract tests for LLM output parsing.
- Add Redis connection monitoring with auto-reconnect and exponential backoff.
- Page immediately on `AlertEngineDown`; page on `AlertQueueDepthHigh` after 5 minutes.

---

Document Version: 1.0  
Last Updated: 2026-11-09  
Review Cycle: Monthly
