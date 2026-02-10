"""Tests for bot scheduler command helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.bot import TelegramBot
from src.config import (
    AppConfig,
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

    def format_status(self) -> str:
        return self._status_text

    async def trigger_wakeup(self, provider_name: str) -> WakeupResult | None:
        self.last_triggered = provider_name
        return self._result

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
