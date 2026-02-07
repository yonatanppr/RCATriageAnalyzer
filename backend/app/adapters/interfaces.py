"""Adapter interface contracts."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class AlertSourceAdapter(ABC):
    """Normalize external alert payloads."""

    @abstractmethod
    def normalize(self, payload: dict[str, Any]):
        raise NotImplementedError


class EvidenceSourceAdapter(ABC):
    """Fetch correlated evidence."""

    @abstractmethod
    def fetch_logs(self, *, log_group: str, start: datetime, end: datetime, query: str) -> dict[str, Any]:
        raise NotImplementedError
