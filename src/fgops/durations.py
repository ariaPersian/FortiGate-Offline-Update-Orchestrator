from __future__ import annotations

import re
from datetime import timedelta

_DURATION_RE = re.compile(r"^(?P<value>\d+)(?P<unit>[mhdw])$")


def parse_duration(value: str) -> timedelta:
    match = _DURATION_RE.fullmatch(value.strip().lower())
    if not match:
        raise ValueError(f"Invalid duration '{value}'. Use formats such as 30m, 6h, 7d, or 2w.")
    amount = int(match.group("value"))
    unit = match.group("unit")
    if amount <= 0:
        raise ValueError("Duration must be greater than zero.")
    return {
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
    }[unit]
