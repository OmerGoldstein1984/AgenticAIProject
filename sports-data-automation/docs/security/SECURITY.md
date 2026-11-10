# Security Policy

Sports Data Automation Platform — security architecture, controls, and disclosure
terms for the LSports interview project.

## Supported versions

| Version | Status | Notes |
|---------|--------|-------|
| main (current) | ✅ Supported | Receives security patches |
| develop | ✅ Supported | Pre-release, tested in CI |
| All other branches | ❌ Unsupported | Feature branches; not patched |

## Reporting a security vulnerability

If you discover a security issue, please do **not** open a public GitHub issue.
Instead, contact the maintainer directly (see the project README) with:

- A description of the vulnerability and its impact
- Steps to reproduce (endpoints, headers, payloads)
- The affected component and version
- Suggested remediation, if you have one

All reports are acknowledged within 5 business days. Public disclosure is
coordinated with the reporter before any fix is released.

## Security architecture

The platform follows defense-in-depth across four layers:

| Layer | Controls |
|-------|----------|
| **Transport** | TLS/HTTPS in production (HSTS optional, enabled behind HTTPS); n8n basic auth |
| **Ingress (FastAPI)** | API-key auth on `/ingest/*` and `/dlq/*`, CORS with restricted origins, request body size limit (1 MiB default), per-client rate limiting (token bucket), security response headers |
| **Validation** | JSON Schema validation at the system boundary, idempotency/dedup keys (replay protection), trace ID propagation for audit correlation |
| **Operations** | Dead-letter queue with retry, structured security audit logging, CI dependency + SAST scanning |

### Controls implemented in this branch (`feature/security-components`)

| Control | File | What it does |
|---------|------|--------------|
| Token-bucket rate limiting | `packages/ingestion-service/src/ingestion/security/rate_limiter.py` | Per-client (API key or IP) request ceiling on write endpoints; 429 + `Retry-After` |
| Request body size guard | `rate_limiter.py` (`rate_limit_middleware`) | Rejects `Content-Length` > `MAX_REQUEST_BODY_SIZE` with 413 |
| Security response headers | `packages/ingestion-service/src/ingestion/security/headers.py` | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `X-XSS-Protection`, CSP, optional HSTS |
| Security audit logging | `packages/ingestion-service/src/ingestion/security/audit.py` | Structured `security.event` log lines for auth failures, rate-limit hits, rejections, protected access |
| Secret redaction | `packages/ingestion-service/src/ingestion/security/secrets.py` | `redact()` masks secrets in logs; `contains_dev_default()` detects placeholder secrets; `mask_headers()` hides credential headers |
| Dev-default secret validation | `packages/ingestion-service/src/ingestion/config.py` | Startup fails fast if `postgres_dsn` still contains `changeme` in non-dev |
| API-key auth failures audited | `packages/ingestion-service/src/ingestion/main.py` | `verify_api_key` logs failures before returning 401 |
| CI dependency scanning | `.github/workflows/security.yml` | `pip-audit` on Python packages; `npm audit --audit-level=high` on n8n-nodes |
| CI SAST scanning | `.github/workflows/security.yml` | `bandit` on Python source (fails on any issue) |

### Required environment variables

| Variable | Purpose | Default | Production requirement |
|----------|---------|---------|------------------------|
| `INGESTION_API_KEY` | API key for `/ingest/*` | `""` (fail-open) | **Must be set** |
| `POSTGRES_DSN` | PostgreSQL connection string | `...changeme...` | Must not contain `changeme` |
| `POSTGRES_PASSWORD` | Postgres password (compose) | `changeme` | Must be changed |
| `N8N_PASSWORD` | n8n basic auth password | `changeme` | Must be changed |
| `GRAFANA_PASSWORD` | Grafana admin password | `admin` | Must be changed |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | LLM provider keys | unset | Required for alert engine |
| `RATE_LIMIT_ENABLED` | Rate limiter on/off | `true` | Keep `true` |
| `MAX_REQUEST_BODY_SIZE` | Max request body (bytes) | `1048576` | Tune to expected payloads |
| `SECURITY_HEADERS_ENABLED` | Security headers on/off | `true` | Keep `true` |
| `HSTS_ENABLED` | Strict-Transport-Security | `false` | Enable only behind HTTPS |

Never commit real values to `.env`, `.env.local`, or version control. `.env.example` is the
only committed template; real secrets live in the environment or a secret manager.

### Security headers (applied to every response)

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-XSS-Protection: 1; mode=block`
- `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; object-src 'none';`
- `Strict-Transport-Security` — only when `HSTS_ENABLED=true` (HTTPS production)

## Local development

```bash
# Copy the template (never commit real values)
cp .env.example .env
# Edit .env: set INGESTION_API_KEY, POSTGRES_PASSWORD, N8N_PASSWORD, GRAFANA_PASSWORD

# Run security scans locally (mirrors CI)
pip install pip-audit bandit
pip-audit --exit-code -r packages/ingestion-service/...   # or pip-audit on each package
bandit -r packages/ingestion-service/src
bandit -r packages/processing-engine/src

# Run tests
pytest tests/
```

## Security testing

Tests for the security controls live in `tests/`:

- `tests/test_rate_limiter.py` — token bucket + per-client rate limiting
- `tests/test_security_headers.py` — response security headers
- `tests/test_security_request.py` — rate limit / body size / auth audit integration
- `tests/test_secrets.py` — secret redaction + dev-default detection

Run the full suite: `pytest tests/`.

## Threat model

See [`threat-model.md`](threat-model.md) for the STRIDE-based threat model and
mitigations.

## Disclaimer

Built for interview demonstration. Controls here demonstrate production-grade
security design patterns; adjust limits, algorithms, and key management to your
deployment's threat profile before production use.
