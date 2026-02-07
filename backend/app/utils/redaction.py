"""Sensitive data redaction utilities."""

import re

_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)(password|secret|token)\s*=\s*[^\s,;]+"),
    re.compile(r"\b[A-Za-z0-9+/]{32,}={0,2}\b"),
]


def redact_text(text: str) -> str:
    """Redact likely secrets in arbitrary text."""

    redacted = text
    for pattern in _PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_object(value):
    """Recursively redact strings within lists/dicts."""

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_object(item) for item in value]
    if isinstance(value, dict):
        return {k: redact_object(v) for k, v in value.items()}
    return value
