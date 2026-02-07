# Incident Auto-Triage Service (IATS) Prototype

First working v1 prototype for local demo using Docker Compose.

## What this implements
- CloudWatch Alarm ingestion (`POST /v1/alerts/cloudwatch`)
- Canonical `AlertEvent` normalization
- Deduplicated `Incident` upsert + async worker triage (Celery/Redis)
- Evidence collection via CloudWatch Logs Insights adapter (fixture mode by default)
- Evidence Pack persistence
- Pluggable LLM provider:
  - `local` (Ollama, default)
  - `openai` (remote API)
- Triage report persistence and UI rendering
- Console notification + optional Slack webhook

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
  -H 'Content-Type: application/json' \
  --data @fixtures/cloudwatch_alarm_event.json
```

3. Open UI:
- [http://localhost:5173](http://localhost:5173)

4. Inspect API directly:
```bash
curl -sS http://localhost:8000/v1/incidents | jq
curl -sS http://localhost:8000/v1/incidents/<INCIDENT_ID> | jq
curl -sS http://localhost:8000/v1/incidents/<INCIDENT_ID>/evidence | jq
curl -sS http://localhost:8000/v1/incidents/<INCIDENT_ID>/report | jq
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
  - Incident transitions to `triaged`.

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
- `REPO_BASE_PATH`
- `ALLOW_RAW_STORAGE=false` (default)

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
