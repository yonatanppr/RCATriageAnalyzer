"""Service registry lookup."""

import os
from pathlib import Path

import yaml

from app.config import get_settings


class ServiceRegistry:
    """Config-driven service/env resolver."""

    def __init__(self) -> None:
        settings = get_settings()
        path = Path(__file__).resolve().parents[1] / "config" / "service_registry.yaml"
        text = path.read_text(encoding="utf-8")
        expanded = os.path.expandvars(text)
        self._registry = yaml.safe_load(expanded) or {}

    def resolve(self, key: str) -> dict:
        entry = self._registry.get("alarms", {}).get(key)
        if not entry:
            entry = self._registry.get("services", {}).get(key)
        if entry:
            return entry
        return {
            "service": "unknown-service",
            "env": "unknown",
            "log_groups": ["/aws/lambda/unknown"],
            "repo_local_path": "",
            "owners": [],
            "runbook_url": "",
            "dashboard_url": "",
        }
