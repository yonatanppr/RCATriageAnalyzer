"""CloudWatch adapters."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dateutil.parser import isoparse

from app.adapters.interfaces import AlertSourceAdapter, EvidenceSourceAdapter
from app.config import get_settings
from app.domain.models import AlertEvent


class CloudWatchNormalizationError(ValueError):
    """Raised when payload is not a cloudwatch alarm state event."""


class CloudWatchAlertAdapter(AlertSourceAdapter):
    """Normalize CloudWatch alarm state payloads into AlertEvent."""

    def normalize(self, payload: dict[str, Any]) -> AlertEvent:
        detail = payload.get("detail")
        if not isinstance(detail, dict):
            raise CloudWatchNormalizationError("missing detail in CloudWatch payload")

        alarm_name = detail.get("alarmName", "unknown-alarm")
        state_obj = detail.get("state", {})
        prev_state_obj = detail.get("previousState", {})
        state_value = state_obj.get("value", "UNKNOWN")
        fired_time = state_obj.get("timestamp") or payload.get("time")
        if not fired_time:
            raise CloudWatchNormalizationError("missing state timestamp")

        fired_at = isoparse(fired_time)
        ended_at = fired_at if state_value == "OK" else None
        labels = {
            "alarm_name": alarm_name,
            "region": payload.get("region", ""),
            "account_id": payload.get("account", ""),
            "previous_state": prev_state_obj.get("value", ""),
        }
        reason = state_obj.get("reason", "")
        correlation_id = self._extract_correlation_id(payload, detail, reason)
        severity = "critical" if state_value == "ALARM" else "info"
        return AlertEvent(
            source="cloudwatch",
            external_id=str(payload.get("id", alarm_name)),
            title=f"CloudWatch Alarm: {alarm_name}",
            severity=severity,
            state=state_value,
            correlation_id=correlation_id,
            fired_at=fired_at,
            ended_at=ended_at,
            labels=labels,
            annotations={"reason": reason},
            resource_refs={
                "alarm_name": alarm_name,
                "region": payload.get("region", ""),
                "account_id": payload.get("account", ""),
                "correlation_id": correlation_id or "",
            },
            raw_payload=payload,
        )

    def _extract_correlation_id(self, payload: dict[str, Any], detail: dict[str, Any], reason: str) -> str | None:
        candidates = [
            detail.get("correlationId"),
            detail.get("correlation_id"),
            detail.get("requestId"),
            detail.get("request_id"),
            detail.get("traceId"),
            detail.get("trace_id"),
            payload.get("correlationId"),
            payload.get("correlation_id"),
        ]
        for value in candidates:
            if isinstance(value, str) and value.strip():
                return value.strip()

        match = re.search(r"(?i)(correlation[_\s-]?id|request[_\s-]?id|trace[_\s-]?id)\s*[:=]\s*([A-Za-z0-9_.:/-]{6,})", reason)
        if match:
            return match.group(2)
        return None


class CloudWatchLogsAdapter(EvidenceSourceAdapter):
    """Fetch logs from CloudWatch Logs Insights with fixture fallback."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = boto3.client("logs", region_name=self.settings.aws_region)

    def fetch_logs(self, *, log_group: str, start: datetime, end: datetime, query: str) -> dict[str, Any]:
        if self.settings.fixture_mode:
            return self._load_fixture()

        try:
            start_query = self.client.start_query(
                logGroupName=log_group,
                startTime=int(start.timestamp()),
                endTime=int(end.timestamp()),
                queryString=query,
                limit=200,
            )
            query_id = start_query["queryId"]
            result = self.client.get_query_results(queryId=query_id)
            return {"query_id": query_id, "result": result}
        except (BotoCoreError, ClientError) as exc:
            if self.settings.fixture_mode:
                return self._load_fixture()
            raise RuntimeError(f"failed to query CloudWatch logs: {exc}") from exc

    def _load_fixture(self) -> dict[str, Any]:
        fixture = Path(__file__).resolve().parents[3] / "fixtures" / "logs_insights_result.json"
        with fixture.open("r", encoding="utf-8") as handle:
            return json.load(handle)
