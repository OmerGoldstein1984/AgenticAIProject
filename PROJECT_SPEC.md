# LSports Interview Project: Real-Time Sports Data Automation Platform

## Executive Summary

Build a **production-grade sports data automation platform** that demonstrates end-to-end business process automation for a sportsbook operation. This project directly mirrors LSports' core value proposition: "real-time data with unmatched accuracy and reliability" for sportsbooks.

---

## Why This Project Wins the Interview

| LSports Requirement | How This Project Demonstrates It |
|---------------------|----------------------------------|
| AI-driven business process automation in production | Full n8n workflow + Python services deployed with Docker Compose, observability, CI/CD |
| n8n/Workato experience | Complex n8n workflows with custom nodes, error handling, rate limiting, retry logic |
| APIs, integrations, SaaS data workflows | REST + WebSocket + GraphQL integrations; mock Sportsbook CRM, Odds API, Settlement systems |
| Translate business needs → technical solutions | Business Process Document → Technical Spec → Implementation → KPI Dashboard |
| KPIs, success metrics, tangible value | Automated metrics collection: latency, accuracy, cost savings, error rates |
| Production ownership: monitoring, alerting, error handling | Prometheus/Grafana, structured logging, dead-letter queues, automated reconciliation |
| Cross-team communication | Business-facing dashboard, runbooks, deployment docs, stakeholder demo script |

---

## Project Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SPORTS DATA AUTOMATION PLATFORM                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐  │
│  │  MOCK DATA   │    │   INGESTION  │    │  PROCESSING  │    │  OUTPUT  │  │
│  │  PROVIDERS   │───▶│   PIPELINE   │───▶│   ENGINE     │───▶│  SYSTEMS │  │
│  └──────────────┘    └──────────────┘    └──────────────┘    └──────────┘  │
│       │                     │                    │                  │       │
│       ▼                     ▼                    ▼                  ▼       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    N8N ORCHESTRATION LAYER                            │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────────┐  │   │
│  │  │ Event   │ │ Odds    │ │ Settle- │ │ Alert   │ │ Reconcilia-  │  │   │
│  │  │ Router  │ │ Normal- │ │ ment    │ │ Engine  │ │ tion Job     │  │   │
│  │  │         │ │ ization │ │ Worker  │ │ (LLM)   │ │ (Scheduled)  │  │   │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └──────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    OBSERVABILITY & CONTROL PLANE                      │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │   │
│  │  │Prometheus│ │ Grafana  │ │  Alert   │ │  KPI     │ │  Runbook   │  │   │
│  │  │ Metrics  │ │ Dashboards│ │ Manager │ │ Tracker  │ │  Generator │  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Mock Data Providers (Simulating LSports Feed)
- **Live Odds Feed**: WebSocket server pushing odds updates every 500ms-2s
- **Event Feed**: REST API with match events (goals, cards, injuries, substitutions)
- **Settlement Feed**: Batch API for post-match results
- **Historical Replay**: CLI tool to replay historical data for backtesting

### 2. Ingestion Pipeline (Python + n8n)
- **Protocol Adapters**: WebSocket client, REST pollers, GraphQL subscriptions
- **Normalization Layer**: Transform provider-specific schemas → canonical internal format
- **Validation & Enrichment**: Schema validation, reference data lookup (team IDs, player IDs)
- **Idempotency & Ordering**: Deduplication keys, sequence numbers, out-of-order handling

### 3. Processing Engine (n8n Workflows + Python Services)
| Workflow | Business Purpose | Technical Highlights |
|----------|------------------|---------------------|
| **Event Router** | Route events to correct downstream systems | Content-based routing, priority queues |
| **Odds Normalization** | Unify odds from multiple providers | Decimal/American/Fractional conversion, arbitrage detection |
| **Settlement Worker** | Auto-settle bets when official result arrives | Rule engine, partial settlement, void handling |
| **Alert Engine (LLM)** | Detect anomalies, generate human-readable alerts | Few-shot prompting, structured JSON output, confidence scoring |
| **Reconciliation Job** | Daily batch to catch drift between systems | Checksum comparison, automated correction, audit trail |

### 4. Output Systems (Mock SaaS Integrations)
- **Sportsbook CRM** (mock HubSpot/Salesforce): Customer notifications, bet updates
- **Risk Management System**: Exposure calculation, limit enforcement
- **Reporting Warehouse**: ClickHouse/PostgreSQL for analytics
- **Notification Service**: Email, Slack, SMS, Push (with template engine)

### 5. Observability & Control Plane
- **Metrics**: Latency (p50/p95/p99), throughput, error rates, data freshness
- **Business KPIs**: Time-to-settle, alert precision/recall, automation rate, cost per event
- **Alerting**: Multi-level (warning/critical/page), on-call rotation, runbook links
- **Reconciliation Dashboard**: Daily drift report, manual override capability

---

## Implementation Phases

### Phase 1: Foundation (Week 1) - *Do this first*
- [ ] Docker Compose stack: n8n, PostgreSQL, Redis, Prometheus, Grafana, mock providers
- [ ] n8n custom node development setup (TypeScript)
- [ ] Canonical data models (TypeScript interfaces + Python Pydantic)
- [ ] CI/CD pipeline (GitHub Actions): lint, test, build, deploy

### Phase 2: Ingestion & Normalization (Week 1-2)
- [ ] WebSocket ingestion service with backpressure handling
- [ ] REST/GraphQL pollers with exponential backoff
- [ ] Schema validation pipeline (JSON Schema + custom rules)
- [ ] n8n workflow: Event Router with priority queuing

### Phase 3: Core Business Logic (Week 2-3)
- [ ] Odds Normalization workflow (multi-provider, arbitrage detection)
- [ ] Settlement Worker (rule engine with DSL for settlement rules)
- [ ] Alert Engine with LLM integration (Anthropic/OpenAI)
- [ ] Reconciliation scheduled job

### Phase 4: Production Hardening (Week 3)
- [ ] Error handling: Dead letter queues, retry policies, circuit breakers
- [ ] Observability: Custom metrics, structured logging, distributed tracing
- [ ] Alerting rules + runbook generator
- [ ] KPI dashboard with business metrics

### Phase 5: Business-Facing Layer (Week 3-4)
- [ ] Stakeholder dashboard (Grafana + custom React panel)
- [ ] API for business users to query automation status
- [ ] Documentation: Architecture decision records, runbooks, API docs
- [ ] Demo script + recorded walkthrough

---

## Technical Stack

| Layer | Technology | Why |
|-------|------------|-----|
| Orchestration | **n8n** (self-hosted) | Directly matches job requirement; visual workflow debugging |
| Primary Language | **Python 3.11+** (FastAPI) | Your strength; great for data pipelines, LLM integration |
| Custom n8n Nodes | **TypeScript** | Extends n8n properly; shows full-stack capability |
| Message Queue | **Redis Streams** | Your event-driven experience; built-in consumer groups |
| Database | **PostgreSQL** + **TimescaleDB** | Time-series sports data; your SQL strength |
| Metrics | **Prometheus** + **Grafana** | Industry standard; shows production mindset |
| LLM | **Anthropic SDK** (Claude) | Your stated expertise; structured output for alerts |
| Testing | **pytest** + **Playwright** | Your QA background; contract testing for integrations |
| Deploy | **Docker Compose** (local) → **K8s manifests** (prod-ready) | Shows scaling awareness |

---

## Key Differentiators to Highlight in Interview

### 1. **"I built this like a production system, not a demo"**
- Idempotent processing with exactly-once semantics
- Circuit breakers and graceful degradation
- Comprehensive integration tests with contract testing
- Zero-downtime deployment strategy

### 2. **"I solved the real business problems, not just technical ones"**
- Business Process Document showing stakeholder interviews
- KPI definitions with baseline measurements
- Runbooks written for non-technical on-call
- Cost analysis: build vs buy, automation ROI calculation

### 3. **"I used AI where it adds value, not as a buzzword"**
- LLM for alert summarization (high variance, needs human review)
- Structured output + confidence scoring → human-in-the-loop
- Prompt versioning and evaluation harness
- Shadow mode for safe rollout

### 4. **"I know the sports betting domain risks"**
- Settlement accuracy > latency (regulatory requirement)
- Audit trail for every automated decision
- Regulatory compliance considerations (GDPR, gambling regulations)
- Fraud detection patterns (arbitrage, syndicate behavior)

---

## Repository Structure

```
sports-data-automation/
├── docker-compose.yml              # Full local stack
├── docker-compose.override.yml     # Local overrides (not committed)
├── Makefile                        # Common commands
├── .github/
│   └── workflows/
│       ├── ci.yml                  # Lint, test, build
│       └── cd.yml                  # Deploy to staging/prod
├── docs/
│   ├── architecture/
│   │   ├── 001-canonical-data-model.md
│   │   ├── 002-event-routing-strategy.md
│   │   └── 003-llm-alert-design.md
│   ├── runbooks/
│   │   ├── alert-engine-down.md
│   │   ├── settlement-discrepancy.md
│   │   └── provider-feed-outage.md
│   ├── business/
│   │   ├── process-map.md          # Business process documentation
│   │   ├── kpi-definitions.md      # KPIs with formulas
│   │   └── roi-analysis.md         # Build vs buy, cost savings
│   └── api/
│       └── openapi.yaml
├── packages/
│   ├── canonical-types/            # Shared TypeScript/Python types
│   │   ├── package.json
│   │   ├── src/types.ts
│   │   └── python/types.py
│   ├── n8n-nodes/                  # Custom n8n nodes
│   │   ├── package.json
│   │   ├── src/
│   │   │   ├── nodes/
│   │   │   │   ├── SportsEventRouter/
│   │   │   │   ├── OddsNormalizer/
│   │   │   │   ├── SettlementWorker/
│   │   │   │   └── LLMAlertGenerator/
│   │   │   └── credentials/
│   │   └── jest.config.js
│   ├── ingestion-service/          # Python FastAPI service
│   │   ├── pyproject.toml
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── providers/
│   │   │   │   ├── websocket_client.py
│   │   │   │   ├── rest_poller.py
│   │   │   │   └── graphql_subscription.py
│   │   │   ├── normalization/
│   │   │   │   ├── schema_validator.py
│   │   │   │   ├── canonical_transformer.py
│   │   │   │   └── enrichment.py
│   │   │   └── idempotency/
│   │   │       └── deduplicator.py
│   │   └── tests/
│   ├── processing-engine/          # Python business logic
│   │   ├── pyproject.toml
│   │   ├── src/
│   │   │   ├── settlement/
│   │   │   │   ├── rule_engine.py
│   │   │   │   ├── models.py
│   │   │   │   └── dsl_parser.py
│   │   │   ├── alerts/
│   │   │   │   ├── llm_client.py
│   │   │   │   ├── prompt_templates.py
│   │   │   │   ├── confidence_scorer.py
│   │   │   │   └── human_review_queue.py
│   │   │   └── reconciliation/
│   │   │       ├── checksum.py
│   │   │       ├── drift_detector.py
│   │   │       └── auto_corrector.py
│   │   └── tests/
│   ├── mock-providers/             # Mock data generators
│   │   ├── pyproject.toml
│   │   ├── src/
│   │   │   ├── odds_feed.py        # WebSocket server
│   │   │   ├── event_feed.py       # REST API
│   │   │   ├── settlement_feed.py  # Batch API
│   │   │   └── historical_replay.py
│   │   └── tests/
│   └── notification-service/       # Multi-channel notifications
│       ├── pyproject.toml
│       └── src/
├── n8n-workflows/                  # Exported n8n workflow JSON
│   ├── event-router.json
│   ├── odds-normalization.json
│   ├── settlement-worker.json
│   ├── alert-engine.json
│   └── reconciliation.json
├── monitoring/
│   ├── prometheus/
│   │   ├── prometheus.yml
│   │   ├── rules/
│   │   │   ├── latency.rules.yml
│   │   │   ├── error-rate.rules.yml
│   │   │   └── business-kpi.rules.yml
│   │   └── alerts/
│   │       └── alertmanager.yml
│   └── grafana/
│       ├── dashboards/
│       │   ├── system-overview.json
│       │   ├── business-kpis.json
│       │   ├── ingestion-pipeline.json
│       │   └── alert-quality.json
│       └── provisioning/
│           └── datasources.yml
├── scripts/
│   ├── dev-setup.sh
│   ├── load-test.sh
│   ├── replay-historical.py
│   └── generate-runbooks.py
└── tests/
    ├── contract/
    │   ├── test_odds_feed_contract.py
    │   └── test_settlement_contract.py
    ├── integration/
    │   ├── test_full_pipeline.py
    │   └── test_reconciliation.py
    └── e2e/
        └── test_business_scenarios.py
```

---

## Interview Talking Points by Component

### When asked about **n8n experience**:
> "I built custom n8n nodes in TypeScript for sports-specific logic: an Event Router with priority queuing, an Odds Normalizer handling 3 odds formats with arbitrage detection, and an LLM Alert Generator with structured output parsing. The workflows include error handling with dead-letter queues, retry policies with exponential backoff, and circuit breakers. I can show you the node code and the exported workflow JSON."

### When asked about **AI/LLM in production**:
> "The Alert Engine uses Claude with few-shot prompting to convert raw anomaly data into human-readable alerts with confidence scores. Low-confidence alerts go to a human review queue in n8n; high-confidence ones auto-escalate. I built a prompt evaluation harness to measure precision/recall before each deploy, and a shadow mode to compare LLM decisions against rules-based baseline. This mirrors your IRSF fraud detection approach."

### When asked about **production operations**:
> "The platform has full observability: custom Prometheus metrics for business KPIs (time-to-settle, automation rate, alert precision), Grafana dashboards for both engineers and business stakeholders, Alertmanager with tiered routing and runbook links. The reconciliation job runs daily with checksum comparison and produces an audit trail. I wrote runbooks for the top 5 failure scenarios."

### When asked about **business collaboration**:
> "I started with a Business Process Document mapping the current manual settlement process, identified 3 automation opportunities with ROI calculations, defined KPIs with the business team (target: 95% auto-settlement within 30 seconds), and built a stakeholder dashboard so they can monitor automation health without engineering help."

---

## Skills to Install in Claude Code

### Essential (Install First)
| Skill | Why |
|-------|-----|
| **code-review** | Review your own code before interview; catch bugs, improve quality |
| **simplify** | Refactor for clarity; interviewers love clean, maintainable code |
| **artifact-design** | Create polished diagrams/architectural docs for your portfolio |
| **artifact-diagramming** | Draw the architecture diagram above as inline SVG for README |

### High Value
| Skill | Why |
|-------|-----|
| **run** | Actually run the stack locally and verify it works end-to-end |
| **workflow-authoring** | If you want to automate parts of the build (e.g., generate n8n nodes from spec) |
| **dataviz** | Create the KPI dashboard charts properly |

### Nice to Have
| Skill | Why |
|-------|-----|
| **claude-api** | Reference for LLM integration patterns in your code |
| **fewer-permission-prompts** | Reduce friction during development |

### Installation Commands
```bash
# In your project directory:
claude skill install code-review
claude skill install simplify
claude skill install artifact-design
claude skill install artifact-diagramming
claude skill install run
claude skill install dataviz
```

---

## 30-Minute Interview Demo Script

### 2 min: Problem Statement
> "Sportsbooks receive messy, multi-provider data feeds. Manual settlement is slow and error-prone. I built an automation platform that ingests, normalizes, and settles in real-time with human-in-the-loop for exceptions."

### 3 min: Architecture Walkthrough (show diagram)
> "Here's the data flow... [point to components]... n8n orchestrates, Python services do heavy lifting, LLM handles the fuzzy classification..."

### 5 min: Live Demo
1. Start stack: `make up`
2. Trigger live odds feed → show Grafana latency dashboard
3. Inject test event → trace through n8n UI (visual debugging!)
4. Show settlement auto-complete → check database
5. Trigger anomaly → show LLM alert with confidence score → human review queue

### 5 min: Production Readiness
- Show Prometheus alerts firing in Alertmanager
- Open runbook link from alert
- Show reconciliation report
- Show KPI dashboard (business-facing)

### 5 min: Business Value
- "This replaces 4 hours of manual settlement per day"
- "Alert precision: 92% (measured), recall: 89%"
- "Cost: $X/month vs $Y manual effort"
- "Regulatory audit trail: every decision logged"

### 10 min: Q&A Deep Dives
Be ready to go deep on any component. The project is designed so you can speak authoritatively on:
- n8n custom node architecture
- Exactly-once processing with Redis Streams
- LLM prompt engineering + evaluation
- Settlement rule DSL design
- Testing strategy (contract + integration + chaos)

---

## Quick Start Commands

```bash
# Clone and setup
cd C:\projects\Agentic ai\LSports_Interview_Project
make dev-setup    # Installs deps, starts stack, runs migrations

# Run tests
make test         # Unit + integration
make test-e2e     # Full pipeline tests

# Development
make logs         # Follow all logs
make n8n-logs     # Just n8n
make shell-ingestion  # Shell into ingestion service

# Demo
make demo-data    # Seed test data
make load-test    # 1000 events/sec for 60s

# Cleanup
make down         # Stop stack
make clean        # Remove volumes
```

---

## Success Criteria for Interview

- [ ] Stack runs locally with one command (`make up`)
- [ ] End-to-end flow works: feed → ingestion → n8n → settlement → notification
- [ ] Grafana dashboards show real metrics
- [ ] Alert fires and routes to runbook
- [ ] Reconciliation job produces report
- [ ] You can explain every component in 2 minutes each
- [ ] Code is clean, typed, tested, documented
- [ ] You have a 30-min demo script rehearsed

---

## Next Steps

1. **Initialize the project**: `mkdir -p sports-data-automation && cd sports-data-automation`
2. **Install recommended skills** (see above)
3. **Start with Phase 1**: Docker Compose + canonical types + CI/CD
4. **Use `/code-review`** on each component as you build
5. **Use `/artifact-design`** for architecture diagrams in README
6. **Use `/run`** to verify the stack works end-to-end

---

*Built specifically for LSports AI Business Automation Engineer interview. Every component maps to a stated requirement. Good luck! 🎯*