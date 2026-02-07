# Backlog Status (Implementation Snapshot)

This file maps the requested epics to current implementation status in this repo.

## Epic A
- A1 `Implemented`: unified evidence refs via `artifact_id + pointer` in report schema.
- A2 `Implemented`: report schema split into `facts`, `hypotheses`, `next_checks`, `mitigations`.
- A3 `Implemented`: hypotheses include `confidence`, `disconfirming_signals`, `missing_data`.
- A4 `Implemented`: no-guess fallback (`mode=insufficient_evidence`) when evidence is weak.
- A5 `Implemented`: evidence-first prompt hardening + strict schema validation.

## Epic B
- B1 `Implemented`: deployment event ingest endpoint and correlation in triage.
- B2 `Implemented`: incident stores `service_version` and `git_sha`.
- B3 `Implemented (MVP)`: config change ingest endpoint + artifact correlation.
- B4 `Implemented (MVP)`: UI timeline view from alert/deploy/config events.

## Epic C
- C1 `Implemented (MVP)`: auth required on `/v1/*` using bearer token scheme.
- C2 `Implemented (MVP)`: RBAC by role and per-service visibility.
- C3 `Implemented`: evidence redaction pipeline in triage path.
- C4 `Implemented`: audit logs for reads, decisions, ingests, and LLM generation.
- C5 `Implemented`: retention purge endpoint with audit log.

## Epic D
- D1 `Implemented`: query template library with alarm overrides.
- D2 `Implemented (heuristic)`: dynamic incident window with reason in provenance.
- D3 `Implemented`: signature extraction artifact with samples.
- D4 `Implemented (MVP)`: line normalization-based de-dup reduces repetitive signatures.
- D5 `Implemented (MVP UI)`: query pointers can be copied/opened from citations.

## Epic E
- E1 `Implemented`: service registry mapping for repo/owners/runbook/dashboard.
- E2 `Implemented (MVP)`: commit-aware snippet retrieval when SHA available.
- E3 `Implemented (MVP)`: stack-trace-to-source frame extraction and snippet mapping.
- E4 `Implemented`: keyword search is fallback when stack mapping does not resolve.

## Epic F
- F1 `Implemented`: second alert source adapter (`alertmanager`) and endpoint.
- F2 `Implemented (stub)`: notifier interface with ticket sink stub behind feature flag.

## Epic G
- G1 `Implemented`: production reference doc in `docs/reference_architecture.md`.
- G2 `Implemented (MVP)`: quality + runtime metrics endpoints.
- G3 `Implemented (MVP)`: retries, idempotent skip, query caps, state consistency checks.
- G4 `Implemented (MVP)`: cost estimate added to triage provenance.

## Epic H
- H1 `Implemented`: triage summary card in UI.
- H2 `Implemented (MVP)`: one-click runbook/dashboard/owner/ticket actions.
- H3 `Implemented`: feedback endpoint and UI feedback actions.

## Epic I
- I1 `Implemented (MVP)`: ground-truth fixture + expected report structure fixture.
- I2 `Implemented (MVP)`: offline evaluation harness script.
- I3 `Implemented (MVP metrics scaffold)`: pilot metrics endpoint fields in quality/runtime outputs.
