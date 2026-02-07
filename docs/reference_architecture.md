# Production Reference Architecture (MVP)

## Services
- `api`: FastAPI service for ingest, query, decision workflows.
- `worker`: Celery worker for asynchronous triage pipeline.
- `redis`: queue/broker and celery result backend.
- `postgres`: persistent storage for incidents, evidence, reports, audit, metrics.
- `ollama` or `openai`: LLM backend.

## Network and Trust Boundaries
- External ingest enters via authenticated `/v1/alerts/*` and `/v1/changes/*`.
- Internal worker reads/writes DB and calls evidence/LLM adapters.
- Auth enforced on `/v1/*`; service account tokens needed for ingest endpoints.

## Scaling Knobs
- Scale API replicas independently from workers.
- Scale worker concurrency based on queue depth and adapter capacity.
- Tune `CELERY_TASK_MAX_RETRIES`, `CELERY_RETRY_BACKOFF_SECONDS`.
- Use `MAX_LOGS_QUERIES_PER_INCIDENT` and `MAX_REPO_SNIPPETS` to cap workload.

## Reliability and Safety
- Incident upsert with dedup key.
- Idempotent triage skip when same alert event already processed.
- No-guess mode when evidence score is low.
- Redaction before LLM/context persistence in non-raw mode.

## Observability
- `GET /v1/metrics/quality`: incident lifecycle and review quality metrics.
- `GET /v1/metrics/runtime`: pipeline run counts/failures/duration.
- Audit table captures evidence/report reads, LLM generation, and admin actions.

## Retention and Governance
- Use `POST /v1/admin/purge?days=N` for data purge.
- Keep audit logs append-only for compliance traceability.

## Deployment Notes
- Keep `api` and `worker` as separate deployments.
- Pin model and adapter timeouts explicitly in environment.
- Prefer managed Postgres/Redis in production, not local container state.
