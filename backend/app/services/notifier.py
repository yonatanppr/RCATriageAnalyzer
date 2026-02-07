"""Notification sinks."""

import json

import httpx

from app.config import get_settings


class Notifier:
    """Console and optional Slack notifier."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def notify(self, message: str) -> None:
        print(f"[IATS] {message}")
        if self.settings.slack_webhook_url:
            self._notify_slack(message)

    def _notify_slack(self, message: str) -> None:
        payload = {"text": message}
        try:
            httpx.post(self.settings.slack_webhook_url, content=json.dumps(payload), timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            print(f"[IATS] Slack notify failed: {exc}")
