# 05_trace_walkthrough.md

# Trace Walkthrough — One Odds Update End to End

**Audience:** the learner. **How to use:** read after 02_architecture.md. This narrates ONE real-
looking request through the system, hop by hop, with real values and `file:line` at every hop,
plus what happens at each failure point.

> ⚠️ **UNVERIFIED:** The full stack cannot be run in this session (Docker daemon not running), so
> this trace is a *static trace* grounded in the code — every hop cites actual `file:line` and
> actual variable shapes — but it has not been executed end-to-end. Where a behavior is assumed
> rather than observed, it is marked **[UNVERIFIED]**. The learner should run the stack and
> confirm before presenting it as fact.

---

## The scenario

A single live-odds update from the mock odds feed:

```json
{
  "providerId": "provider_1",
  "eventId": "evt_000007",
  "marketId": "match_winner",
  "selectionId": "home",
  "odds": -140,
  "format": "american",
  "timestamp": "2026-11-09T14:32:00Z",
  "sequence": 128
}
```

This is American odds (-140 = favorite). The platform must convert it to decimal, dedup it, and
forward it to n8n.

---

## Hop-by-hop trace

### Hop 1 — MockOddsFeed generates the update
**File:** `packages/mock-providers/src/mock/odds_feed.py`

- `_generate_odds_update()` picks a random event (`evt_000007`), provider (`provider_1`),
  market (`match_winner`), selection (`home`), base odds (~2.1), adds noise, converts to American
  (-140), assigns `sequence = 128` (per-producer counter incremented at line ~137), and emits
  JSON with ISO-8601 timestamp.
- **Output:** the JSON above, serialized and broadcast to connected WebSocket clients in
  `_broadcast_loop()` (~line 150).
- **Failure if:** broadcast loop errors → logged, loop continues (resilient); port already in use
  at `start()` → OSError, process exits. **[UNVERIFIED]** no backpressure — a slow client blocks
  all clients (noted in 04_gap_bridge.md).

### Hop 2 — WebSocketClient receives and reconnects
**File:** `packages/ingestion-service/src/ingestion/providers/websocket_client.py`

- `connect()` → `_connect_with_retry()` opens `websockets.connect(ws://localhost:8080/ws)` with
  ping keepalive (30s/10s).
- `_handle_messages()` iterates `async for message in self._websocket`, parses JSON, and schedules
  `_safe_on_message(data)` as a background task — so a slow handler never blocks receiving.
- `on_message` = `handle_odds_message` (main.py:169).
- **Failure if:** connect fails → exponential backoff up to max 10 attempts then stops (odds
  ingestion halts until restart — **[GAP]**). Invalid JSON → logged and skipped. **[UNVERIFIED]**

### Hop 3 — handle_odds_message → process_odds
**File:** `packages/ingestion-service/src/ingestion/main.py` (line 169 `handle_odds_message`, line 187 `process_odds`)

- `handle_odds_message(message)` logs debug and calls `await process_odds(message)`.
- `process_odds(data)` runs the pipeline:
  1. **Validate:** `schema_validator.validate("odds", data)` — checks required fields
     (providerId, eventId, marketId, selectionId, odds, format, timestamp, sequence), odds in
     [1.01, 10000], format enum, timestamp date-time (schema_validator.py:validate).
     - If invalid → returns `{"status":"rejected","reason":"validation_failed","errors":[...]}`.
  2. **Transform:** `canonical_transformer.transform_odds(data, provider="provider_1")` — applies
     `PROVIDER_MAPPINGS["lsports"]["odds"]` field map, defaults, `_normalize_odds(-140,"american")`
     → 1.7142857..., sets format="decimal", parses timestamp, coerces sequence to int.
     - **Canonical result (real value):** `odds = 1.7143` (decimal), format `decimal`.
  3. **Deduplicate:** `deduplicator.check_and_store("odds:provider_1:evt_000007:128")` — Redis
     `SET NX EX` with 24h TTL. If already exists → `{"status":"duplicate",...}` (skip).
  4. **Forward:** `forward_to_n8n("odds", canonical)` — POST to
     `http://n8n:5678/webhook/odds`.
- **Output:** `{"status":"processed","eventId":"evt_000007"}`.
- **Failure if:** schema invalid → rejected (correct, fail-fast). Redis down → dedup returns False
  (allow-through — process anyway). n8n down → error logged, **data silently dropped** ([**GAP**]
  no DLQ/retry).

### Hop 4 — n8n receives the webhook
**File:** n8n workflow (not shipped as workflow JSON; handled by custom nodes)

- n8n Queue Mode + Redis Streams receives the webhook at `/webhook/odds`.
- Routes into the **Sports Event Router** custom node (packages/n8n-nodes/.../SportsEventRouter.node.ts).
- **[UNVERIFIED]** The workflow JSON files (n8n-workflows/*.json) don't exist in the repo, so the
  exact wiring is configured in the n8n UI at interview time.

### Hop 5 — Sports Event Router
**File:** `packages/n8n-nodes/src/Nodes/SportsEventRouter/SportsEventRouter.node.ts`

- `execute()` validates required fields (id/sport/status) — for an odds update these come from
  canonical form. Determines priority (default normal → output index 1) based on routing mode.
- Adds `_routing` metadata: priority, streamKey (e.g. `sports:events:normal`), routedAt,
  routedBy, originalIndex.
- Emits to output index 1 (Normal Priority).
- **Failure if:** missing required id/sport/status → dead-letter output (if sendInvalidToDlq) or
  skipped.

### Hop 6 — Odds Normalizer
**File:** `packages/n8n-nodes/src/Nodes/OddsNormalizer/OddsNormalizer.node.ts`

- `execute()` groups odds by `eventId:marketId` (= `evt_000007:match_winner`), converts to
  output format (decimal), computes implied probability = 1/1.7143 ≈ 0.5833.
- Detects arbitrage across providers for the same selection: if total implied probability <
  minMarginPercent (0.5%), emits arbitrage opportunity.
- Marks best odds (`isBestOdds=true`) per selection.
- **Output:** Normalized odds + Arbitrage (if any) + Errors.
- **Failure if:** odds missing/stale/out of range → error output for that item only.

### Hop 7 — Downstream output systems
**Conceptual:** normalized odds flow to mock Sportsbook CRM, Risk Management (exposure), and
Reporting Warehouse (TimescaleDB). These are referenced in README:120 but are mock/not implemented
as separate services in this repo. **[UNVERIFIED]**

---

## End-to-end failure summary (what breaks where)

| Hop | Component | If it fails… | User/customer impact |
|-----|-----------|--------------|---------------------|
| 1 | MockOddsFeed | broadcast error | logged, loop continues; no new odds |
| 2 | WebSocketClient | connect fails (×10) | odds ingestion halts until restart **[GAP]** |
| 3a | SchemaValidator | invalid payload | rejected, no forwarding (correct) |
| 3b | CanonicalTransformer | transform error | returns raw data (may fail at n8n) |
| 3c | Deduplicator | Redis down | allow-through (process anyway) |
| 3d | forward_to_n8n | n8n down | **silently dropped** **[GAP] no DLQ** |
| 5 | SportsEventRouter | missing fields | dead-letter or skipped |
| 6 | OddsNormalizer | bad odds | error output for that item |

---

## What the learner should say (2-minute version)

> "An odds update arrives as American odds (-140) over WebSocket from the mock feed. The
> ingestion service validates it against JSON Schema, converts it to decimal (≈1.71), deduplicates
> it via Redis SET NX EX so it's processed once, and forwards it to n8n. n8n's Sports Event
> Router assigns priority, then the Odds Normalizer computes implied probability and checks for
> arbitrage. Every hop has a defined failure mode — schema rejection fails fast, Redis failure
> degrades gracefully, and an n8n outage would drop data today (a gap I'd fix with a dead-letter
> queue)."

---

## Drill: run it yourself

1. Start the stack (`make dev-setup` — needs Docker; not runnable here).
2. Watch `make logs-ingestion` while the mock odds feed broadcasts.
3. Call `POST http://localhost:8000/ingest/odds` with the sample JSON above.
4. Confirm `{"status":"processed","eventId":"evt_000007"}` and check Grafana's ingestion
   dashboard for the latency counter.
5. Send the same JSON again → expect `{"status":"duplicate"}` (dedup working).

**[UNVERIFIED]** Steps 1–4 require a running stack; confirm them before the interview.
