"""Notification sinks."""

import json
from abc import ABC, abstractmethod

import httpx

from app.config import get_settings


class NotificationSink(ABC):
    @abstractmethod
    def send(self, message: str, payload: dict) -> None:
        raise NotImplementedError


class ConsoleSink(NotificationSink):
    def send(self, message: str, payload: dict) -> None:
        _ = payload
        print(f"[IATS] {message}")


class SlackSink(NotificationSink):
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, message: str, payload: dict) -> None:
        body = {"text": message, **payload}
        try:
            httpx.post(self.webhook_url, content=json.dumps(body), timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            print(f"[IATS] Slack notify failed: {exc}")


class TicketSink(NotificationSink):
    """Stub sink for ticket creation integration."""

    def send(self, message: str, payload: dict) -> None:
        print(f"[IATS][TICKET_STUB] {message} payload={json.dumps(payload)}")


class Notifier:
    """Console and optional Slack notifier."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.sinks: list[NotificationSink] = [ConsoleSink()]
        if self.settings.slack_webhook_url:
            self.sinks.append(SlackSink(self.settings.slack_webhook_url))
        if getattr(self.settings, "ticket_sink_enabled", False):
            self.sinks.append(TicketSink())

    def notify(self, message: str) -> None:
        for sink in self.sinks:
            sink.send(message, {})

    def notify_incident_update(
        self,
        *,
        incident_id: str,
        service: str,
        env: str,
        status: str,
        owners: list[str] | None = None,
        runbook_url: str | None = None,
        dashboard_url: str | None = None,
        details: str | None = None,
    ) -> None:
        owners_text = ", ".join(owners or []) or "unknown"
        message = f"incident={incident_id} service={service} env={env} status={status} owners={owners_text}"
        if details:
            message += f" details={details}"
        attachments = [
            {"title": "Owners", "value": ", ".join(owners or []) or "unknown", "short": False},
            {"title": "Runbook", "value": runbook_url or "not configured", "short": False},
            {"title": "Dashboard", "value": dashboard_url or "not configured", "short": False},
        ]
        payload = {"attachments": [{"fields": attachments}]}
        for sink in self.sinks:
            sink.send(message, payload)
