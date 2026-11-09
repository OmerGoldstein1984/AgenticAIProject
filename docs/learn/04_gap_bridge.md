# 04_gap_bridge.md

# Gap Bridge — "Typical Web App" vs. "This Production System"

**Audience:** the learner. **Audience background:** 10 years QA/automation, web/REST APIs, n8n,
Python/JS, Docker, CI/CD. Strong on *flow*, weaker on production-grade patterns (concurrency,
auth/multi-tenancy, observability, evals, deployment, cost/latency tradeoffs).

**How to read:** For each pattern, "In a typical web app you did X; in this production system
this repo does Y, because Z." Marked **[GAP]** where the repo *intends* Y but hasn't built it —
those are honest gaps to discuss in an interview (and are listed in 07_issues_found.md).

---

## 1. Failure handling

| Aspect | Typical web app (your QA background) | This production system | Because |
|--------|--------------------------------------|------------------------|---------|
| Bad provider payload | Crash or return 500; debug later | Validated against JSON Schema first; rejected with `status: "rejected"` + errors | schema_validator.py:validate — fail fast, never let bad data reach settlement |
| Transient provider failure | Retry blindly or fail the request | Conditional requests (ETag/Last-Modified) + 429 backoff (60s) per endpoint | rest_poller.py:_fetch_and_process — don't hammer a struggling provider |
| Downstream (n8n) outage | Request fails, user sees error | forward_to_n8n catches + logs, **silently drops** data | main.py:forward_to_n8n — **[GAP]** no dead-letter queue/retry yet |
| Unreachable Redis | App won't start / errors everywhere | Deduplicator returns False (allow-through) on Redis failure | deduplicator.py:check_and_store — availability over perfect dedup |
| Untransformable record | Exception bubbles up, request fails | Catch-all returns original data unchanged | canonical_transformer.py:transform_* — pipeline stays up |
| LLM can't parse / no API key | 500 error | All items → error output; parse failures → error output for that item only | LLMAlertGenerator.node.ts:execute — one bad item never aborts the batch |

**Interview line:** "I prefer failing closed on data correctness (schema rejection) but failing open on
availability (let odds through if Redis is down) — you can reprocess a duplicate, but you can't
un-settle a wrongly-paid bet."

---

## 2. Scale & concurrency

| Aspect | Typical web app | This production system | Because |
|--------|----------------|------------------------|---------|
| Concurrency model | Sync request/thread per request | Asyncio throughout (FastAPI, websockets, httpx, redis.asyncio) | main.py / websocket_client.py — thousands of concurrent feed connections on few threads |
| High-volume feed | Poll an API endpoint | WebSocket push (500ms–2s) + fan-out to all connected clients | odds_feed.py:_broadcast_loop — matches real provider push semantics |
| Message ordering | Not guaranteed | Per-producer monotonic sequence + dedup key includes sequence | canonical_transformer / deduplicator — odds arrive out of order; sequence orders them |
| Backpressure | Server queues requests | **[GAP]** none — slow WebSocket client blocks the broadcast loop | odds_feed.py:# GAP — a production feed needs per-client queues or a broker |
| Horizontal scale | Add app instances behind LB | Designed stateless (ingestion), n8n queue mode + Redis Streams for workers | docker-compose + README — stateless services scale; DBs are single-instance here |
| Batch vs stream | Mostly batch (nightly jobs) | Continuous streaming (odds WebSocket) + REST polling + daily reconciliation batch | Different SLA per data type: odds = seconds, reconciliation = daily |

**Interview line:** "The ingestion service is stateless and async — you can run N replicas behind a
load balancer and shard by provider. Redis dedup keys are shared, so no replica processes the same
odds twice."

---

## 3. Security & auth

| Aspect | Typical web app | This production system | Because |
|--------|----------------|------------------------|---------|
| Secrets | Env vars, sometimes committed | Env vars via `.env` + Pydantic Settings; `extra="ignore"` | config.py:Settings — central, typed, doesn't crash on unknown CI vars |
| Stored credentials | Plain text in config | n8n credential type with `password: typeOptions` (encrypted at rest) | SportsApiCredentials.credentials.ts — API keys/secrets not in node configs |
| CORS | Often `*` in dev, tight in prod | `allow_origins=["*"]` (dev-friendly) | main.py:CORS — **[INFERENCE]** tighten origins before prod |
| Input trust | Trust the frontend/API caller | Validate everything from providers with JSON Schema | schema_validator.py — providers are external, untrusted |
| Audit trail | Often missing for business decisions | Settlement audit trail (rule version, evaluated rules, confidence, timestamps) | SettlementWorker.node.ts — regulatory requirement in betting |
| LLM prompt injection | Not a concern | Few-shot + schema constrain output; system prompt instructs "JSON only" | LLMAlertGenerator.node.ts:buildSystemPrompt — limits LLM freedom |

**Interview line:** "Credentials live in n8n's encrypted credential store, never hard-coded in node
configs — that's the difference between a demo and something you'd hand to a security reviewer."

---

## 4. Cost

| Aspect | Typical web app | This production system | Because |
|--------|----------------|------------------------|---------|
| Cost visibility | Infra bill at month-end | Prometheus cost-per-event metric + alerts | monitoring/prometheus/rules/business-kpi.rules.yml:HighCostPerEvent |
| LLM cost | Not tracked | Per-alert token estimate tracked; temperature 0.1 for cheap, consistent output | LLMAlertGenerator.node.ts (temperature, maxTokens) |
| Over-provisioning | Common | Right-sized dev stack (256mb Redis, single replicas) | docker-compose.yml — sized for laptop/demo, not production |
| Build vs buy | Often not analyzed | ROI analysis: build $800K 3yr vs Workato $1,120K vs SaaS $825K | docs/business/roi-analysis.md — recommends BUILD |

**Interview line:** "We track cost-per-event as a KPI and alert when it exceeds $0.01 — infrastructure
cost is a first-class operational concern, not a footnote."

---

## 5. Observability

| Aspect | Typical web app | This production system | Because |
|--------|----------------|------------------------|---------|
| Metrics | Maybe request count/latency | Counters + histograms + gauges for business + system KPIs | metrics.py — events_received/validated/deduplicated/forwarded, latency histograms |
| Dashboards | Ad-hoc | Grafana business dashboard (executives) + system dashboard (engineers) | kpi-definitions.md:282-297 + monitoring/grafana/dashboards/*.json |
| Alerting | PagerDuty on errors | Tiered (page/critical/warning/info) + routing to pager/warning/business/info | alertmanager.yml:route |
| Runbooks | Tribal knowledge | Runbook links on every alert annotation | alertmanager.yml annotations + runbook references |
| Distributed tracing | Often missing | **[GAP]** no tracing (trace ID propagation) | 07_issues_found.md — note it |
| Structured logging | console.log / print | logging.basicConfig with timestamp+level+message | main.py / module loggers |

**Interview line:** "Every alert carries a runbook URL and every KPI has a warning/critical/page
threshold — an on-call engineer can act without paging the developer who wrote the code."

---

## 6. Testing & evals

| Aspect | Typical web app | This production system | Because |
|--------|----------------|------------------------|---------|
| Unit tests | pytest/jest on business logic | **[GAP]** no `tests/` directory exists in the repo | 07_issues_found.md — test suite referenced by Makefile/CI but not shipped |
| Contract tests | Sometimes | Provider→canonical contract via types.ts/types.py (manual sync — no automated test) | **[GAP]** no automated TS↔Python sync test |
| LLM eval | Rarely | Rule-based baseline agreement + precision/recall measurement | LLMAlertGenerator ruleBasedBaseline + kpi-definitions.md alert precision |
| Shadow mode | Rarely | Referenced (PROJECT_SPEC) but not implemented | **[GAP]** — evaluate LLM vs rules before cutover |
| Chaos/fault injection | Rarely | **[GAP]** not implemented | 07_issues_found.md |
| CI | GitHub Actions | Lint + test + type-check + docker-build on every PR | ci.yml |

**Interview line:** "My QA background means I think in tests first; the repo's CI gate and contract
types reflect that — but the automated test suite itself is a gap I'd fill before shipping."

---

## 7. Deployment

| Aspect | Typical web app | This production system | Because |
|--------|----------------|------------------------|---------|
| Local dev | `docker compose up` or manual | One-command `make dev-setup` (build+start+migrate+seed) | Makefile:dev-setup |
| Deploy | kubectl / terraform / PaaS | Docker Compose locally; K8s manifests mentioned but not shipped | PROJECT_SPEC:Deploy → K8s manifests |
| Zero-downtime deploy | Rolling updates | **[GAP]** not implemented | 07_issues_found.md |
| Config management | Env vars per env | Pydantic Settings + `.env`; same image in dev/CI/prod | config.py — 12-factor config |
| Release gating | Manual or CI | CI gate (lint/test/type/build) before deploy-staging/prod | ci.yml — deploy jobs gated |

**Interview line:** "The CI pipeline is the release gate: nothing reaches staging/production
without lint, tests, type-check, and a successful docker build."

---

## 8. Honest "this repo intends X but hasn't built Y" gaps

These are real and worth naming in an interview (it shows maturity):

1. **No automated test suite** — Makefile/CI reference `tests/` but the directory doesn't exist. (07_issues_found.md)
2. **metrics.py syntax error** — `await` outside `async function` breaks import of the whole ingestion service. (07_issues_found.md)
3. **n8n dist/ not built** — docker-compose mounts `./packages/n8n-nodes/dist` which isn't produced. (07_issues_found.md)
4. **processing-engine service missing** — docker-compose/CI reference it; no package exists. (07_issues_found.md)
5. **LLM SDK calls commented out** — LLMAlertGenerator uses simulated responses, not real Anthropic/OpenAI calls. (07_issues_found.md)
6. **No dead-letter queue / retry on n8n forward** — data dropped on outage. (main.py:forward_to_n8n)
7. **No TS↔Python contract sync test** — types can drift. (07_issues_found.md)
8. **No provider hot-reload / registry** — adding a provider requires code edits. (07_issues_found.md)
