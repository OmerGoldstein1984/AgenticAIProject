# KPI Definitions: Sports Data Automation Platform

## Overview

This document defines all Key Performance Indicators (KPIs) for the sports data automation platform. Each KPI includes:
- **Formula**: Exact calculation method
- **Target**: Success threshold
- **Data Source**: Where the metric originates
- **Frequency**: How often it's measured
- **Owner**: Responsible team/role

---

## 1. Throughput & Latency KPIs

### 1.1 Events Ingested Per Second
| Attribute | Value |
|-----------|-------|
| **Formula** | `sum(rate(events_received_total[5m]))` |
| **Unit** | events/second |
| **Target** | > 1,000 eps (peak), > 100 eps (average) |
| **Data Source** | Ingestion service Prometheus metrics |
| **Frequency** | Real-time (5m window) |
| **Owner** | Platform Engineering |

**Breakdown by source/type:**
- `events_received_total{source="websocket", type="odds"}`
- `events_received_total{source="rest", type="event"}`
- `events_received_total{source="rest", type="settlement"}`

### 1.2 End-to-End Processing Latency
| Attribute | Value |
|-----------|-------|
| **Formula** | `histogram_quantile(0.95, sum(rate(processing_latency_seconds_bucket[5m])) by (le, type))` |
| **Unit** | seconds |
| **Target** | p50 < 100ms, p95 < 500ms, p99 < 1s |
| **Data Source** | Ingestion service `processing_latency_seconds` histogram |
| **Frequency** | Real-time (5m window) |
| **Owner** | Platform Engineering |

**Per type:**
- Odds: p95 < 200ms
- Events: p95 < 500ms
- Settlements: p95 < 1s

### 1.3 Provider Latency
| Attribute | Value |
|-----------|-------|
| **Formula** | `histogram_quantile(0.95, sum(rate(provider_latency_seconds_bucket[5m])) by (le, provider, type))` |
| **Unit** | seconds |
| **Target** | p95 < 5s per provider |
| **Data Source** | Ingestion service `provider_latency_seconds` histogram |
| **Frequency** | Real-time (5m window) |
| **Owner** | Platform Engineering |

---

## 2. Quality & Accuracy KPIs

### 2.1 Validation Success Rate
| Attribute | Value |
|-----------|-------|
| **Formula** | `sum(rate(events_validated_total{result="valid"}[5m])) / sum(rate(events_validated_total[5m])) * 100` |
| **Unit** | percentage |
| **Target** | > 99.5% |
| **Data Source** | Ingestion service `events_validated_total` counter |
| **Frequency** | Real-time (5m window) |
| **Owner** | Data Engineering |

### 2.2 Deduplication Efficiency
| Attribute | Value |
|-----------|-------|
| **Formula** | `sum(rate(events_deduplicated_total{result="new"}[5m])) / sum(rate(events_deduplicated_total[5m])) * 100` |
| **Unit** | percentage |
| **Target** | > 95% new (low duplicate rate expected in production) |
| **Data Source** | Ingestion service `events_deduplicated_total` counter |
| **Frequency** | Real-time (5m window) |
| **Owner** | Data Engineering |

**Note:** High duplicate rate (>50%) triggers alert - indicates replay or provider issue.

### 2.3 n8n Forwarding Success Rate
| Attribute | Value |
|-----------|-------|
| **Formula** | `sum(rate(events_forwarded_total{result="success"}[5m])) / sum(rate(events_forwarded_total[5m])) * 100` |
| **Unit** | percentage |
| **Target** | > 99.9% |
| **Data Source** | Ingestion service `events_forwarded_total` counter |
| **Frequency** | Real-time (5m window) |
| **Owner** | Platform Engineering |

---

## 3. Business Outcome KPIs

### 3.1 Automation Rate
| Attribute | Value |
|-----------|-------|
| **Definition** | Percentage of events processed end-to-end without human intervention |
| **Formula** | `sum(rate(events_forwarded_total{result="success"}[1h])) by (type) / sum(rate(events_received_total[1h])) by (type) * 100` |
| **Unit** | percentage |
| **Target** | > 90% overall, > 95% for odds, > 85% for settlements |
| **Data Source** | Combined ingestion + n8n metrics |
| **Frequency** | Hourly |
| **Owner** | AI Solutions Engineering |

**Per type targets:**
- Odds normalization: > 98%
- Event routing: > 95%
- Settlement: > 85% (lower due to rule complexity)
- Alert generation: > 80% (human review by design)

### 3.2 Time to Settle
| Attribute | Value |
|-----------|-------|
| **Definition** | Time from official result availability to settlement completion |
| **Formula** | `histogram_quantile(0.95, sum(rate(settlement_latency_seconds_bucket[1h])) by (le))` |
| **Unit** | seconds |
| **Target** | p50 < 10s, p95 < 30s, p99 < 60s |
| **Data Source** | Processing engine `settlement_latency_seconds` histogram |
| **Frequency** | Hourly |
| **Owner** | AI Solutions Engineering |

**Includes:** Rule evaluation, audit logging, CRM notification, risk update

### 3.3 Alert Precision
| Attribute | Value |
|-----------|-------|
| **Definition** | Percentage of generated alerts that are confirmed as valid (agree with rule-based baseline or human review) |
| **Formula** | `sum(rate(alert_evaluation_total{agreed="true"}[1h])) by (type) / sum(rate(alert_evaluation_total[1h])) by (type) * 100` |
| **Unit** | percentage |
| **Target** | > 85% overall, > 90% for critical alerts |
| **Data Source** | LLM Alert Generator evaluation metrics |
| **Frequency** | Hourly |
| **Owner** | AI Solutions Engineering |

**Per type targets:**
- Odds anomaly: > 85%
- Settlement discrepancy: > 95%
- Feed outage: > 98%
- Arbitrage: > 80% (informational)
- Suspicious pattern: > 75% (investigative)
- Reconciliation drift: > 90%

### 3.4 Alert Recall
| Attribute | Value |
|-----------|-------|
| **Definition** | Percentage of actual anomalies that were detected and alerted |
| **Formula** | `sum(rate(alert_evaluation_total{recalled="true"}[1h])) by (type) / sum(rate(alert_generated_total[1h])) by (type) * 100` |
| **Unit** | percentage |
| **Target** | > 80% |
| **Data Source** | Reconciliation + manual review feedback |
| **Frequency** | Daily |
| **Owner** | AI Solutions Engineering |

**Measured via:** Reconciliation drift detection + periodic manual audits

### 3.5 Human Review Rate
| Attribute | Value |
|-----------|-------|
| **Definition** | Percentage of alerts requiring human review (confidence below threshold) |
| **Formula** | `sum(rate(alert_human_review_total[1h])) / sum(rate(alert_generated_total[1h])) * 100` |
| **Unit** | percentage |
| **Target** | < 20% overall, < 10% for critical/page severity |
| **Data Source** | LLM Alert Generator routing metrics |
| **Frequency** | Hourly |
| **Owner** | AI Solutions Engineering |

**Trend:** Should decrease over time as LLM improves and rules are refined

---

## 4. Operational KPIs

### 4.1 System Availability
| Attribute | Value |
|-----------|-------|
| **Formula** | `sum(up{job=~"ingestion-service|n8n|processing-engine"}) / count(up{job=~"ingestion-service|n8n|processing-engine"}) * 100` |
| **Unit** | percentage |
| **Target** | 99.9% (monthly) |
| **Data Source** | Prometheus `up` metric |
| **Frequency** | Continuous |
| **Owner** | Platform Engineering |

### 4.2 Mean Time to Recovery (MTTR)
| Attribute | Value |
|-----------|-------|
| **Definition** | Average time from alert firing to resolution |
| **Formula** | `avg(alert_resolved_timestamp - alert_fired_timestamp)` per incident |
| **Unit** | minutes |
| **Target** | < 15 min (critical), < 60 min (warning) |
| **Data Source** | Alertmanager + incident tracking |
| **Frequency** | Per incident, reported monthly |
| **Owner** | Platform Engineering |

### 4.3 Reconciliation Discrepancies
| Attribute | Value |
|-----------|-------|
| **Formula** | `reconciliation_discrepancies_total` (daily job output) |
| **Unit** | count |
| **Target** | < 10 per day (auto-correctable), 0 critical |
| **Data Source** | Daily reconciliation job |
| **Frequency** | Daily |
| **Owner** | Data Engineering |

**Severity breakdown:**
- Low: < 50/day (auto-correct)
- Medium: < 10/day (review required)
- High: 0 (immediate escalation)

### 4.4 Auto-Correction Rate
| Attribute | Value |
|-----------|-------|
| **Formula** | `reconciliation_auto_corrected_total / reconciliation_discrepancies_total * 100` |
| **Unit** | percentage |
| **Target** | > 80% |
| **Data Source** | Daily reconciliation job |
| **Frequency** | Daily |
| **Owner** | Data Engineering |

---

## 5. Cost & Efficiency KPIs

### 5.1 Infrastructure Cost per Event
| Attribute | Value |
|-----------|-------|
| **Formula** | `(sum(rate(infrastructure_cost_per_hour[1h])) / sum(rate(events_received_total[1h]))) * 3600` |
| **Unit** | USD/event |
| **Target** | < $0.01/event |
| **Data Source** | Cloud billing + Prometheus metrics |
| **Frequency** | Hourly |
| **Owner** | Platform Engineering + Finance |

**Components:**
- Compute (ECS/Fargate/K8s)
- Database (RDS/TimescaleDB)
- Cache (ElastiCache/Redis)
- Monitoring (Prometheus/Grafana Cloud)
- n8n hosting

### 5.2 Cost Savings vs Manual Process
| Attribute | Value |
|-----------|-------|
| **Formula** | `(manual_cost_per_event - automated_cost_per_event) * events_per_month` |
| **Unit** | USD/month |
| **Target** | > $50K/month savings |
| **Data Source** | Finance + operations tracking |
| **Frequency** | Monthly |
| **Owner** | AI Solutions Engineering + Finance |

**Manual cost baseline:** $0.15/event (2 FTE ops team, 24/7 coverage)

---

## 6. Compliance & Audit KPIs

### 6.1 Audit Trail Completeness
| Attribute | Value |
|-----------|-------|
| **Formula** | `settlements_with_audit_trail / total_settlements * 100` |
| **Unit** | percentage |
| **Target** | 100% |
| **Data Source** | Settlement worker audit output |
| **Frequency** | Continuous |
| **Owner** | Compliance |

### 6.2 Regulatory Report Timeliness
| Attribute | Value |
|-----------|-------|
| **Formula** | `reports_delivered_on_time / total_reports_due * 100` |
| **Unit** | percentage |
| **Target** | 100% |
| **Data Source** | Compliance tracking system |
| **Frequency** | Per reporting period |
| **Owner** | Compliance |

---

## Dashboard Layout (Grafana)

### Business KPI Dashboard (Executive View)
```
Row 1: Automation Rate (Gauge) | Time to Settle (Gauge) | Alert Precision (Gauge) | Human Review Rate (Gauge)
Row 2: Automation Rate Over Time (Time Series) | Time to Settle Distribution (Time Series)
Row 3: Alert Precision & Recall (Time Series) | Alert Volume by Type & Severity (Time Series)
Row 4: Reconciliation Discrepancies (Gauge) | Auto-Corrected (Gauge) | Cost/Event (Gauge) | Throughput (Gauge)
Row 5: Event Volume by Source & Type (Bar Chart)
```

### System Health Dashboard (Engineering View)
```
Row 1: Validation Error Rate (Gauge) | Processing Latency p50/p95/p99 (Time Series)
Row 2: Events Received Rate (Time Series) | Events Forwarded Rate (Time Series)
Row 3: Duplicate Rate (Gauge) | Active Connections (Gauge) | n8n Webhook Latency (Time Series)
Row 4: Service Health Stats (Ingestion, n8n, Postgres, Redis)
```

---

## Alerting Thresholds Summary

| KPI | Warning | Critical | Page |
|-----|---------|----------|------|
| Automation Rate | < 90% | < 70% | - |
| Time to Settle (p95) | > 30s | > 60s | > 120s |
| Alert Precision | < 85% | < 70% | - |
| Human Review Rate | > 30% | > 50% | - |
| Validation Error Rate | > 5% | > 20% | - |
| Processing Latency (p95) | > 1s | > 5s | - |
| Reconciliation Discrepancies | > 0 | > 100 | - |
| System Availability | < 99.9% | < 99.5% | < 99% |

---

## Measurement Implementation

### Prometheus Metric Naming Convention
```
<subsystem>_<metric>_<unit>
Examples:
- events_received_total
- processing_latency_seconds
- settlement_latency_seconds
- alert_evaluation_total
- reconciliation_discrepancies_total
```

### Label Standards
- `type`: odds, event, settlement
- `source`: websocket, rest, manual
- `provider`: provider_a, provider_b, etc.
- `severity`: info, warning, critical, page
- `result`: success, failed, valid, invalid, new, duplicate
- `agreed`: true, false (for alert evaluation)

---

*Document Version: 1.0*  
*Last Updated: 2026-10-26*  
*Review Cycle: Monthly*