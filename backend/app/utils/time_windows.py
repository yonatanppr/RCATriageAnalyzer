"""Time window helpers."""

from datetime import datetime, timedelta


def around(timestamp: datetime, minutes: int) -> tuple[datetime, datetime]:
    """Return +/- time window around timestamp."""

    delta = timedelta(minutes=minutes)
    return timestamp - delta, timestamp + delta
