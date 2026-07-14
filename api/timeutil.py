from __future__ import annotations

from datetime import datetime, timezone


def utc_now(now: datetime | None = None) -> str:
    """UTC timestamp in the canonical second-precision `YYYY-MM-DDTHH:MM:SSZ` form."""
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
