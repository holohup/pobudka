"""Tests for Codex provider -- all CLI calls are mocked."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.config import ProviderConfig, ResetMode
from src.providers.base import AuthStatus, WakeupFailureKind
from src.providers.codex import CodexProvider
from src.providers.subprocess import CLIResult


@pytest.fixture()
def provider() -> CodexProvider:
    config = ProviderConfig(
        name="codex",
        model="o4-mini",
        wakeup_message="say hi",
        reset_mode=ResetMode.ROLLING,
        window_seconds=18000,
        wake_delay_seconds=2,
    )
    return CodexProvider(config)


# --- check_auth ---


@pytest.mark.asyncio
async def test_check_auth_success(provider):
    result = CLIResult(returncode=0, stdout="Logged in using ChatGPT", stderr="")
    with patch(
        "src.providers.codex.run_cli", new_callable=AsyncMock, return_value=result
    ):
        status = await provider.check_auth()
    assert status == AuthStatus.OK


@pytest.mark.asyncio
async def test_check_auth_not_logged_in(provider):
    result = CLIResult(returncode=1, stdout="Not authenticated", stderr="")
    with patch(
        "src.providers.codex.run_cli", new_callable=AsyncMock, return_value=result
    ):
        status = await provider.check_auth()
    assert status == AuthStatus.NOT_AUTHENTICATED


@pytest.mark.asyncio
async def test_check_auth_error(provider):
    result = CLIResult(returncode=1, stdout="", stderr="something went wrong")
    with patch(
        "src.providers.codex.run_cli", new_callable=AsyncMock, return_value=result
    ):
        status = await provider.check_auth()
    assert status == AuthStatus.ERROR


# --- send_wakeup ---


@pytest.mark.asyncio
async def test_send_wakeup_success(provider):
    jsonl = "\n".join(
        [
            json.dumps({"type": "task.start"}),
            json.dumps({"type": "task.complete", "message": "done"}),
        ]
    )
    result = CLIResult(returncode=0, stdout=jsonl, stderr="")
    with patch(
        "src.providers.codex.run_cli", new_callable=AsyncMock, return_value=result
    ):
        wakeup = await provider.send_wakeup()
    assert wakeup.success


@pytest.mark.asyncio
async def test_send_wakeup_auth_failure(provider):
    jsonl = "\n".join(
        [
            json.dumps(
                {
                    "type": "error",
                    "message": "Your access token could not be refreshed because your refresh token was already used. Please log out and sign in again.",
                }
            ),
            json.dumps(
                {
                    "type": "turn.failed",
                    "error": {
                        "message": "Your access token could not be refreshed because your refresh token was already used. Please log out and sign in again.",
                    },
                }
            ),
        ]
    )
    result = CLIResult(returncode=1, stdout=jsonl, stderr="")
    with patch(
        "src.providers.codex.run_cli", new_callable=AsyncMock, return_value=result
    ):
        wakeup = await provider.send_wakeup()
    assert not wakeup.success
    assert wakeup.failure_kind == WakeupFailureKind.AUTH
    assert "Auth error" in wakeup.message


@pytest.mark.asyncio
async def test_send_wakeup_rate_limited(provider):
    jsonl = json.dumps(
        {
            "type": "error",
            "message": "You've hit your usage limit. Try again in 3 days 1 hour 58 minutes.",
        }
    )
    result = CLIResult(returncode=1, stdout=jsonl, stderr="")
    with patch(
        "src.providers.codex.run_cli", new_callable=AsyncMock, return_value=result
    ):
        wakeup = await provider.send_wakeup()
    assert not wakeup.success
    assert wakeup.failure_kind == WakeupFailureKind.RATE_LIMIT
    assert wakeup.rate_limit_reset is not None
    assert "3 days" in wakeup.rate_limit_reset


@pytest.mark.asyncio
async def test_send_wakeup_timeout(provider):
    result = CLIResult(returncode=-1, stdout="", stderr="Timed out after 60s")
    with patch(
        "src.providers.codex.run_cli", new_callable=AsyncMock, return_value=result
    ):
        wakeup = await provider.send_wakeup()
    assert not wakeup.success
    assert wakeup.failure_kind == WakeupFailureKind.TRANSIENT
    assert "timed out" in wakeup.message.lower()
