# 00_START_HERE.md

# Start Here — Reading Guide for the LSports Interview Project

**Audience:** the learner (senior QA/automation engineer → AI Solutions Engineer).
**Goal:** After studying this repo you can explain, defend, and extend every part of it in an FDE
interview, as if you built it yourself.

**Assumed pace:** ~2 hours/day. Total estimated study time: ~18–22 hours over ~10 days.

---

## 1. What this project is (in 5 sentences)

1. It's a demonstration platform for an LSports "AI Business Automation Engineer" interview — a
   real-time sports-data automation pipeline from live odds/events to settlement and alerts.
2. Mock providers (WebSocket odds, REST events/settlements) feed a Python/FastAPI ingestion
   service that validates, normalizes to a canonical schema, deduplicates, and forwards to n8n.
3. Four custom TypeScript n8n nodes route events by priority, normalize odds across providers
   (with arbitrage detection), auto-settle bets via a rule DSL (with audit trail), and generate
   LLM alerts (with confidence scoring and human review).
4. Prometheus/Grafana/Alertmanager provide observability; business KPIs (automation rate,
   time-to-settle, alert precision) are tracked and dashboarded.
5. Everything runs in Docker Compose with a GitHub Actions CI gate — designed to be explained,
   defended, and extended in an interview.

---

## 2. Exact reading order (file by file)

The order follows **dependency order: leaves first, entrypoint last**. After each file, answer
the question before moving on — if you can't, re-read that file.

| # | File | Reason for the order | Question to answer after reading | Est. time |
|---|------|----------------------|----------------------------------|-----------|
| 1 | docs/learn/01_business_context.md | Why the system exists (motivation first) | What pain does this solve, and for whom? | 25 min |
| 2 | docs/learn/03_glossary.md | Learn the vocabulary before reading code | Define: canonical format, idempotency, implied probability, DLQ | 30 min |
| 3 | docs/learn/07_issues_found.md | Know what's broken before you trust the code | What's the metrics.py bug? What tests are missing? | 25 min |
| 4 | packages/canonical-types/src/types.ts + python/sports_automation/types.py | Leaf module — the single source-of-truth contract | What's the difference between a settlement "won" and "void"? | 30 min |
| 5 | packages/mock-providers/src/mock/odds_feed.py | First data producer (no repo dependencies) | How does an odds update get a sequence number? | 25 min |
| 6 | packages/mock-providers/src/mock/event_feed.py | Second data producer (REST) | How does pagination + `since` filtering work? | 20 min |
| 7 | packages/ingestion-service/src/ingestion/config.py | Bootstrap — everything else reads settings | Where do Redis/Postgres/n8n addresses come from? | 15 min |
| 8 | packages/ingestion-service/src/ingestion/schema_validator.py | First ingestion stage (validate) | What happens when a payload is invalid? | 20 min |
| 9 | packages/ingestion-service/src/ingestion/canonical_transformer.py | Second stage (transform) | How are American odds converted to decimal? | 25 min |
| 10 | packages/ingestion-service/src/ingestion/idempotency/deduplicator.py | Third stage (dedupe) | What's the Redis dedup key for an odds update? | 15 min |
| 11 | packages/ingestion-service/src/ingestion/main.py | Entrypoint (validate→transform→dedupe→forward) | Trace one odds item through `process_odds` | 30 min |
| 12 | packages/n8n-nodes/src/index.ts + credentials | Orchestration layer registration | How does n8n discover the custom nodes? | 15 min |
| 13 | packages/n8n-nodes/src/Nodes/SportsEventRouter.node.ts | Routing node | What are the 4 outputs and their order? | 20 min |
| 14 | packages/n8n-nodes/src/Nodes/OddsNormalizer.node.ts | Normalization + arbitrage | How is arbitrage detected (formula)? | 20 min |
| 15 | packages/n8n-nodes/src/Nodes/SettlementWorker.node.ts | Settlement + audit | What's the default outcome and why? | 20 min |
| 16 | packages/n8n-nodes/src/Nodes/LLMAlertGenerator.node.ts | Alerts + human review | How does confidence route auto-escalate vs review? | 20 min |
| 17 | docker-compose.yml + Makefile + ci.yml | Infra / deploy / CI gate | How does one command bring up the whole stack? | 25 min |
| 18 | monitoring/prometheus/*.yml + alertmanager.yml + grafana/ | Observability plane | Where do alert thresholds live? | 20 min |
| 19 | docs/business/kpi-definitions.md + process-map.md + roi-analysis.md | Business layer | What's the automation-rate formula and target? | 25 min |
| 20 | docs/learn/02_architecture.md | System-level view (read after components) | Draw the data flow from memory | 30 min |
| 21 | docs/learn/04_gap_bridge.md | Patterns: web app vs production system | Name 3 differences from a typical web app | 30 min |
| 22 | docs/learn/05_trace_walkthrough.md | End-to-end narrative (run it after the stack) | Trace the sample odds update hop by hop | 30 min |
| 23 | docs/learn/06_interview_pack.md | Interview prep (25 Q&As, scenarios, drills) | Pick 5 questions and answer them out loud | 45 min |

**Total reading:** ~9–11 hours. Plus ~4–6 hours of running/breaking (below).

---

## 3. Day-by-day study plan (2 hours/day)

| Day | Focus | Activities | Reading |
|-----|-------|------------|---------|
| Day 1 | Context & vocabulary | Read business context, glossary; browse the repo tree | 01, 03 |
| Day 2 | The contract & data sources | Read types (TS + Python); read both mock providers; compile-check Python | 04, 05, 06 |
| Day 3 | Ingestion pipeline (1) | Read config, schema_validator, canonical_transformer | 07, 08, 09 |
| Day 4 | Ingestion pipeline (2) | Read deduplicator, main.py; trace one odds item; note the metrics.py bug | 10, 11, 07 (A1) |
| Day 5 | Orchestration layer | Read n8n nodes (router, normalizer, settlement, LLM) + index/credentials | 12–16 |
| Day 6 | Infra, CI, observability | Read docker-compose, Makefile, ci.yml, monitoring configs | 17, 18 |
| Day 7 | Business layer & architecture | Read KPIs, process map, ROI; then architecture doc (draw from memory) | 19, 20 |
| Day 8 | Patterns & trace walkthrough | Read gap bridge; trace walkthrough; run the stack if Docker available | 21, 22 |
| Day 9 | Interview prep | Read interview pack; answer 5 Q&As out loud; attempt 3 break-it drills | 23 |
| Day 10 | Review & gaps | Re-read 07_issues_found.md; rehearse the 2-min and 5-min walkthroughs | 07 + Part A/B |

> **If you fall behind:** prioritize Days 1–4 and the interview pack (Part A Q1–Q8, Part B 2-min walkthrough). That's enough to defend the core.

---

## 4. One-page mental map

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  sports-data-automation/                                                    │
│  ├── README.md / PROJECT_SPEC.md / GAP_ANALYSIS.md / QUICKSTART.md  (why)  │
│  ├── docs/business/          KPIs, process map, ROI                        │
│  ├── monitoring/             Prometheus + Grafana + Alertmanager           │
│  ├── packages/                                           │
│  │   ├── canonical-types/   TS + Python shared contract  (LEAF — read first)│
│  │   ├── mock-providers/    WebSocket + REST feed simulators              │
│  │   ├── ingestion-service/ FastAPI: validate→transform→dedupe→forward    │
│  │   └── n8n-nodes/         4 custom TS nodes + credentials               │
│  ├── docker-compose.yml      one-command stack                            │
│  ├── Makefile                dev ops commands                              │
│  └── .github/workflows/ci.yml CI gate: lint+test+type+docker              │
└─────────────────────────────────────────────────────────────────────────────┘
            data flow: providers → ingestion → n8n nodes → (CRM/Risk/Reporting)
                              │                          │
                              └── Prometheus/Grafana/Alertmanager (observability)
```

**docs/learn/ map:**
- `00_START_HERE.md` — this guide (start here)
- `01_business_context.md` — who, what pain, how success is measured
- `02_architecture.md` — components, data flow, sequence, trust boundaries
- `03_glossary.md` — every term, library, acronym, config key
- `04_gap_bridge.md` — "typical web app vs this production system"
- `05_trace_walkthrough.md` — one odds update, hop by hop, with file:line
- `06_interview_pack.md` — 25+ Q&As, walkthroughs, customer scenarios, break-it drills
- `07_issues_found.md` — bugs, smells, UNVERIFIED items, missing tests, security
- `_plan.md` — the annotation plan (internal)

---

## 5. Links to every doc in docs/learn/

- [_plan.md](_plan.md) — Phase 0 annotation plan
- [01_business_context.md](01_business_context.md)
- [02_architecture.md](02_architecture.md)
- [03_glossary.md](03_glossary.md)
- [04_gap_bridge.md](04_gap_bridge.md)
- [05_trace_walkthrough.md](05_trace_walkthrough.md)
- [06_interview_pack.md](06_interview_pack.md)
- [07_issues_found.md](07_issues_found.md)

**Source-of-truth links (the actual code):**
- `packages/canonical-types/src/types.ts`
- `packages/canonical-types/python/sports_automation/types.py`
- `packages/mock-providers/src/mock/odds_feed.py`
- `packages/mock-providers/src/mock/event_feed.py`
- `packages/ingestion-service/src/ingestion/main.py`
- `packages/n8n-nodes/src/index.ts`

---

## 6. How to practice (run it / break it)

1. **Run it:** If Docker is available, `make dev-setup` then `make demo-data`. Verify
   http://localhost:8000/health, n8n http://localhost:5678, Grafana http://localhost:3000.
   (Not runnable in this session — no Docker daemon — see 07_issues_found.md C-items.)
2. **Trace it:** Follow 05_trace_walkthrough.md with the sample odds update; confirm each hop.
3. **Break it:** Attempt the 10 break-it drills in 06_interview_pack.md Part D, then check the
   hidden answer key.
4. **Defend it:** Answer the 25+ questions in 06_interview_pack.md Part A out loud, in first
   person, citing file:line.

**You're ready when you can:** draw the data flow from memory, name the metrics.py bug and the
missing tests, explain why settlement defaults to "void", and walk through one odds update hop
by hop — all without notes.
