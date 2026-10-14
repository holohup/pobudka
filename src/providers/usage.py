"""Subscription quota contract and strict, inference-free CLI output parsers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


class UsageError(Exception):
    """Sanitized, actionable collection failure safe to publish."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class UsageWindow:
    used_percent: float
    resets_at: str | None = None


@dataclass(frozen=True)
class SubscriptionUsage:
    primary: UsageWindow | None = None
    weekly: UsageWindow | None = None


def utc_iso(value: datetime) -> str:
    """Return an aware instant as UTC ISO 8601."""
    return value.astimezone(UTC).isoformat()


def percentage(value: object) -> float:
    """Validate a quota percentage; never replace invalid data with zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UsageError("invalid_output", "Invalid usage percentage")
    if not 0 <= value <= 100:
        raise UsageError("invalid_output", "Usage percentage outside 0..100")
    return float(value)


def parse_reset(text: str, now: datetime) -> str:
    """Parse supported English CLI reset dates in an explicit timezone.

    No-year dates choose the next occurrence (including December rollover).
    Ambiguous/nonexistent local DST times fail rather than inventing an instant.
    """
    zone_match = re.search(r"\(([^()]+)\)\s*$", text)
    try:
        zone = ZoneInfo(zone_match[1] if zone_match else "Asia/Jerusalem")
    except (KeyError, ValueError) as exc:
        raise UsageError("invalid_output", "Unknown reset timezone") from exc
    text = text[: zone_match.start()].strip() if zone_match else text.strip()
    local_now = now.astimezone(zone)
    relative = re.fullmatch(
        r"in\s+((?:\d+\s*(?:days?|hours?|minutes?)\s*)+)", text, re.IGNORECASE
    )
    if relative:
        seconds = sum(
            int(n)
            * {"day": 86400, "hour": 3600, "minute": 60}[unit.rstrip("s").lower()]
            for n, unit in re.findall(
                r"(\d+)\s*(days?|hours?|minutes?)", relative[1], re.IGNORECASE
            )
        )
        return utc_iso(now + timedelta(seconds=seconds))
    match = re.fullmatch(
        r"(?:(today|tomorrow)|([A-Za-z]{3,9})\s+(\d{1,2})(?:,?\s+(\d{4}))?)?[, ]*\s*(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise UsageError("invalid_output", "Unrecognized reset date")
    relative_day, month, day, year, hour, minute, period = match.groups()
    h, m = int(hour), int(minute or 0)
    if period:
        if not 1 <= h <= 12:
            raise UsageError("invalid_output", "Invalid AM/PM reset hour")
        h = h % 12 + (12 if period.lower() == "pm" else 0)
    try:
        if month:
            month_number = datetime.strptime(month[:3].title(), "%b").month
            date = local_now.replace(
                year=int(year or local_now.year),
                month=month_number,
                day=int(day),
                hour=h,
                minute=m,
                second=0,
                microsecond=0,
            )
        else:
            date = local_now.replace(hour=h, minute=m, second=0, microsecond=0)
            if relative_day and relative_day.lower() == "tomorrow":
                date += timedelta(days=1)
        if not year and not relative_day and date < local_now:
            date = (
                date.replace(year=date.year + 1) if month else date + timedelta(days=1)
            )
        if date.replace(fold=0).utcoffset() != date.replace(fold=1).utcoffset():
            raise UsageError(
                "invalid_output", "Ambiguous or nonexistent DST reset time"
            )
        if date.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != date.replace(
            tzinfo=None
        ):
            raise UsageError("invalid_output", "Nonexistent DST reset time")
        return utc_iso(date)
    except ValueError as exc:
        raise UsageError("invalid_output", "Invalid reset date") from exc


def parse_claude_usage(data: dict, now: datetime) -> SubscriptionUsage:
    """Require local `/usage`, zero inference and recognized quota lines."""
    text = str(data.get("result", ""))
    lower = text.lower()
    if "unknown skill: usage" in lower:
        raise UsageError(
            "incompatible_cli", "Claude CLI does not support print-mode /usage"
        )
    if any(
        s in lower
        for s in (
            "not logged in",
            "please run /login",
            "expired",
            "unauthorized",
            "authentication required",
        )
    ):
        raise UsageError(
            "auth_required", "Claude login required; use /auth claude in Pobudka"
        )
    if data.get("local_command") != "usage" or data.get("is_error") is not False:
        raise UsageError("invalid_output", "Claude did not execute local /usage")
    if any(
        data.get(k) != 0 for k in ("duration_api_ms", "num_turns", "total_cost_usd")
    ):
        raise UsageError(
            "inference_detected", "Claude usage read was not inference-free"
        )

    def nonzero_tokens(obj: object) -> bool:
        if isinstance(obj, dict):
            return any(
                ("token" in k and isinstance(v, (int, float)) and v != 0)
                or nonzero_tokens(v)
                for k, v in obj.items()
            )
        if isinstance(obj, list):
            return any(nonzero_tokens(v) for v in obj)
        return False

    if nonzero_tokens(data.get("usage", {})) or data.get("modelUsage"):
        raise UsageError(
            "inference_detected", "Claude usage read reported inference tokens"
        )
    windows = {}
    for label, key in (
        ("Current session", "primary"),
        ("Current week (all models)", "weekly"),
    ):
        match = re.search(
            r"^"
            + re.escape(label)
            + r":\s*(\d+(?:\.\d+)?)% used(?:\s*[·•]\s*resets\s+(.+))?\s*$",
            text,
            re.MULTILINE | re.IGNORECASE,
        )
        if match:
            windows[key] = UsageWindow(
                percentage(float(match[1])),
                parse_reset(match[2], now) if match[2] else None,
            )
    if not windows and ("subscription" in lower or "total cost:" in lower):
        raise UsageError(
            "auth_required",
            "Claude returned no subscription quotas; a full Claude subscription login is required",
        )
    if not windows:
        raise UsageError("invalid_output", "Claude subscription output format changed")
    for label in ("Current session:", "Current week (all models):"):
        if label in text and not re.search(
            r"^" + re.escape(label) + r"\s*\d+(?:\.\d+)?% used", text, re.MULTILINE
        ):
            raise UsageError("invalid_output", "Claude quota output format changed")
    return SubscriptionUsage(**windows)


def parse_codex_usage(data: dict) -> SubscriptionUsage:
    """Select Codex's bucket and classify windows by duration, not position."""
    buckets = data.get("rateLimitsByLimitId")
    bucket = (
        buckets.get("codex") if isinstance(buckets, dict) else data.get("rateLimits")
    )
    if not isinstance(bucket, dict) or bucket.get("limitId") not in (None, "codex"):
        raise UsageError("invalid_output", "Codex subscription bucket is unavailable")
    windows = {}
    for slot in ("primary", "secondary"):
        window = bucket.get(slot)
        if window is None:
            continue
        duration = window.get("windowDurationMins")
        key = {300: "primary", 10080: "weekly"}.get(duration)
        if key is None:
            continue
        if key in windows:
            raise UsageError("invalid_output", "Ambiguous Codex quota windows")
        reset = window.get("resetsAt")
        try:
            instant = (
                utc_iso(datetime.fromtimestamp(reset, UTC))
                if reset is not None
                else None
            )
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            raise UsageError("invalid_output", "Invalid Codex reset timestamp") from exc
        windows[key] = UsageWindow(percentage(window.get("usedPercent")), instant)
    if not windows and (bucket.get("primary") or bucket.get("secondary")):
        raise UsageError(
            "invalid_output", "Codex returned unsupported quota window durations"
        )
    return SubscriptionUsage(**windows)
