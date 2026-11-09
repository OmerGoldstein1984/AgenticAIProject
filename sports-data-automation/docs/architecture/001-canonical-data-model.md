# Canonical Data Model

## FILE HEADER
-----------
Business problem this file solves:
    Every service in the platform speaks a different "dialect": one provider sends odds as
    American moneyline, another as UK fractional, event IDs arrive as camelCase from one
    system and snake_case from another. Without a shared contract, each integration re-derives
    the same field names and types, drifts out of sync, and silently corrupts bets. This ADR
    records the decision to keep one canonical schema — TypeScript interfaces in
    packages/canonical-types/src/types.ts mirrored 1:1 by Python Pydantic models in
    packages/canonical-types/python/sports_automation/types.py — so data keeps the same shape
    from provider → ingestion → n8n → output systems.

Where it sits in the flow:
    Leaf module (imported conceptually by everything, imports nothing from this repo). Provider
    adapters write into these shapes; the ingestion service validates against them; n8n nodes
    route and settle using them; monitoring KPIs are labelled by their fields.

What calls it / what it calls:
    Pure type library — calls nothing, called by every data-handling module. TS consumers:
    packages/n8n-nodes/*.ts. Python consumers: packages/ingestion-service/*.py,
    packages/mock-providers/*.py (via the mirrored types.py).

What breaks if removed:
    All downstream type references break; providers and ingestion could no longer agree on field
    names, and the TS↔Python contract (critical for contract testing between n8n nodes and the
    Python ingestion service) would vanish.

Language conventions:
    TypeScript (camelCase, matches provider payloads) and Python 3.11+ Pydantic v2 (snake_case,
    Python idiom). The mapping is documented field by field and kept in sync manually — no
    automated TS↔Python codegen exists in this repo.

GAP:
    No automated test asserts that types.ts and types.py stay in sync. A field added to one but
    not the other would only surface at runtime. See 07_issues_found.md.

---

## Status

Accepted

## 1. Context

### Problem being solved

The platform ingests sports data from multiple mock providers (live odds WebSocket, event REST,
settlement batch). Each provider uses its own schema, odds format, and identifier casing:

- Odds: decimal vs American moneyline vs UK fractional
- Event IDs: camelCase from one system, snake_case from another
- Status values: free-text strings that vary by provider

Without a single source of truth, every module would re-derive field names and types, the
TS↔Python contract between n8n nodes and the Python ingestion service would silently break, and
provider drift would corrupt settlements and payouts.

### Why it matters

Settlement accuracy is a regulatory requirement. A canonical event means settlement rules read
score/status without provider-specific parsing. A canonical odds shape lets the OddsNormalizer
compare across providers and detect arbitrage without caring which provider sent what.

## 2. Decision

### What was chosen

A single canonical schema expressed twice, kept in sync manually:

| Layer | File | Language | Field naming |
|-------|------|----------|--------------|
| TypeScript interfaces | `packages/canonical-types/src/types.ts` | TypeScript | camelCase (matches provider payloads) |
| Python Pydantic models | `packages/canonical-types/python/sports_automation/types.py` | Python 3.11+ Pydantic v2 | snake_case (Python idiom) |

The two are mirror images; every TS field has a corresponding Python field, documented field by
field. No automated codegen exists, so sync is a manual discipline enforced by review.

### Canonical models defined

| Model | Purpose |
|-------|---------|
| `OddsFormat` | Closed vocabulary: decimal / american / fractional |
| `EventStatus` | Match lifecycle: scheduled / live / half_time / ended / cancelled / postponed / abandoned |
| `AlertSeverity` | info → warning → critical → page (drives Alertmanager routing) |
| `AlertType` | odds_anomaly / settlement_discrepancy / feed_outage / arbitrage_detected / suspicious_pattern / reconciliation_drift |
| `SettlementOutcome` | won / lost / void / half_won / half_lost |
| `Team`, `PeriodScore`, `Score` | Event participants and scoring |
| `CanonicalEvent` | Core match record anchored by id; referenced by odds, settlement, alerts |
| `CanonicalOdds` | Flattened odds quote, always decimal internally, original format kept for audit |
| `SettlementResult` | Outcome + settled_at + source + confidence (full audit trail) |
| `Alert` | Structured alert routed by confidence to auto-escalate or human-review queue |
| `Discrepancy`, `ReconciliationReport` | Daily reconciliation drift output |
| `IngestionMetrics`, `AuthConfig`, `RateLimitConfig`, `ProviderConfig` | Ingestion configuration and telemetry |
| `WorkflowError`, `WorkflowExecution` | n8n workflow execution records |
| `RuleCondition`, `SettlementRule`, `SettlementRuleSet` | Settlement rule DSL |
| `FewShotExample`, `LLMAlertRequest`, `LLMAlertResponse`, `AlertEvaluationResult` | LLM alert types |
| `ReconciliationJob`, `ChecksumRecord` | Reconciliation job and checksum tracking |

Enums (str-enums in Python, discriminated unions in TS) make invalid values unrepresentable, so
invalid provider values fail schema validation at ingestion rather than propagating silently.

## 3. Consequences

### Positive

- All modules agree on field names and types; no silent corruption from dialect mismatch.
- The TS↔Python contract enables contract testing between n8n nodes (TS) and the Python ingestion
  service — a key production-grade signal for the interview.
- Enums make invalid odds formats, statuses, and settlement outcomes unrepresentable; boundary
  validation catches bad provider data early.
- The flat `CanonicalOdds` shape supports independent deduplication keyed on
  `provider:event:market:selection:sequence`.
- A single canonical `CanonicalEvent` means settlement rules act on one authoritative event state
  instead of joining per-provider records at query time.

### Negative / tradeoffs

- Manual TS↔Python sync: a field added to one side but not the other surfaces only at runtime.
  No automated test enforces parity (recorded as a GAP; see 07_issues_found.md).
- `ProviderConfig` and `NormalizationRule` are defined but no provider-registry loader or
  rule-driven transform engine is implemented; providers are wired in `Settings.rest_endpoints`
  and `CanonicalTransformer` uses hard-coded `PROVIDER_MAPPINGS` (both recorded as GAPs).
- Keeping two mirrored copies doubles the surface area for schema drift; discipline and code
  review are the only guardrails.

## 4. References

- `sports-data-automation/packages/canonical-types/src/types.ts` — TypeScript canonical interfaces
- `sports-data-automation/packages/canonical-types/python/sports_automation/types.py` — Python Pydantic canonical models
- `PROJECT_SPEC.md` — Technical Stack, Repository Structure, Core Components
- `07_issues_found.md` — Recorded GAPs (types sync, provider registry, normalization engine)

---

*Document Version: 1.0*  
*Date: 2026-11-09*  
*Owner: Architecture*
