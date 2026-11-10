# Threat Model

STRIDE-based threat model for the Sports Data Automation Platform. Each threat
lists the affected component, the impact, and the mitigation(s) implemented or
recommended.

## Scope

In scope: ingestion service (FastAPI), processing engine, n8n orchestration,
mock providers, notification service, Redis, Postgres/TimescaleDB, Prometheus,
Grafana, Alertmanager. Out of scope: end-user browsers, provider networks, the
Anthropic/OpenAI LLM APIs.

## Threat model (STRIDE)

| ID | Category | Threat | Asset | Impact | Mitigation | Status |
|----|----------|--------|-------|--------|------------|--------|
| T1 | Spoofing | Attacker calls `/ingest/*` without a valid API key, impersonating a provider | Ingestion service | Unauthorized data injection; false settlements | API-key auth (`X-API-Key`) on all `/ingest/*` and `/dlq/*`; failures audited | Implemented |
| T2 | Tampering | Attacker modifies a payload in transit to change odds/settlement | Ingestion → n8n | Incorrect settlement/payouts | TLS in production; schema validation rejects malformed payloads; trace IDs for correlation | Partial (TLS ops-side) |
| T3 | Repudiation | A trader denies submitting/settling a bet; no audit trail | Ingestion, n8n | Disputes, regulatory exposure | Every `/ingest/*` call logged with client + trace ID; security audit log; n8n DLQ/audit | Implemented |
| T4 | Information disclosure | Logs or error bodies leak API keys, DB passwords, or provider payloads | All services | Credential theft, data leak | Secret redaction (`redact()`); masked credential headers (`mask_headers`); generic 500 errors (no stack traces to client) | Implemented |
| T5 | Denial of service | Attacker floods `/ingest/*` or posts oversized bodies to exhaust Redis/n8n | Ingestion service | Service unavailability for legitimate traders | Token-bucket rate limiting (per client/IP); `MAX_REQUEST_BODY_SIZE` (413); Redis maxmemory policy | Implemented |
| T6 | Elevation of privilege | Anonymous caller reaches admin/n8n or bypasses auth | n8n, ingestion | Unauthorized workflow execution | n8n basic auth; CORS restricted origins; `/health`/`/metrics` read-only and unauthenticated by design | Implemented |
| T7 | Dependency vulnerability | Known-vulnerable Python/Node package exploited | All services | Remote code execution / data breach | CI `pip-audit` + `npm audit --audit-level=high` gate; `bandit` SAST gate | Implemented (CI) |
| T8 | Insecure defaults | Dev secrets (`changeme`, `admin`) reach production | Postgres, n8n, Grafana | Well-known credentials | Startup validator rejects `changeme` in `postgres_dsn` when `DEBUG=0`; docs flag all defaults | Implemented |
| T9 | Injection | Malformed JSON/fields reach schema validator or downstream | Ingestion service | Parser crashes, bad data | JSON Schema validation before transform; type coercion via Pydantic | Implemented |

## Assumptions

- The ingestion service sits behind a TLS-terminating ingress/load balancer in
  production (HSTS is opt-in for this reason).
- n8n is not exposed to the public internet; it is reached by the ingestion
  service over the internal Docker network.
- API keys are long-lived for this demo; production should rotate them and store
  hashes (not plaintext) in a secret manager.
- Each uvicorn worker keeps its own in-memory token buckets; multi-node
  deployments need a shared backend (Redis) for the rate limiter.

## Residual risks

- API keys are compared in plaintext in memory; key hashing is deferred to a
  secret-manager integration.
- Rate limiting is per-process; a distributed attacker can bypass per-workner
  limits until a shared bucket backend is added.
- Body-size guard reads `Content-Length` only (fast pre-flight); a reverse
  proxy/WAF should enforce the same limit at the edge.

## Review cadence

Revisit this threat model on every major release, after any security incident,
and before exposing the ingestion service or n8n to public networks.
