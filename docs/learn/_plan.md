# Phase 0 Plan — Teaching Copy for the LSports Interview Project

**Learner:** senior QA/automation engineer turned AI Solutions Engineer (telecom/eSIM, IoT connectivity).
**Goal:** After studying this repo he can explain, defend, and extend every part of it in an FDE interview as if he built it himself.
**Branch:** `learn/annotated` (new branch, never touch `main`).
**Constraint (hard rule):** CODE MUST NOT CHANGE. Only add comments/docstrings and new files under `docs/learn/`. Bugs go in `07_issues_found.md`, never fixed.

## Repo map (actual files on disk — note: PROJECT_SPEC.md/QUICKSTART.md describe a larger idealized structure that does not fully exist)

| Area | Files (actual) | Notes |
|------|----------------|-------|
| Root docs | README.md, PROJECT_SPEC.md, GAP_ANALYSIS.md, QUICKSTART.md, architecture-diagram.svg | PROJECT_SPEC/QUICKSTART describe services/packages (processing-engine, notification-service, tests/, scripts/, n8n-workflows/, docs/architecture/ADRs, docs/runbooks, .env.example) that do NOT exist on disk. Treat them as the "planned" vision; `07_issues_found.md` records the gaps. |
| Shared types | packages/canonical-types/src/types.ts, python/sports_automation/types.py, package.json, tsconfig.json, python/pyproject.toml | Leaf module — the single source-of-truth contract (TS + Pydantic). |
| Mock providers | packages/mock-providers/src/mock/odds_feed.py, event_feed.py, pyproject.toml, Dockerfile.odds, Dockerfile.events | WebSocket + REST feed simulators (LSports stand-ins). |
| Ingestion service | packages/ingestion-service/src/ingestion/{main.py, config.py, metrics.py, idempotency/deduplicator.py, normalization/{schema_validator.py, canonical_transformer.py}, providers/{rest_poller.py, websocket_client.py}}, pyproject.toml, Dockerfile | FastAPI entry point: validate → transform → deduplicate → forward to n8n. |
| n8n custom nodes | packages/n8n-nodes/src/{index.ts, Nodes/{SportsEventRouter, OddsNormalizer, SettlementWorker, LLMAlertGenerator}.node.ts, credentials/SportsApiCredentials.credentials.ts}, package.json, tsconfig.json | 4 custom nodes + credentials; orchestration layer. |
| Infra / CI | docker-compose.yml, Makefile, .github/workflows/ci.yml | docker-compose references a `processing-engine` service and `scripts/init-db.sql` that don't exist; Makefile targets reference `tests/`, `alembic`, `scripts.seed_demo_data` that don't exist. |
| Monitoring | monitoring/prometheus/{prometheus.yml, rules/*.yml, alerts/alertmanager.yml}, monitoring/grafana/{provisioning/*, dashboards/*} | Prometheus + Grafana + Alertmanager config. |
| Business docs | docs/business/{kpi-definitions.md, process-map.md, roi-analysis.md} | KPI formulas, manual→automated process map, ROI build-vs-buy. |

## Dependency order (leaves first, entrypoint last) — annotation assignment

1. **packages/canonical-types/** — nothing imports from the repo; everyone depends on it conceptually. Annotate first.
2. **packages/mock-providers/** — standalone feed simulators; produce the raw data the ingestion service consumes.
3. **packages/ingestion-service/** — consumes providers, depends on canonical types conceptually; produces normalized events for n8n.
4. **packages/n8n-nodes/** — consumes webhooks from ingestion; the orchestration/business-logic layer.
5. **Infra/config + root docs** — docker-compose, Makefile, CI, monitoring, business docs. Annotate last (they reference the above).

## File ownership (disjoint, one annotator per group if parallelized)

- Canonical types annotator: packages/canonical-types/*
- Mock providers annotator: packages/mock-providers/*
- Ingestion annotator: packages/ingestion-service/*
- n8n-nodes annotator: packages/n8n-nodes/*
- Infra/docs annotator: docker-compose.yml, Makefile, ci.yml, monitoring/*, docs/business/*, root docs

## Docs/learn deliverables (Phase 1 → Phase 2)

| Doc | Owner | Purpose |
|-----|-------|---------|
| 00_START_HERE.md | lead (after Phase 1) | 5-sentence summary, file-by-file reading order w/ questions + times, 2-hr/day study plan, mental map, links to all other docs. |
| 01_business_context.md | business-context agent | Who the customer is, the pain, cost of inaction, success measures, client questions an FDE would hear. Mark inferences. |
| 02_architecture.md | architecture agent | Mermaid system diagram, components, data flow, main-use-case sequence, trust boundaries, state, what scales. |
| 03_glossary.md | glossary agent | Every domain term, library, pattern, acronym, config key: plain def, file:line, why it matters, one-line analogy. |
| 04_gap_bridge.md | gap-bridge agent | "Typical web app does X; this production system does Y because Z" for each non-trivial pattern. |
| 05_trace_walkthrough.md | trace agent | One real request end-to-end with real values, file:line at every hop, per-hop failure modes. |
| 06_interview_pack.md | interview agent | 25+ FDE questions with first-person model answers, 2-min & 5-min walkthroughs, 5 customer scenarios, 10 break-it drills (answer key hidden), honest weaknesses. |
| 07_issues_found.md | lead (Phase 2) | Bugs (incl. metrics.py await-outside-async), smells, UNVERIFIED items, missing tests, security concerns, production gaps. |

## Verification (Phase 3)

1. Prove code unchanged: strip comments/docstrings, compare to `main` (Python: `ast.dump`; TS: comment-stripped / compiler). Revert anything differing beyond comments.
2. Run `python3 -m py_compile` on all Python files on both branches; confirm identical results.
3. Fact-check ≥30% of annotations and every `# GAP:`/`# INTERVIEW:` against code + library docs.
4. Confirm every doc link and `file:line` reference resolves.
5. Run test suite + lint on both branches (no tests exist yet — record in 07_issues_found.md).

## Environment notes (recon findings)

- Docker installed but daemon NOT running → full `make dev-setup` stack cannot be started in this session.
- Python 3.14.4 available; Node 24.15.0 + npm available.
- `python3 -m py_compile` on all Python files found **one syntax error**: `packages/ingestion-service/src/ingestion/metrics.py:135` uses `await` inside non-async `metrics_middleware`. Recorded as a bug in 07_issues_found.md; NOT fixed.
- Pre-existing unstaged modification: `.claude-flow/mods/session.json` — not mine, will not be included in my commits.

## Acceptance criteria

- Every code file under packages/ has a file header + per-function docstrings + intent inline comments + # GAP/# BUSINESS/# INTERVIEW tags.
- docs/learn/00–07 all exist and cross-link; every file:line reference resolves.
- Verification shows code is byte-identical to `main` modulo comments/docstrings.
- Final message lists the docs/learn tree, annotated files, verification results, the 10 must-master concepts, and UNVERIFIED items.
