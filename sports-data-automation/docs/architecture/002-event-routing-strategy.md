# Event Routing Strategy

## FILE HEADER
-----------
Business problem this file solves:
    The ingestion service validates, transforms, and deduplicates raw provider data, then hands it
    to the n8n orchestration layer. But once data reaches n8n, it must be routed to the correct
    downstream system: odds go to the Odds Normalizer, match events to settlement/alert logic,
    settlements to the Settlement Worker, anomalies to the Alert Engine. Without a defined routing
    strategy, every event type would fan out to every worker, causing duplicate processing,
    missed settlements, and an inability to prioritize latency-sensitive paths.

Where it sits in the flow:
    Stage 3 of the pipeline, immediately after ingestion (stage 2) and before the output systems
    (stage 4). Ingestion forwards canonical payloads to n8n webhooks; the n8n Event Router custom
    node inspects content and dispatches to the correct worker node with priority queuing.

What calls it / what it calls:
    Called by: ingestion service via `forward_to_n8n("odds|event|settlement", canonical)` in
    packages/ingestion-service/src/ingestion/main.py. Calls: n8n Event Router node → Odds
    Normalizer / Settlement Worker / Alert Engine / Reconciliation Job nodes.

What breaks if removed:
    No defined destination for validated canonical data; n8n would have no routing logic, odds
    and settlements could not be prioritized, and the orchestration layer collapses into
    unstructured fan-out.

Language conventions:
    TypeScript custom n8n node (packages/n8n-nodes/src/nodes/SportsEventRouter/), exported
    workflow JSON (n8n-workflows/event-router.json), Python ingestion pipeline
    (packages/ingestion-service/src/ingestion/main.py).

GAP:
    forward_to_n8n swallows exceptions with no dead-letter queue or retry; a n8n outage silently
    drops data. See 07_issues_found.md.

---

## Status

Accepted

## 1. Context

### Problem being solved

After the ingestion service validates, transforms to canonical form, and deduplicates each item,
it forwards the payload to n8n via webhook. n8n must then:

- Route each event type to the correct downstream worker (odds → Odds Normalizer, events →
  settlement/alert logic, settlements → Settlement Worker).
- Protect latency-critical paths (settlement must fire within ~30s) from being blocked by the
  high-volume odds feed (WebSocket pushes every 500ms–2s).
- Preserve ordering and idempotency so duplicate odds quotes or re-polling don't double-settle.

### Why it matters

Settlement accuracy is regulatory, and odds staleness means trading loss. Routing must be
content-based (decided by payload fields, not a static endpoint) and priority-aware so a burst of
odds quotes cannot starve settlement or alert processing.

## 2. Decision

### What was chosen

An **n8n Event Router custom node (TypeScript)** performing content-based routing over priority
queues, preceded by a fixed pipeline in the ingestion service:

**Pipeline: validate → transform → deduplicate → forward**

| Stage | Responsibility | Location |
|-------|---------------|----------|
| Validate | Schema validation against canonical schema | `SchemaValidator` (ingestion) |
| Transform | Coerce raw provider JSON → canonical shape | `CanonicalTransformer` (ingestion) |
| Deduplicate | Drop exact duplicates via Redis key | `Deduplicator` (ingestion, Redis) |
| Forward | POST canonical payload to n8n webhook | `forward_to_n8n` (ingestion) |

The n8n Event Router node then inspects the canonical payload's `type` field (`odds` /
`event` / `settlement`) and dispatches to the appropriate worker node:

| Route | Worker node | Business purpose |
|-------|-------------|------------------|
| odds | Odds Normalizer | Decimal/American/Fractional conversion, arbitrage detection |
| event | Settlement Worker / Alert Engine | Match status updates, anomaly detection |
| settlement | Settlement Worker | Rule-engine auto-settlement, audit trail |

Priority queues ensure settlement and alert events are dequeued before background odds
normalization. The orchestration layer matches LSports' stated n8n/Workato requirement and gives
visual workflow debugging in the n8n UI.

### Why n8n

- Directly matches the LSports job requirement ("n8n/Workato experience: Complex n8n workflows
  with custom nodes, error handling, rate limiting, retry logic").
- Custom nodes in TypeScript show full-stack capability.
- Visual debugging accelerates the interview demo (trace an event through the n8n UI).

## 3. Consequences

### Positive

- Content-based routing keeps downstream systems decoupled; adding a new worker means adding a
  route, not rewriting ingestion.
- Priority queues protect critical paths (settlement, alerts) from odds-volume bursts.
- The validate→transform→dedup→forward pipeline is a clean gate sequence: invalid data is
  rejected, duplicates dropped, only clean canonical data reaches n8n.
- n8n provides visual workflow debugging, retry policies, and circuit breakers for production
  ownership.

### Negative / tradeoffs

- Direct webhook forward from ingestion to n8n is not reliable: `forward_to_n8n` catches all
  exceptions and swallows them, so a n8n outage silently drops odds/events/settlements (no
  dead-letter queue, no retry). Recorded as a GAP; the production alternative is Redis Streams
  with DLQ + retry.
- `ProviderConfig` is defined in canonical types but no provider-registry loader exists;
  providers are wired in `Settings.rest_endpoints` instead of via the registry (GAP).
- The Event Router's rule-based hot-reload from DB/remote is declared in the node UI but not
  implemented; only embedded JSON works (GAP).

## 4. References

- `sports-data-automation/packages/ingestion-service/src/ingestion/main.py` — `process_*`,
  `forward_to_n8n`, lifespan wiring
- `sports-data-automation/packages/n8n-nodes/src/nodes/SportsEventRouter/` — Event Router custom node
- `sports-data-automation/n8n-workflows/event-router.json` — exported n8n workflow
- `sports-data-automation/packages/canonical-types/src/types.ts` — `CanonicalEvent`,
  `CanonicalOdds`, `SettlementResult`
- `sports-data-automation/packages/canonical-types/python/sports_automation/types.py` — Python mirror
- `PROJECT_SPEC.md` — Core Components (Event Router), Implementation Phases (Phase 2)
- `kpi-definitions.md` — Automation rate, processing latency, forwarding success rate KPIs
- `07_issues_found.md` — Recorded GAPs (forward_to_n8n DLQ, provider registry, rule hot-reload)

---

*Document Version: 1.0*  
*Date: 2026-11-09*  
*Owner: Architecture*
