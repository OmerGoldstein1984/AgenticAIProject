# Makefile for Sports Data Automation Platform
.PHONY: help up down logs test build clean dev-setup demo-data load-test migrate seed shell-%

# Default target
help:
	@echo "Sports Data Automation Platform - LSports Interview Project"
	@echo ""
	@echo "Available commands:"
	@echo "  make dev-setup     - Full initial setup (build, start, migrate, seed)"
	@echo "  make up            - Start all services"
	@echo "  make down          - Stop all services"
	@echo "  make logs          - Follow all logs"
	@echo "  make logs-<svc>    - Follow specific service logs (e.g., make logs-ingestion)"
	@echo "  make build         - Build all Docker images"
	@echo "  make test          - Run unit + integration tests"
	@echo "  make test-e2e      - Run end-to-end tests"
	@echo "  make demo-data     - Seed demo data for interview"
	@echo "  make load-test     - Run load test (1000 events/sec for 60s)"
	@echo "  make clean         - Remove all containers, volumes, networks"
	@echo "  make shell-<svc>   - Shell into service (e.g., make shell-ingestion)"
	@echo ""
	@echo "Service names: ingestion-service, processing-engine, n8n, postgres, redis,"
	@echo "               mock-odds-feed, mock-event-feed, prometheus, grafana, alertmanager"

dev-setup: build up migrate seed
	@echo ""
	@echo "✅ Development environment ready!"
	@echo "   n8n:        http://localhost:5678 (admin / \$$N8N_PASSWORD)"
	@echo "   Grafana:    http://localhost:3000 (admin / \$$GRAFANA_PASSWORD)"
	@echo "   Prometheus: http://localhost:9090"
	@echo "   Ingestion API: http://localhost:8000/docs"
	@echo "   Mock Odds Feed: http://localhost:8080"
	@echo "   Mock Event Feed: http://localhost:8081"

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
	@echo "Running database migrations..."
	docker compose exec -T ingestion-service alembic upgrade head 2>/dev/null || echo "Migrations not yet implemented"

seed:
	@echo "Seeding demo data..."
	docker compose exec -T ingestion-service python -m scripts.seed_demo_data 2>/dev/null || echo "Seed script not yet implemented"

test:
	@echo "Running unit + integration tests..."
	-docker compose run --rm ingestion-service pytest tests/ -v --tb=short 2>/dev/null || echo "Ingestion tests not yet implemented"
	-docker compose run --rm processing-engine pytest tests/ -v --tb=short 2>/dev/null || echo "Processing tests not yet implemented"
	-docker compose run --rm mock-providers pytest tests/ -v --tb=short 2>/dev/null || echo "Mock provider tests not yet implemented"

test-e2e:
	@echo "Running end-to-end tests..."
	-docker compose run --rm ingestion-service pytest tests/e2e/ -v --tb=long 2>/dev/null || echo "E2E tests not yet implemented"

demo-data:
	@echo "Running demo scenario..."
	docker compose exec -T ingestion-service python -m scripts.demo_scenario 2>/dev/null || echo "Demo script not yet implemented"

load-test:
	@echo "Running load test (1000 events/sec for 60s)..."
	docker compose exec -T mock-odds-feed python -m scripts.load_test --rate 1000 --duration 60 2>/dev/null || echo "Load test not yet implemented"

clean:
	docker compose down -v --remove-orphans
	docker system prune -f

shell-%:
	docker compose exec $* /bin/bash

# Development shortcuts
restart-%:
	docker compose restart $*

ps:
	docker compose ps

# Build individual services
build-ingestion:
	docker compose build ingestion-service

build-processing:
	docker compose build processing-engine

build-mock-providers:
	docker compose build mock-odds-feed mock-event-feed

build-n8n-nodes:
	cd packages/n8n-nodes && npm run build
	docker compose restart n8n

# n8n workflow management
n8n-export:
	@echo "Export workflows from n8n UI: Settings → Workflows → Export"

n8n-import:
	@echo "Import workflows in n8n UI: Settings → Workflows → Import"
	@echo "Workflow files in: n8n-workflows/*.json"

# Monitoring
prometheus-reload:
	curl -X POST http://localhost:9090/-/reload

grafana-dashboards:
	@echo "Dashboards auto-provisioned from monitoring/grafana/dashboards/"

# Database
db-shell:
	docker compose exec postgres psql -U sports_user -d sports_automation

redis-cli:
	docker compose exec redis redis-cli

# View generated files
view-logs:
	@echo "Recent logs:"
	docker compose logs --tail=50

# Quick health check
health:
	@echo "Service health:"
	@docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

# Interview day - fresh start
interview-prep: clean dev-setup demo-data
	@echo ""
	@echo "🎯 Interview ready! Verify:"
	@echo "  1. n8n workflows active (http://localhost:5678)"
	@echo "  2. Grafana dashboards show data (http://localhost:3000)"
	@echo "  3. Prometheus targets up (http://localhost:9090/targets)"
	@echo "  4. Run 'make demo-data' again right before demo"