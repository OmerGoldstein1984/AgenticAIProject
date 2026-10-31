"""Python Pydantic models matching TypeScript canonical types."""
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime


class OddsFormat(str, Enum):
    DECIMAL = "decimal"
    AMERICAN = "american"
    FRACTIONAL = "fractional"


class EventStatus(str, Enum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    HALF_TIME = "half_time"
    ENDED = "ended"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"
    ABANDONED = "abandoned"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    PAGE = "page"


class AlertType(str, Enum):
    ODDS_ANOMALY = "odds_anomaly"
    SETTLEMENT_DISCREPANCY = "settlement_discrepancy"
    FEED_OUTAGE = "feed_outage"
    ARBITRAGE_DETECTED = "arbitrage_detected"
    SUSPICIOUS_PATTERN = "suspicious_pattern"
    RECONCILIATION_DRIFT = "reconciliation_drift"


class SettlementOutcome(str, Enum):
    WON = "won"
    LOST = "lost"
    VOID = "void"
    HALF_WON = "half_won"
    HALF_LOST = "half_lost"


class Team(BaseModel):
    id: str
    name: str
    short_name: Optional[str] = None


class PeriodScore(BaseModel):
    period: str
    home: int
    away: int


class Score(BaseModel):
    home: int
    away: int
    period_scores: Optional[List[PeriodScore]] = None


class CanonicalEvent(BaseModel):
    id: str
    sport: str
    league: str
    home_team: Team
    away_team: Team
    start_time: datetime
    status: EventStatus
    score: Optional[Score] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CanonicalOdds(BaseModel):
    provider_id: str
    event_id: str
    market_id: str
    selection_id: str
    odds: float
    format: OddsFormat
    timestamp: datetime
    sequence: int


class SettlementResult(BaseModel):
    event_id: str
    market_id: str
    selection_id: str
    outcome: SettlementOutcome
    settled_at: datetime
    source: str  # 'official' | 'manual' | 'auto_reconciled'
    confidence: float = Field(ge=0, le=1)


class Alert(BaseModel):
    id: str
    type: AlertType
    severity: AlertSeverity
    title: str
    description: str
    source_event_id: Optional[str] = None
    confidence: float = Field(ge=0, le=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class Discrepancy(BaseModel):
    entity_type: str  # 'event' | 'odds' | 'settlement'
    entity_id: str
    field: str
    expected: Any
    actual: Any
    severity: str  # 'low' | 'medium' | 'high'


class ReconciliationReport(BaseModel):
    date: str
    total_events: int
    matched: int
    discrepancies: List[Discrepancy]
    auto_corrected: int
    manual_review_required: int


# Ingestion-specific types
class IngestionMetrics(BaseModel):
    events_received: int
    events_validated: int
    events_rejected: int
    events_deduplicated: int
    processing_latency_ms: float
    provider_latency_ms: Dict[str, float]


class AuthConfig(BaseModel):
    type: str  # 'none' | 'bearer' | 'api_key' | 'oauth2' | 'basic'
    credentials: Optional[Dict[str, str]] = None


class RateLimitConfig(BaseModel):
    requests_per_second: int
    burst: Optional[int] = None


class ProviderConfig(BaseModel):
    id: str
    name: str
    type: str  # 'websocket' | 'rest' | 'graphql' | 'batch'
    endpoint: str
    auth: Optional[AuthConfig] = None
    schema_version: str
    rate_limit: Optional[RateLimitConfig] = None
    enabled: bool = True


class NormalizationRule(BaseModel):
    field: str
    transform: str  # 'map' | 'convert_odds' | 'parse_datetime' | 'extract' | 'default'
    config: Optional[Dict[str, Any]] = None


# n8n workflow types
class WorkflowError(BaseModel):
    node: str
    message: str
    code: Optional[str] = None
    retryable: bool
    context: Optional[Dict[str, Any]] = None


class WorkflowExecution(BaseModel):
    id: str
    workflow_id: str
    status: str  # 'running' | 'success' | 'error' | 'waiting'
    started_at: datetime
    finished_at: Optional[datetime] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[WorkflowError] = None


# Settlement Rule DSL
class RuleCondition(BaseModel):
    operator: Optional[str] = None  # 'and' | 'or' | 'not'
    conditions: Optional[List['RuleCondition']] = None
    field: Optional[str] = None
    comparator: Optional[str] = None  # 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'in' | 'contains'
    value: Optional[Any] = None


class SettlementRule(BaseModel):
    id: str
    name: str
    condition: RuleCondition
    outcome: SettlementOutcome
    priority: int
    metadata: Optional[Dict[str, Any]] = None


class SettlementRuleSet(BaseModel):
    version: str
    rules: List[SettlementRule]
    default_outcome: SettlementOutcome


# LLM Alert types
class FewShotExample(BaseModel):
    input: Dict[str, Any]
    output: 'LLMAlertResponse'


class LLMAlertRequest(BaseModel):
    event_data: CanonicalEvent | CanonicalOdds
    anomaly_type: AlertType
    context: Dict[str, Any]
    few_shot_examples: List[FewShotExample]


class LLMAlertResponse(BaseModel):
    title: str
    description: str
    severity: AlertSeverity
    confidence: float = Field(ge=0, le=1)
    suggested_action: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AlertEvaluationResult(BaseModel):
    alert: Alert
    llm_response: LLMAlertResponse
    rule_based_baseline: Optional[Alert] = None
    agreed: bool
    sent_to_human_review: bool


# Reconciliation types
class ReconciliationJob(BaseModel):
    id: str
    date: str
    status: str  # 'pending' | 'running' | 'completed' | 'failed'
    started_at: datetime
    completed_at: Optional[datetime] = None
    report: Optional[ReconciliationReport] = None
    error: Optional[str] = None


class ChecksumRecord(BaseModel):
    entity_type: str  # 'event' | 'odds' | 'settlement'
    entity_id: str
    checksum: str
    source_system: str
    last_updated: datetime


# Resolve forward references
RuleCondition.model_rebuild()