"""Query template library loader."""

from pathlib import Path

import yaml

from app.config import project_root


class QueryLibrary:
    def __init__(self) -> None:
        path = project_root() / "config" / "query_library.yaml"
        if path.exists():
            self._data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            self._data = {}

    def get_queries(self, alarm_name: str | None = None) -> dict[str, str]:
        default = self._data.get("default", {})
        queries = {name: entry.get("query", "") for name, entry in default.items() if isinstance(entry, dict)}
        alarm_block = self._data.get("alarms", {}).get(alarm_name or "", {})
        for name, entry in alarm_block.items():
            if isinstance(entry, dict) and entry.get("query"):
                queries[name] = entry["query"]
        return queries

