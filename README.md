# Sports Data Automation Platform

> **Built for the LSports AI Business Automation Engineer interview** — A production-grade platform demonstrating end-to-end business process automation for real-time sports data feeds.

[![Architecture](architecture-diagram.svg)](architecture-diagram.svg)

---

## Why This Project Exists

This project directly addresses every requirement in the LSports job description:

| Requirement | Implementation |
|-------------|----------------|
| **AI-driven business process automation in production** | Full n8n + Python stack with Docker Compose, CI/CD, observability |
| **n8n/Workato hands-on experience** | Custom TypeScript n8n nodes: Event Router, Odds Normalizer, Settlement Worker, LLM Alert Generator |
| **APIs, integrations, SaaS data workflows** | WebSocket, REST, GraphQL ingestion; mock CRM, Risk, Reporting, Notification integrations |
| **Translate business needs → technical solutions** | Business Process Document, KPI definitions, ROI analysis, stakeholder dashboard |
| **KPIs, success metrics, tangible value** | Automated Prometheus metrics: automation rate, time-to-settle, alert precision/recall, cost saved |
| **Production ownership: monitoring, alerting, error handling** | Prometheus/Grafana/Alertmanager, runbook generator, dead-letter queues, reconciliation |
| **Cross-team communication** | Business-facing Grafana dashboard, runbooks for non-technical on-call, demo script |

---

## Quick Start

```bash
# 1. Clone and enter project
cd C:\projects\Agentic ai\LSports_Interview_Project\sports-data-automation

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys (ANTHROPIC_API_KEY for LLM alerts)

# 3. Start everything
make dev-setup

# 4. Verify
# n8n:        http://localhost:5678 (admin / your N8N_PASSWORD)
# Grafana:    http://localhost:3000 (admin / your GRAFANA_PASSWORD)
# Prometheus: http://localhost:9090
# Ingestion API: http://localhost:8000/docs
```

**See [QUICKSTART.md](QUICKSTART.md) for full commands, troubleshooting, and interview-day checklist.**

---

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  MOCK PROVIDERS │────▶│  INGESTION SVC   │────▶│   N8N ORCHESTRATION │
│  (WebSocket,    │     │  (FastAPI)       │     │   (Queue Mode +    │
│   REST, Batch)  │     │  Normalize,      │     │    Redis Streams)  │
└─────────────────┘     │  Validate,       │     └─────────┬──────────┘
                        │  Deduplicate     │               │
                        └──────────────────┘               ▼
                                    ┌─────────────────────────────────┐
                                    │      CUSTOM N8N NODES           │
                                    │  • Event Router (Priority Queue)│
                                    │  • Odds Normalizer (3 formats, │
                                    │    arbitrage detection)         │
                                    │  • Settlement Worker (Rule DSL) │
                                    │  • LLM Alert Gen (Structured    │
                                    │    Output + Confidence)         │
                                    │  • Reconciliation (Daily Batch) │
                                    └─────────────────┬───────────────┘
                                                      ▼
                        ┌─────────────────────────────┼─────────────────────────────┐
                        ▼                             ▼                             ▼
               ┌───────────────┐             ┌───────────────┐             ┌───────────────┐
               │ Sportsbook    │             │ Risk Mgmt     │             │ Reporting     │
               │ CRM (Mock)    │             │ (Exposure,    │             │ Warehouse     │
               │ OAuth, Webhook│             │  Limits)      │             │ (TimescaleDB) │
               └───────────────┘             └───────────────┘             └───────────────┘
                        │                             │                             │
                        └─────────────────────────────┼─────────────────────────────┘
                                                      ▼
                                    ┌─────────────────────────────────┐
                                    │      OBSERVABILITY PLANE        │
                                    │  • Prometheus (Custom Metrics)  │
                                    │  • Grafana (System + Business)  │
                                    │  • Alertmanager (Tiered +       │
                                    │    Runbook Links)               │
                                    │  • KPI Tracker (Auto)           │
                                    │  • Runbook Generator            │
                                    └─────────────────────────────────┘
```

**Full diagram:** [architecture-diagram.svg](architecture-diagram.svg)

---

## Core Components

### 1. Mock Data Providers (Simulating LSports Feeds)
| Provider | Protocol | Purpose |
|----------|----------|---------|
| **Live Odds Feed** | WebSocket | Pushes odds updates every 500ms–2s in Decimal/American/Fractional |
| **Event Feed** | REST API | Match events: goals, cards, substitutions, injuries |
| **Settlement Feed** | Batch REST | Post-match official results for auto-settlement |
| **Historical Replay** | CLI | Backtesting, shadow mode evaluation |

### 2. Ingestion Service (Python FastAPI)
- **Protocol Adapters**: WebSocket client, REST pollers, GraphQL subscriptions
- **Normalization**: Provider-specific schemas → canonical internal format
- **Validation**: JSON Schema + custom business rules
- **Idempotency**: Deduplication keys, sequence numbers, out-of-order handling

### 3. n8n Custom Nodes (TypeScript)
| Node | Business Logic | Technical Highlights |
|------|----------------|---------------------|
| **Event Router** | Route events to correct downstream workflows | Content-based routing, priority queues, Redis Streams consumer groups |
| **Odds Normalizer** | Unify odds from multiple providers | 3-format conversion, arbitrage detection, best-odds selection |
| **Settlement Worker** | Auto-settle bets on official result | Rule DSL (won/lost/void/half-won/half-lost), partial settlement, audit trail |
| **LLM Alert Generator** | Detect anomalies, generate human-readable alerts | Few-shot prompting, structured JSON output, confidence scoring, human review queue |
| **Reconciliation Job** | Daily batch drift detection | Checksum comparison, auto-correction, manual review queue |

### 4. Output Systems (Mock SaaS)
- **Sportsbook CRM**: Customer notifications, bet updates (OAuth + webhooks)
- **Risk Management**: Real-time exposure calculation, limit enforcement
- **Reporting Warehouse**: TimescaleDB for time-series analytics
- **Notifications**: Email, Slack, SMS, Push with template engine
- **Audit Trail**: Immutable log for regulatory compliance

### 5. Observability & Control Plane
- **Metrics**: Latency (p50/p95/p99), throughput, error rates, data freshness
- **Business KPIs**: Automation rate, time-to-settle, alert precision/recall, cost per event
- **Alerting**: Multi-level (warning/critical/page), on-call rotation, runbook links
- **Reconciliation Dashboard**: Daily drift report, manual override capability

---

## Repository Structure

```
sports-data-automation/
├── docker-compose.yml              # Full local stack
├── Makefile                        # Common commands (make dev-setup, make demo-data, etc.)
├── .env.example                    # Environment template
├── .github/workflows/ci.yml        # CI/CD pipeline
├── docs/
│   ├── architecture/               # ADRs: data model, routing, LLM design
│   ├── runbooks/                   # Alert runbooks (auto-generated)
│   ├── business/                   # Process map, KPI definitions, ROI analysis
│   └── api/openapi.yaml            # Ingestion service API spec
├── packages/
│   ├── canonical-types/            # Shared TS/Python types (single source of truth)
│   ├── n8n-nodes/                  # Custom n8n nodes (TypeScript)
│   ├── ingestion-service/          # Python FastAPI service
│   ├── processing-engine/          # Python business logic (settlement, alerts, reconciliation)
│   ├── mock-providers/             # Mock data generators
│   └── notification-service/       # Multi-channel notifications
├── n8n-workflows/                  # Exported n8n workflow JSON
├── monitoring/
│   ├── prometheus/                 # Prometheus config, alert rules
│   └── grafana/                    # Dashboards + provisioning
├── scripts/                        # Dev setup, load test, replay, runbook generation
└── tests/
    ├── contract/                   # Provider contract tests
    ├── integration/                # Cross-service integration tests
    └── e2e/                        # Full business scenario tests
```

---

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| **n8n Queue Mode + Redis Streams** | Exactly-once semantics, horizontal scaling, dead-letter handling — production pattern |
| **Custom TypeScript n8n Nodes** | Not just workflow JSON — real code with tests, versioning, type safety |
| **Canonical Types (TS + Python)** | Single source of truth; contract testing between services |
| **Rule DSL for Settlement** | Business rules change; engineers shouldn't redeploy for rule updates |
| **LLM with Structured Output + Confidence** | Production LLM pattern: never auto-act on low confidence; human-in-the-loop queue |
| **Shadow Mode + Historical Replay** | Evaluate rule/LLM changes before enforcement (mirrors your IRSF approach) |
| **Prometheus Business Metrics** | Engineers see system health; stakeholders see business value — same data, different dashboards |
| **Runbook Generator** | Alerts without runbooks are noise; auto-generate from alert rules |

---

## Interview Demo Script (30 Minutes)

| Time | Segment | What to Show |
|------|---------|--------------|
| 2 min | Problem Statement | "Sportsbooks receive messy multi-provider feeds. Manual settlement is slow/error-prone." |
| 3 min | Architecture | Walk through [diagram](architecture-diagram.svg) — emphasize n8n custom nodes, Redis Streams, observability |
| 5 min | Live Demo | `make demo-data` → trace event through n8n UI → show settlement → show Grafana |
| 5 min | Production Ops | Trigger alert → show Alertmanager → click runbook link → show reconciliation report |
| 5 min | Business Value | Open business KPI dashboard: "This is what Head of Trading sees — no engineering help needed" |
| 10 min | Q&A Deep Dives | Be ready on: n8n node architecture, exactly-once, LLM eval, settlement DSL, testing strategy |

**Full script in [QUICKSTART.md](QUICKSTART.md#interview-day-commands)**

---

## Business Artifacts (Print for Interview)

| Document | Purpose |
|----------|---------|
| [Business Process Map](docs/business/process-map.md) | Shows you map manual processes before automating |
| [KPI Definitions](docs/business/kpi-definitions.md) | Formulas, targets, measurement method |
| [ROI Analysis](docs/business/roi-analysis.md) | Build vs buy, cost savings, payback period |
| [Architecture ADRs](docs/architecture/) | Shows you document decisions |

---

## Skills to Install in Claude Code

```bash
# Essential — use during development
claude skill install code-review      # Review your code before committing
claude skill install simplify         # Refactor for clarity
claude skill install artifact-design  # Polish diagrams/docs
claude skill install artifact-diagramming  # Create architecture diagrams

# High value
claude skill install run              # Actually run and verify the stack
claude skill install dataviz          # Proper KPI charts

# Optional
claude skill install claude-api       # LLM integration reference
claude skill install fewer-permission-prompts  # Less friction
```

---

## Gap Analysis: Your CV vs. This Role

**You're an 8/10 match.** Your Webbing experience (real-time telecom feeds, n8n at scale, LLM in production with guardrails, QA DNA) maps directly. The gaps are **sports betting domain** and **business-facing deliverables** — both closed by this project.

**See [GAP_ANALYSIS.md](GAP_ANALYSIS.md) for:**
- Requirement-by-requirement mapping
- Your unique strengths to lead with
- How to answer "sports betting experience?" questions
- Interview strategy to turn gaps into strengths

---

## Project Spec & Build Plan

**Full specification:** [PROJECT_SPEC.md](PROJECT_SPEC.md)

| Phase | Focus | Weeks |
|-------|-------|-------|
| 1 | Foundation: Docker stack, canonical types, CI/CD, n8n nodes skeleton | 1 |
| 2 | Ingestion + Core Workflows: Event Router, Odds Normalizer, Settlement | 1-2 |
| 3 | LLM Alert Engine + Reconciliation + Observability | 2-3 |
| 4 | Business Layer: Stakeholder dashboard, runbooks, docs, demo rehearsal | 3-4 |

**Minimum viable (2 weeks):** Phases 1-2 + basic Grafana + demo script

---

## License

MIT — Built for interview demonstration. Feel free to adapt for your portfolio.

---

## Contact

**Omer Goldstein**  
AI Solutions Engineer | Software Engineer  
📧 omergldb@gmail.com | 📱 +972-53-825-3231  
🔗 [LinkedIn](https://linkedin.com/in/omer-goldstein--ai-solutions)

*Good luck with the interview! This project proves you can do the job — now go show them.* 🎯