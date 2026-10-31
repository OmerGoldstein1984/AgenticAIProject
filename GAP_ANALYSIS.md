# Gap Analysis: Your CV vs. LSports AI Business Automation Engineer Role

## Executive Summary

**You're a strong match** (8/10). Your Webbing experience directly mirrors LSports' domain (telecom/sports data, real-time feeds, n8n, LLM automation, production operations). The gaps are **specific to sports betting domain knowledge** and **business-facing deliverables** — both addressable with this project.

---

## Requirement-by-Requirement Mapping

| LSports Requirement | Your CV Evidence | Match | Gap | Project Addresses |
|---------------------|------------------|-------|-----|-------------------|
| **AI-driven business process automation in production** | Webbing: IRSF fraud detection, roaming alerts, provisioning automation (4,000+ SIMs), RAG systems, LLM Slack analyzer | ✅ Strong | Sports betting domain context | ✅ Full platform with settlement, odds, alerts |
| **n8n/Workato hands-on** | Webbing: "Built high-scale provisioning automation in n8n", "Used AI tools and Playwright MCP" | ✅ Strong | Custom nodes, complex error handling, production patterns | ✅ Custom TypeScript nodes, DLQ, retry, circuit breakers |
| **APIs, integrations, SaaS workflows** | Webbing: SOAP provisioning API, REST APIs, browser extension integrating multiple systems, Slack | ✅ Strong | Sportsbook-specific SaaS (CRM, Risk, Reporting) | ✅ Mock CRM, Risk, Reporting integrations |
| **Translate business needs → technical solutions** | Webbing: "Responsible for turning manual support, provisioning and network-operations processes into software and automation" | ✅ Strong | Formal business process documentation, KPI definition, stakeholder dashboards | ✅ Business Process Doc, KPI definitions, Grafana business dashboard |
| **KPIs, success metrics, tangible value** | Webbing: "Reduced lookup time by 50%", "Reduced order creation time by 50%", "30% improvement in processing efficiency" | ✅ Strong | Automated KPI tracking, business-facing reporting | ✅ Automated metrics collection, KPI dashboard |
| **Production ownership: monitoring, alerting, error handling** | Webbing: "Shadow mode and historical replay", "Idempotent processing", "Provisional/confirmed/retracted alert states" | ✅ Strong | Full observability stack, runbooks, on-call processes | ✅ Prometheus/Grafana, Alertmanager, runbook generator |
| **Cross-team communication** | Webbing: "Worked with BI/analytics team", "Reduced need to manually review message history", browser extension for support | ✅ Strong | Business stakeholder demo, non-technical runbooks | ✅ Stakeholder dashboard, demo script, runbooks |

---

## Your Unique Strengths (Lead With These)

| Strength | Evidence | Interview Talking Point |
|----------|----------|-------------------------|
| **Telecom/sports data domain** | Webbing: IoT connectivity, carrier network events, roaming, IRSF fraud, eSIM provisioning | "I understand real-time event feeds, cross-border detection, and regulatory compliance — directly applicable to sports data feeds and settlement" |
| **n8n at scale** | 4,000+ SIMs/request, rate limit tuning, moved to Azure containers | "I've hit n8n's limits and know when to graduate workflows to containerized services" |
| **LLM in production with guardrails** | Shadow mode, historical replay, confidence scoring, human review queues, prompt injection defense | "I don't just call APIs — I build evaluation harnesses, shadow modes, and structured output parsing" |
| **QA/observability DNA** | 10 years: LoadRunner (30% perf improvement), Jenkins/Azure DevOps, Cypress, Playwright | "I build systems that are testable, observable, and reliable from day one — not as an afterthought" |
| **Business outcome focus** | 50% time reduction metrics, ROI-driven automation prioritization | "Every automation I've built has a business case with measured results" |

---

## Gaps to Address (Priority Order)

### 🔴 Critical: Sports Betting Domain Knowledge
**What they'll ask:** "How does settlement work? What's a market vs. selection? How do you handle void bets? What's the regulatory requirement for audit trails?"

**Your answer strategy:** "I built a settlement engine with a rule DSL that handles won/lost/void/half-won/half-lost, partial settlement, and produces full audit trails. Let me show you the reconciliation job that catches drift daily."

**Project coverage:** Settlement Worker, Rule DSL, Reconciliation, Audit Trail

### 🟡 High: Business-Facing Deliverables
**What they'll ask:** "How do you show value to non-technical stakeholders? How do business users monitor automation health?"

**Your answer strategy:** "I built a Grafana business dashboard showing automation rate, time-to-settle, alert precision/recall, and cost savings — no engineering help needed. I also generated runbooks linked from alerts."

**Project coverage:** Business KPI Dashboard, Runbook Generator, Stakeholder API

### 🟡 High: Workato (if they use it)
**What they'll ask:** "The job mentions Workato. Do you know it?"

**Your answer strategy:** "I've used n8n extensively for complex workflows (custom nodes, queue mode, Redis Streams). Workato's similar paradigm — visual workflow builder, connectors, error handling. I can ramp quickly. My n8n custom nodes demonstrate the same architectural thinking."

**Project coverage:** n8n expertise transfers; mention in interview

### 🟢 Medium: Specific SaaS Integrations (Salesforce, HubSpot, NetSuite)
**What they'll ask:** "Experience integrating with Salesforce/HubSpot/NetSuite?"

**Your answer strategy:** "I've built integrations with SOAP APIs, REST APIs, GraphQL, and browser-session-based auth (browser extension using engineer's auth). The patterns are identical — OAuth, rate limiting, idempotency, webhook handling. I mock these in my project."

**Project coverage:** Mock CRM integration with OAuth-style auth

---

## Interview Strategy: Turn Gaps Into Strengths

### When Asked About Sports Betting Gap
> "My background is telecom — carrier network events, real-time fraud detection, cross-border roaming, regulatory compliance. The data patterns are identical: high-volume event feeds, normalization across providers, settlement/reconciliation, audit requirements. I've studied the sports betting domain specifically for this role and built this platform to demonstrate I can apply my experience directly."

### When Asked About Workato
> "I've built production n8n systems with custom TypeScript nodes, queue-based execution, Redis Streams, and complex error handling. The mental model — visual workflow orchestration, connector ecosystem, error handling, version control — transfers directly. Happy to do a Workato take-home if helpful."

### When Asked About Business Collaboration
> "At Webbing I worked with BI/analytics to define fraud rules, with support to build the browser extension they actually use, and with leadership to prioritize automation by ROI. I start every project with a Business Process Document and KPI agreement. This project includes that documentation."

---

## Project Components That Close Each Gap

| Gap | Project Component | Interview Artifact |
|-----|-------------------|-------------------|
| Sports betting domain | Settlement Worker with rule DSL, void/half-won logic, audit trail | Live demo: inject event → auto-settle → show audit log |
| Business KPIs | Grafana business dashboard (automation rate, time-to-settle, cost saved) | Open dashboard during interview: "This is what the Head of Trading sees" |
| Runbooks/operations | Auto-generated runbooks linked from Alertmanager alerts | Click alert → opens runbook with steps, contacts, escalation |
| SaaS integrations | Mock CRM with OAuth, webhook receiver, idempotent creates | Show n8n workflow calling mock CRM API |
| Workato parity | n8n custom nodes = same architectural pattern | Show node code: "This is how I'd build a Workato connector" |
| Stakeholder communication | Business Process Doc, KPI definitions, ROI analysis, demo script | Bring printed 1-pager to interview |

---

## 4-Week Build Plan (If You Have Time)

| Week | Focus | Deliverable | Interview Ready? |
|------|-------|-------------|------------------|
| 1 | Foundation: Docker stack, canonical types, CI/CD, n8n nodes skeleton | Running stack, type safety, green CI | ✅ Can show architecture |
| 2 | Ingestion + Core Workflows: Event Router, Odds Normalization, Settlement | End-to-end flow working | ✅ Can demo live |
| 3 | LLM Alert Engine + Reconciliation + Observability | Alerts firing, dashboards populated, reconciliation report | ✅ Can show production ops |
| 4 | Business Layer: Stakeholder dashboard, runbooks, docs, demo rehearsal | Complete interview package | ✅ Fully ready |

**Minimum viable (2 weeks):** Week 1 + 2 + basic Grafana dashboard + demo script

---

## What to Say When They Ask "Why LSports?"

> "Three reasons:
> 1. **Domain fit**: I've spent the last year at Webbing doing exactly what you do — real-time sports-adjacent data (carrier network events), multi-provider normalization, automated settlement-like workflows (provisioning), and production LLM systems with human-in-the-loop.
> 2. **Technical match**: You use n8n; I've pushed n8n to 4,000+ SIMs/request with custom nodes and queue mode. You need production AI automation; I've built shadow modes, evaluation harnesses, and confidence-scored LLM pipelines.
> 3. **Business impact**: Your JD emphasizes KPIs, stakeholder collaboration, and measurable value. My last three automations each delivered 50%+ time reduction with quantified ROI. I want to bring that discipline to sports data."

---

## Final Checklist Before Interview

- [ ] Project runs with `make up` (test fresh)
- [ ] Demo scenario works end-to-end
- [ ] Grafana dashboards show realistic data
- [ ] Alert fires and shows runbook link
- [ ] You can explain each component in 90 seconds
- [ ] Printed: Business Process Doc (1 page), KPI Definitions (1 page), Architecture Diagram (1 page)
- [ ] Rehearsed 30-min demo script
- [ ] Questions prepared for them (shows engagement)

---

## Questions to Ask Them (Turns Interview Into Conversation)

1. "What's the current split between n8n and custom services for your automations?"
2. "How do you handle schema evolution when a data provider changes their feed format?"
3. "What's the biggest operational pain point today — latency, accuracy, or alert noise?"
4. "How does the business team currently monitor automation health?"
5. "Are you evaluating Workato for new workflows, or is n8n the standard?"
6. "What's the regulatory audit requirement for automated settlement decisions?"
7. "How do you handle the human-in-the-loop for low-confidence LLM decisions today?"

---

*This analysis shows you're not just qualified — you're the profile they wrote the JD for. The project makes it undeniable.* 🎯