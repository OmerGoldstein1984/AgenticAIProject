# 01_business_context.md

# Business Context — Sports Data Automation Platform

**Audience:** the learner (senior QA/automation engineer → AI Solutions Engineer) preparing for an
FDE interview. **How to use:** read this first to understand *why* the system exists, then read
02_architecture.md for *how* it's built.

> 📌 How to read this doc: sections marked **[INFERENCE]** are not stated in the repo; they are
> reasonable deductions from the README, PROJECT_SPEC, GAP_ANALYSIS, and QUICKSTART. Everything
> else is grounded in the repo (quoted file:line where possible).

---

## 1. The one-paragraph summary

This project is a demonstration platform for an LSports "AI Business Automation Engineer"
interview. It shows an end-to-end sports-data automation pipeline: live odds and match events
flow from mock providers (WebSocket + REST) into a Python/FastAPI ingestion service, which
validates, normalizes, deduplicates, and forwards them to n8n. Four custom n8n nodes then route
events by priority, normalize odds across providers (with arbitrage detection), auto-settle bets
via a rule DSL (with audit trail), and generate LLM-powered alerts (with confidence scoring and
human review). Prometheus/Grafana/Alertmanager provide observability, and a daily reconciliation
job catches drift. The whole thing is wrapped in Docker Compose + GitHub Actions CI.

**Business problem it solves:** sportsbooks receive messy, high-frequency, multi-provider data
feeds and today settle bets manually — slow (10–45 min), error-prone (~2% error rate), no audit
trail, and 24/7 ops coverage. This platform automates ingestion → normalization → settlement →
alerting with human-in-the-loop for exceptions, targeting >90% automation, <30s settlement, and
full audit coverage.

---

## 2. Who the customer / user is

| Stakeholder | Role | What they care about | How the platform serves them |
|-------------|------|---------------------|------------------------------|
| **Head of Trading** | Sportsbook trading lead | Settlement accuracy, time-to-settle, avoiding wrong payouts | Settlement Worker rule DSL + void default + audit trail; Time-to-Settle KPI (docs/business/kpi-definitions.md:113) |
| **Risk Manager** | Exposure & fraud | Arbitrage, suspicious patterns, limit breaches | OddsNormalizer arbitrage output; LLMAlertGenerator suspicious_pattern / arbitrage_detected alerts |
| **Operations Team** | 24/7 feed monitoring | Not waking up for false positives; clear runbooks | Alertmanager tiered routing + runbook links (monitoring/prometheus/alerts/alertmanager.yml); human-review queue |
| **Compliance** | Audit & regulation | Audit trail for every automated decision; regulatory reports | Settlement audit trail (100% target, kpi-definitions.md:258); ReconciliationReport with checksums |
| **Engineering** | Reliability, deploys | Uptime, latency, on-call load | Prometheus metrics, Grafana dashboards, CI pipeline (ci.yml), structured logging |

**[INFERENCE]** The repo doesn't name a real paying customer; the "customer" is the interviewer
(LSports) and the persona is a sportsbook operator. Stakeholder interests are inferred from
docs/business/process-map.md:178 (Stakeholder Mapping).

---

## 3. The pain (current manual process) — from docs/business/process-map.md

| Process | Manual pain | Automation opportunity |
|---------|------------|------------------------|
| Odds ingestion & normalization | 15–30 min per match; ~2% conversion error; no systematic arbitrage detection | Real-time WebSocket ingestion, auto format conversion, built-in arbitrage (process-map.md:13-23) |
| Event monitoring & settlement | 24/7 coverage; settlement 10–45 min post-match; inconsistent rules (tennis retirement); no audit trail | Rule-based settlement DSL; full audit trail; human-in-the-loop only for exceptions (process-map.md:28-49) |
| Alert management | Alert fatigue (~60% false positive); no standard format; slow escalation (~20 min) | LLM-structured alerts + confidence + human-review queue + auto-escalation (process-map.md:53-73) |
| Reconciliation & QA | 2–3 hours daily; drift found days later; no auto-correction | Automated daily reconciliation with checksums + auto-correction (process-map.md:77-94) |

**Cost of doing nothing (per ROI analysis, docs/business/roi-analysis.md):**
- 4 FTE operations team (~$480K/year) for 24/7 manual monitoring
- ~50 disputed settlements/month × $500 = $24K/month ($288K/year)
- ~$15K/month arbitrage losses ($156K/year)
- Incident response ~$384K/year (50% counted = $192K/year)

**[INFERENCE]** These dollar figures are interview-demo estimates, not audited financials. Mark them
as illustrative.

---

## 4. What happens without this system

- **Slow settlement:** 10–45 min post-match vs target <30s (kpi-definitions.md:113) → delayed payouts, angry customers.
- **Wrong payouts:** ~2% manual error rate (process-map.md:15) → disputes ($500 each), regulatory fines.
- **Arbitrage leakage:** no systematic detection → sure-loss markets ($15K/month per ROI).
- **No audit trail:** regulators can't verify how a bet was settled → compliance risk.
- **Alert fatigue:** ~60% false positives → on-call burnout, real alerts missed.
- **24/7 ops cost:** 4 FTEs just to watch feeds.

---

## 5. How success is measured (KPIs — docs/business/kpi-definitions.md)

| KPI | Target | Where measured |
|-----|--------|----------------|
| Automation rate | >90% overall | events_forwarded_success / events_received (kpi-definitions.md:96) |
| Time to settle (p95) | <30s | settlement_latency_seconds (kpi-definitions.md:113) |
| Alert precision | >85% | alert_evaluation agreed/generated (kpi-definitions.md:127) |
| Human review rate | <20% | alert_human_review / alert_generated (kpi-definitions.md:158) |
| Validation success rate | >99.5% | events_validated valid/total (kpi-definitions.md:60) |
| System availability | 99.9% | Prometheus up metric (kpi-definitions.md:176) |
| Cost per event | <$0.01 | infrastructure_cost / events_received (kpi-definitions.md:226) |
| Reconciliation discrepancies | <10/day, 0 critical | daily reconciliation job (kpi-definitions.md:197) |

Alerting thresholds (warning/critical/page) are summarized at kpi-definitions.md:303.

---

## 6. What a client (interviewer) would ask an FDE about this

- "How does settlement work for a tennis retirement? What's void vs won?" → Settlement Worker rule DSL (SettlementWorker.node.ts), default "void" outcome.
- "How do you handle a provider changing their feed format?" → SchemaValidator (schema_validator.py) + adapter mappings (CanonicalTransformer PROVIDER_MAPPINGS); contract testing gap noted in 07_issues_found.md.
- "What if n8n goes down?" → forward_to_n8n swallows errors today (bug, 07_issues_found.md); production would need a dead-letter queue.
- "How do you know the LLM isn't hallucinating alerts?" → confidence threshold + human-review queue + rule-based baseline agreement (LLMAlertGenerator.node.ts).
- "How do business users see value without engineering?" → Grafana business dashboard (business-kpis.json), KPI definitions.
- "What's your rollback / incident process?" → Alertmanager runbook links (alertmanager.yml), runbooks (docs/runbooks — referenced but not present, gap).

---

## 7. Domain analogies (learner's telecom/QA world)

| Platform concept | Telecom/QA analogy |
|------------------|-------------------|
| Provider feed (WebSocket odds) | Carrier network event feed / roaming push |
| Normalization (decimal) | Protocol translation across vendors (e.g. SOAP↔REST provisioning) |
| Deduplication (Redis SET NX) | Idempotent SIM provisioning — process an activation once even if retried |
| Settlement rule DSL | Fraud/roaming rule engine — business rules change without redeploy |
| LLM + human review | IRSF fraud alert with confidence → analyst queue before action |
| Reconciliation (checksums) | Daily CDR reconciliation between switch and billing |
| Dead-letter output | Failed-message queue for manual reprocessing |
| Runbook | Standard operating procedure (SOP) for NOC on-call |

---

## 8. Bottom line for the interview

> "I built a production-grade sports-data automation platform that ingests multi-provider feeds,
> normalizes and deduplicates them, auto-settles bets with a full audit trail, and generates
> LLM-powered alerts with human-in-the-loop — with observability, CI, and business KPIs. It
> mirrors the real-time feed normalization, automated settlement, and production-LLM guardrails
> I did in telecom, translated to the sports-betting domain."

**[INFERENCE]** This talking point is the learner's to adapt; the repo supports every claim above
with file:line references.
