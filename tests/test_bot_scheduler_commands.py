"""Tests for bot scheduler command helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.bot import TelegramBot
from src.config import (
    AppConfig,
    ProviderConfig,
    ResetMode,
    SchedulerConfig,
    TelegramConfig,
)
from src.providers.base import WakeupFailureKind, WakeupResult
from src.scheduler import ProviderScheduleState


class DummyScheduler:
    def __init__(
        self,
        *,
        result: WakeupResult | None,
        state: ProviderScheduleState | None,
        status_text: str,
    ) -> None:
        self._result = result
        self._state = state
        self._status_text = status_text
        self.last_triggered: str | None = None
        self.last_scheduled: str | None = None
        self.last_scheduled_at: datetime | None = None

    def format_status(self) -> str:
        return self._status_text

    async def trigger_wakeup(self, provider_name: str) -> WakeupResult | None:
        self.last_triggered = provider_name
        return self._result

    async def schedule_next_wakeup(
        self,
        provider_name: str,
        next_run_at: datetime,
    ) -> ProviderScheduleState | None:
        self.last_scheduled = provider_name
        self.last_scheduled_at = next_run_at
        if self._state is None:
            return None
        self._state.next_run_at = next_run_at
        self._state.weekly_next_run_at = next_run_at
        return self._state

    def reload_provider_config(
        self,
        provider_name: str,
        provider_config: ProviderConfig,
    ) -> bool:
        del provider_config
        return provider_name != "unknown"

    def get_state(self, provider_name: str) -> ProviderScheduleState | None:
        del provider_name
        return self._state


def _build_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        telegram=TelegramConfig(bot_token="12345:test", chat_id="1"),
        scheduler=SchedulerConfig(
            state_path=str(tmp_path / "scheduler_state.json"),
            auth_recheck_seconds=60,
            retry_base_seconds=60,
            retry_max_seconds=3600,
        ),
        providers={},
    )


@pytest.mark.asyncio
async def test_get_schedule_text_without_scheduler(tmp_path: Path) -> None:
    bot = TelegramBot(_build_config(tmp_path), {})
    try:
        assert await bot.get_schedule_text() == "Scheduler is not initialized yet."
    finally:
        await bot.stop()


@pytest.mark.asyncio
async def test_get_schedule_text_with_scheduler(tmp_path: Path) -> None:
    bot = TelegramBot(_build_config(tmp_path), {})
    scheduler = DummyScheduler(result=None, state=None, status_text="scheduler ok")
    bot.set_scheduler(scheduler)  # type: ignore[arg-type]

    try:
        assert await bot.get_schedule_text() == "scheduler ok"
    finally:
        await bot.stop()


@pytest.mark.asyncio
async def test_run_manual_wake_success(tmp_path: Path) -> None:
    bot = TelegramBot(_build_config(tmp_path), {})
    scheduler = DummyScheduler(
        result=WakeupResult(success=True, message="OK"),
        state=ProviderScheduleState(next_run_at=datetime(2026, 2, 10, tzinfo=timezone.utc)),
        status_text="status",
    )
    bot.set_scheduler(scheduler)  # type: ignore[arg-type]

    try:
        text = await bot.run_manual_wake("codex")
        assert "wake-up succeeded" in text
        assert "Next run:" in text
        assert scheduler.last_triggered == "codex"
    finally:
        await bot.stop()


@pytest.mark.asyncio
async def test_run_manual_wake_failure(tmp_path: Path) -> None:
    bot = TelegramBot(_build_config(tmp_path), {})
    scheduler = DummyScheduler(
        result=WakeupResult(
            success=False,
            message="rate limit",
            failure_kind=WakeupFailureKind.RATE_LIMIT,
        ),
        state=ProviderScheduleState(next_run_at=datetime(2026, 2, 10, tzinfo=timezone.utc)),
        status_text="status",
    )
    bot.set_scheduler(scheduler)  # type: ignore[arg-type]

    try:
        text = await bot.run_manual_wake("codex")
        assert "wake-up failed (rate_limit)" in text
        assert "Message: rate limit" in text
    finally:
        await bot.stop()


@pytest.mark.asyncio
async def test_run_manual_wake_unknown_provider(tmp_path: Path) -> None:
    bot = TelegramBot(_build_config(tmp_path), {})
    scheduler = DummyScheduler(result=None, state=None, status_text="status")
    bot.set_scheduler(scheduler)  # type: ignore[arg-type]

    try:
        text = await bot.run_manual_wake("unknown")
        assert text == "Unknown provider: unknown"
    finally:
        await bot.stop()


@pytest.mark.asyncio
async def test_schedule_wake_at_israel_time_success(tmp_path: Path) -> None:
    bot = TelegramBot(_build_config(tmp_path), {})
    state = ProviderScheduleState(next_run_at=datetime(2026, 2, 10, tzinfo=timezone.utc))
    scheduler = DummyScheduler(result=None, state=state, status_text="status")
    bot.set_scheduler(scheduler)  # type: ignore[arg-type]

    provider_cfg = ProviderConfig(
        name="codex",
        model="gpt-5.1-codex-mini",
        wakeup_message="say hi",
        reset_mode=ResetMode.ROLLING,
        window_seconds=18000,
        wake_delay_seconds=10,
        weekly_window_seconds=604800,
        weekly_wake_delay_seconds=10,
    )
    refreshed_config = AppConfig(
        telegram=TelegramConfig(bot_token="12345:test", chat_id="1"),
        scheduler=SchedulerConfig(
            state_path=str(tmp_path / "scheduler_state.json"),
            auth_recheck_seconds=60,
            retry_base_seconds=60,
            retry_max_seconds=3600,
        ),
        providers={"codex": provider_cfg},
    )

    target = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    bot._next_israel_occurrence = lambda _text: (target, False)  # type: ignore[assignment]

    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("src.bot.load_config", lambda: refreshed_config)
            text = await bot.schedule_wake_at_israel_time("codex", "12:00")
        assert "next reset scheduled" in text
        assert scheduler.last_scheduled == "codex"
        assert scheduler.last_scheduled_at == target
    finally:
        await bot.stop()


@pytest.mark.asyncio
async def test_schedule_wake_at_israel_time_invalid_format(tmp_path: Path) -> None:
    bot = TelegramBot(_build_config(tmp_path), {})
    scheduler = DummyScheduler(
        result=None,
        state=ProviderScheduleState(next_run_at=datetime(2026, 2, 10, tzinfo=timezone.utc)),
        status_text="status",
    )
    bot.set_scheduler(scheduler)  # type: ignore[arg-type]

    provider_cfg = ProviderConfig(
        name="codex",
        model="gpt-5.1-codex-mini",
        wakeup_message="say hi",
        reset_mode=ResetMode.ROLLING,
        window_seconds=18000,
        wake_delay_seconds=10,
        weekly_window_seconds=604800,
        weekly_wake_delay_seconds=10,
    )
    refreshed_config = AppConfig(
        telegram=TelegramConfig(bot_token="12345:test", chat_id="1"),
        scheduler=SchedulerConfig(
            state_path=str(tmp_path / "scheduler_state.json"),
            auth_recheck_seconds=60,
            retry_base_seconds=60,
            retry_max_seconds=3600,
        ),
        providers={"codex": provider_cfg},
    )

    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("src.bot.load_config", lambda: refreshed_config)
            text = await bot.schedule_wake_at_israel_time("codex", "99:99")
        assert "Invalid time format" in text
    finally:
        await bot.stop()
