"""Incident triage orchestration."""

import json
import re
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import UUID

from app.adapters.cloudwatch import CloudWatchLogsAdapter
from app.adapters.llm import LLMConfigurationError, get_llm_client
from app.adapters.repo import RepoSnippetFetcher
from app.config import get_settings
from app.domain.models import IncidentStatus, TriageReportPayload
from app.services.notifier import Notifier
from app.services.query_library import QueryLibrary
from app.storage.database import SessionLocal
from app.storage.repositories import IncidentRepository
from app.utils.hashing import stable_hash
from app.utils.redaction import redact_object
from app.utils.time_windows import around


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _flatten_logs_result(result: dict[str, Any]) -> list[str]:
    rows = result.get("result", {}).get("results", [])
    lines: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            maybe = row.get("@message") or row.get("message")
            if maybe:
                lines.append(str(maybe))
        elif isinstance(row, list):
            for col in row:
                if isinstance(col, dict) and col.get("field") == "@message":
                    lines.append(str(col.get("value", "")))
    return [line for line in lines if line]


def _patterns_from_lines(lines: list[str]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    for line in lines:
        normalized = line[:180]
        counts[normalized] = counts.get(normalized, 0) + 1
        samples.setdefault(normalized, []).append(line)
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    output: list[dict[str, Any]] = []
    for pattern, count in ranked:
        signature_id = stable_hash(pattern)[:12]
        output.append(
            {
                "signature_id": signature_id,
                "count": count,
                "pattern": pattern,
                "samples": samples.get(pattern, [])[:3],
            }
        )
    return output


def _escape_logs_regex(value: str) -> str:
    return re.escape(value).replace("/", "\\/")


def _compute_window(alert_fired_at: datetime, has_correlation_id: bool, severity: str, base_minutes: int) -> tuple[datetime, datetime, str]:
    multiplier = 1.0
    reason = "default-window"
    if has_correlation_id:
        multiplier = 0.8
        reason = "narrowed-window-correlation-id"
    elif severity.lower() in {"critical", "high"}:
        multiplier = 1.5
        reason = "expanded-window-critical"
    start, end = around(alert_fired_at, max(5, int(base_minutes * multiplier)))
    return start, end, reason


def _extract_stack_frames(lines: list[str]) -> list[tuple[str, int]]:
    frames: list[tuple[str, int]] = []
    py_pattern = re.compile(r'File "([^"]+)", line (\d+)')
    for line in lines:
        match = py_pattern.search(line)
        if match:
            file_path, line_no = match.group(1), int(match.group(2))
            if "/" in file_path:
                frames.append((file_path.split("/")[-1], line_no))
    return frames[:5]


def _score_evidence(
    *,
    patterns: list[dict[str, Any]],
    repo_snippets: list[dict[str, Any]],
    query_results: dict[str, dict[str, Any]],
    correlation_id: str | None,
    alert_state: str,
    alert_reason: str | None,
    fixture_mode: bool,
) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []
    if correlation_id:
        corr_lines = len(_flatten_logs_result(query_results.get("correlation", {})))
        if corr_lines > 0:
            score += 0.35
            reasons.append("correlation id matched in logs")
    if patterns:
        score += 0.3
        reasons.append("error signatures extracted")
    if repo_snippets:
        score += 0.2
        reasons.append("code context linked")
    if len(query_results) >= 2:
        score += 0.15
        reasons.append("multi-query evidence")
    signal_text = " ".join(
        [str(p.get("pattern", "")) for p in patterns] + ([alert_reason] if alert_reason else [])
    ).lower()
    if any(token in signal_text for token in ("traceback", "exception", "valueerror", "timeout", "endpointconnectionerror")):
        score += 0.2
        reasons.append("strong exception/timeout signal")
    if alert_state.upper() == "OK":
        score += 0.15
        reasons.append("recovery-state signal")
    if fixture_mode:
        score = max(0.0, score - 0.1)
        reasons.append("fixture mode confidence penalty")
    normalized = round(min(1.0, score), 2)
    level = "high" if normalized >= 0.75 else "medium" if normalized >= 0.45 else "low"
    return {"score": normalized, "level": level, "reasons": reasons}


def _artifact(artifact_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    artifact_id = stable_hash(f"{artifact_type}:{canonical}")[:12]
    return {"artifact_id": artifact_id, "type": artifact_type, **payload}


def _fallback_insufficient_report(artifacts: list[dict[str, Any]], score: dict[str, Any]) -> dict[str, Any]:
    query_refs = [
        {"artifact_id": a["artifact_id"], "pointer": f"query_id:{a.get('query_id', 'unknown')}"}
        for a in artifacts
        if a.get("type") == "logs_query"
    ][:2]
    next_checks = [
        {
            "check_id": "check-collect-more-logs",
            "step": "Expand log window and validate whether error signatures persist.",
            "command_or_query": "rerun errors and patterns queries with broader interval",
            "evidence_refs": query_refs,
        },
        {
            "check_id": "check-deploy-diff",
            "step": "Compare deployed version against last known healthy release.",
            "command_or_query": "inspect deployment timeline and diff config changes",
            "evidence_refs": query_refs,
        },
    ]
    claims = [
        {
            "claim_id": "claim-insufficient-evidence",
            "type": "next_check",
            "text": "Current evidence does not support a reliable root-cause hypothesis.",
            "evidence_refs": query_refs,
        }
    ]
    return {
        "summary": "Insufficient evidence for a confident root-cause statement.",
        "mode": "insufficient_evidence",
        "facts": [],
        "hypotheses": [],
        "next_checks": next_checks,
        "mitigations": [],
        "claims": claims,
        "uncertainty_note": f"evidence_score={score.get('score')} ({score.get('level')})",
        "generation_metadata": {
            "llm_provider": "fallback",
            "llm_endpoint_used": None,
            "endpoint_failover_count": 0,
        },
    }


def _estimate_cost(evidence_digest: dict[str, Any]) -> dict[str, Any]:
    chars = len(json.dumps(evidence_digest, default=str))
    est_tokens = max(1, chars // 4)
    # Rough blended estimate for local prototype visibility.
    est_cost = round(est_tokens * 0.000002, 6)
    return {"estimated_tokens": est_tokens, "estimated_cost_usd": est_cost}


def triage_incident_sync(incident_id: str) -> None:
    settings = get_settings()
    notifier = Notifier()
    db = SessionLocal()
    repo = IncidentRepository(db)
    run_start = perf_counter()

    try:
        incident = repo.get_incident(UUID(incident_id))
        if not incident:
            return
        repo.set_incident_status(incident, IncidentStatus.triaging)
        db.commit()

        alert = repo.get_latest_alert_event(incident)
        if not alert:
            raise RuntimeError("incident missing latest alert")
        latest_evidence = repo.get_latest_evidence_pack(incident.id)
        if latest_evidence and latest_evidence.provenance.get("alert_event_id") == str(alert.id):
            repo.create_pipeline_run(
                incident_id=incident.id,
                stage="triage",
                status="skipped",
                duration_ms=int((perf_counter() - run_start) * 1000),
                error=None,
                metrics={"reason": "idempotent-skip"},
            )
            db.commit()
            return

        from app.services.service_registry import ServiceRegistry

        key = alert.resource_refs.get("alarm_name", "") or incident.service
        registry_entry = ServiceRegistry().resolve(key)
        log_group = (registry_entry.get("log_groups") or ["/aws/lambda/default"])[0]
        correlation_id = alert.correlation_id or incident.correlation_id
        start, end, window_reason = _compute_window(
            alert.fired_at,
            bool(correlation_id),
            alert.severity,
            settings.triage_window_minutes,
        )

        recent_deploys = repo.list_recent_deployments(service=incident.service, env=incident.env, since=start, until=end)
        recent_config = repo.list_recent_config_changes(service=incident.service, env=incident.env, since=start, until=end)
        if recent_deploys:
            repo.attach_incident_version(incident, recent_deploys[0].version, recent_deploys[0].git_sha)
            db.commit()

        query_templates = QueryLibrary().get_queries(alert.resource_refs.get("alarm_name"))
        queries = dict(query_templates)
        if correlation_id:
            queries["correlation"] = (
                f"fields @timestamp, @message | filter @message like /{_escape_logs_regex(correlation_id)}/"
                " | sort @timestamp desc | limit 200"
            )
        query_items = list(queries.items())[: settings.max_logs_queries_per_incident]

        logs_adapter = CloudWatchLogsAdapter()
        query_results: dict[str, dict[str, Any]] = {}
        for name, query in query_items:
            query_results[name] = logs_adapter.fetch_logs(log_group=log_group, start=start, end=end, query=query)

        lines: list[str] = []
        if "correlation" in query_results:
            lines.extend(_flatten_logs_result(query_results["correlation"]))
        for q_name, result in query_results.items():
            if q_name != "correlation":
                lines.extend(_flatten_logs_result(result))
        reason_line = alert.annotations.get("reason")
        if isinstance(reason_line, str) and reason_line.strip():
            lines.append(reason_line.strip())
        patterns = _patterns_from_lines(lines)
        stack_frames = _extract_stack_frames(lines)

        service_repo_path = registry_entry.get("repo_local_path", "")
        snippet_fetcher = RepoSnippetFetcher()
        commit_sha = incident.git_sha
        stack_snippets: list[dict[str, Any]] = []
        for file_name, line_no in stack_frames:
            mapped = snippet_fetcher.snippet_for_file_line(service_repo_path, file_name, line_no, commit_sha=commit_sha)
            if mapped:
                stack_snippets.append(mapped)
        keyword_snippets = []
        if not stack_snippets:
            keywords = [p["pattern"].split()[0] for p in patterns if p.get("pattern")]
            keyword_snippets = snippet_fetcher.search_snippets(
                service_repo_path,
                [k for k in keywords if len(k) > 3],
                limit=settings.max_repo_snippets,
            )
        repo_snippets = stack_snippets or keyword_snippets
        recent_commits = snippet_fetcher.recent_commits(service_repo_path, settings.repo_recent_commits_limit)
        score = _score_evidence(
            patterns=patterns,
            repo_snippets=repo_snippets,
            query_results=query_results,
            correlation_id=correlation_id,
            alert_state=alert.state,
            alert_reason=alert.annotations.get("reason"),
            fixture_mode=settings.fixture_mode,
        )

        artifacts: list[dict[str, Any]] = []
        artifacts.append(_artifact("log_signatures", {"signatures": patterns}))
        for name, query in query_items:
            result = query_results[name]
            artifacts.append(
                _artifact(
                    "logs_query",
                    {
                        "query_name": name,
                        "query_id": result.get("query_id", f"fixture-{name}"),
                        "log_group": log_group,
                        "query_string": query,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "status": "Complete",
                    },
                )
            )
        if correlation_id:
            artifacts.append(_artifact("correlation", {"correlation_id": correlation_id}))
        for snippet in repo_snippets:
            artifacts.append(_artifact("repo_snippet", snippet))
        artifacts.append(
            _artifact(
                "change_context",
                {
                    "repo_path": service_repo_path,
                    "branch": "main",
                    "git_sha": incident.git_sha,
                    "service_version": incident.service_version,
                    "last_commits": recent_commits,
                },
            )
        )
        artifacts.append(
            _artifact(
                "deploy_timeline",
                {
                    "events": [
                        {
                            "deployed_at": row.deployed_at.isoformat(),
                            "version": row.version,
                            "git_sha": row.git_sha,
                            "actor": row.actor,
                        }
                        for row in recent_deploys
                    ],
                },
            )
        )
        artifacts.append(
            _artifact(
                "config_changes",
                {
                    "events": [
                        {
                            "changed_at": row.changed_at.isoformat(),
                            "actor": row.actor,
                            "diff": row.diff,
                        }
                        for row in recent_config
                    ],
                },
            )
        )
        timeline_events = [
            {"type": "alert", "time": alert.fired_at.isoformat(), "label": alert.title},
            *[
                {"type": "deploy", "time": d.deployed_at.isoformat(), "label": f"deploy {d.version or d.git_sha or 'unknown'}"}
                for d in recent_deploys
            ],
            *[
                {"type": "config", "time": c.changed_at.isoformat(), "label": "config changed"}
                for c in recent_config
            ],
        ]
        artifacts.append(_artifact("timeline", {"events": timeline_events}))
        artifacts.append(_artifact("evidence_score", score))

        digest = _build_llm_digest(alert.title, artifacts)
        cost = _estimate_cost(digest)

        effective_confidence_threshold = settings.no_guess_confidence_threshold
        if settings.fixture_mode:
            # Keep fixture demos resilient even when external env uses stricter production thresholds.
            effective_confidence_threshold = min(effective_confidence_threshold, 0.6)
        no_guess = score["score"] < effective_confidence_threshold
        no_guess_reasons: list[str] = []
        if no_guess:
            no_guess_reasons.append(
                f"score_below_threshold:{score['score']}<{effective_confidence_threshold}"
            )
        query_artifact_count = len([a for a in artifacts if a.get("type") == "logs_query"])
        required_query_refs = settings.evidence_min_refs_for_confident_report
        if settings.fixture_mode:
            # Fixture mode usually runs fewer query variants; relax the minimum to avoid perpetual no-guess demos.
            required_query_refs = max(1, required_query_refs - 1)
            # Do not require more references than the current run can actually produce.
            required_query_refs = min(required_query_refs, max(1, len(query_items)))
        if query_artifact_count < required_query_refs:
            no_guess = True
            no_guess_reasons.append(
                f"insufficient_query_refs:{query_artifact_count}<{required_query_refs}"
            )

        if no_guess:
            payload_obj = _fallback_insufficient_report(artifacts, score)
            model_name = "fallback:no-guess"
            llm_meta = {
                "llm_provider": "fallback",
                "llm_endpoint_used": None,
                "endpoint_failover_count": 0,
            }
        else:
            llm_client = get_llm_client()
            redacted_digest = redact_object(digest)
            repo.create_audit_log(
                actor="system",
                action="llm.generate",
                resource_type="incident",
                resource_id=str(incident.id),
                details={"model": llm_client.model_name},
            )
            payload_obj = llm_client.generate_triage_report(redacted_digest, TriageReportPayload.model_json_schema())
            model_name = llm_client.model_name
            llm_meta = llm_client.generation_metadata()
            payload_obj["generation_metadata"] = {**payload_obj.get("generation_metadata", {}), **llm_meta}

        validated = TriageReportPayload.model_validate(payload_obj)
        repo.store_triage_report(incident.id, model_name, validated)
        repo.set_incident_status(incident, IncidentStatus.awaiting_human_review)
        artifacts_to_store = artifacts if (settings.allow_raw_storage or settings.fixture_mode) else redact_object(artifacts)
        repo.store_evidence_pack(
            incident.id,
            start,
            end,
            artifacts_to_store,
            {
                "generated_at": _now_utc().isoformat(),
                "window_reason": window_reason,
                "query_names": [name for name, _ in query_items],
                "correlation_id": correlation_id,
                "alert_event_id": str(alert.id),
                "evidence_score": score,
                "no_guess_mode": no_guess,
                "no_guess_reasons": no_guess_reasons,
                "effective_confidence_threshold": effective_confidence_threshold,
                "required_query_refs": required_query_refs,
                "query_artifact_count": query_artifact_count,
                "cost_estimate": cost,
            },
        )
        duration_ms = int((perf_counter() - run_start) * 1000)
        repo.create_pipeline_run(
            incident_id=incident.id,
            stage="triage",
            status="success",
            duration_ms=duration_ms,
            error=None,
            metrics={
                "score": score["score"],
                "no_guess_mode": no_guess,
                "no_guess_reasons": no_guess_reasons,
                "effective_confidence_threshold": effective_confidence_threshold,
                "required_query_refs": required_query_refs,
                "query_artifact_count": query_artifact_count,
                **cost,
                **llm_meta,
            },
        )
        db.commit()
        notifier.notify_incident_update(
            incident_id=str(incident.id),
            service=incident.service,
            env=incident.env,
            status=IncidentStatus.awaiting_human_review.value,
            owners=registry_entry.get("owners", []),
            runbook_url=registry_entry.get("runbook_url"),
            dashboard_url=registry_entry.get("dashboard_url"),
            details=f"score={score['score']} no_guess={no_guess}",
        )
    except LLMConfigurationError as exc:
        duration_ms = int((perf_counter() - run_start) * 1000)
        if "incident" in locals() and incident:
            repo.set_incident_status(incident, IncidentStatus.failed, str(exc))
            repo.create_pipeline_run(
                incident_id=incident.id,
                stage="llm",
                status="failed",
                duration_ms=duration_ms,
                error=str(exc),
                metrics={},
            )
            db.commit()
        notifier.notify(f"triage failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        duration_ms = int((perf_counter() - run_start) * 1000)
        if "incident" in locals() and incident:
            repo.set_incident_status(incident, IncidentStatus.failed, str(exc))
            repo.create_pipeline_run(
                incident_id=incident.id,
                stage="triage",
                status="failed",
                duration_ms=duration_ms,
                error=str(exc),
                metrics={},
            )
            db.commit()
        notifier.notify(f"triage pipeline error: {exc}")
    finally:
        db.close()


def _build_llm_digest(alert_title: str, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    signatures = []
    snippets = []
    queries = []
    timeline = []
    correlation_id = None
    change_context = {}
    for artifact in artifacts:
        a_type = artifact.get("type")
        if a_type == "log_signatures":
            signatures = artifact.get("signatures", [])
        elif a_type == "repo_snippet":
            snippets.append(
                {
                    "snippet_id": artifact.get("snippet_id"),
                    "file_path": artifact.get("file_path"),
                    "line_range": f"{artifact.get('start_line', 1)}-{artifact.get('end_line', 1)}",
                    "content": str(artifact.get("content", ""))[:1800],
                    "artifact_id": artifact.get("artifact_id"),
                }
            )
        elif a_type == "logs_query":
            queries.append(
                {
                    "query_id": artifact.get("query_id"),
                    "query_name": artifact.get("query_name"),
                    "query": artifact.get("query_string"),
                    "artifact_id": artifact.get("artifact_id"),
                }
            )
        elif a_type == "correlation":
            correlation_id = artifact.get("correlation_id")
        elif a_type == "timeline":
            timeline = artifact.get("events", [])
        elif a_type == "change_context":
            change_context = {
                "service_version": artifact.get("service_version"),
                "git_sha": artifact.get("git_sha"),
                "last_commits": artifact.get("last_commits", [])[:5],
                "artifact_id": artifact.get("artifact_id"),
            }

    return {
        "alert_summary": alert_title,
        "correlation_id": correlation_id,
        "signatures": signatures,
        "repo_snippets": snippets,
        "queries": queries,
        "timeline": timeline,
        "change_context": change_context,
    }
