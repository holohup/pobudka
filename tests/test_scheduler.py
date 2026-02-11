"""Tests for wake-up scheduler behavior."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.config import (
    AppConfig,
    ProviderConfig,
    ResetMode,
    SchedulerConfig,
    TelegramConfig,
)
from src.providers.base import AuthStatus, DeviceCodeInfo, WakeupFailureKind, WakeupResult
from src.scheduler import (
    ProviderScheduleState,
    WakeupScheduler,
    compute_next_run,
    compute_next_weekly_run,
    parse_duration_seconds,
)


class FakeProvider:
    """Simple fake provider used by scheduler tests."""

    def __init__(
        self,
        name: str,
        wakeup_results: list[WakeupResult] | None = None,
        auth_statuses: list[AuthStatus] | None = None,
    ) -> None:
        self._name = name
        self._wakeup_results = deque(wakeup_results or [])
        self._auth_statuses = deque(auth_statuses or [AuthStatus.OK])
        self.send_calls = 0
        self.check_calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def check_auth(self) -> AuthStatus:
        self.check_calls += 1
        if len(self._auth_statuses) > 1:
            return self._auth_statuses.popleft()
        return self._auth_statuses[0]

    async def send_wakeup(self) -> WakeupResult:
        self.send_calls += 1
        if self._wakeup_results:
            return self._wakeup_results.popleft()
        return WakeupResult(success=True, message="ok")

    async def start_device_auth(self) -> DeviceCodeInfo | None:
        return None

    async def wait_for_device_auth(self) -> bool:
        return False

    async def cancel_device_auth(self) -> None:
        return None


def _build_app_config(
    state_path: Path,
    provider_config: ProviderConfig,
    *,
    auth_recheck_seconds: int = 1,
    retry_base_seconds: int = 1,
    retry_max_seconds: int = 8,
) -> AppConfig:
    return AppConfig(
        telegram=TelegramConfig(bot_token="12345:test", chat_id="1"),
        scheduler=SchedulerConfig(
            state_path=str(state_path),
            auth_recheck_seconds=auth_recheck_seconds,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        ),
        providers={provider_config.name: provider_config},
    )


def _rolling_provider_config(name: str = "codex", *, wake_delay_seconds: int = 0) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        model="o4-mini",
        wakeup_message="say hi",
        reset_mode=ResetMode.ROLLING,
        window_seconds=18000,
        wake_delay_seconds=wake_delay_seconds,
    )


def test_compute_next_run_rolling() -> None:
    cfg = _rolling_provider_config(wake_delay_seconds=2)
    success_at = datetime(2026, 2, 10, 10, 13, 0, tzinfo=timezone.utc)
    assert compute_next_run(cfg, success_at) == datetime(
        2026,
        2,
        10,
        15,
        13,
        2,
        tzinfo=timezone.utc,
    )


def test_compute_next_run_clock_aligned() -> None:
    cfg = ProviderConfig(
        name="claude",
        model="claude-sonnet-4-5-20250929",
        wakeup_message="hi",
        reset_mode=ResetMode.CLOCK_ALIGNED_HOUR,
        window_seconds=18000,
        wake_delay_seconds=2,
    )
    success_at = datetime(2026, 2, 10, 10, 13, 0, tzinfo=timezone.utc)
    assert compute_next_run(cfg, success_at) == datetime(
        2026,
        2,
        10,
        15,
        0,
        2,
        tzinfo=timezone.utc,
    )


def test_compute_next_weekly_run() -> None:
    cfg = _rolling_provider_config(wake_delay_seconds=10)
    success_at = datetime(2026, 2, 10, 10, 13, 0, tzinfo=timezone.utc)
    assert compute_next_weekly_run(cfg, success_at) == datetime(
        2026,
        2,
        17,
        10,
        13,
        10,
        tzinfo=timezone.utc,
    )


def test_parse_duration_seconds() -> None:
    assert parse_duration_seconds("Try again in 3 days 1 hour 58 minutes") == (
        3 * 24 * 60 * 60 + 1 * 60 * 60 + 58 * 60
    )
    assert parse_duration_seconds("no duration present") is None


@pytest.mark.asyncio
async def test_transient_failure_exponential_backoff(tmp_path: Path) -> None:
    provider_cfg = _rolling_provider_config(wake_delay_seconds=3600)
    config = _build_app_config(tmp_path / "state.json", provider_cfg)

    provider = FakeProvider(
        "Codex",
        wakeup_results=[
            WakeupResult(
                success=False,
                message="network error",
                failure_kind=WakeupFailureKind.TRANSIENT,
            ),
            WakeupResult(
                success=False,
                message="still broken",
                failure_kind=WakeupFailureKind.TRANSIENT,
            ),
        ],
    )

    notifications: list[str] = []
    auth_requests: list[str] = []

    scheduler = WakeupScheduler(
        config=config,
        providers={"codex": provider},
        notify=lambda text: _append_async(notifications, text),
        request_auth=lambda name: _append_async(auth_requests, name),
    )

    await scheduler.start()
    try:
        await scheduler.trigger_wakeup("codex")
        state1 = scheduler.get_state("codex")
        assert state1 is not None
        assert state1.consecutive_failures == 1
        assert state1.backoff_until is not None
        assert state1.last_attempt_at is not None
        delta1 = (state1.next_run_at - state1.last_attempt_at).total_seconds()
        assert 0.5 <= delta1 <= 1.5

        await scheduler.trigger_wakeup("codex")
        state2 = scheduler.get_state("codex")
        assert state2 is not None
        assert state2.consecutive_failures == 2
        assert state2.last_attempt_at is not None
        delta2 = (state2.next_run_at - state2.last_attempt_at).total_seconds()
        assert 1.5 <= delta2 <= 2.5

        assert auth_requests == []
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_auth_failure_triggers_single_auto_auth_request(tmp_path: Path) -> None:
    provider_cfg = _rolling_provider_config(wake_delay_seconds=0)
    config = _build_app_config(tmp_path / "state.json", provider_cfg)

    provider = FakeProvider(
        "Codex",
        wakeup_results=[
            WakeupResult(
                success=False,
                message="expired token",
                failure_kind=WakeupFailureKind.AUTH,
            ),
            WakeupResult(
                success=False,
                message="still expired",
                failure_kind=WakeupFailureKind.AUTH,
            ),
            WakeupResult(success=True, message="ok"),
        ],
    )

    notifications: list[str] = []
    auth_requests: list[str] = []

    scheduler = WakeupScheduler(
        config=config,
        providers={"codex": provider},
        notify=lambda text: _append_async(notifications, text),
        request_auth=lambda name: _append_async(auth_requests, name),
    )

    await scheduler.start()
    try:
        await scheduler.trigger_wakeup("codex")
        state1 = scheduler.get_state("codex")
        assert state1 is not None
        assert state1.paused_reason == "auth_required"
        assert state1.auth_request_sent
        assert auth_requests == ["codex"]

        await scheduler.trigger_wakeup("codex")
        state2 = scheduler.get_state("codex")
        assert state2 is not None
        assert state2.auth_request_sent
        # No repeated automatic /auth triggers.
        assert auth_requests == ["codex"]

        await scheduler.trigger_wakeup("codex")
        state3 = scheduler.get_state("codex")
        assert state3 is not None
        assert state3.paused_reason is None
        assert not state3.auth_request_sent
        assert state3.last_success_at is not None
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_recover_overdue_provider_from_persisted_state(tmp_path: Path) -> None:
    state_path = tmp_path / "scheduler_state.json"
    now = datetime.now(timezone.utc)

    # Persist a stale schedule in the past to force immediate wake-up.
    state_path.write_text(
        (
            '{"schema_version":1,"providers":{"codex":'
            f'{{"next_run_at":"{(now - timedelta(seconds=5)).isoformat()}",' 
            '"last_success_at":null,"last_attempt_at":null,'
            '"consecutive_failures":0,"paused_reason":null,"backoff_until":null}}}'
        ),
        encoding="utf-8",
    )

    provider_cfg = _rolling_provider_config(wake_delay_seconds=3600)
    config = _build_app_config(state_path, provider_cfg)
    provider = FakeProvider("Codex", wakeup_results=[WakeupResult(success=True, message="ok")])

    scheduler = WakeupScheduler(
        config=config,
        providers={"codex": provider},
        notify=lambda text: _append_async([], text),
        request_auth=lambda name: _append_async([], name),
    )

    await scheduler.start()
    try:
        await asyncio.sleep(0.2)
        state = scheduler.get_state("codex")
        assert state is not None
        assert provider.send_calls >= 1
        assert state.last_attempt_at is not None
        assert state.last_success_at is not None
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_corrupt_state_file_falls_back_to_defaults(tmp_path: Path) -> None:
    state_path = tmp_path / "scheduler_state.json"
    state_path.write_text("not-json", encoding="utf-8")

    provider_cfg = _rolling_provider_config(wake_delay_seconds=10)
    config = _build_app_config(state_path, provider_cfg)
    provider = FakeProvider("Codex")

    scheduler = WakeupScheduler(
        config=config,
        providers={"codex": provider},
        notify=lambda text: _append_async([], text),
        request_auth=lambda name: _append_async([], name),
    )

    await scheduler.start()
    try:
        state = scheduler.get_state("codex")
        assert isinstance(state, ProviderScheduleState)
        assert state is not None
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_schedule_next_wakeup_sets_both_timers(tmp_path: Path) -> None:
    provider_cfg = _rolling_provider_config(wake_delay_seconds=10)
    config = _build_app_config(tmp_path / "state.json", provider_cfg)
    provider = FakeProvider("Codex")
    scheduler = WakeupScheduler(
        config=config,
        providers={"codex": provider},
        notify=lambda text: _append_async([], text),
        request_auth=lambda name: _append_async([], name),
    )

    await scheduler.start()
    try:
        target = datetime(2026, 2, 11, 12, 0, tzinfo=timezone.utc)
        state = await scheduler.schedule_next_wakeup("codex", target)
        assert state is not None
        assert state.next_run_at == target
        assert state.weekly_next_run_at == target
    finally:
        await scheduler.stop()


async def _append_async(target: list[str], value: str) -> None:
    target.append(value)
