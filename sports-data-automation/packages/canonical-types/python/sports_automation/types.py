"""
packages/canonical-types/python/sports_automation/types.py

FILE HEADER
-----------
Business problem this file solves:
    Python mirror of packages/canonical-types/src/types.ts. It is the single source of truth for
    the canonical data contract on the Python side (ingestion service, mock providers). Every
    Pydantic model here has a corresponding TypeScript interface in types.ts so the Python
    ingestion service and the TypeScript n8n nodes can be contract-tested against the same schema.
    Without it, each Python module would re-derive field names and types, and the TS↔Python
    contract that keeps provider→ingestion→n8n consistent would silently break.

Where it sits in the flow:
    Leaf module (imported by ingestion-service and mock-providers; imports only pydantic/stdlib).
    Provider adapters instantiate these models; schema validation and normalization coerce raw
    provider JSON into them before forwarding to n8n.

What calls it / what it calls:
    Called by: packages/ingestion-service/src/ingestion/*.py, packages/mock-providers/src/mock/*.py.
    Calls: nothing from this repo (only pydantic, typing, datetime).

What breaks if removed:
    All Pydantic validation, normalization, and metrics serialization in the ingestion service
    and mock providers break; the TS↔Python contract vanishes.

Language conventions:
    Python 3.11+. Pydantic v2 BaseModel. str-enums for closed vocabularies. snake_case field
    names (Python idiom) vs the camelCase TS mirror — the mapping is documented field by field
    and must be kept in sync manually (no automated TS↔Python codegen exists in this repo).

GAP: No automated test asserts that types.ts and types.py stay in sync. A field added to one but
    not the other would only surface at runtime. See 07_issues_found.md.
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime


class OddsFormat(str, Enum):
    """The three odds formats a provider may report.

    WHAT: Closed vocabulary of odds representations.
    WHY: Providers disagree (decimal vs American moneyline vs UK fractional). The platform
        normalizes everything TO decimal internally but keeps the original format for audit.
    EXAMPLE: OddsFormat.DECIMAL == "decimal"
    SIDE EFFECTS: none (enum).
    FAILURE MODES: a provider format not in this set fails schema validation at ingestion.
    ALTERNATIVE: plain string + runtime check. Chosen str-enum so invalid values are
        unrepresentable and pydantic validates automatically.
    """
    DECIMAL = "decimal"
    AMERICAN = "american"
    FRACTIONAL = "fractional"


class EventStatus(str, Enum):
    """Lifecycle status of a sports event.

    WHAT: Enumerated match status.
    WHY: Settlement rules gate on status (only "ended" events auto-settle; cancelled/postponed
        go void). The enum makes invalid statuses unrepresentable.
    EXAMPLE: EventStatus.ENDED == "ended"
    FAILURE MODES: a provider sending an unknown status fails JSON-schema validation at ingestion.
    ALTERNATIVE: free-text status. Chosen enum for exhaustive handling and validation.
    """
    SCHEDULED = "scheduled"
    LIVE = "live"
    HALF_TIME = "half_time"
    ENDED = "ended"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"
    ABANDONED = "abandoned"


class AlertSeverity(str, Enum):
    """Severity of a platform alert.

    WHAT: info → warning → critical → page (increasing urgency).
    WHY: Drives alert routing in Alertmanager (pager vs warning vs business vs info).
    EXAMPLE: AlertSeverity.PAGE == "page"
    SIDE EFFECTS: none (enum).
    """
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    PAGE = "page"


class AlertType(str, Enum):
    """Taxonomy of alerts the platform can emit.

    WHAT: Six alert families (odds_anomaly, settlement_discrepancy, feed_outage,
        arbitrage_detected, suspicious_pattern, reconciliation_drift).
    WHY: Standardized taxonomy lets Alertmanager route, Grafana group, and runbooks target
        each family differently.
    EXAMPLE: AlertType.SETTLEMENT_DISCREPANCY == "settlement_discrepancy"
    """
    ODDS_ANOMALY = "odds_anomaly"
    SETTLEMENT_DISCREPANCY = "settlement_discrepancy"
    FEED_OUTAGE = "feed_outage"
    ARBITRAGE_DETECTED = "arbitrage_detected"
    SUSPICIOUS_PATTERN = "suspicious_pattern"
    RECONCILIATION_DRIFT = "reconciliation_drift"


class SettlementOutcome(str, Enum):
    """Financial outcome of settling one bet selection.

    WHAT: won / lost / void / half_won / half_lost.
    WHY: Void and half outcomes matter financially (tennis retirement, abandoned matches) and
        are a regulatory audit requirement. A boolean settled/not-settled would lose this.
    EXAMPLE: SettlementOutcome.VOID == "void"
    FAILURE MODES: an unknown outcome string is defaulted to "void" in
        canonical_transformer.transform_settlement to avoid propagating garbage.
    ALTERNATIVE: boolean. Chosen 5-value enum for financial correctness.
    """
    WON = "won"
    LOST = "lost"
    VOID = "void"
    HALF_WON = "half_won"
    HALF_LOST = "half_lost"


class Team(BaseModel):
    """A sports team or participant.

    WHAT: id, name, optional short name.
    WHY: Referenced by CanonicalEvent.home_team / away_team; used for alert titles and
        customer-facing display.
    EXAMPLE: Team(id="team_1_home", name="Red United", short_name="RED")
    SIDE EFFECTS: none (pure data model).
    """
    id: str
    name: str
    short_name: Optional[str] = None


class PeriodScore(BaseModel):
    """Score for a single period (quarter, half, set).

    WHAT: period label + home/away points.
    EXAMPLE: PeriodScore(period="Q1", home=3, away=7)
    """
    period: str
    home: int
    away: int


class Score(BaseModel):
    """Score for an event, with optional per-period breakdown.

    WHAT: home/away totals plus optional period-by-period detail.
    EXAMPLE: Score(home=2, away=1, period_scores=[PeriodScore(...)])
    SIDE EFFECTS: none.
    """
    home: int
    away: int
    period_scores: Optional[List[PeriodScore]] = None


class CanonicalEvent(BaseModel):
    """Canonical representation of a sports event (match).

    WHAT: Teams, timing, status, score — the core record everything else references by id.
    WHY: Events anchor odds, settlement, and alerts. One canonical event means settlement
        rules read score/status without provider-specific parsing.
    EXAMPLE:
        CanonicalEvent(
            id="evt_000001", sport="football", league="Premier League",
            home_team=Team(id="team_1_home", name="Red United"),
            away_team=Team(id="team_1_away", name="Blue City"),
            start_time=datetime(2026, 11, 10, 15, 0),
            status=EventStatus.SCHEDULED,
            score=Score(home=0, away=0),
            metadata={},
            trace_id="trace_abc123"
        )
    INPUTS/OUTPUTS: instantiated by canonical_transformer.transform_event; consumed by
        SettlementWorker n8n node and schema validation.
    FAILURE MODES: absent status/score → defaults applied in the transformer.
    ALTERNATIVE: per-provider event models joined at query time. Chosen canonical because
        settlement must act on one authoritative event state.
    """
    id: str
    sport: str
    league: str
    home_team: Team
    away_team: Team
    start_time: datetime
    status: EventStatus
    score: Optional[Score] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None


class CanonicalOdds(BaseModel):
    """Canonical representation of a single odds quote (highest-volume feed).

    WHAT: One flattened odds record, always decimal internally, with original format kept.
    WHY: Odds arrive via WebSocket every 500ms–2s from multiple providers. One canonical
        shape lets OddsNormalizer compare across providers and detect arbitrage.
    EXAMPLE:
        CanonicalOdds(
            provider_id="provider_0", event_id="evt_000001", market_id="match_winner",
            selection_id="home", odds=2.1, format=OddsFormat.DECIMAL,
            timestamp=datetime(2026, 11, 9, 14, 30), sequence=42
        )
    INPUTS/OUTPUTS: produced by canonical_transformer.transform_odds; consumed by
        schema_validator, deduplicator, OddsNormalizer node.
    FAILURE MODES: missing/malformed fields → rejected by JSON Schema at ingestion.
    ALTERNATIVE: nested market/selection inside event. Chosen flat because each quote moves
        independently and is deduplicated on provider:event:market:selection:sequence.
    """
    provider_id: str
    event_id: str
    market_id: str
    selection_id: str
    odds: float
    format: OddsFormat
    timestamp: datetime
    sequence: int
    trace_id: Optional[str] = None


class SettlementResult(BaseModel):
    """Result of settling one bet selection.

    WHAT: Outcome, when settled, source, confidence.
    WHY: Settlement accuracy is a regulatory requirement. outcome + source + confidence =
        full audit trail (100% audit-trail-coverage KPI).
    EXAMPLE:
        SettlementResult(
            event_id="evt_000001", market_id="match_winner", selection_id="home",
            outcome=SettlementOutcome.WON, settled_at=datetime(2026,11,10,17,5),
            source="official", confidence=1.0
        )
    FAILURE MODES: confidence outside [0,1] → pydantic validation error (Field ge=0, le=1).
    ALTERNATIVE: boolean settled/not-settled. Chosen 5-value enum for financial correctness.
    """
    event_id: str
    market_id: str
    selection_id: str
    outcome: SettlementOutcome
    settled_at: datetime
    source: str  # 'official' | 'manual' | 'auto_reconciled'
    confidence: float = Field(ge=0, le=1)
    trace_id: Optional[str] = None


class Alert(BaseModel):
    """A platform-generated alert about an anomaly.

    WHAT: Structured alert routed to auto-escalate or human-review queue by confidence.
    WHY: Ops teams cannot watch every feed; structured alerts can be paged, ticketed, and
        dashboarded.
    EXAMPLE:
        Alert(id="alert_123", type=AlertType.ODDS_ANOMALY, severity=AlertSeverity.WARNING,
              title="...", description="...", source_event_id="evt_000001",
              confidence=0.92, metadata={}, created_at=datetime.now())
    FAILURE MODES: LLM response missing required fields → routed to error output in the node.
    ALTERNATIVE: plain free-text Slack message. Chosen structured JSON for automation.
    """
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
    trace_id: Optional[str] = None


class Discrepancy(BaseModel):
    """A single disagreement found during reconciliation.

    WHAT: entity type/id, field, expected vs actual, severity.
    WHY: Pinpoints exactly what drifted so it can be auto-corrected or sent to manual review.
    EXAMPLE: Discrepancy(entity_type="settlement", entity_id="evt_1", field="outcome",
        expected="won", actual="void", severity="high")
    """
    entity_type: str  # 'event' | 'odds' | 'settlement'
    entity_id: str
    field: str
    expected: Any
    actual: Any
    severity: str  # 'low' | 'medium' | 'high'


class ReconciliationReport(BaseModel):
    """Output of the daily reconciliation job for one date.

    WHAT: total/matched/discrepancies/auto-corrected/manual-review counts.
    WHY: Reconciliation catches compounding data errors before a trader notices them.
    FAILURE MODES: high discrepancy count → critical alert
        (reconciliation_discrepancies_total > 100).
    ALTERNATIVE: trust providers, no reconciliation. Chosen automated checksum comparison
        because provider drift silently corrupts settlements/payouts.
    """
    date: str
    total_events: int
    matched: int
    discrepancies: List[Discrepancy]
    auto_corrected: int
    manual_review_required: int
    trace_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Ingestion-specific types
# ---------------------------------------------------------------------------


class IngestionMetrics(BaseModel):
    """Snapshot of ingestion throughput/quality counters emitted to Prometheus.

    WHAT: events_received/validated/rejected/deduplicated counts, latency histograms.
    WHY: KPI dashboard (automation rate, validation success rate) is computed from these.
    SIDE EFFECTS: incremented as side effects in ingestion.metrics (record_* helpers).
    """
    events_received: int
    events_validated: int
    events_rejected: int
    events_deduplicated: int
    processing_latency_ms: float
    provider_latency_ms: Dict[str, float]


class AuthConfig(BaseModel):
    """Authentication settings for one provider.

    WHAT: auth type (none/bearer/api_key/oauth2/basic) plus optional credentials.
    WHY: Different providers use different auth; one config shape handles all.
    """
    type: str  # 'none' | 'bearer' | 'api_key' | 'oauth2' | 'basic'
    credentials: Optional[Dict[str, str]] = None


class RateLimitConfig(BaseModel):
    """Rate-limit ceiling for a provider.

    WHAT: requests per second plus optional burst.
    WHY: Prevents overwhelming provider feeds and triggering 429s.
    """
    requests_per_second: int
    burst: Optional[int] = None


class ProviderConfig(BaseModel):
    """Configuration for one data provider.

    WHAT: How to reach/authenticate a provider, its schema version, rate limit, enabled flag.
    WHY: Adding a new provider is configuration, not code (adapter pattern).
    GAP: ProviderConfig is defined here but no provider-registry loader is implemented;
        providers are wired in Settings.rest_endpoints (config.py) instead. See 07_issues_found.md.
    """
    id: str
    name: str
    type: str  # 'websocket' | 'rest' | 'graphql' | 'batch'
    endpoint: str
    auth: Optional[AuthConfig] = None
    schema_version: str
    rate_limit: Optional[RateLimitConfig] = None
    enabled: bool = True


class NormalizationRule(BaseModel):
    """One field-level normalization instruction.

    WHAT: How to transform one provider field into a canonical field.
    WHY: Encapsulates adapter mapping so new providers need new rules, not new code.
    GAP: defined but the rule-driven transform engine is not implemented;
        CanonicalTransformer uses hard-coded PROVIDER_MAPPINGS instead. See 07_issues_found.md.
    """
    field: str
    transform: str  # 'map' | 'convert_odds' | 'parse_datetime' | 'extract' | 'default'
    config: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# n8n workflow types
# ---------------------------------------------------------------------------


class WorkflowError(BaseModel):
    """Error detail attached to a failed n8n workflow execution.

    WHAT: failing node, message, optional code, retryable flag, context.
    WHY: Enables dead-letter-queue routing and retry decisions.
    """
    node: str
    message: str
    code: Optional[str] = None
    retryable: bool
    context: Optional[Dict[str, Any]] = None


class WorkflowExecution(BaseModel):
    """Record of one n8n workflow execution.

    WHAT: id, workflow id, status, timestamps, data, optional error.
    WHY: Observable execution history for the orchestration layer.
    """
    id: str
    workflow_id: str
    status: str  # 'running' | 'success' | 'error' | 'waiting'
    started_at: datetime
    finished_at: Optional[datetime] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[WorkflowError] = None


# ---------------------------------------------------------------------------
# Settlement Rule DSL
# ---------------------------------------------------------------------------


class RuleCondition(BaseModel):
    """One condition node in the settlement rule tree.

    WHAT: Supports AND/OR/NOT composition (compound) or leaf field comparisons (field/comparator/value).
    WHY: Settlement business logic is expressed declaratively so it can change without redeploy.
    EXAMPLE:
        RuleCondition(operator="and", conditions=[
            RuleCondition(field="event.status", comparator="eq", value="ended"),
            RuleCondition(field="event.score.home", comparator="gt", value=...)
        ])
    """
    operator: Optional[str] = None  # 'and' | 'or' | 'not'
    conditions: Optional[List['RuleCondition']] = None
    field: Optional[str] = None
    comparator: Optional[str] = None  # 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'in' | 'contains'
    value: Optional[Any] = None


class SettlementRule(BaseModel):
    """One rule evaluated by the Settlement Worker n8n node.

    WHAT: condition + outcome + priority. Highest-priority matching rule wins.
    WHY: Business users change settlement rules (new sport, new void condition) without a code
        deploy — the DSL lives in JSON (embedded in the node, or DB/remote in production).
    GAP: hot-reload from DB/remote declared in the node UI but not implemented; only embedded
        JSON works. See 07_issues_found.md.
    """
    id: str
    name: str
    condition: RuleCondition
    outcome: SettlementOutcome
    priority: int
    metadata: Optional[Dict[str, Any]] = None


class SettlementRuleSet(BaseModel):
    """Versioned collection of settlement rules with a default outcome.

    WHAT: version + rules + default_outcome.
    WHY: Versioning lets rule sets be audited and rolled back; default_outcome covers
        unmatched cases (chosen "void" for safety — never pay on an unknown match).
    """
    version: str
    rules: List[SettlementRule]
    default_outcome: SettlementOutcome


# ---------------------------------------------------------------------------
# LLM Alert types
# ---------------------------------------------------------------------------


class FewShotExample(BaseModel):
    """One few-shot (input → expected output) pair used to prime the LLM prompt.

    WHAT: input data + the desired structured LLMAlertResponse output.
    WHY: Few-shot prompting steers the LLM toward the required schema and tone without
        fine-tuning.
    """
    input: Dict[str, Any]
    output: 'LLMAlertResponse'


class LLMAlertRequest(BaseModel):
    """Request sent to the LLM to generate one alert.

    WHAT: event data, anomaly type, context, few-shot examples.
    WHY: Standardizes what the alert node sends to the LLM provider.
    """
    event_data: CanonicalEvent | CanonicalOdds
    anomaly_type: AlertType
    context: Dict[str, Any]
    few_shot_examples: List[FewShotExample]


class LLMAlertResponse(BaseModel):
    """Structured LLM response for one alert.

    WHAT: title, description, severity, confidence, optional suggested action + metadata.
    WHY: Structured output lets downstream systems page/ticket/dashboard on the alert.
    EXAMPLE:
        LLMAlertResponse(title="Odds Anomaly Detected", description="...",
                         severity=AlertSeverity.WARNING, confidence=0.85,
                         suggested_action="Verify with other providers",
                         metadata={"deviation_percent": 25})
    """
    title: str
    description: str
    severity: AlertSeverity
    confidence: float = Field(ge=0, le=1)
    suggested_action: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AlertEvaluationResult(BaseModel):
    """Result of comparing an LLM alert against a rule-based baseline.

    WHAT: the alert, the LLM response, optional rule baseline, agreement flag, human-review flag.
    WHY: Measures LLM precision/recall against a deterministic baseline (shadow mode / eval).
    """
    alert: Alert
    llm_response: LLMAlertResponse
    rule_based_baseline: Optional[Alert] = None
    agreed: bool
    sent_to_human_review: bool


# ---------------------------------------------------------------------------
# Reconciliation types
# ---------------------------------------------------------------------------


class ReconciliationJob(BaseModel):
    """One reconciliation job run.

    WHAT: id, date, status, timestamps, optional report/error.
    WHY: Trackable unit of the daily drift-detection job.
    """
    id: str
    date: str
    status: str  # 'pending' | 'running' | 'completed' | 'failed'
    started_at: datetime
    completed_at: Optional[datetime] = None
    report: Optional[ReconciliationReport] = None
    error: Optional[str] = None


class ChecksumRecord(BaseModel):
    """Checksum fingerprint of one entity in one source system, used to detect drift.

    WHAT: entity type/id, checksum string, source system, last updated.
    WHY: Comparing checksums across systems is how reconciliation finds drift without
        transferring full payloads.
    """
    entity_type: str  # 'event' | 'odds' | 'settlement'
    entity_id: str
    checksum: str
    source_system: str
    last_updated: datetime


# Resolve forward references (RuleCondition references itself)
RuleCondition.model_rebuild()
