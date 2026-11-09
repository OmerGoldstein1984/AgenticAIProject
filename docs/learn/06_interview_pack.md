# 06_interview_pack.md

# Interview Pack — Sports Data Automation Platform

**Audience:** the learner, preparing for an LSports Forward Deployed Engineer (FDE) interview.
**Goal:** Be able to explain, defend, and extend every part of this repo *as if you built it*.

> 📌 All answers are in **first person** ("I...") and grounded in the repo (file:line cited).
> Sections marked **[INFERENCE]** are the learner's talking points to adapt, not quotes.

---

## Part A — 25+ FDE questions with model answers

### Design choices & tradeoffs

**Q1. Why n8n instead of just Python services for orchestration?**

> "The job description explicitly asks for n8n/Workato experience, and n8n gives visual workflow
> debugging — an on-call engineer can see exactly where a workflow stuck. But I didn't use n8n
> for everything: the ingestion service (Python/FastAPI) does validation, normalization, and
> deduplication because that's heavy, type-safe, testable logic; n8n does the routing and
> business rules. I wrote custom TypeScript n8n nodes (Event Router, Odds Normalizer,
> Settlement Worker, LLM Alert Generator) rather than only workflow JSON, so the logic is
> versioned, typed, and testable as code [packages/n8n-nodes/src/index.ts]. I ran n8n in Queue
> Mode with Redis Streams for exactly-once semantics and dead-letter handling
> [docker-compose.yml:n8n]."

**Q2. Why a canonical data model shared between TypeScript and Python?**

> "Providers send odds in different formats and field names. Without one contract, each module
> re-derives fields and they drift. I defined CanonicalOdds/CanonicalEvent/SettlementResult in
> TypeScript [packages/canonical-types/src/types.ts] and mirrored them in Pydantic Python
> [packages/canonical-types/python/sports_automation/types.py] so the ingestion service and the
> n8n nodes agree on field names. This enables contract testing between services. **[GAP]** there's
> no automated test asserting the two stay in sync — a field added to one but not the other would
> surface only at runtime [07_issues_found.md]."

**Q3. Why normalize all odds to decimal internally?**

> "Providers quote decimal, American, and fractional. Storing everything as decimal lets the
> OddsNormalizer compare prices across providers and compute implied probability (1/decimal
> odds) and arbitrage [canonical_transformer.py:_normalize_odds; OddsNormalizer.node.ts]. I keep
> the original `format` field so the raw provider payload can be reconstructed for audit."

**Q4. Why a Rule DSL for settlement instead of hard-coded logic?**

> "Settlement rules (home win/away win/draw/void/half) change with sport and regulation, and
> getting a payout wrong is a regulatory issue. A declarative JSON DSL lets business users change
> rules without a code deploy [SettlementWorker.node.ts embeddedRuleSet]. The engine evaluates
> AND/OR/NOT conditions, picks the highest-priority match, and computes confidence. **[GAP]**
> hot-reload from Database/Remote is declared in the UI but not implemented — only embedded JSON
> works [07_issues_found.md]."

**Q5. Why default settlement outcome to "void"?**

> "In betting it's safer to withhold a payout than to pay on an unrecognized match. The DSL
> defaultOutcome is 'void' [types.ts:SettlementRuleSet / SettlementWorker.getDefaultRuleSet],
> and unknown outcomes are defaulted to void [canonical_transformer.py:transform_settlement].
> Low-confidence settlements go to a human-review queue rather than auto-paying."

### Concurrency / async

**Q6. How does the ingestion service handle high-frequency WebSocket odds (500ms–2s)?**

> "asyncio throughout: FastAPI lifespan, websockets client, httpx, redis.asyncio all async
> [main.py; websocket_client.py]. The WebSocket client fans each message to a background task
> (`asyncio.create_task(self._safe_on_message(data))`) so a slow handler never blocks the receive
> loop [websocket_client.py:_handle_messages]. The ingestion service is stateless, so N replicas
> can run behind a load balancer. **[GAP]** the mock feed has no backpressure — a slow client
> blocks the broadcast loop for all clients [odds_feed.py:# GAP]."

**Q7. How do you guarantee exactly-once processing on retries?**

> "Deduplicator uses Redis `SET NX EX` (atomic check-and-set) with a 24h TTL on keys like
> `odds:{providerId}:{eventId}:{sequence}` [deduplicator.py:check_and_store]. If the same odds
> arrives twice (retry/reconnect), the second is detected as a duplicate and skipped. If Redis is
> down, it allow-through (availability over perfect dedup) so the pipeline stays up
> [deduplicator.py:check_and_store failure mode]."

### Auth / multi-tenancy

**Q8. How are provider API keys handled?**

> "Through an n8n credential type `SportsApiCredentials` with `typeOptions: { password: true }`
> for apiKey/apiSecret — n8n encrypts them at rest and they're never hard-coded in node configs
> [SportsApiCredentials.credentials.ts]. The LLMAlertGenerator reads the API key from node config
> or an env var (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`) [LLMAlertGenerator.node.ts:execute]."

**Q9. Is this multi-tenant?**

> "Not in this build. There's a `providerId` on every odds record and a `ProviderConfig` type
> [types.ts:ProviderConfig], so the data model is provider-aware, but there's no tenant isolation,
> RBAC, or per-customer config. **[INFERENCE]** For a real SaaS I'd add tenant_id and
> row-level security — worth naming as a gap."

### Observability

**Q10. What metrics do you expose and why?**

> "Prometheus counters/histograms at /metrics [metrics.py]: events_received/validated/
> deduplicated/forwarded (by source, type, result), processing_latency_seconds, provider_latency,
> active_connections, n8n_webhook_latency/errors. The KPI dashboard computes automation rate,
> validation success rate, alert precision from these [kpi-definitions.md]. Alertmanager tiers
> alerts to pager/warning/business/info with runbook links [alertmanager.yml]."

**Q11. How do you know if the LLM is hallucinating alerts?**

> "Confidence scoring (0–1) with a threshold (default 0.8): above threshold + rule-based
> baseline agreement → auto-escalate; below → human-review queue [LLMAlertGenerator.node.ts].
> Alert precision/recall are measured against a rule-based baseline [kpi-definitions.md:127].
> **[GAP]** real LLM SDK calls are commented out; the node uses simulated responses in this build
> [07_issues_found.md]."

**Q12. What's your incident/on-call story?**

> "Alertmanager routes by severity — page/critical go to on-call immediately with runbook URL;
> warning/business go to team channels with delay [alertmanager.yml:route]. Every alert
> annotation carries a runbook_url. MTTR target <15 min critical, <60 min warning
> [kpi-definitions.md:185]. **[GAP]** no runbooks directory is actually present in the repo
> (docs/runbooks referenced but missing) [07_issues_found.md]."

### Evals / testing / quality

**Q13. Where are the automated tests?**

> "The Makefile and CI reference `packages/*/tests/` and pytest, but no `tests/` directory
> exists in this repo — they print a 'not yet implemented' fallback [Makefile:test; ci.yml].
> My QA background means I'd write unit tests for canonical_transformer, deduplicator, and
> SettlementWorker rule evaluation, plus contract tests for the TS↔Python types, before shipping.
> **[GAP]** noted in 07_issues_found.md."

**Q14. How do you prevent provider schema changes from breaking ingestion?**

> "JSON Schema validation rejects malformed payloads before they reach settlement
> [schema_validator.py]. Provider field mappings live in CanonicalTransformer PROVIDER_MAPPINGS,
> so a new provider needs new mappings, not new code. **[GAP]** no automated contract test
> asserts TS↔Python type sync, and there's no versioned schema registry (schemas auto-created on
> disk) [07_issues_found.md]."

### Cost / latency / scaling

**Q15. What's the cost model?**

> "Infrastructure cost-per-event is a tracked KPI with an alert above $0.01/event
> [monitoring/prometheus/rules/business-kpi.rules.yml:HighCostPerEvent; kpi-definitions.md:226].
> ROI analysis compares Build ($800K 3yr) vs Workato ($1,120K) vs SaaS ($825K) and recommends
> BUILD [docs/business/roi-analysis.md]. LLM cost is tracked per-alert (temperature 0.1 for
> cheap, consistent output)."

**Q16. What scales and what doesn't in this architecture?**

> "Stateless ingestion service, Redis dedup, and n8n queue mode scale horizontally. The
> single-instance Postgres, Prometheus, Grafana, and n8n DB in docker-compose don't — production
> would move them to managed services (RDS, Prometheus Cloud). **[INFERENCE]** The repo targets
> laptop/demo scale (256mb Redis, single replicas); production intent is documented but K8s
> manifests aren't shipped [PROJECT_SPEC]."

**Q17. Latency targets?**

> "p95 processing latency <1s (odds <200ms, events <500ms, settlements <1s) [kpi-definitions.md:
> 1.2]. Time-to-settle p95 <30s [kpi-definitions.md:3.2]. Alertmanager evaluates rules every
> 15–60s [monitoring/prometheus/*.rules.yml]."

### Security

**Q18. What would a security reviewer flag?**

> "`allow_origins=['*']` CORS [main.py]; dev default passwords (`changeme`/`admin`) in
> docker-compose; `pip install -e '.[dev]'` puts test tools in the image [Dockerfile]; no
> secrets management beyond env vars; metrics.py has a syntax error that breaks the service
> [07_issues_found.md]. I'd fix these before production."

### "What would you change"

**Q19. What's the biggest gap you'd fix first?**

> "The metrics.py syntax error (`await` outside async function) that prevents the ingestion
> service from importing — observability is broken until it's fixed [metrics.py:171;
> 07_issues_found.md]. After that: add a test suite, a dead-letter queue for n8n forwards, and
> real LLM SDK calls instead of simulated responses."

**Q20. How would you extend this to a new provider?**

> "Add a ProviderConfig (endpoint, auth, rate limit) [types.ts:ProviderConfig], add field
> mappings to CanonicalTransformer PROVIDER_MAPPINGS [canonical_transformer.py], wire the
> endpoint in Settings.rest_endpoints [config.py], and add contract tests. **[GAP]** no provider
> registry/loader exists, so it's code changes not config [07_issues_found.md]."

**Q21. How would you handle a provider going dark (feed outage)?**

> "The LLMAlertGenerator has a `feed_outage` anomaly type [types.ts:AlertType] and a simulated
> 'Feed Outage Detected' alert [LLMAlertGenerator.getSimulatedResponse]. A production version
> would track last-message-per-provider and alert when silent. The REST poller backs off on 429
> [rest_poller.py:_fetch_and_process]. **[GAP]** no proactive outage detection is implemented."

**Q22. How do you reconcile data drift between systems?**

> "A daily reconciliation job compares checksums across systems and produces a
> ReconciliationReport (total/matched/discrepancies/auto-corrected/manual-review)
> [types.ts:ReconciliationReport; kpi-definitions.md:4.3]. **[GAP]** the reconciliation package
> (checksum.py, drift_detector.py, auto_corrector.py) is referenced in PROJECT_SPEC but not
> implemented in this repo [07_issues_found.md]."

**(More — pick any that fit time)**

**Q23. Idempotency vs exactly-once — what's the difference here?** "Idempotency = same input processed once (Redis SET NX EX). Exactly-once = n8n Queue Mode + Redis Streams consumer groups with dead-letter handling [README] — no duplicates, no skips."

**Q24. Why asyncio instead of threads?** "Thousands of concurrent feed connections on a few threads; async I/O for WebSocket, HTTP polling, and Redis [main.py; websocket_client.py; rest_poller.py]."

**Q25. What does the settlement confidence number mean?** "0.5 + 0.4×(matched priority / max priority), +0.1 for exact-score matches, capped at 1.0 [SettlementWorker.evaluateRules]. Threshold 0.95 auto-settles; below goes to review."

**Q26. How is this different from a CRUD web app?** "It's event-driven and streaming, not request/response. Odds flow continuously; settlement is stateful (match → outcome); correctness and audit matter more than UI polish."

**Q27. How would you demo this in 30 minutes?** "See QUICKSTART.md interview script: problem → architecture diagram → live demo (make demo-data → trace event in n8n UI → settlement → Grafana) → production ops (alert → runbook) → business value → Q&A."

**Q28. What's your testing philosophy given your QA background?** "Test the gates: schema validation, dedup, rule evaluation, and the TS↔Python contract. Contract tests + integration tests in CI [ci.yml lint-and-test] — and I'd ship the missing tests/ directory before an interview."

---

## Part B — Walkthroughs

### 2-minute spoken walkthrough

> "This is a sports-data automation platform I built for an LSports FDE interview. Live odds and
> match events come from mock providers (WebSocket + REST) into a Python/FastAPI ingestion
> service that validates, normalizes to a canonical schema shared with TypeScript, deduplicates
> via Redis, and forwards to n8n. Four custom n8n nodes route events by priority, normalize odds
> with arbitrage detection, auto-settle bets via a rule DSL with audit trail, and generate LLM
> alerts with confidence scoring and human review. Prometheus/Grafana/Alertmanager provide
> observability, and CI gates every change. It's production-grade: idempotent, observable, and
> auditable — and I can point to the exact file for every claim."

### 5-minute spoken walkthrough

> "The problem: sportsbooks get messy multi-provider feeds and settle bets manually — slow,
> error-prone, no audit trail. My solution has five layers. **(1) Providers:** mock WebSocket
> odds feed and REST event/settlement feed simulate LSports [packages/mock-providers]. **(2)
> Ingestion:** FastAPI service validates with JSON Schema, transforms provider fields to a
> canonical decimal format, deduplicates with Redis SET NX EX, and forwards to n8n webhooks
> [packages/ingestion-service]. **(3) Orchestration:** n8n in Queue Mode with four custom
> TypeScript nodes — Sports Event Router (priority queues), Odds Normalizer (3-format conversion
> + arbitrage), Settlement Worker (rule DSL + audit trail), LLM Alert Generator (structured
> alerts + confidence + human review) [packages/n8n-nodes]. **(4) Observability:** Prometheus
> metrics at /metrics, Grafana business + system dashboards, Alertmanager tiered routing with
> runbook links [monitoring/]. **(5) Business:** KPI definitions (automation rate >90%,
> time-to-settle <30s), process map, and ROI analysis showing build beats buy
> [docs/business/]. Every design decision maps to an interview talking point, and I've documented
> the honest gaps [docs/learn/07_issues_found.md]."

---

## Part C — 5 customer scenarios (discovery + proposal)

**S1. "Our settlement takes 30 minutes and we're missing payout windows."**
- Discovery: Which sports/markets? Current error rate? What's the cost of a missed window?
- Propose: rule-DSL settlement engine, void default, <30s target, human review for exceptions
  [SettlementWorker; kpi-definitions.md:113].

**S2. "We're losing money to arbitrage across our odds providers."**
- Discovery: How many providers? Which markets? Current detection is manual/ad-hoc.
- Propose: real-time cross-provider arbitrage detection in OddsNormalizer with margin threshold
  [OddsNormalizer arbitrage output; kpi-definitions.md].

**S3. "Our on-call is drowning in false-positive alerts."**
- Discovery: Alert volume, false-positive rate, current escalation path.
- Propose: LLM-structured alerts with confidence threshold, human-review queue, rule-based
  baseline agreement, runbooks [LLMAlertGenerator; alertmanager.yml].

**S4. "Regulators want an audit trail for every automated bet decision."**
- Discovery: What must be audited? Retention period? Who reviews?
- Propose: settlement audit trail (rule version, evaluated rules, confidence, timestamps),
> 100% audit-trail-coverage KPI [SettlementWorker._audit; kpi-definitions.md:258].

**S5. "The business team wants to see automation health without asking engineering."**
- Discovery: Which KPIs matter to them? How often do they need it?
- Propose: Grafana business dashboard (automation rate, time-to-settle, alert precision, cost per
> event) — self-service [monitoring/grafana/dashboards/business-kpis.json; kpi-definitions.md:282].

For each: run discovery (ask constraints, current metrics, decision-makers), propose scoped
phases, name tradeoffs, define success metric.

---

## Part D — 10 "break it" drills

**Instructions:** Each drill is a change request or bug. The learner must locate the code and
say what to change. Answer key is hidden at the bottom — don't look until you've tried.

1. **Drill:** A new odds provider sends odds as `bookmaker_odds` (not `odds`) and match id as
   `match_ref` (not `eventId`). Where do you add the mapping?
2. **Drill:** Settlement for a tennis match that retired at 2-1 sets is wrongly paid as "won."
   Where's the rule that decides outcome, and how do you make retirement void?
3. **Drill:** The same odds is being processed twice → double payout risk. Where's dedup, and
   what's the dedup key for odds?
4. **Drill:** The ingestion service won't start. There's a syntax error in a metrics file — find
   it and state the fix (without applying it).
5. **Drill:** n8n goes down and events are silently dropped. Where's the forward call, and what's
   missing?
6. **Drill:** A provider changes the odds format from decimal to American mid-stream. Where's the
   conversion, and what's the formula for negative American odds?
7. **Drill:** An LLM alert comes back with no `title` field. Where's the validation, and where
   does the item go?
8. **Drill:** You want p95 processing latency <1s alerted. Where are the latency histogram and
   the alert rule?
9. **Drill:** You want to add a new provider (endpoint, auth, rate limit) — name every file you'd
   touch.
10. **Drill:** The business wants automation rate >90% per type. Where's the KPI formula and the
    Prometheus metric it's computed from?

<details>
<summary>🔑 Answer key (hidden until you click)</summary>

1. `packages/canonical-types/src/types.ts` `PROVIDER_MAPPINGS` (add provider entry) AND
   `packages/ingestion-service/src/ingestion/normalization/canonical_transformer.py`
   `PROVIDER_MAPPINGS` — both TS and Python mirrors. Also `Settings.rest_endpoints` in config.py
   for the endpoint.
2. `packages/n8n-nodes/src/Nodes/SettlementWorker/SettlementWorker.node.ts` `evaluateRules` /
   `getDefaultRuleSet` embeddedRuleSet (rules `goal_home_win`/`goal_away_win`/`draw` and
   `match_abandoned`). Add a retirement condition (status ended + incomplete sets → void) with
   high priority; void is the safe default.
3. `packages/ingestion-service/src/ingestion/idempotency/deduplicator.py` `check_and_store`;
   odds key = `odds:{providerId}:{eventId}:{sequence}` (main.py:process_odds).
4. `packages/ingestion-service/src/ingestion/metrics.py` — `metrics_middleware` is `def` not
   `async def` but uses `await call_next(request)` → SyntaxError. Fix: `async def
   metrics_middleware`. [Do NOT apply — record in 07_issues_found.md.]
5. `packages/ingestion-service/src/ingestion/main.py` `forward_to_n8n` — catches and swallows
   exceptions, no dead-letter queue/retry. Add DLQ + retry.
6. `packages/ingestion-service/src/ingestion/normalization/canonical_transformer.py`
   `_normalize_odds` — American: if odds>0 → (odds/100)+1 else → (100/abs(odds))+1.
7. `packages/n8n-nodes/src/Nodes/LLMAlertGenerator/LLMAlertGenerator.node.ts` `execute` —
   validates `title/description/severity/confidence`; missing → exception → error output for that
   item only.
8. `metrics.py` `processing_latency_seconds` histogram; `monitoring/prometheus/rules/latency.rules.yml`
   `IngestionHighLatency` / `IngestionCriticalLatency`.
9. `types.ts`/`types.py` (ProviderConfig), `canonical_transformer.py` (PROVIDER_MAPPINGS),
   `config.py` (Settings.rest_endpoints), plus contract tests [GAP].
10. `docs/business/kpi-definitions.md` (3.1 Automation Rate formula) computed from
    `events_received_total` / `events_forwarded_total` Prometheus metrics [metrics.py].

</details>

---

## Part E — Honest weaknesses & how to talk about them

| Weakness | Evidence | How to frame it |
|----------|----------|-----------------|
| No automated test suite | Makefile/CI reference `tests/`; directory missing | "I know the CI gate expects tests; I'd ship them before production — here's exactly what I'd test first..." |
| metrics.py syntax error | breaks ingestion import [metrics.py:171] | "Found it during review; it's logged as a known issue [07_issues_found.md] — observability is broken until fixed." |
| LLM not real (simulated) | SDK calls commented out [LLMAlertGenerator] | "The pattern (structured output + confidence + human review) is real; I'd wire the SDK for the actual demo." |
| processing-engine / tests / n8n-workflows missing | referenced in PROJECT_SPEC/QUICKSTART, not on disk | "The spec describes the full vision; this repo ships the ingestion + n8n-node core. Here's what's planned vs built." |
| No multi-tenancy / RBAC | providerId exists but no tenant isolation | "Data model is provider-aware; tenant isolation is a deliberate phase-2 addition." |
| No provider registry / hot-reload | PROVIDER_MAPPINGS hard-coded [canonical_transformer.py] | "Adding a provider is a code change today; a registry would make it config — a tradeoff I'd revisit at scale." |

**Closing line:** "I built this to show I can design, not just demo. Every decision has a
rationale, every layer has an observability hook, and I know exactly where it's still rough —
that's what production ownership looks like."
