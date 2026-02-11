"""Tests for configuration loading."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.config import AppConfig, ResetMode, load_config


@pytest.fixture()
def _env_vars():
    """Provide minimal valid environment variables."""
    env = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "12345",
        "ENABLED_PROVIDERS": "claude,codex",
    }
    with patch.dict(os.environ, env, clear=False):
        yield


def test_load_config_with_defaults(_env_vars):
    config = load_config()
    assert config.telegram.bot_token == "test-token"
    assert config.telegram.chat_id == "12345"
    assert config.scheduler.state_path == "data/scheduler_state.json"
    assert config.scheduler.retry_base_seconds == 60
    assert config.scheduler.retry_max_seconds == 3600
    assert "claude" in config.providers
    assert "codex" in config.providers
    assert config.providers["claude"].wakeup_message == "hi"
    assert config.providers["codex"].wakeup_message == "say hi"
    assert config.providers["claude"].reset_mode == ResetMode.CLOCK_ALIGNED_HOUR
    assert config.providers["codex"].reset_mode == ResetMode.ROLLING
    assert config.providers["claude"].wake_delay_seconds == 10
    assert config.providers["codex"].wake_delay_seconds == 10
    assert config.providers["claude"].weekly_window_seconds == 604800
    assert config.providers["codex"].weekly_window_seconds == 604800
    assert config.providers["claude"].weekly_wake_delay_seconds == 10
    assert config.providers["codex"].weekly_wake_delay_seconds == 10


def test_load_config_custom_model(_env_vars):
    with patch.dict(os.environ, {"CLAUDE_MODEL": "custom-model"}):
        config = load_config()
    assert config.providers["claude"].model == "custom-model"


def test_load_config_invalid_reset_mode(_env_vars):
    with patch.dict(os.environ, {"CLAUDE_RESET_MODE": "weird"}):
        with pytest.raises(RuntimeError, match="CLAUDE_RESET_MODE"):
            load_config()


def test_load_config_scheduler_retry_bounds(_env_vars):
    with patch.dict(
        os.environ,
        {
            "SCHEDULER_RETRY_BASE_SECONDS": "120",
            "SCHEDULER_RETRY_MAX_SECONDS": "60",
        },
    ):
        with pytest.raises(RuntimeError, match="SCHEDULER_RETRY_MAX_SECONDS"):
            load_config()


def test_load_config_missing_telegram_token():
    with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "12345"}, clear=True):
        with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
            load_config()


def test_load_config_single_provider():
    env = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "TELEGRAM_CHAT_ID": "123",
        "ENABLED_PROVIDERS": "claude",
    }
    with patch.dict(os.environ, env, clear=True):
        config = load_config()
    assert list(config.providers.keys()) == ["claude"]


def test_load_config_maps_legacy_claude_token_name():
    env = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "TELEGRAM_CHAT_ID": "123",
        "ENABLED_PROVIDERS": "claude",
        "CLAUDE_AUTH_TOKEN": "legacy-token",
    }
    with patch.dict(os.environ, env, clear=True):
        load_config()
        assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "legacy-token"


def test_load_config_prefers_new_claude_token_name():
    env = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "TELEGRAM_CHAT_ID": "123",
        "ENABLED_PROVIDERS": "claude",
        "CLAUDE_AUTH_TOKEN": "legacy-token",
        "CLAUDE_CODE_OAUTH_TOKEN": "new-token",
    }
    with patch.dict(os.environ, env, clear=True):
        load_config()
        assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "new-token"
