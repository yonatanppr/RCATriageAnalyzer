# Incident Auto-Triage Service (IATS) Prototype

First working v1 prototype for local demo using Docker Compose.

## What this implements
- CloudWatch Alarm ingestion (`POST /v1/alerts/cloudwatch`)
- Alertmanager ingestion (`POST /v1/alerts/alertmanager`, MVP adapter)
- Canonical `AlertEvent` normalization
- Deduplicated `Incident` upsert + async worker triage (Celery/Redis)
- Evidence collection via query-template library + CloudWatch Logs Insights adapter (fixture mode by default)
- Correlation-aware evidence retrieval (correlation/request/trace ids when present)
- Deployment/config change correlation timeline
- Evidence Pack persistence
- Pluggable LLM provider:
  - `local` (Ollama, default)
  - `openai` (remote API)
- Triage report persistence and UI rendering
- Human decision workflow (`awaiting_human_review` + approve/reject + lifecycle statuses)
- Auth + RBAC guardrails for `/v1/*`
- Audit logging, feedback loop, runtime metrics, and retention purge endpoint
- Console notification + optional Slack + ticket sink stub

## Scope (v1)
- Input source: CloudWatch alarm state change events only
- Evidence source: CloudWatch Logs Insights only
- Repo context: local keyword snippet fetcher only
- UI: incidents list + incident detail

## Project layout
- `/backend`: FastAPI app, domain logic, adapters, storage, tests
- `/worker`: Celery worker entrypoint
- `/ui`: React + Vite TypeScript UI
- `/infra/docker-compose.yml`: local stack definition
- `/fixtures`: sample alert and logs results
- `/repos/checkout-api`: local demo repo context for snippet extraction

## Prerequisites
- Docker + Docker Compose plugin

## Quick start (local LLM by default)
1. Start stack:
```bash
docker compose -f infra/docker-compose.yml up --build
```

This starts an `ollama` service and auto-pulls `LOCAL_LLM_MODEL` (default `qwen2.5:7b-instruct`).

2. Post sample CloudWatch event:
```bash
curl -sS -X POST http://localhost:8000/v1/alerts/cloudwatch \
  -H 'Authorization: Bearer dev-shared-token' \
  -H 'Content-Type: application/json' \
  --data @fixtures/cloudwatch_alarm_event.json
```

3. Open UI:
- [http://localhost:5173](http://localhost:5173)

4. Inspect API directly:
```bash
AUTH='Authorization: Bearer dev-shared-token'
curl -sS http://localhost:8000/v1/incidents -H "$AUTH" | jq
curl -sS http://localhost:8000/v1/incidents/<INCIDENT_ID> -H "$AUTH" | jq
curl -sS http://localhost:8000/v1/incidents/<INCIDENT_ID>/evidence -H "$AUTH" | jq
curl -sS http://localhost:8000/v1/incidents/<INCIDENT_ID>/report -H "$AUTH" | jq
curl -sS -X POST http://localhost:8000/v1/incidents/<INCIDENT_ID>/decision -H "$AUTH" -H 'Content-Type: application/json' --data '{"decision":"approve"}' | jq
curl -sS -X POST http://localhost:8000/v1/incidents/<INCIDENT_ID>/status -H "$AUTH" -H 'Content-Type: application/json' --data '{"status":"resolved"}' | jq
curl -sS http://localhost:8000/v1/metrics/quality -H "$AUTH" | jq
curl -sS http://localhost:8000/v1/metrics/runtime -H "$AUTH" | jq
curl -sS -X POST http://localhost:8000/v1/changes/deployments -H "$AUTH" -H 'Content-Type: application/json' --data '{"service":"checkout-api","env":"prod","deployed_at":"2026-02-07T18:00:00Z","version":"1.2.3","git_sha":"abc123"}' | jq
```

## LLM provider configuration
Set provider using `.env.example` (or `.env`):

### Option A: Local model (recommended for private data)
```env
LLM_PROVIDER=local
LOCAL_LLM_MODEL=qwen2.5:7b-instruct
OLLAMA_BASE_URL=http://ollama:11434
```

### Option B: OpenAI API
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5.3-codex
```

## LLM behavior
- LLM step is mandatory in pipeline.
- If selected provider is unavailable/misconfigured:
  - Evidence Pack is still created.
  - Incident status becomes `failed` with clear error.
  - UI report section shows fallback message (`LLM unavailable or not configured`).
- If provider is correctly configured:
  - Worker requests strict JSON report.
  - Response is validated against `TriageReportPayload` schema.
  - Incident transitions to `awaiting_human_review`.
  - Reviewer approves via decision endpoint before final `triaged`.

## Environment
Important variables:
- `DATABASE_URL`
- `REDIS_URL`
- `LLM_PROVIDER` (`local` or `openai`)
- `LOCAL_LLM_MODEL`, `OLLAMA_BASE_URL` (local mode)
- `OPENAI_API_KEY`, `OPENAI_MODEL` (openai mode)
- `AWS_REGION`
- `FIXTURE_MODE=true` (default)
- `SLACK_WEBHOOK_URL` (optional)
- `AUTH_ENABLED`, `AUTH_SHARED_TOKEN`
- `TICKET_SINK_ENABLED`
- `REPO_BASE_PATH`
- `ALLOW_RAW_STORAGE=false` (default)
- `REPO_RECENT_COMMITS_LIMIT=5`
- `CELERY_TASK_MAX_RETRIES=3`
- `CELERY_RETRY_BACKOFF_SECONDS=5`
- `CELERY_RETRY_JITTER=true`
- `DATA_RETENTION_DAYS`
- `NO_GUESS_CONFIDENCE_THRESHOLD`
- `EVIDENCE_MIN_REFS_FOR_CONFIDENT_REPORT`
- `MAX_LOGS_QUERIES_PER_INCIDENT`

## Run backend tests locally
```bash
cd backend
pip install -e .[dev]
pytest -q
```

## Extension points
### Add Prometheus Alertmanager adapter later
1. Add adapter implementing `AlertSourceAdapter` in `/backend/app/adapters/alertmanager.py`.
2. Add endpoint `POST /v1/alerts/alertmanager` that normalizes to `AlertEvent`.
3. Reuse existing ingestion service and dedup logic.

### Add Loki evidence adapter later
1. Add adapter implementing `EvidenceSourceAdapter` in `/backend/app/adapters/loki.py`.
2. Select adapter by service config in registry.
3. Keep Evidence Pack artifact shapes stable (`logs_query`, `log_summary`) so LLM + UI remain unchanged.
