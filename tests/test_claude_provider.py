"""Tests for Claude provider -- all CLI calls are mocked."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.config import ProviderConfig, ResetMode
from src.providers.base import AuthStatus, WakeupFailureKind
from src.providers.claude import ClaudeProvider
from src.providers.subprocess import CLIResult


@pytest.fixture()
def provider() -> ClaudeProvider:
    config = ProviderConfig(
        name="claude",
        model="test-model",
        wakeup_message="hi",
        reset_mode=ResetMode.CLOCK_ALIGNED_HOUR,
        window_seconds=18000,
        wake_delay_seconds=2,
    )
    return ClaudeProvider(config)


# --- check_auth ---


@pytest.mark.asyncio
async def test_check_auth_success(provider):
    result = CLIResult(
        returncode=0,
        stdout=json.dumps({"is_error": False, "result": "hello"}),
        stderr="",
    )
    with patch(
        "src.providers.claude.run_cli", new_callable=AsyncMock, return_value=result
    ):
        status = await provider.check_auth()
    assert status == AuthStatus.OK


@pytest.mark.asyncio
async def test_check_auth_invalid_key(provider):
    result = CLIResult(
        returncode=0,
        stdout=json.dumps(
            {"is_error": True, "result": "Invalid API key · Fix external API key"}
        ),
        stderr="",
    )
    with patch(
        "src.providers.claude.run_cli", new_callable=AsyncMock, return_value=result
    ):
        status = await provider.check_auth()
    assert status == AuthStatus.NOT_AUTHENTICATED


@pytest.mark.asyncio
async def test_check_auth_timeout(provider):
    result = CLIResult(returncode=-1, stdout="", stderr="Timed out after 30s")
    with patch(
        "src.providers.claude.run_cli", new_callable=AsyncMock, return_value=result
    ):
        status = await provider.check_auth()
    assert status == AuthStatus.ERROR


@pytest.mark.asyncio
async def test_check_auth_non_json_auth_error(provider):
    result = CLIResult(returncode=1, stdout="please log in first", stderr="")
    with patch(
        "src.providers.claude.run_cli", new_callable=AsyncMock, return_value=result
    ):
        status = await provider.check_auth()
    assert status == AuthStatus.NOT_AUTHENTICATED


# --- send_wakeup ---


@pytest.mark.asyncio
async def test_send_wakeup_success(provider):
    result = CLIResult(
        returncode=0,
        stdout=json.dumps(
            {"is_error": False, "result": "hi there!", "total_cost_usd": 0.01}
        ),
        stderr="",
    )
    with patch(
        "src.providers.claude.run_cli", new_callable=AsyncMock, return_value=result
    ):
        wakeup = await provider.send_wakeup()
    assert wakeup.success
    assert "hi there!" in wakeup.message


@pytest.mark.asyncio
async def test_send_wakeup_rate_limited(provider):
    result = CLIResult(
        returncode=0,
        stdout=json.dumps(
            {
                "is_error": True,
                "result": "Claude usage limit reached. Your limit will reset in 3 hours 42 minutes.",
            }
        ),
        stderr="",
    )
    with patch(
        "src.providers.claude.run_cli", new_callable=AsyncMock, return_value=result
    ):
        wakeup = await provider.send_wakeup()
    assert not wakeup.success
    assert wakeup.failure_kind == WakeupFailureKind.RATE_LIMIT
    assert wakeup.rate_limit_reset is not None
    assert "3 hours" in wakeup.rate_limit_reset


@pytest.mark.asyncio
async def test_send_wakeup_auth_error(provider):
    result = CLIResult(
        returncode=0,
        stdout=json.dumps({"is_error": True, "result": "Invalid API key"}),
        stderr="",
    )
    with patch(
        "src.providers.claude.run_cli", new_callable=AsyncMock, return_value=result
    ):
        wakeup = await provider.send_wakeup()
    assert not wakeup.success
    assert wakeup.failure_kind == WakeupFailureKind.AUTH
    assert "Auth error" in wakeup.message


@pytest.mark.asyncio
async def test_send_wakeup_timeout(provider):
    result = CLIResult(returncode=-1, stdout="", stderr="Timed out after 60s")
    with patch(
        "src.providers.claude.run_cli", new_callable=AsyncMock, return_value=result
    ):
        wakeup = await provider.send_wakeup()
    assert not wakeup.success
    assert wakeup.failure_kind == WakeupFailureKind.TRANSIENT
    assert "timed out" in wakeup.message.lower()
