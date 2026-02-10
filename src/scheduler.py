"""Async per-provider wake-up scheduler."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from src.config import AppConfig, ProviderConfig, ResetMode
from src.providers.base import AuthStatus, Provider, WakeupFailureKind, WakeupResult

logger = logging.getLogger(__name__)

_DURATION_PART_RE = re.compile(
    r"(?P<value>\d+)\s*(?P<unit>day|days|hour|hours|minute|minutes|second|seconds)",
    re.IGNORECASE,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def compute_next_run(provider_config: ProviderConfig, success_at: datetime) -> datetime:
    """Compute the next wake-up timestamp after a successful wake-up."""
    success_at = _ensure_utc(success_at)

    if provider_config.reset_mode == ResetMode.ROLLING:
        return success_at + timedelta(
            seconds=provider_config.window_seconds + provider_config.wake_delay_seconds
        )

    if provider_config.reset_mode == ResetMode.CLOCK_ALIGNED_HOUR:
        anchor = success_at.replace(minute=0, second=0, microsecond=0)
        return anchor + timedelta(
            seconds=provider_config.window_seconds + provider_config.wake_delay_seconds
        )

    raise ValueError(f"Unsupported reset mode: {provider_config.reset_mode!r}")


def parse_duration_seconds(text: str | None) -> int | None:
    """Parse human-readable duration snippets from provider CLI output."""
    if not text:
        return None

    total = 0
    matches = list(_DURATION_PART_RE.finditer(text))
    if not matches:
        return None

    for match in matches:
        value = int(match.group("value"))
        unit = match.group("unit").lower()
        if unit.startswith("day"):
            total += value * 24 * 60 * 60
        elif unit.startswith("hour"):
            total += value * 60 * 60
        elif unit.startswith("minute"):
            total += value * 60
        else:
            total += value

    return total if total > 0 else None


def format_time(value: datetime | None) -> str:
    if value is None:
        return "-"
    return _ensure_utc(value).strftime("%Y-%m-%d %H:%M:%SZ")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _serialize_time(value: datetime | None) -> str | None:
    return _ensure_utc(value).isoformat() if value is not None else None


def _parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    return _ensure_utc(datetime.fromisoformat(value))


@dataclass
class ProviderScheduleState:
    next_run_at: datetime
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    consecutive_failures: int = 0
    paused_reason: str | None = None
    backoff_until: datetime | None = None


class WakeupScheduler:
    """Coordinates provider wake-up requests according to policy."""

    def __init__(
        self,
        config: AppConfig,
        providers: dict[str, Provider],
        notify: Callable[[str], Awaitable[None]],
        request_auth: Callable[[str], Awaitable[None]],
    ) -> None:
        self._config = config
        self._providers = providers
        self._notify = notify
        self._request_auth = request_auth

        self._state_path = Path(config.scheduler.state_path)
        self._states: dict[str, ProviderScheduleState] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._provider_locks = {name: asyncio.Lock() for name in providers}
        self._state_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._started = False

    async def start(self) -> None:
        """Load state and spawn one worker loop per provider."""
        if self._started:
            return

        self._stop_event.clear()
        loaded = self._load_state()
        now = utc_now()

        for name in self._providers:
            state = loaded.get(name)
            if state is None:
                provider_config = self._config.providers[name]
                state = ProviderScheduleState(
                    next_run_at=now
                    + timedelta(seconds=provider_config.wake_delay_seconds)
                )
            self._states[name] = state
            self._tasks[name] = asyncio.create_task(self._provider_loop(name))

        self._started = True
        await self._persist_state()
        logger.info("Scheduler started with providers: %s", ", ".join(self._providers))

    async def stop(self) -> None:
        """Stop worker loops and persist current state."""
        if not self._started:
            return

        self._stop_event.set()

        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

        self._tasks.clear()
        await self._persist_state()
        self._started = False
        logger.info("Scheduler stopped")

    def format_status(self) -> str:
        """Render a human-readable scheduler snapshot for Telegram."""
        lines = ["<b>Scheduler</b>"]
        for name in sorted(self._providers):
            state = self._states.get(name)
            if state is None:
                lines.append(f"{name}: not initialized")
                continue

            status = "paused(auth_required)" if state.paused_reason else "active"
            lines.append(
                f"{name}: {status} | next={format_time(state.next_run_at)} "
                f"| last_ok={format_time(state.last_success_at)} "
                f"| failures={state.consecutive_failures}"
            )
        return "\n".join(lines)

    def get_state(self, provider_name: str) -> ProviderScheduleState | None:
        """Return a copy of in-memory schedule state for one provider."""
        state = self._states.get(provider_name)
        return replace(state) if state is not None else None

    async def trigger_wakeup(self, provider_name: str) -> WakeupResult | None:
        """Force an immediate wake-up attempt for one provider."""
        if provider_name not in self._providers:
            return None
        if provider_name not in self._states:
            provider_config = self._config.providers[provider_name]
            self._states[provider_name] = ProviderScheduleState(
                next_run_at=utc_now() + timedelta(seconds=provider_config.wake_delay_seconds)
            )
        return await self._attempt_wakeup(provider_name, triggered_by_user=True)

    async def _provider_loop(self, provider_name: str) -> None:
        provider = self._providers[provider_name]
        auth_wait = self._config.scheduler.auth_recheck_seconds

        while not self._stop_event.is_set():
            try:
                state = self._states[provider_name]
                now = utc_now()

                if state.paused_reason == "auth_required":
                    status = await provider.check_auth()
                    if status == AuthStatus.OK:
                        state.paused_reason = None
                        state.consecutive_failures = 0
                        state.backoff_until = None
                        state.next_run_at = now
                        await self._persist_state()
                        await self._safe_notify(
                            f"{provider.name}: authentication restored, "
                            "resuming wake-up schedule."
                        )
                    else:
                        state.next_run_at = now + timedelta(seconds=auth_wait)
                        await self._persist_state()
                        await self._sleep_or_stop(auth_wait)
                        continue

                delay_seconds = (state.next_run_at - now).total_seconds()
                if delay_seconds > 0:
                    await self._sleep_or_stop(delay_seconds)
                    continue

                await self._attempt_wakeup(provider_name, triggered_by_user=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler loop crashed for provider %s", provider_name)
                await self._sleep_or_stop(5)

    async def _attempt_wakeup(
        self,
        provider_name: str,
        *,
        triggered_by_user: bool,
    ) -> WakeupResult:
        provider = self._providers[provider_name]
        provider_config = self._config.providers[provider_name]

        async with self._provider_locks[provider_name]:
            state = self._states[provider_name]
            now = utc_now()
            state.last_attempt_at = now

            try:
                result = await provider.send_wakeup()
            except Exception as exc:  # defensive: provider wrappers should not raise
                logger.exception("Wake-up command raised for provider %s", provider_name)
                result = WakeupResult(
                    success=False,
                    message=f"Unhandled wake-up error: {exc}",
                    failure_kind=WakeupFailureKind.TRANSIENT,
                )

            if result.success:
                had_recovery = (
                    state.paused_reason is not None or state.consecutive_failures > 0
                )
                state.last_success_at = now
                state.consecutive_failures = 0
                state.paused_reason = None
                state.backoff_until = None
                state.next_run_at = compute_next_run(provider_config, now)
                await self._persist_state()

                if triggered_by_user or had_recovery:
                    await self._safe_notify(
                        f"{provider.name}: wake-up successful. "
                        f"Next run at {format_time(state.next_run_at)}."
                    )
                return result

            kind = (
                result.failure_kind
                if result.failure_kind != WakeupFailureKind.NONE
                else WakeupFailureKind.TRANSIENT
            )

            if kind == WakeupFailureKind.AUTH:
                newly_paused = state.paused_reason != "auth_required"
                state.paused_reason = "auth_required"
                state.consecutive_failures += 1
                state.backoff_until = None
                state.next_run_at = now + timedelta(
                    seconds=self._config.scheduler.auth_recheck_seconds
                )
                await self._persist_state()

                if newly_paused or triggered_by_user:
                    await self._safe_notify(
                        f"{provider.name}: authentication required. "
                        "Scheduler is paused until auth is restored."
                    )

                try:
                    await self._request_auth(provider_name)
                except Exception:
                    logger.exception(
                        "Failed to trigger device auth for provider %s", provider_name
                    )
                return result

            if kind == WakeupFailureKind.RATE_LIMIT:
                reset_seconds = parse_duration_seconds(result.rate_limit_reset)
                if reset_seconds is None:
                    reset_seconds = provider_config.window_seconds

                state.consecutive_failures = 0
                state.paused_reason = None
                state.backoff_until = None
                state.next_run_at = now + timedelta(
                    seconds=reset_seconds + provider_config.wake_delay_seconds
                )
                await self._persist_state()

                if triggered_by_user:
                    await self._safe_notify(
                        f"{provider.name}: rate limited. "
                        f"Next retry at {format_time(state.next_run_at)}."
                    )
                return result

            state.consecutive_failures += 1
            backoff_seconds = min(
                self._config.scheduler.retry_base_seconds
                * (2 ** (state.consecutive_failures - 1)),
                self._config.scheduler.retry_max_seconds,
            )
            state.backoff_until = now + timedelta(seconds=backoff_seconds)
            state.next_run_at = state.backoff_until
            await self._persist_state()

            if triggered_by_user or state.consecutive_failures in (1, 3, 5):
                await self._safe_notify(
                    f"{provider.name}: wake-up failed ({result.message[:120]}). "
                    f"Retrying in {backoff_seconds}s."
                )
            return result

    async def _sleep_or_stop(self, seconds: float) -> None:
        if seconds <= 0:
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return

    async def _safe_notify(self, message: str) -> None:
        try:
            await self._notify(message)
        except Exception:
            logger.exception("Failed to send scheduler notification")

    def _default_state(self, provider_name: str) -> ProviderScheduleState:
        now = utc_now()
        provider_config = self._config.providers[provider_name]
        return ProviderScheduleState(
            next_run_at=now + timedelta(seconds=provider_config.wake_delay_seconds)
        )

    def _load_state(self) -> dict[str, ProviderScheduleState]:
        if not self._state_path.exists():
            return {}

        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "Could not read scheduler state from %s, using defaults",
                self._state_path,
            )
            return {}

        providers_payload = payload.get("providers")
        if not isinstance(providers_payload, dict):
            logger.warning("Scheduler state format invalid, using defaults")
            return {}

        loaded: dict[str, ProviderScheduleState] = {}
        for name, state_data in providers_payload.items():
            if name not in self._providers:
                continue
            if not isinstance(state_data, dict):
                continue

            try:
                next_run_at = _parse_time(state_data.get("next_run_at"))
                if next_run_at is None:
                    raise ValueError("next_run_at is required")

                loaded[name] = ProviderScheduleState(
                    next_run_at=next_run_at,
                    last_success_at=_parse_time(state_data.get("last_success_at")),
                    last_attempt_at=_parse_time(state_data.get("last_attempt_at")),
                    consecutive_failures=int(state_data.get("consecutive_failures", 0)),
                    paused_reason=state_data.get("paused_reason"),
                    backoff_until=_parse_time(state_data.get("backoff_until")),
                )
            except (TypeError, ValueError):
                logger.warning("Invalid scheduler state for provider %s, using default", name)

        return loaded

    async def _persist_state(self) -> None:
        async with self._state_lock:
            payload = {
                "schema_version": 1,
                "providers": {
                    name: {
                        "next_run_at": _serialize_time(state.next_run_at),
                        "last_success_at": _serialize_time(state.last_success_at),
                        "last_attempt_at": _serialize_time(state.last_attempt_at),
                        "consecutive_failures": state.consecutive_failures,
                        "paused_reason": state.paused_reason,
                        "backoff_until": _serialize_time(state.backoff_until),
                    }
                    for name, state in self._states.items()
                },
            }

            try:
                self._state_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = self._state_path.with_suffix(
                    f"{self._state_path.suffix}.tmp"
                )
                tmp_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                os.replace(tmp_path, self._state_path)
            except OSError:
                logger.exception("Failed to persist scheduler state to %s", self._state_path)

