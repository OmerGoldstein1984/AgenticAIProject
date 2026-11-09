# 03_glossary.md

# Glossary — Sports Data Automation Platform

Every domain term, library, pattern, acronym, and config key used in the repo. Each entry has:
a plain definition, where it appears (file:line), why it matters, and a one-line analogy.

> 📌 file:line references point into `sports-data-automation/` unless noted. Line numbers are
> approximate (they shift as comments are added) — use them to locate the area, then confirm.

---

## A. Domain terms (sports betting)

| Term | Plain definition | Where (file:line) | Why it matters | Analogy |
|------|-----------------|-------------------|----------------|---------|
| **Odds** | The price of a bet; how much a winning bet returns relative to stake. | types.ts:OddsFormat; canonical_transformer.py:_normalize_odds | Core product of a sportsbook; wrong odds = lost money. | Price tag on a product. |
| **Decimal odds** | Odds format where odds = total payout per unit staked (e.g. 2.10). | types.ts:OddsFormat.DECIMAL | Internal canonical format; everything normalized to decimal. | Metric system — one common unit. |
| **American odds** | Moneyline format (+150 underdog / -110 favorite). | types.ts:OddsFormat.AMERICAN | One of 3 provider formats the platform must convert. | One foreign currency. |
| **Fractional odds** | UK format (e.g. 5/1 = profit per unit staked). | types.ts:OddsFormat.FRACTIONAL | Third provider format. | Another foreign currency. |
| **Event / Match** | A sporting fixture (teams, start time, status, score). | types.ts:CanonicalEvent | Anchors odds, settlement, alerts. | A scheduled service appointment. |
| **Market** | A bettable outcome category (match_winner, total_goals, ...). | types.ts:CanonicalOdds.marketId | Groups selections within an event. | A line item on a menu. |
| **Selection** | A specific choice within a market (home/draw/away). | types.ts:CanonicalOdds.selectionId | What a customer actually bets on. | A specific dish. |
| **Settlement** | Deciding won/lost/void for a bet after the match ends. | types.ts:SettlementResult; SettlementWorker | Triggers payouts; regulatory/audit-critical. | Closing a claim after an incident. |
| **Void** | Bet cancelled; stake returned, no payout. | types.ts:SettlementOutcome.VOID | Used for abandoned/cancelled matches; safer default. | Voiding a transaction. |
| **Arbitrage** | Betting all outcomes across providers for guaranteed profit. | OddsNormalizer arbitrage output | A risk the book must detect and limit. | Buying low in one market, selling high in another. |
| **Implied probability** | 1 / decimal odds; the book's estimate of an outcome's chance. | OddsNormalizer | Basis for arbitrage detection (sum < 100% = arb). | Odds converted to a percentage. |
| **Audit trail** | Immutable record of how each decision was made. | SettlementWorker audit; kpi-definitions.md:258 | Regulatory compliance; dispute resolution. | A paper receipt trail. |

## B. Technical terms & patterns

| Term | Plain definition | Where (file:line) | Why it matters | Analogy |
|------|-----------------|-------------------|----------------|---------|
| **Canonical format** | One internal data shape all modules agree on. | types.ts / types.py | Prevents provider-specific drift; one contract everywhere. | Universal adapter plug. |
| **Idempotency** | Processing the same input once, even if repeated. | deduplicator.py:check_and_store (SET NX EX) | Prevents double payouts on retries. | Pressing an elevator button once. |
| **Exactly-once** | Each item processed precisely one time. | n8n Queue Mode + Redis Streams (README) | Stronger than at-least-once; no duplicates, no skips. | A numbered ticket served once. |
| **Dead-letter queue (DLQ)** | Holding area for messages that can't be processed. | SportsEventRouter output 3 (dead letter) | Isolates bad events without stopping the pipeline. | A "returns" bin at a store. |
| **Consumer group** | Set of workers sharing a message stream. | n8n Queue Mode + Redis Streams (README) | Lets multiple workers split the load. | A team sharing a support inbox. |
| **Backpressure** | Slowing a fast producer so a slow consumer isn't overwhelmed. | odds_feed.py:# GAP (no backpressure) | Prevents memory exhaustion under load. | A narrow pipe limiting water flow. |
| **Circuit breaker** | Stop calling a failing dependency for a while. | (referenced in PROJECT_SPEC, not implemented) | Stops cascading failures. | A fuse that trips. |
| **Shadow mode** | Run a new rule/LLM alongside the old one without acting. | (referenced, not implemented) | Safe evaluation before cutover. | Test-driving on a closed course. |
| **Few-shot prompting** | Giving the LLM input→output examples before the real task. | LLMAlertGenerator fewShotExamples | Steers LLM output format without retraining. | Showing worked examples before an exam. |
| **Human-in-the-loop** | A person reviews low-confidence automated decisions. | LLMAlertGenerator human-review queue | Catches LLM mistakes before they reach customers. | A supervisor signing off a trainee's work. |
| **Structured output** | LLM returns machine-readable JSON, not free text. | LLMAlertGenerator outputSchema | Lets downstream systems page/ticket/dashboard on alerts. | Filling a form instead of writing a letter. |
| **Rule DSL** | Declarative JSON rules (condition + outcome + priority). | SettlementWorker embeddedRuleSet | Business users change rules without redeploy. | A checklist with if/then steps. |
| **Conditional request** | HTTP with ETag/If-Modified-Since to avoid refetching. | rest_poller.py:_fetch_and_process | Saves bandwidth; only processes changed data. | Asking "anything new since last time?" |
| **Health check** | Endpoint reporting service dependency status. | main.py:/health | Tells orchestration if the service is up. | A pilot's pre-flight checklist. |

## C. Libraries & tools

| Term | Plain definition | Where (file:line) | Why it matters | Analogy |
|------|-----------------|-------------------|----------------|---------|
| **FastAPI** | Python web framework for APIs. | main.py:app = FastAPI | Powers the ingestion service + mock event feed. | A ready-to-use restaurant kitchen. |
| **Pydantic** | Data validation / settings library (Python). | types.py:BaseModel; config.py:Settings | Enforces schemas at runtime; env-based config. | A form that rejects bad input. |
| **TypeScript** | Typed JavaScript compiled to JS. | types.ts; n8n nodes | Type safety for the custom n8n nodes. | Blueprint before construction. |
| **n8n** | Self-hosted workflow automation (like Workato/Zapier). | docker-compose.yml:n8n; nodes/ | Orchestrates routing/normalization/settlement/alerts visually. | A visual switchboard for tasks. |
| **Redis** | In-memory data store (used for dedup + n8n queue). | deduplicator.py; docker-compose.yml:redis | Fast, shared, TTL-based state. | A shared whiteboard with expiry. |
| **Postgres/TimescaleDB** | Relational DB (time-series extension). | docker-compose.yml:postgres | n8n DB + (intended) reporting warehouse. | A well-organized filing cabinet. |
| **Prometheus** | Metrics collection & alerting. | monitoring/prometheus/prometheus.yml | Scrapes /metrics; evaluates alert rules. | A building's sensor network. |
| **Grafana** | Dashboard visualization. | monitoring/grafana/ | Turns metrics into business & system dashboards. | A control-room display panel. |
| **Alertmanager** | Alert routing & notification. | monitoring/prometheus/alerts/alertmanager.yml | Routes alerts to pager/warning/business/info. | A 911 dispatcher. |
| **jsonschema** | JSON Schema validation (Python). | schema_validator.py | Validates provider payloads against Draft 7 schemas. | A customs inspector. |
| **websockets** | WebSocket client/server library. | odds_feed.py; websocket_client.py | Real-time push for live odds. | A live phone line. |
| **httpx** | Async HTTP client (Python). | rest_poller.py; forward_to_n8n | Polls providers; POSTs to n8n webhooks. | A courier. |
| **tenacity** | Retry library (imported, unused — gap). | rest_poller.py import | Intended retry/backoff; currently hand-rolled. | An auto-redial. |
| **uvicorn** | ASGI server for FastAPI. | Dockerfile CMD; main.py __main__ | Serves the ingestion API. | The waiter taking orders. |

## D. Acronyms

| Acronym | Plain definition | Where |
|--------|-----------------|-------|
| **API** | Application Programming Interface — how two programs talk. | Throughout |
| **CRM** | Customer Relationship Management (mock Sportsbook CRM). | README:121 |
| **DLQ** | Dead-Letter Queue. | SportsEventRouter.node.ts output 3 |
| **DSL** | Domain-Specific Language (settlement rules in JSON). | SettlementWorker.node.ts |
| **ETL** | Extract-Transform-Load (roughly what ingestion does). | main.py pipeline |
| **FDE** | Forward Deployed Engineer — the role this teaching copy targets. | Mission |
| **KPI** | Key Performance Indicator. | kpi-definitions.md |
| **MTTR** | Mean Time To Recovery. | kpi-definitions.md:185 |
| **OSS** | Open Source Software (n8n, Prometheus, Grafana are OSS). | docker-compose images |
| **SLA** | Service Level Agreement (targets like 99.9% uptime). | kpi-definitions.md:176 |
| **TSDB** | Time-Series Database (TimescaleDB). | docker-compose.yml:postgres |
| **UI** | User Interface (n8n config panel, Grafana). | nodes |
| **UX** | User Experience. | — |
| **API Key** | Secret token authenticating a caller. | SportsApiCredentials apiKey |

## E. Config keys (environment variables)

| Key | Default | Meaning | Where |
|-----|---------|---------|-------|
| PORT | 8000 | Ingestion service HTTP port | config.py:port |
| REDIS_URL | redis://localhost:6379/0 | Redis for dedup | config.py:redis_url |
| POSTGRES_DSN | postgres://sports_user:changeme@... | Postgres connection string | config.py:postgres_dsn |
| N8N_WEBHOOK_URL | http://localhost:5678/webhook | Where ingestion forwards data | config.py:n8n_webhook_url |
| ODDS_FEED_WS_URL | ws://localhost:8080/ws | Mock odds feed WebSocket | config.py:odds_feed_ws_url |
| DEDUPLICATION_TTL_SECONDS | 86400 (24h) | How long dedup keys persist | config.py:deduplication_ttl_seconds |
| LOG_LEVEL | INFO | Logging verbosity | config.py:log_level |
| N8N_PASSWORD | changeme | n8n basic auth password | docker-compose.yml:N8N_PASSWORD |
| GRAFANA_PASSWORD | admin | Grafana admin password | docker-compose.yml:GRAFANA_PASSWORD |
| ANTHROPIC_API_KEY | (none) | LLM API key | docker-compose.yml:processing-engine env (service missing) |
| FEED_INTERVAL_MS | 500 | Mock odds broadcast interval | docker-compose.yml:mock-odds-feed |

## F. How to pronounce / say it (interview-ready)

- **Canonical** = ca-NON-ik-al ("the standard version")
- **Idempotent** = eye-dem-ME-pot-ent ("safe to repeat")
- **Arbitrage** = AR-bih-trahzh ("risk-free price gap")
- **Pydantic** = pie-DAN-tic
- **Idempotency key** = the Redis key that guarantees once-only processing
