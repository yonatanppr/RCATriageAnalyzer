# Incident Auto-Triage Service (IATS) Prototype

Local demo prototype that ingests alerts, builds evidence packs, and generates evidence-cited triage reports.

## Current functionality
- Alert ingestion:
  - `POST /v1/alerts/cloudwatch`
  - `POST /v1/alerts/alertmanager`
- Canonical alert normalization and incident dedup/upsert.
- Async triage pipeline via Celery + Redis.
- Evidence collection:
  - CloudWatch Logs Insights query library (fixture mode by default).
  - Correlation-id-aware retrieval.
  - Deployment/config change correlation in timeline artifacts.
- Triage report generation:
  - Local Ollama (`LLM_PROVIDER=local`) with ordered endpoint failover.
  - OpenAI provider (`LLM_PROVIDER=openai`).
  - No-guess fallback mode when evidence is weak.
- Persistence in Postgres:
  - incidents, evidence packs, reports, review decisions, feedback, audit logs, pipeline runs.
- Human review + lifecycle workflow:
  - approve/reject report
  - incident status transitions (`triaged` -> `mitigated` -> `resolved` / `postmortem_required`)
- Auth + RBAC on `/v1/*`.
- Runtime and quality metrics endpoints.
- React UI for incidents, evidence, citations, decisions, and feedback.

## Architecture
- `backend`: FastAPI API + orchestration.
- `worker`: Celery worker for background triage jobs.
- `redis`: Celery broker/result backend.
- `postgres`: persistence.
- `ui`: React + Vite.
- `ollama` (optional but included in compose): local model server.

## Project layout
- `/backend`: API, domain, adapters, storage, tests.
- `/worker`: worker entrypoint image.
- `/ui`: frontend app.
- `/infra/docker-compose.yml`: local stack.
- `/fixtures`: demo fixtures.
- `/repos/checkout-api`: local repo context for snippet lookup.

## Prerequisites
- Docker Desktop + Docker Compose plugin.

## Quick start
1. Start stack:
```bash
docker compose -f infra/docker-compose.yml up --build
```

2. Ingest sample CloudWatch alert:
```bash
curl -sS -X POST http://localhost:8000/v1/alerts/cloudwatch \
  -H 'Authorization: Bearer dev-shared-token' \
  -H 'Content-Type: application/json' \
  --data @fixtures/cloudwatch_alarm_event.json
```

Post multiple CloudWatch fixtures in one run:
```bash
for file in fixtures/cloudwatch_alarm_event*.json; do
  echo "Posting $file"
  curl -sS -X POST http://localhost:8000/v1/alerts/cloudwatch \
    -H 'Authorization: Bearer dev-shared-token' \
    -H 'Content-Type: application/json' \
    --data @"$file" | jq
done
```

3. Open UI:
- [http://localhost:5173](http://localhost:5173)

## Local Ollama fallback behavior
When `LLM_PROVIDER=local`, the backend/worker use `OLLAMA_ENDPOINTS` in order:
- Default: `http://host.docker.internal:11434,http://ollama:11434`
- First healthy endpoint wins and is cached.
- If generation fails mid-call, it retries once on the next healthy endpoint.
- If all endpoints fail, incident moves to `failed` with a clear error.

Compose includes managed fallback:
- `ollama` service for containerized local inference.
- `ollama-init` ensures `LOCAL_LLM_MODEL` is present (`ollama pull` when missing).
- `ollama` uses Docker named volume `ollama-data` (cross-platform).

## API quick checks
```bash
AUTH='Authorization: Bearer dev-shared-token'
INCIDENT_ID='<INCIDENT_ID>'

curl -sS http://localhost:8000/v1/incidents -H "$AUTH" | jq
curl -sS http://localhost:8000/v1/incidents/$INCIDENT_ID -H "$AUTH" | jq
curl -sS http://localhost:8000/v1/incidents/$INCIDENT_ID/evidence -H "$AUTH" | jq
curl -sS http://localhost:8000/v1/incidents/$INCIDENT_ID/report -H "$AUTH" | jq

curl -sS -X POST http://localhost:8000/v1/incidents/$INCIDENT_ID/decision \
  -H "$AUTH" -H 'Content-Type: application/json' --data '{"decision":"approve"}' | jq

curl -sS -X POST http://localhost:8000/v1/incidents/$INCIDENT_ID/status \
  -H "$AUTH" -H 'Content-Type: application/json' --data '{"status":"resolved"}' | jq

curl -sS http://localhost:8000/v1/metrics/quality -H "$AUTH" | jq
curl -sS http://localhost:8000/v1/metrics/runtime -H "$AUTH" | jq
curl -sS http://localhost:8000/v1/metrics/runtime -H "$AUTH" \
  | jq '.recent_runs[0]?.metrics // {} | {llm_endpoint_used, endpoint_failover_count, llm_provider}'
```

## Configuration
Set values via `.env` (see `.env.example`).

### Core
- `DATABASE_URL`
- `REDIS_URL`
- `AUTH_ENABLED`
- `AUTH_SHARED_TOKEN`
- `FIXTURE_MODE`
- `REPO_BASE_PATH`

### LLM
- `LLM_PROVIDER` = `local` or `openai`
- Local mode:
  - `LOCAL_LLM_MODEL`
  - `OLLAMA_ENDPOINTS`
  - `OLLAMA_HEALTHCHECK_TIMEOUT_SECONDS`
  - `OLLAMA_ENDPOINT_CACHE_TTL_SECONDS`
  - `LOCAL_LLM_TIMEOUT_SECONDS`
  - `OLLAMA_BASE_URL` (deprecated compatibility; prepended if set)
- OpenAI mode:
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`

### Triage tuning
- `TRIAGE_WINDOW_MINUTES`
- `MAX_LOGS_QUERIES_PER_INCIDENT`
- `MAX_REPO_SNIPPETS`
- `REPO_RECENT_COMMITS_LIMIT`
- `NO_GUESS_CONFIDENCE_THRESHOLD`
- `EVIDENCE_MIN_REFS_FOR_CONFIDENT_REPORT`
- `ALLOW_RAW_STORAGE`

### Worker retries / ops
- `CELERY_TASK_ALWAYS_EAGER`
- `CELERY_TASK_MAX_RETRIES`
- `CELERY_RETRY_BACKOFF_SECONDS`
- `CELERY_RETRY_JITTER`
- `DATA_RETENTION_DAYS`
- `SLACK_WEBHOOK_URL`
- `TICKET_SINK_ENABLED`

## Running tests
```bash
cd backend
pip install -e .[dev]
pytest -q
```

Current test suite includes:
- normalization/adapters/schema tests
- integration pipeline tests
- Ollama endpoint failover tests
- showcase scenario tests (RBAC, lifecycle conflicts, no-guess mode, timeline correlation, runtime metadata)

## Notes
- This is a prototype and currently uses lightweight schema compatibility updates on startup instead of formal migrations.
- Celery worker runs as root in the compose dev setup (acceptable for local demo, not production hardening).
