"""Hashing helpers."""

import hashlib
import json


def stable_hash(value: str) -> str:
    """Compute deterministic sha256 hash for string."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def dedup_key_for(
    service: str,
    env: str,
    alarm_name: str,
    labels: dict[str, str],
    correlation_id: str | None = None,
) -> str:
    """Build deterministic dedup key from selected alert fields."""

    payload = {
        "service": service,
        "env": env,
        "alarm_name": alarm_name,
        "correlation_id": correlation_id or "",
        "labels": {k: labels[k] for k in sorted(labels)},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return stable_hash(canonical)
