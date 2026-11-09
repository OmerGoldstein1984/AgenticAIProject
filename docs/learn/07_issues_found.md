# 07_issues_found.md

# Issues Found — Bugs, Smells, UNVERIFIED Items, Missing Tests, Security Concerns

**Audience:** the learner (and the interviewer). **Rule followed:** per the hard rules, none of
these were fixed in the code — they are only documented here. This is intentional: the learner
must be able to *find* and *discuss* them, not have them silently patched.

---

## A. Confirmed bugs (do not fix — discuss)

### A1. metrics.py: `await` outside an async function — breaks the whole ingestion service
**File:** `packages/ingestion-service/src/ingestion/metrics.py` (~line 171 after annotation)

**What's wrong:** `metrics_middleware(request, call_next)` is declared `def` (not `async def`) but
uses `await call_next(request)`. Python raises `SyntaxError: 'await' outside async function` at
import time.

**Consequence:** `main.py` does `from ingestion.metrics import setup_metrics, metrics_middleware`,
so importing `metrics.py` fails → the entire ingestion service cannot start. Observability is
broken until this is fixed.

**Correct fix (documented, not applied):** change `def metrics_middleware` to
`async def metrics_middleware`.

**Status:** UNVERIFIED fix — the stack could not be run (no Docker daemon) to confirm the import
chain, but `python3 -m py_compile` reproduces the SyntaxError.

### A2. (None other confirmed as runtime crashes)
All other Python files compile cleanly with `python3 -m py_compile`. The TypeScript files could
not be compiled (no `node_modules` / `n8n-workflow` package available offline).

---

## B. Code smells & dead code

| # | Smell | File(s) | Why it matters |
|---|-------|---------|----------------|
| B1 | `SlidingWindowDeduplicator` and `BloomFilterDeduplicator` defined but never wired | `deduplicator.py` | Dead code — implies sophistication that isn't actually used; `main.py` hard-codes `Deduplicator` |
| B2 | `tenacity` imported but unused; retry/backoff hand-rolled | `rest_poller.py`, `websocket_client.py` | Misleading dependency; retry policy not declarative or configurable |
| B3 | Dedup key construction duplicated across `process_odds`/`process_event`/`process_settlement` | `main.py` | If the key format changes, three places must be edited; easy to diverge |
| B4 | `provider_latency_ms` in `IngestionMetrics` typed but never populated | `metrics.py`, `canonical_transformer.py` | Metric exists but is never recorded — dashboard would show nothing |
| B5 | `WorkflowError`/`WorkflowExecution` types defined but no workflow persistence | `types.ts`/`types.py` | Types for a feature (workflow execution tracking) that isn't implemented |
| B6 | n8n `dist/` mounted into container but never built in repo | `docker-compose.yml`, `packages/n8n-nodes/package.json` | `docker compose up` will fail because `./packages/n8n-nodes/dist` doesn't exist |

---

## C. UNVERIFIED items (could not run; confirm before interview)

The Docker daemon was not running in this session, so the full stack (`make dev-setup`) and the
end-to-end trace in `05_trace_walkthrough.md` are **static traces grounded in file:line**, not
executed runs. Confirm the following before presenting them as fact:

| # | Item | How to verify |
|---|------|---------------|
| C1 | Full stack starts with `make dev-setup` | Run `docker compose up -d` and `docker compose ps` |
| C2 | Ingestion service imports & serves /health | `curl http://localhost:8000/health` |
| C3 | Odds flow end-to-end: mock feed → ingestion → n8n | `POST /ingest/odds` with sample JSON; check n8n UI |
| C4 | Dedup works (same odds → duplicate) | POST same JSON twice; expect `{"status":"duplicate"}` |
| C5 | Grafana dashboards auto-provision & show data | Open http://localhost:3000 |
| C6 | Prometheus targets all UP | http://localhost:9090/targets |
| C7 | TypeScript n8n nodes compile (`tsc --noEmit`) | `cd packages/n8n-nodes && npx tsc --noEmit` (needs node_modules) |
| C8 | Python services import without the metrics.py bug | `python3 -c "from ingestion.main import app"` (after fixing A1) |

---

## D. Missing tests & test gaps

| # | Gap | File(s) referenced | 
|---|-----|-------------------|
| D1 | No `tests/` directory exists anywhere | `Makefile:test` (references `tests/`, `tests/e2e/`), `ci.yml` lint-and-test job |
| D2 | No contract tests for TS↔Python type sync | `types.ts` / `types.py` |
| D3 | No unit tests for `canonical_transformer`, `deduplicator`, `SchemaValidator` | ingestion-service modules |
| D4 | No tests for n8n custom nodes | `packages/n8n-nodes` (jest configured but no tests) |
| D5 | No e2e / business-scenario tests | `ci.yml` `test-e2e` job references `tests/e2e/` |

---

## E. Security concerns

| # | Concern | File(s) | Risk |
|---|---------|---------|------|
| E1 | CORS `allow_origins=["*"]` | `main.py` | Any origin can call the ingestion API |
| E2 | Dev default passwords (`changeme`/`admin`) | `docker-compose.yml` | Credentials committed; would reach prod if `.env` missing |
| E3 | `pip install -e ".[dev]"` in Docker image | `packages/ingestion-service/Dockerfile` | Dev tools (pytest, mypy, ruff) ship to prod — image bloat + attack surface |
| E4 | No secrets manager; API keys via env vars | `config.py`, `SportsApiCredentials` | Env vars can leak via logs/process listing |
| E5 | No auth on ingestion `/ingest/*` endpoints | `main.py` | Anyone who can reach :8000 can inject events/odds/settlements |
| E6 | LLM API key read from node config/env | `LLMAlertGenerator.node.ts` | Key could be exposed in n8n UI exports |

---

## F. Gaps between the documented vision (PROJECT_SPEC / QUICKSTART) and the actual repo

The spec and quickstart describe a larger system than what's on disk. These are **planned, not
built**:

| # | Missing piece | Referenced in | 
|---|---------------|---------------|
| F1 | `packages/processing-engine/` (settlement, alerts, reconciliation Python service) | `docker-compose.yml`, `ci.yml`, `PROJECT_SPEC`, `Makefile` |
| F2 | `packages/notification-service/` | `PROJECT_SPEC`, `QUICKSTART` |
| F3 | `tests/` (contract/integration/e2e) | `ci.yml`, `Makefile`, `PROJECT_SPEC` |
| F4 | `scripts/` (`init-db.sql`, `seed_demo_data`, `demo_scenario`, `load_test`) | `docker-compose.yml`, `Makefile`, `QUICKSTART` |
| F5 | `n8n-workflows/*.json` (exported workflows) | `Makefile`, `QUICKSTART` |
| F6 | `docs/architecture/` ADRs (001/002/003) | `PROJECT_SPEC` |
| F7 | `docs/runbooks/` | `PROJECT_SPEC`, `alertmanager.yml` (runbook_url links) |
| F8 | `docs/api/openapi.yaml` | `PROJECT_SPEC` |
| F9 | `.env.example` | `QUICKSTART` |
| F10 | Real Anthropic/OpenAI SDK calls in LLMAlertGenerator | `LLMAlertGenerator.node.ts:callLLM` (commented out, simulated) |

---

## G. What a production version would need (honest talk track)

1. Fix metrics.py syntax error (A1) — observability is currently broken.
2. Ship the missing `tests/` suite (unit + contract + integration + e2e).
3. Dead-letter queue + retry on `forward_to_n8n` so n8n outages don't lose data.
4. Real LLM SDK calls (Anthropic/OpenAI) instead of simulated responses.
5. Provider registry / hot-reload so adding a provider is config, not code.
6. Automated TS↔Python contract sync test.
7. Tighten CORS, remove dev passwords from compose, split runtime/dev Docker images.
8. Add auth to `/ingest/*` endpoints.
9. Implement reconciliation package (checksum/drift/auto-correct) referenced in PROJECT_SPEC.
10. Add distributed tracing (trace IDs across ingestion → n8n → outputs).
11. Reconcile the docker-compose references (`processing-engine`, `init-db.sql`) with reality.

**Interview line:** "I know exactly where this is rough, and I've documented every gap — that's
the difference between a demo that breaks under questions and a system you can defend."
