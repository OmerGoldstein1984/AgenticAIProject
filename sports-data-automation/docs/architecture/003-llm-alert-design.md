# LLM Alert Design

## FILE HEADER
-----------
Business problem this file solves:
    Ops teams cannot watch every feed, and manual alerting suffers from alert fatigue, no
    standardized format, slow escalation (~20 min to notify), no confidence scoring, and knowledge
    silos. The platform needs anomaly detection that produces human-readable, structured alerts
    with confidence scoring, routed to auto-escalation or a human-review queue — using the LLM
    only where it adds value (high-variance classification that needs human review), never as a
    buzzword.

Where it sits in the flow:
    Stage 4 of the n8n orchestration layer (Alert Engine). The LLM Alert Generator custom node
    receives anomaly context from ingestion, builds an LLMAlertRequest with few-shot examples,
    calls the LLM (Anthropic Claude), parses the structured LLMAlertResponse, then routes the
    alert by confidence: high confidence → auto-escalate (page/Alertmanager + runbook), low
    confidence → human-review queue in n8n.

What calls it / what it calls:
    Called by: n8n Alert Engine workflow (n8n-workflows/alert-engine.json). Calls:
    packages/processing-engine/src/processing_engine/alerts/llm_client.py (Anthropic SDK),
    prompt_templates.py (few-shot prompt assembly), confidence_scorer.py (confidence gating),
    human_review_queue.py (low-confidence routing). Consumes CanonicalEvent / CanonicalOdds from
    canonical types; emits Alert records.

What breaks if removed:
    No structured anomaly alerting; ops revert to manual dashboard-watching with no confidence
    scoring, no human-review queue, and no audit trail for LLM-driven alert decisions.

Language conventions:
    TypeScript n8n node (packages/n8n-nodes/src/nodes/LLMAlertGenerator/), Python processing
    engine (packages/processing-engine/src/processing_engine/alerts/*), exported workflow JSON
    (n8n-workflows/alert-engine.json), canonical types (Alert, AlertType, AlertSeverity,
    LLMAlertRequest, LLMAlertResponse, AlertEvaluationResult).

GAP:
    LLM response missing required fields → routed to error output in the node; shadow mode and
    prompt evaluation harness are declared but not fully implemented. See 07_issues_found.md.

---

## Status

Accepted

## 1. Context

### Problem being solved

The platform generates anomaly signals (odds spikes, feed outages, settlement mismatches,
arbitrage, suspicious patterns, reconciliation drift). Manual alerting today has these pain
points:

- Alert fatigue from high false-positive rates
- No standardized alert format (free-text Slack/email messages)
- Slow escalation (~20 minutes average to notify)
- No confidence scoring — every alert treated equally
- Knowledge silos: only senior staff know resolution steps

Ops teams cannot watch every feed, so the platform must generate structured, actionable alerts
automatically — but the LLM must be used responsibly: structured output + confidence scoring +
human-in-the-loop, with shadow mode and eval harness before each deploy.

### Why it matters

Alert precision (>85% target) and recall (>80%) are business KPIs. Settlement discrepancies and
feed outages are regulatory/reputational risks. A confidence threshold plus human-review queue
keeps the automation rate under control (<20% human review target) while catching genuine
anomalies.

## 2. Decision

### What was chosen

An **LLM Alert Engine** built around few-shot prompting, structured JSON output, and confidence
scoring:

| Element | Choice | Rationale |
|---------|--------|-----------|
| LLM provider | Anthropic Claude (Anthropic SDK) | Stated expertise; strong structured-output instruction following |
| Prompting | Few-shot examples + system prompt | Steers the LLM toward the required schema and tone without fine-tuning |
| Output format | Structured JSON (`LLMAlertResponse`) | Downstream systems can page/ticket/dashboard on it; not free-text |
| Confidence scoring | `confidence` field (0–1) on every response | Drives routing: auto-escalate vs human-review queue |
| Alert taxonomy | `AlertType` (6 families) + `AlertSeverity` (info→page) | Standardized routing in Alertmanager; runbooks per family |
| Routing rule | Confidence ≥ threshold → auto-escalate; below → human-review queue | Human-in-the-loop for low-confidence alerts |
| Safety net | Shadow mode + eval harness vs rule-based baseline | Measure LLM precision/recall before each deploy |
| Prompt management | Versioned prompt templates | Audit trail and rollback for prompt changes |

### Data flow

1. Ingestion emits a canonical `CanonicalEvent` / `CanonicalOdds` plus anomaly context.
2. n8n Alert Engine builds an `LLMAlertRequest` (event_data, anomaly_type, context,
   few_shot_examples).
3. `llm_client.py` calls Claude; response parsed into `LLMAlertResponse`
   (title, description, severity, confidence, suggested_action, metadata).
4. `confidence_scorer.py` gates: high confidence → auto-escalate (Alertmanager + runbook link);
   low confidence → `human_review_queue.py` for ops review.
5. Every decision is recorded as an `Alert` with full audit trail; `AlertEvaluationResult`
   compares LLM vs rule-based baseline in shadow mode.

### Alert taxonomy and severity

| AlertType | Example trigger | Typical severity |
|-----------|----------------|------------------|
| odds_anomaly | Odds spike vs other providers | warning |
| settlement_discrepancy | Internal vs official result mismatch | critical |
| feed_outage | Provider WebSocket/REST silent | critical / page |
| arbitrage_detected | Cross-provider arbitrage opportunity | info |
| suspicious_pattern | Syndicate/betting-pattern signal | warning |
| reconciliation_drift | Daily checksum drift found | warning |

`AlertSeverity` (info → warning → critical → page) drives Alertmanager routing: `page` alerts
trigger on-call paging, `warning` routes to tickets, `info` to dashboards.

## 3. Consequences

### Positive

- Structured JSON alerts can be paged, ticketed, and dashboarded — replacing free-text Slack
  messages that can't be automated.
- Confidence scoring + human-in-the-loop keeps ops focused on genuine exceptions (<20% human
  review target).
- Few-shot prompting steers the LLM without fine-tuning; prompt versioning gives an audit trail
  and rollback path.
- Shadow mode + eval harness (`AlertEvaluationResult`) measures LLM precision/recall against a
  deterministic rule-based baseline before each deploy — safe rollout.
- Matches the interview differentiator: "I used AI where it adds value, not as a buzzword"
  (LLM for alert summarization, structured output, confidence scoring, human-in-the-loop).

### Negative / tradeoffs

- LLM hallucinations are mitigated but not eliminated: confidence threshold, human-review
  queue, and rule-based baseline are required safety nets.
- LLM response missing required fields → routed to error output in the node (a malformed
  response never auto-escalates silently).
- Alert generation is >80% automated by design — some human review is always needed, so the
  system never reaches 100% hands-off alerting.
- Shadow mode and the prompt evaluation harness are declared in design but not fully
  implemented (recorded as a GAP).

## 4. References

- `sports-data-automation/packages/processing-engine/src/processing_engine/alerts/llm_client.py`
- `sports-data-automation/packages/processing-engine/src/processing_engine/alerts/prompt_templates.py`
- `sports-data-automation/packages/processing-engine/src/processing_engine/alerts/confidence_scorer.py`
- `sports-data-automation/packages/processing-engine/src/processing_engine/alerts/human_review_queue.py`
- `sports-data-automation/n8n-workflows/alert-engine.json`
- `sports-data-automation/packages/canonical-types/src/types.ts` — `Alert`, `AlertType`,
  `AlertSeverity`, `LLMAlertRequest`, `LLMAlertResponse`, `AlertEvaluationResult`
- `sports-data-automation/packages/canonical-types/python/sports_automation/types.py` — Python mirror
- `kpi-definitions.md` — Alert precision/recall/human-review-rate KPIs and alerting thresholds
- `PROJECT_SPEC.md` — Core Components (Alert Engine LLM), Key Differentiators (AI where it adds value)
- `07_issues_found.md` — Recorded GAPs (LLM error output, shadow mode, eval harness)

---

*Document Version: 1.0*  
*Date: 2026-11-09*  
*Owner: Architecture*
