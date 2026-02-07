"""Incident triage orchestration."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.adapters.cloudwatch import CloudWatchLogsAdapter
from app.adapters.llm import LLMConfigurationError, get_llm_client
from app.adapters.repo import RepoSnippetFetcher
from app.config import get_settings
from app.domain.models import IncidentStatus, TriageReportPayload
from app.services.notifier import Notifier
from app.storage.database import SessionLocal
from app.storage.repositories import IncidentRepository
from app.utils.hashing import stable_hash
from app.utils.redaction import redact_object
from app.utils.time_windows import around


LOG_QUERIES = {
    "errors": "fields @timestamp, @message | filter @message like /ERROR|Exception|Traceback/ | sort @timestamp desc | limit 200",
    "patterns": "fields @message | stats count(*) as count by @message | sort count desc | limit 20",
}


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
        normalized = line[:140]
        counts[normalized] = counts.get(normalized, 0) + 1
        samples.setdefault(normalized, []).append(line)

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    output: list[dict[str, Any]] = []
    for pattern, count in ranked:
        pattern_id = stable_hash(pattern)[:12]
        output.append(
            {
                "pattern_id": pattern_id,
                "count": count,
                "sample_lines": samples.get(pattern, [])[:3],
                "pattern": pattern,
            }
        )
    return output


def triage_incident_sync(incident_id: str) -> None:
    """Run the full triage pipeline for one incident."""

    settings = get_settings()
    notifier = Notifier()
    db = SessionLocal()
    repo = IncidentRepository(db)

    try:
        incident = repo.get_incident(UUID(incident_id))
        if not incident:
            return
        repo.set_incident_status(incident, IncidentStatus.triaging)
        db.commit()

        alert = repo.get_latest_alert_event(incident)
        if not alert:
            raise RuntimeError("incident missing latest alert")

        start, end = around(alert.fired_at, settings.triage_window_minutes)
        from app.services.service_registry import ServiceRegistry

        registry_entry = ServiceRegistry().resolve(alert.resource_refs.get("alarm_name", ""))
        log_group = (registry_entry.get("log_groups") or ["/aws/lambda/default"])[0]

        logs_adapter = CloudWatchLogsAdapter()
        errors_result = logs_adapter.fetch_logs(log_group=log_group, start=start, end=end, query=LOG_QUERIES["errors"])
        patterns_result = logs_adapter.fetch_logs(log_group=log_group, start=start, end=end, query=LOG_QUERIES["patterns"])
        lines = _flatten_logs_result(errors_result) + _flatten_logs_result(patterns_result)
        patterns = _patterns_from_lines(lines)
        keywords = [p["pattern"].split()[0] for p in patterns if p.get("pattern")]

        service_repo_path = registry_entry.get("repo_local_path", "")

        snippet_fetcher = RepoSnippetFetcher()
        repo_snippets = snippet_fetcher.search_snippets(
            service_repo_path,
            [k for k in keywords if len(k) > 3],
            limit=settings.max_repo_snippets,
        )

        artifacts: list[dict[str, Any]] = [
            {
                "type": "logs_query",
                "query_id": errors_result.get("query_id", "fixture-errors"),
                "log_group": log_group,
                "query_string": LOG_QUERIES["errors"],
                "start": start.isoformat(),
                "end": end.isoformat(),
                "status": "Complete",
            },
            {
                "type": "logs_query",
                "query_id": patterns_result.get("query_id", "fixture-patterns"),
                "log_group": log_group,
                "query_string": LOG_QUERIES["patterns"],
                "start": start.isoformat(),
                "end": end.isoformat(),
                "status": "Complete",
            },
            {
                "type": "log_summary",
                "patterns": patterns,
                "top_exceptions": [line for line in lines if "Exception" in line][:5],
            },
        ]
        artifacts.extend(repo_snippets)
        artifacts.append(
            {
                "type": "change_context",
                "repo_path": service_repo_path,
                "branch": "main",
                "last_commits": [],
            }
        )

        artifacts_to_store = artifacts if (settings.allow_raw_storage or settings.fixture_mode) else redact_object(artifacts)
        repo.store_evidence_pack(
            incident.id,
            start,
            end,
            artifacts_to_store,
            {
                "generated_at": datetime.utcnow().isoformat(),
                "log_queries": [LOG_QUERIES["errors"], LOG_QUERIES["patterns"]],
            },
        )
        db.commit()

        llm_evidence_digest = _build_llm_digest(alert.title, artifacts)
        llm_evidence_digest = redact_object(llm_evidence_digest)

        try:
            llm_client = get_llm_client()
            payload = llm_client.generate_triage_report(llm_evidence_digest, TriageReportPayload.model_json_schema())
            validated = TriageReportPayload.model_validate(payload)
            repo.store_triage_report(incident.id, llm_client.model_name, validated)
            repo.set_incident_status(incident, IncidentStatus.triaged)
            db.commit()
            notifier.notify(f"incident={incident.id} triaged")
        except LLMConfigurationError as exc:
            existing_report = repo.get_triage_report(incident.id)
            if existing_report:
                repo.set_incident_status(incident, IncidentStatus.triaged)
                db.commit()
                notifier.notify(f"incident={incident.id} kept triaged (report already exists)")
            else:
                repo.set_incident_status(incident, IncidentStatus.failed, str(exc))
                db.commit()
                notifier.notify(f"incident={incident.id} failed triage: {exc}")
        except Exception as exc:  # noqa: BLE001
            existing_report = repo.get_triage_report(incident.id)
            if existing_report:
                repo.set_incident_status(incident, IncidentStatus.triaged)
                db.commit()
                notifier.notify(f"incident={incident.id} kept triaged (report already exists)")
            else:
                repo.set_incident_status(incident, IncidentStatus.failed, str(exc))
                db.commit()
                notifier.notify(f"incident={incident.id} failed triage: {exc}")

    except Exception as exc:  # noqa: BLE001
        if "incident" in locals() and incident:
            repo.set_incident_status(incident, IncidentStatus.failed, str(exc))
            db.commit()
            notifier.notify(f"incident={incident.id} triage pipeline error: {exc}")
        else:
            notifier.notify(f"triage pipeline error: {exc}")
    finally:
        db.close()


def _build_llm_digest(alert_title: str, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    patterns = []
    snippets = []
    queries = []
    for artifact in artifacts:
        if artifact.get("type") == "log_summary":
            patterns = artifact.get("patterns", [])[:5]
        if artifact.get("type") == "repo_snippet":
            snippets.append(
                {
                    "snippet_id": artifact.get("snippet_id"),
                    "file_path": artifact.get("file_path"),
                    "content": artifact.get("content", "")[:1500],
                }
            )
        if artifact.get("type") == "logs_query":
            queries.append({"query_id": artifact.get("query_id"), "query": artifact.get("query_string")})

    return {
        "alert_summary": alert_title,
        "top_log_patterns": patterns,
        "repo_snippets": snippets,
        "queries": queries,
    }
