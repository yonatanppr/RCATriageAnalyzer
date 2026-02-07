from app.utils.redaction import redact_text


def test_redaction_masks_common_secret_patterns() -> None:
    raw = "AKIAABCDEFGHIJKLMNOP bearer abcde12345 token=supersecret password=hunter2"
    redacted = redact_text(raw)
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted
    assert "supersecret" not in redacted
    assert "hunter2" not in redacted
    assert "[REDACTED]" in redacted
