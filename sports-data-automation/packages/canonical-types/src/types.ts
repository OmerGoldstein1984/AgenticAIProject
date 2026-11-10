/**
 * packages/canonical-types/src/types.ts
 *
 * FILE HEADER
 * -----------
 * Business problem this file solves:
 *   Every service in the platform (ingestion, n8n nodes, mock providers, processing engine)
 *   speaks a different "dialect": one provider sends odds as American moneyline, another as
 *   fractional, event IDs come as camelCase from one system and snake_case from another.
 *   Without a shared contract, each integration would re-derive the same fields, drift out of
 *   sync, and silently corrupt bets. This file is the SINGLE SOURCE OF TRUTH: one canonical
 *   schema (TypeScript here, mirrored in python/sports_automation/types.py) that every module
 *   agrees on, so data keeps the same shape from provider → ingestion → n8n → output systems.
 *
 * Where it sits in the flow:
 *   Leaf module (imported conceptually by everything, imports nothing from this repo).
 *   Provider adapters write into these shapes; the ingestion service validates against them;
 *   n8n nodes route and settle using them; monitoring KPIs are labelled by their fields.
 *
 * What calls it / what it calls:
 *   Pure type library — calls nothing, called by every data-handling module.
 *   TS consumers: packages/n8n-nodes/*.ts. Python consumers: packages/ingestion-service/*.py,
 *   packages/mock-providers/*.py (via the mirrored types.py).
 *
 * What breaks if removed:
 *   All downstream type references break; providers and ingestion could no longer agree on field
 *   names, and the TS↔Python contract (critical for contract testing between n8n nodes and the
 *   Python ingestion service) would vanish.
 *
 * Language conventions:
 *   TypeScript. JSDoc above each exported type/interface. camelCase field names match provider
 *   payloads (providerId, eventId); the Python mirror uses snake_case.
 */

// ---------------------------------------------------------------------------
// Core domain primitives
// ---------------------------------------------------------------------------

/**
 * The three odds formats used by sports-data providers.
 *
 * WHAT: Union of literal string values a provider may report odds in.
 * WHY: Providers disagree on format (decimal, American moneyline, UK fractional). The platform
 *   normalizes everything TO decimal internally (CanonicalTransformer._normalize_odds in the
 *   ingestion service) but remembers the original format so the raw provider payload can be
 *   reconstructed for audit.
 *
 * EXAMPLE: 'decimal' | 'american' | 'fractional'
 *
 * SIDE EFFECTS: none (type-level only).
 * FAILURE MODES: none at runtime; a typo here is a compile-time error (caught early — good).
 * ALTERNATIVE: single string field with runtime validation. Chosen a discriminated union because
 *   it makes invalid formats unrepresentable and lets the compiler exhaustively check handling.
 */
export type OddsFormat = 'decimal' | 'american' | 'fractional';

/**
 * Canonical representation of a single odds quote, the most frequently ingested entity.
 *
 * WHAT: One flattened odds record in the platform's internal format (always decimal internally).
 * WHY: Odds are the highest-volume feed (WebSocket pushes every 500ms–2s). A single canonical
 *   shape lets the OddsNormalizer n8n node compare across providers and detect arbitrage without
 *   caring which provider sent what.
 *
 * EXAMPLE:
 *   {
 *     providerId: "provider_0",
 *     eventId: "evt_000001",
 *     marketId: "match_winner",
 *     selectionId: "home",
 *     odds: 2.1,
 *     format: "decimal",
 *     timestamp: "2026-11-09T14:30:00Z",
 *     sequence: 42
 *   }
 *
 * INPUTS/OUTPUTS: consumed by schema_validator, canonical_transformer, deduplicator,
 *   OddsNormalizer node.
 * SIDE EFFECTS: none (pure data structure).
 * FAILURE MODES: missing/malformed fields → rejected by JSON Schema at ingestion
 *   (schema_validator.py required list).
 * ALTERNATIVE: nest market/selection inside event. Chosen flat because each odds quote moves
 *   independently and is deduplicated keyed on provider:event:market:selection:sequence.
 */
export interface CanonicalOdds {
  providerId: string;   // Which feed supplied the quote (foreign key to ProviderConfig.id)
  eventId: string;      // Underlying match/event the quote is for
  marketId: string;     // Betting market (e.g. match_winner, total_goals)
  selectionId: string;  // Selection within the market (e.g. home, over_2.5)
  odds: number;         // Decimal odds value (e.g. 2.10)
  format: OddsFormat;   // Original provider format before normalization
  timestamp: string;    // ISO 8601 when the quote was produced
  sequence: number;     // Monotonic per-provider sequence for ordering/dedup
  traceId?: string;     // Distributed trace ID for end-to-end propagation
}

/**
 * Canonical representation of a sports event (match).
 *
 * WHAT: The core event record: teams, timing, status, score.
 * WHY: Events anchor everything — odds, settlement, alerts all reference eventId. A canonical
 *   event means settlement rules (SettlementWorker) can read score/status without provider-specific
 *   parsing.
 *
 * EXAMPLE:
 *   {
 *     id: "evt_000001",
 *     sport: "football",
 *     league: "Premier League",
 *     homeTeam: { id: "team_1_home", name: "Red United", shortName: "RED" },
 *     awayTeam: { id: "team_1_away", name: "Blue City", shortName: "BLU" },
 *     startTime: "2026-11-10T15:00:00Z",
 *     status: "scheduled",
 *     score: { home: 0, away: 0 },
 *     metadata: {}
 *   }
 *
 * SIDE EFFECTS: none (pure data structure).
 * FAILURE MODES: absent status/score → defaults applied in canonical_transformer (unknown/scheduled).
 * ALTERNATIVE: keep events normalized per-provider and join at query time. Chosen canonical because
 *   settlement must act on a single authoritative event state.
 */
export interface CanonicalEvent {
  id: string;
  sport: string;
  league: string;
  homeTeam: Team;
  awayTeam: Team;
  startTime: string;
  status: EventStatus;
  score?: Score;
  metadata: Record<string, unknown>;
  traceId?: string;  // Distributed trace ID for end-to-end propagation
}

/**
 * A sports team/participant.
 */
export interface Team {
  id: string;
  name: string;
  shortName?: string;
}

/**
 * Score for an event, with optional per-period breakdown.
 */
export interface Score {
  home: number;
  away: number;
  periodScores?: PeriodScore[];
}

/**
 * Score for a single period (quarter, half, set).
 */
export interface PeriodScore {
  period: string;
  home: number;
  away: number;
}

/**
 * Lifecycle status of an event.
 *
 * WHAT: Enumerated status a match can be in.
 * WHY: Settlement rules gate on status (only "ended" events auto-settle; cancelled/postponed
 *   go to void). The enum makes invalid statuses unrepresentable.
 *
 * FAILURE MODES: a provider sending an unknown status string fails schema validation.
 * ALTERNATIVE: free-text status. Chosen enum for exhaustive handling and validation.
 */
export type EventStatus =
  | 'scheduled'
  | 'live'
  | 'half_time'
  | 'ended'
  | 'cancelled'
  | 'postponed'
  | 'abandoned';

/**
 * The result of settling one bet selection.
 *
 * WHAT: What happened to a bet (won/lost/void/half_won/half_lost), when, and how confidently.
 * WHY: Settlement accuracy is a regulatory requirement in sports betting. Recording outcome +
 *   source + confidence gives a full audit trail (100% audit-trail-coverage KPI).
 *
 * EXAMPLE:
 *   { eventId: "evt_000001", marketId: "match_winner", selectionId: "home",
 *     outcome: "won", settledAt: "2026-11-10T17:05:00Z", source: "official", confidence: 1.0 }
 *
 * FAILURE MODES: confidence outside [0,1] rejected by schema; unknown outcome defaulted to "void"
 *   in canonical_transformer.transform_settlement.
 * ALTERNATIVE: a boolean settled/not-settled. Chosen 5-value outcome because void/half outcomes
 *   matter financially (tennis retirement, abandoned matches).
 */
export interface SettlementResult {
  eventId: string;
  marketId: string;
  selectionId: string;
  outcome: 'won' | 'lost' | 'void' | 'half_won' | 'half_lost';
  settledAt: string;
  source: 'official' | 'manual' | 'auto_reconciled';
  confidence: number; // 0-1
  traceId?: string;  // Distributed trace ID for end-to-end propagation
}

/**
 * A platform-generated alert about an anomaly.
 *
 * WHAT: Structured alert (title, description, severity, confidence) produced by the LLM Alert
 *   Generator n8n node or a rule-based baseline.
 * WHY: Ops teams cannot watch every feed; alerts route to auto-escalate or a human-review queue
 *   based on confidence, replacing manual dashboard-watching.
 *
 * EXAMPLE:
 *   { id: "alert_123", type: "odds_anomaly", severity: "warning", title: "...",
 *     description: "...", sourceEventId: "evt_000001", confidence: 0.92,
 *     metadata: { deviationPercent: 33 }, createdAt: "..." }
 *
 * FAILURE MODES: LLM response missing required fields → routed to error output in the node.
 * ALTERNATIVE: plain free-text Slack message. Chosen structured JSON so downstream systems can
 *   page, ticket, and dashboard on it.
 */
export interface Alert {
  id: string;
  type: AlertType;
  severity: 'info' | 'warning' | 'critical' | 'page';
  title: string;
  description: string;
  sourceEventId?: string;
  confidence: number;
  metadata: Record<string, unknown>;
  createdAt: string;
  acknowledgedAt?: string;
  resolvedAt?: string;
  traceId?: string;  // Distributed trace ID for end-to-end propagation
}

/**
 * Taxonomy of alert types the platform can emit.
 */
export type AlertType =
  | 'odds_anomaly'
  | 'settlement_discrepancy'
  | 'feed_outage'
  | 'arbitrage_detected'
  | 'suspicious_pattern'
  | 'reconciliation_drift';

/**
 * Output of the daily reconciliation job.
 *
 * WHAT: Summary of drift between internal records and provider records for one date.
 * WHY: Reconciliation catches compounding data errors days before a trader notices them.
 *
 * FAILURE MODES: high discrepancy count → critical alert (reconciliation_discrepancies_total > 100).
 * ALTERNATIVE: no reconciliation, trust providers. Chosen automated checksum comparison because
 *   provider drift silently corrupts settlements and payouts.
 */
export interface ReconciliationReport {
  date: string;
  totalEvents: number;
  matched: number;
  discrepancies: Discrepancy[];
  autoCorrected: number;
  manualReviewRequired: number;
  traceId?: string;  // Distributed trace ID for end-to-end propagation
}

/**
 * A single disagreement found during reconciliation.
 */
export interface Discrepancy {
  entityType: 'event' | 'odds' | 'settlement';
  entityId: string;
  field: string;
  expected: unknown;
  actual: unknown;
  severity: 'low' | 'medium' | 'high';
}

// ---------------------------------------------------------------------------
// Ingestion-specific types
// ---------------------------------------------------------------------------

/**
 * Snapshot of ingestion throughput/quality counters.
 *
 * WHAT: Counters emitted to Prometheus (events_received_total, events_validated_total, ...).
 * WHY: The KPI dashboard (automation rate, validation success rate) is computed from these.
 *
 * SIDE EFFECTS: incremented as side effects in ingestion.metrics (record_* helpers).
 */
export interface IngestionMetrics {
  eventsReceived: number;
  eventsValidated: number;
  eventsRejected: number;
  eventsDeduplicated: number;
  processingLatencyMs: number;
  providerLatencyMs: Record<string, number>;
}

/**
 * Configuration for one data provider.
 *
 * WHAT: Declares how to reach and authenticate a provider, its schema version, and rate limit.
 * WHY: Adding a new provider is then configuration, not code — register ProviderConfig and the
 *   adapter pattern picks it up.
 *
 * GAP: ProviderConfig is defined here but no provider-registry loader is implemented in this
 *   repo; providers are wired in Settings.rest_endpoints (config.py) instead. See 07_issues_found.md.
 */
export interface ProviderConfig {
  id: string;
  name: string;
  type: 'websocket' | 'rest' | 'graphql' | 'batch';
  endpoint: string;
  auth?: AuthConfig;
  schemaVersion: string;
  rateLimit?: RateLimitConfig;
  enabled: boolean;
}

/**
 * Authentication settings for a provider.
 */
export interface AuthConfig {
  type: 'none' | 'bearer' | 'api_key' | 'oauth2' | 'basic';
  credentials?: Record<string, string>;
}

/**
 * Rate-limit ceiling for a provider.
 */
export interface RateLimitConfig {
  requestsPerSecond: number;
  burst?: number;
}

/**
 * One field-level normalization instruction.
 *
 * WHAT: How to transform one provider field into a canonical field.
 * WHY: Encapsulates the adapter mapping so new providers need new rules, not new code.
 *
 * GAP: NormalizationRule is defined but the rule-driven transform engine is not implemented;
 *   CanonicalTransformer uses hard-coded PROVIDER_MAPPINGS instead. See 07_issues_found.md.
 */
export interface NormalizationRule {
  field: string;
  transform: 'map' | 'convert_odds' | 'parse_datetime' | 'extract' | 'default';
  config?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// n8n workflow types
// ---------------------------------------------------------------------------

/**
 * Record of one n8n workflow execution.
 */
export interface WorkflowExecution {
  id: string;
  workflowId: string;
  status: 'running' | 'success' | 'error' | 'waiting';
  startedAt: string;
  finishedAt?: string;
  data: Record<string, unknown>;
  error?: WorkflowError;
}

/**
 * Error detail attached to a failed workflow execution.
 */
export interface WorkflowError {
  node: string;
  message: string;
  code?: string;
  retryable: boolean;
  context?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Settlement Rule DSL
// ---------------------------------------------------------------------------

/**
 * One rule evaluated by the Settlement Worker n8n node.
 *
 * WHAT: condition + outcome + priority. Rules are sorted by priority; the highest-priority
 *   matching rule wins.
 * WHY: Business users change settlement rules (e.g. new sport, new void condition) without a
 *   code deploy — the DSL lives in JSON (embedded in the node or loaded from DB/remote).
 *
 * GAP: rule-set hot-reload from DB/remote is declared in the node UI but not implemented;
 *   only the embedded JSON path works. See 07_issues_found.md.
 */
export interface SettlementRule {
  id: string;
  name: string;
  condition: RuleCondition;
  outcome: SettlementOutcome;
  priority: number;
  metadata?: Record<string, unknown>;
}

/**
 * A condition node in the rule tree — supports AND/OR/NOT composition and leaf comparisons.
 */
export interface RuleCondition {
  operator: 'and' | 'or' | 'not';
  conditions?: RuleCondition[];
  field?: string;
  comparator?: 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'in' | 'contains';
  value?: unknown;
}

/**
 * Possible settlement outcomes (financial meaning).
 */
export type SettlementOutcome = 'won' | 'lost' | 'void' | 'half_won' | 'half_lost';

/**
 * Versioned collection of settlement rules with a default outcome.
 */
export interface SettlementRuleSet {
  version: string;
  rules: SettlementRule[];
  defaultOutcome: SettlementOutcome;
}

// ---------------------------------------------------------------------------
// LLM Alert types
// ---------------------------------------------------------------------------

/**
 * Request sent to the LLM to generate one alert.
 */
export interface LLMAlertRequest {
  eventData: CanonicalEvent | CanonicalOdds;
  anomalyType: AlertType;
  context: Record<string, unknown>;
  fewShotExamples: FewShotExample[];
}

/**
 * One few-shot (input → expected output) pair used to prime the LLM prompt.
 */
export interface FewShotExample {
  input: Record<string, unknown>;
  output: LLMAlertResponse;
}

/**
 * Structured LLM response for one alert.
 */
export interface LLMAlertResponse {
  title: string;
  description: string;
  severity: 'info' | 'warning' | 'critical' | 'page';
  confidence: number;
  suggestedAction?: string;
  metadata: Record<string, unknown>;
}

/**
 * Result of comparing an LLM alert against a rule-based baseline.
 */
export interface AlertEvaluationResult {
  alert: Alert;
  llmResponse: LLMAlertResponse;
  ruleBasedBaseline?: Alert;
  agreed: boolean;
  sentToHumanReview: boolean;
}

// ---------------------------------------------------------------------------
// Reconciliation types
// ---------------------------------------------------------------------------

/**
 * One reconciliation job run.
 */
export interface ReconciliationJob {
  id: string;
  date: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  startedAt: string;
  completedAt?: string;
  report?: ReconciliationReport;
  error?: string;
}

/**
 * Checksum fingerprint of one entity in one source system, used to detect drift.
 */
export interface ChecksumRecord {
  entityType: 'event' | 'odds' | 'settlement';
  entityId: string;
  checksum: string;
  sourceSystem: string;
  lastUpdated: string;
}
