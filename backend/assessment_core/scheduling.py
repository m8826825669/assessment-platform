"""SCH-01 fixed sitting windows and accommodation policy."""

import re
from datetime import UTC, datetime, timedelta


def display_offset(value: str) -> str:
    if value == "UTC":
        return value
    match = re.fullmatch(r"UTC([+-])(\d{2}):(\d{2})", value)
    if not match:
        raise ValueError("Use UTC or a fixed offset such as UTC+05:30")
    hours, minutes = int(match[2]), int(match[3])
    if minutes > 59 or hours > 14 or (hours == 14 and minutes):
        raise ValueError("Timezone offset is out of range")
    return value


def check_window(opens: datetime, closes: datetime, minutes: int) -> None:
    if opens.tzinfo is None or closes.tzinfo is None:
        raise ValueError("Timezone-aware timestamps are required")
    if closes <= opens or closes - opens < timedelta(minutes=minutes):
        raise ValueError("The sitting window must fit the allowed duration")


def start_readiness(opens: datetime, closes: datetime, now: datetime, minutes: int) -> dict:
    if any(value.tzinfo is None for value in (opens, closes, now)):
        raise ValueError("Timezone-aware timestamps are required")
    state = "upcoming" if now < opens else "closed" if now >= closes else "open"
    return {
        "window_state": state,
        "can_start": state == "open",
        "server_time": now.astimezone(UTC),
        "deadline_if_started_now": min(closes, now + timedelta(minutes=minutes)) if state == "open" else None,
    }
