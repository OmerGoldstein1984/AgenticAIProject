export type OddsFormat = 'decimal' | 'american' | 'fractional';

export interface CanonicalOdds {
  providerId: string;
  eventId: string;
  marketId: string;
  selectionId: string;
  odds: number;
  format: OddsFormat;
  timestamp: string; // ISO 8601
  sequence: number;  // For ordering
}

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
}

export interface Team {
  id: string;
  name: string;
  shortName?: string;
}

export interface Score {
  home: number;
  away: number;
  periodScores?: PeriodScore[];
}

export interface PeriodScore {
  period: string;
  home: number;
  away: number;
}

export type EventStatus =
  | 'scheduled'
  | 'live'
  | 'half_time'
  | 'ended'
  | 'cancelled'
  | 'postponed'
  | 'abandoned';

export interface SettlementResult {
  eventId: string;
  marketId: string;
  selectionId: string;
  outcome: 'won' | 'lost' | 'void' | 'half_won' | 'half_lost';
  settledAt: string;
  source: 'official' | 'manual' | 'auto_reconciled';
  confidence: number; // 0-1
}

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
}

export type AlertType =
  | 'odds_anomaly'
  | 'settlement_discrepancy'
  | 'feed_outage'
  | 'arbitrage_detected'
  | 'suspicious_pattern'
  | 'reconciliation_drift';

export interface ReconciliationReport {
  date: string;
  totalEvents: number;
  matched: number;
  discrepancies: Discrepancy[];
  autoCorrected: number;
  manualReviewRequired: number;
}

export interface Discrepancy {
  entityType: 'event' | 'odds' | 'settlement';
  entityId: string;
  field: string;
  expected: unknown;
  actual: unknown;
  severity: 'low' | 'medium' | 'high';
}

// Ingestion-specific types
export interface IngestionMetrics {
  eventsReceived: number;
  eventsValidated: number;
  eventsRejected: number;
  eventsDeduplicated: number;
  processingLatencyMs: number;
  providerLatencyMs: Record<string, number>;
}

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

export interface AuthConfig {
  type: 'none' | 'bearer' | 'api_key' | 'oauth2' | 'basic';
  credentials?: Record<string, string>;
}

export interface RateLimitConfig {
  requestsPerSecond: number;
  burst?: number;
}

export interface NormalizationRule {
  field: string;
  transform: 'map' | 'convert_odds' | 'parse_datetime' | 'extract' | 'default';
  config?: Record<string, unknown>;
}

// n8n workflow types
export interface WorkflowExecution {
  id: string;
  workflowId: string;
  status: 'running' | 'success' | 'error' | 'waiting';
  startedAt: string;
  finishedAt?: string;
  data: Record<string, unknown>;
  error?: WorkflowError;
}

export interface WorkflowError {
  node: string;
  message: string;
  code?: string;
  retryable: boolean;
  context?: Record<string, unknown>;
}

// Settlement Rule DSL
export interface SettlementRule {
  id: string;
  name: string;
  condition: RuleCondition;
  outcome: SettlementOutcome;
  priority: number;
  metadata?: Record<string, unknown>;
}

export interface RuleCondition {
  operator: 'and' | 'or' | 'not';
  conditions?: RuleCondition[];
  field?: string;
  comparator?: 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'in' | 'contains';
  value?: unknown;
}

export type SettlementOutcome = 'won' | 'lost' | 'void' | 'half_won' | 'half_lost';

export interface SettlementRuleSet {
  version: string;
  rules: SettlementRule[];
  defaultOutcome: SettlementOutcome;
}

// LLM Alert types
export interface LLMAlertRequest {
  eventData: CanonicalEvent | CanonicalOdds;
  anomalyType: AlertType;
  context: Record<string, unknown>;
  fewShotExamples: FewShotExample[];
}

export interface FewShotExample {
  input: Record<string, unknown>;
  output: LLMAlertResponse;
}

export interface LLMAlertResponse {
  title: string;
  description: string;
  severity: 'info' | 'warning' | 'critical' | 'page';
  confidence: number;
  suggestedAction?: string;
  metadata: Record<string, unknown>;
}

export interface AlertEvaluationResult {
  alert: Alert;
  llmResponse: LLMAlertResponse;
  ruleBasedBaseline?: Alert;
  agreed: boolean;
  sentToHumanReview: boolean;
}

// Reconciliation types
export interface ReconciliationJob {
  id: string;
  date: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  startedAt: string;
  completedAt?: string;
  report?: ReconciliationReport;
  error?: string;
}

export interface ChecksumRecord {
  entityType: 'event' | 'odds' | 'settlement';
  entityId: string;
  checksum: string;
  sourceSystem: string;
  lastUpdated: string;
}