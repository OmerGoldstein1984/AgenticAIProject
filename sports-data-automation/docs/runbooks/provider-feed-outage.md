# Provider Feed Outage

FILE HEADER
-----------
Business problem this file solves:
    On-call engineers need a deterministic runbook for provider feed outages:
    the WebSocket odds feed or REST event/settlement feed goes down, odds grow
    stale, or reconnection fails. Without this runbook, responders cannot
    quickly distinguish a provider-side outage from an ingestion-side failure,
    prolonging data staleness and risking stale markets and trading loss.
Where it sits in the flow:
    Part of the ingestion pipeline (docs/runbooks/). Covers the mock data
    providers (WebSocket odds, REST events/settlements), the ingestion service
    WebSocket client / REST poller, the /health endpoint, Redis, and the n8n
    webhook forward path.
What calls it / what it calls:
    Referenced by: Alertmanager (pager receiver), ingestion service,
    mock providers, n8n webhook. Calls: none (human-operated runbook).
What breaks if removed:
    Incident responders cannot tell whether the feed or the ingestion service
    is at fault; odds staleness persists, markets go stale, and trading loss
    or customer-impacting mispricing can occur.
Language conventions:
    Markdown. H1 title, overview, markdown tables, --- separators, numbered
    sections, FILE HEADER block. Matches kpi-definitions.md style.
---

## Overview

The platform ingests live odds via WebSocket and events/settlements via REST
from mock data providers (simulating the LSports feed). A provider feed outage
occurs when the WebSocket/REST feed goes down, odds grow stale, or
reconnection fails. This runbook covers diagnosing feed outages, restoring
connectivity, and bounding data staleness.

---

### Alert metadata

| Attribute | Value |
|-----------|-------|
| **Title** | Provider Feed Outage |
| **Severity** | Critical / Page |
| **Triggering alert** | `FeedOutage` (critical), `OddsStaleness` (warning) |
| **Canonical alert type** | `AlertType.FEED_OUTAGE` |
| **Alert severity enum** | `AlertSeverity.CRITICAL`, `AlertSeverity.PAGE` |
| **Receiver** | `pager` (Alertmanager) |
| **Runbook link** | docs/runbooks/provider-feed-outage.md |

---

### Symptoms

- WebSocket `active_connections` gauge at 0 for a provider
- Odds staleness: `provider_latency_seconds` p95 above threshold (no updates)
- REST poller `is_running` false on `GET /health`
- Ingestion `events_received_total` rate dropping to near zero
- Reconnection attempts looping in the ingestion/n8n logs

---

### Likely causes

| Cause | Likelihood |
|-------|------------|
| Provider WebSocket server down or network partition | High |
| REST poller endpoint returning errors or rate-limited (429) | Medium |
| Ingestion WebSocket client reconnect interval misconfigured | Medium |
| DNS or TLS failure to the provider endpoint | Low |
| n8n webhook down so ingestion cannot forward (backpressure) | Low |

---

## 1. Diagnostic steps

1. Call `GET /health` on the ingestion service; check the `websocket` and `rest_poller` flags and the `redis` status.
2. Check the `active_connections` gauge by provider — zero indicates a dead WebSocket.
3. Check the `provider_latency_seconds` histogram by provider/type for staleness.
4. Review ingestion service logs for WebSocket disconnect/reconnect errors and REST poller 4xx/5xx responses.
5. Verify the provider endpoint is reachable (curl/telnet) from the ingestion host.
6. Check `n8n_webhook_errors_total` — if forwarding fails, ingestion may appear healthy while data stalls.

---

## 2. Resolution steps

1. If the provider is down, wait for provider recovery; ingest from a secondary provider if configured.
2. If the WebSocket client is disconnected, restart the ingestion service (lifespan reconnects the WebSocket and REST poller).
3. If the REST poller is erroring, check the rate-limit config (`RateLimitConfig`) and back off; verify endpoint auth.
4. If reconnection is looping, increase `ws_reconnect_interval` and add exponential backoff.
5. If the n8n webhook is down, restore n8n and replay buffered odds/events from the Redis/dedup store.
6. Confirm the feed resumes: `active_connections > 0` and `provider_latency_seconds` p95 back under SLA.

---

## 3. Escalation contacts

| Role | Contact | Channel |
|------|---------|---------|
| On-call engineer | oncall@sports-automation.local | PagerDuty / #oncall (Slack) |
| Platform engineering | team@sports-automation.local | #alerts (Slack) |
| Provider liaison | business@sports-automation.local | #business-alerts (Slack) |

Escalate to Platform Engineering if the feed is not restored within 15 minutes (critical SLA).

---

## 4. Prevention

- Monitor `active_connections` per provider; alert at 0 connections.
- Track `provider_latency_seconds` p95; page if odds go stale beyond the threshold.
- Add exponential backoff with jitter to WebSocket reconnect and the REST poller.
- Configure a secondary/fallback provider for critical odds markets.
- Surface feed health in the stakeholder dashboard (Grafana).

---

Document Version: 1.0  
Last Updated: 2026-11-09  
Review Cycle: Monthly
