# Quick Start: LSports Interview Project

## Prerequisites
- Docker Desktop (with Compose v2)
- Node.js 20+ (for n8n custom nodes)
- Python 3.11+ (for services)
- Make (or use the commands directly in PowerShell)
- Claude Code with recommended skills installed

---

## 1. Install Recommended Claude Skills

Run these in your project directory:

```bash
cd C:\projects\Agentic ai\LSports_Interview_Project

# Essential skills
claude skill install code-review
claude skill install simplify
claude skill install artifact-design
claude skill install artifact-diagramming

# High value
claude skill install run
claude skill install dataviz

# Optional but useful
claude skill install claude-api
claude skill install fewer-permission-prompts
```

**Verify installation:**
```bash
claude skill list
```

---

## 2. Initialize Project Structure

```bash
# Create the full directory structure
mkdir -p sports-data-automation/{docs/architecture,docs/runbooks,docs/business,docs/api,packages/{canonical-types,n8n-nodes,ingestion-service,processing-engine,mock-providers,notification-service},n8n-workflows,monitoring/{prometheus/{rules,alerts},grafana/{dashboards,provisioning}},scripts,tests/{contract,integration,e2e}}

cd sports-data-automation
```

---

## 3. Create Docker Compose Stack (Phase 1 Foundation)

```yaml
# docker-compose.yml
version: '3.8'

services:
  # Core infrastructure
  postgres:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: sports_automation
      POSTGRES_USER: sports_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db.sql:/docker-entrypoint-initdb.d/init-db.sql
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sports_user -d sports_automation"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  # n8n Orchestration
  n8n:
    image: n8nio/n8n:latest
    environment:
      N8N_HOST: 0.0.0.0
      N8N_PORT: 5678
      N8N_PROTOCOL: http
      NODE_ENV: development
      DB_TYPE: postgresdb
      DB_POSTGRESDB_HOST: postgres
      DB_POSTGRESDB_PORT: 5432
      DB_POSTGRESDB_DATABASE: sports_automation
      DB_POSTGRESDB_USER: sports_user
      DB_POSTGRESDB_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
      N8N_BASIC_AUTH_ACTIVE: "true"
      N8N_BASIC_AUTH_USER: admin
      N8N_BASIC_AUTH_PASSWORD: ${N8N_PASSWORD:-changeme}
      N8N_CUSTOM_EXTENSIONS: /home/node/.n8n/custom
      EXECUTIONS_MODE: queue
      QUEUE_BULL_REDIS_HOST: redis
      QUEUE_BULL_REDIS_PORT: 6379
      QUEUE_BULL_REDIS_DB: 1
    volumes:
      - n8n_data:/home/node/.n8n
      - ./packages/n8n-nodes/dist:/home/node/.n8n/custom
    ports:
      - "5678:5678"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:5678/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Ingestion Service (Python FastAPI)
  ingestion-service:
    build:
      context: ./packages/ingestion-service
      dockerfile: Dockerfile
    environment:
      REDIS_URL: redis://redis:6379/0
      POSTGRES_DSN: postgresql://sports_user:${POSTGRES_PASSWORD:-changeme}@postgres:5432/sports_automation
      N8N_WEBHOOK_URL: http://n8n:5678/webhook
      LOG_LEVEL: DEBUG
    ports:
      - "8000:8000"
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    volumes:
      - ./packages/ingestion-service:/app/src
    command: uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

  # Processing Engine (Python)
  processing-engine:
    build:
      context: ./packages/processing-engine
      dockerfile: Dockerfile
    environment:
      REDIS_URL: redis://redis:6379/0
      POSTGRES_DSN: postgresql://sports_user:${POSTGRES_PASSWORD:-changeme}@postgres:5432/sports_automation
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      LOG_LEVEL: DEBUG
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    volumes:
      - ./packages/processing-engine:/app/src

  # Mock Providers
  mock-odds-feed:
    build:
      context: ./packages/mock-providers
      dockerfile: Dockerfile.odds
    environment:
      REDIS_URL: redis://redis:6379/0
      FEED_INTERVAL_MS: 500
    ports:
      - "8080:8080"
    depends_on:
      redis:
        condition: service_healthy

  mock-event-feed:
    build:
      context: ./packages/mock-providers
      dockerfile: Dockerfile.events
    environment:
      REDIS_URL: redis://redis:6379/0
    ports:
      - "8081:8081"
    depends_on:
      redis:
        condition: service_healthy

  # Monitoring
  prometheus:
    image: prom/prometheus:latest
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--web.enable-lifecycle'
    volumes:
      - ./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./monitoring/prometheus/rules:/etc/prometheus/rules
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    depends_on:
      - ingestion-service
      - processing-engine
      - n8n

  alertmanager:
    image: prom/alertmanager:latest
    volumes:
      - ./monitoring/prometheus/alerts/alertmanager.yml:/etc/alertmanager/alertmanager.yml
    ports:
      - "9093:9093"
    depends_on:
      - prometheus

  grafana:
    image: grafana/grafana:latest
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_INSTALL_PLUGINS: grafana-piechart-panel
    volumes:
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning
      - ./monitoring/grafana/dashboards:/var/lib/grafana/dashboards
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    depends_on:
      - prometheus

volumes:
  postgres_data:
  redis_data:
  n8n_data:
  prometheus_data:
  grafana_data:

networks:
  default:
    name: sports-automation-network
```

---

## 4. Create Makefile for Common Commands

```makefile
# Makefile
.PHONY: help up down logs test build clean dev-setup demo-data load-test

help:
	@echo "Available commands:"
	@echo "  make dev-setup    - Full initial setup (build, start, migrate, seed)"
	@echo "  make up           - Start all services"
	@echo "  make down         - Stop all services"
	@echo "  make logs         - Follow all logs"
	@echo "  make logs-<svc>   - Follow specific service logs (e.g., make logs-ingestion)"
	@echo "  make build        - Build all Docker images"
	@echo "  make test         - Run unit + integration tests"
	@echo "  make test-e2e     - Run end-to-end tests"
	@echo "  make demo-data    - Seed demo data for interview"
	@echo "  make load-test    - Run load test (1000 events/sec for 60s)"
	@echo "  make clean        - Remove all containers, volumes, networks"
	@echo "  make shell-<svc>  - Shell into service (e.g., make shell-ingestion)"

dev-setup: build up migrate seed
	@echo "✅ Development environment ready!"
	@echo "   n8n:        http://localhost:5678 (admin/changeme)"
	@echo "   Grafana:    http://localhost:3000 (admin/admin)"
	@echo "   Prometheus: http://localhost:9090"
	@echo "   Ingestion API: http://localhost:8000/docs"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

logs-%:
	docker compose logs -f --tail=100 $*

build:
	docker compose build --parallel

migrate:
	docker compose exec -T ingestion-service alembic upgrade head

seed:
	docker compose exec -T ingestion-service python -m scripts.seed_demo_data

test:
	docker compose run --rm ingestion-service pytest tests/ -v --tb=short
	docker compose run --rm processing-engine pytest tests/ -v --tb=short
	docker compose run --rm mock-providers pytest tests/ -v --tb=short

test-e2e:
	docker compose run --rm ingestion-service pytest tests/e2e/ -v --tb=long

demo-data:
	docker compose exec -T ingestion-service python -m scripts.demo_scenario

load-test:
	docker compose exec -T mock-odds-feed python -m scripts.load_test --rate 1000 --duration 60

clean:
	docker compose down -v --remove-orphans
	docker system prune -f

shell-%:
	docker compose exec $* /bin/bash
```

---

## 5. Create Canonical Types (Shared Between TypeScript & Python)

```bash
# packages/canonical-types/package.json
{
  "name": "@sports-automation/canonical-types",
  "version": "1.0.0",
  "description": "Shared TypeScript types for sports data automation",
  "main": "dist/index.js",
  "types": "dist/index.d.ts",
  "scripts": {
    "build": "tsc",
    "dev": "tsc --watch",
    "test": "jest"
  },
  "devDependencies": {
    "typescript": "^5.3.0",
    "jest": "^29.7.0",
    "@types/jest": "^29.5.0"
  }
}
```

```typescript
// packages/canonical-types/src/types.ts
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
```

```python
# packages/canonical-types/python/types.py
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
```

---

## 6. Initialize n8n Custom Nodes Project

```bash
cd packages/n8n-nodes
npm init -y
```

```json
// packages/n8n-nodes/package.json
{
  "name": "@sports-automation/n8n-nodes",
  "version": "1.0.0",
  "description": "Custom n8n nodes for sports data automation",
  "main": "dist/index.js",
  "types": "dist/index.d.ts",
  "scripts": {
    "build": "tsc && npm run copy-assets",
    "copy-assets": "copyfiles -u 1 \"src/**/*.png\" \"src/**/*.svg\" dist/",
    "dev": "tsc --watch",
    "test": "jest",
    "lint": "eslint src --ext .ts"
  },
  "n8n": {
    "nodes": [
      "dist/nodes/SportsEventRouter/SportsEventRouter.node.js",
      "dist/nodes/OddsNormalizer/OddsNormalizer.node.js",
      "dist/nodes/SettlementWorker/SettlementWorker.node.js",
      "dist/nodes/LLMAlertGenerator/LLMAlertGenerator.node.js"
    ],
    "credentials": [
      "dist/credentials/SportsApiCredentials.credentials.js"
    ]
  },
  "dependencies": {
    "n8n-workflow": "^1.0.0",
    "n8n-core": "^1.0.0"
  },
  "devDependencies": {
    "typescript": "^5.3.0",
    "jest": "^29.7.0",
    "@types/jest": "^29.5.0",
    "@types/node": "^20.10.0",
    "eslint": "^8.55.0",
    "@typescript-eslint/eslint-plugin": "^6.13.0",
    "@typescript-eslint/parser": "^6.13.0",
    "copyfiles": "^2.4.1"
  }
}
```

```json
// packages/n8n-nodes/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "lib": ["ES2022"],
    "outDir": "./dist",
    "rootDir": "./src",
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "moduleResolution": "node"
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist", "**/*.test.ts"]
}
```

---

## 7. Create GitHub Actions CI/CD

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: packages/n8n-nodes/package-lock.json

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
          cache-dependency-path: |
            packages/ingestion-service/pyproject.toml
            packages/processing-engine/pyproject.toml
            packages/mock-providers/pyproject.toml

      - name: Install n8n-nodes deps
        run: cd packages/n8n-nodes && npm ci

      - name: Lint n8n-nodes
        run: cd packages/n8n-nodes && npm run lint

      - name: Test n8n-nodes
        run: cd packages/n8n-nodes && npm test

      - name: Build n8n-nodes
        run: cd packages/n8n-nodes && npm run build

      - name: Install Python deps (ingestion)
        run: |
          cd packages/ingestion-service
          pip install -e ".[dev]"

      - name: Test ingestion-service
        run: |
          cd packages/ingestion-service
          pytest tests/ -v --tb=short --cov=src --cov-report=xml

      - name: Install Python deps (processing)
        run: |
          cd packages/processing-engine
          pip install -e ".[dev]"

      - name: Test processing-engine
        run: |
          cd packages/processing-engine
          pytest tests/ -v --tb=short --cov=src --cov-report=xml

      - name: Install Python deps (mock-providers)
        run: |
          cd packages/mock-providers
          pip install -e ".[dev]"

      - name: Test mock-providers
        run: |
          cd packages/mock-providers
          pytest tests/ -v --tb=short

  type-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Type check canonical-types
        run: |
          cd packages/canonical-types
          npm ci
          npm run build
      - name: Type check n8n-nodes
        run: |
          cd packages/n8n-nodes
          npm ci
          npx tsc --noEmit

  docker-build:
    runs-on: ubuntu-latest
    needs: [lint-and-test, type-check]
    steps:
      - uses: actions/checkout@v4
      - name: Build all Docker images
        run: |
          docker compose build --parallel
      - name: Test Docker images start
        run: |
          docker compose up -d
          sleep 30
          docker compose ps
          docker compose down
```

---

## 8. Environment File Template

```bash
# .env.example (copy to .env and fill in)
POSTGRES_PASSWORD=your_secure_password
N8N_PASSWORD=your_n8n_password
GRAFANA_PASSWORD=your_grafana_password
ANTHROPIC_API_KEY=sk-ant-your-key
OPENAI_API_KEY=sk-your-key
```

---

## 9. First Run Checklist

```bash
# 1. Copy environment template
cp .env.example .env
# Edit .env with your values

# 2. Run dev setup
make dev-setup

# 3. Verify services
make logs

# 4. Open n8n and import workflows
#    http://localhost:5678 → Import from n8n-workflows/*.json

# 5. Open Grafana
#    http://localhost:3000 → Dashboards should auto-provision

# 6. Run demo
make demo-data
```

---

## 10. Development Workflow

### Adding a New n8n Custom Node
```bash
cd packages/n8n-nodes
# 1. Create node structure
mkdir -p src/nodes/MyNewNode
# 2. Write node (MyNewNode.node.ts, MyNewNode.node.png)
# 3. Register in src/nodes/index.ts
# 4. Build and test
npm run build
npm test
# 5. Restart n8n to pick up changes
docker compose restart n8n
```

### Adding a Python Service Endpoint
```bash
cd packages/ingestion-service
# 1. Add route in src/main.py or new module
# 2. Add tests in tests/
# 3. Run tests
pytest tests/ -v
# 4. Rebuild image
docker compose build ingestion-service
docker compose up -d ingestion-service
```

---

## Interview Day Commands

```bash
# Morning of interview - fresh start
make clean
make dev-setup

# 5 min before demo - verify everything
make demo-data
# Check Grafana dashboards have data
# Check n8n workflows are active

# During interview - if something breaks
make logs-ingestion    # Check ingestion service
make logs-n8n          # Check n8n
docker compose restart <service>  # Quick restart
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| n8n can't connect to postgres | Check `POSTGRES_PASSWORD` matches in .env; wait for healthcheck |
| Custom nodes not appearing | `docker compose restart n8n` after `npm run build` |
| Python imports fail | Ensure `pip install -e .` ran in service directory |
| Prometheus targets down | Check service names match docker-compose service names |
| Grafana dashboards empty | Verify provisioning YAML paths; check Prometheus datasource |

---

## Next: Build Phase 1 Components

1. **Database initialization script** (`scripts/init-db.sql`)
2. **Canonical types** (done above)
3. **n8n-nodes project** (done above)
4. **Dockerfiles** for each service
5. **Prometheus config** with custom metrics
6. **Grafana provisioning** for auto-dashboards

Then move to Phase 2: Ingestion & Normalization.

Good luck! 🚀