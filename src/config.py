"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class ProviderConfig:
    """Per-provider configuration."""

    name: str
    model: str
    wakeup_message: str
    reset_mode: "ResetMode"
    window_seconds: int
    wake_delay_seconds: int
    weekly_window_seconds: int = 7 * 24 * 60 * 60
    weekly_wake_delay_seconds: int = 10


class ResetMode(str, Enum):
    ROLLING = "rolling"
    CLOCK_ALIGNED_HOUR = "clock_aligned_hour"


@dataclass(frozen=True)
class SchedulerConfig:
    state_path: str
    auth_recheck_seconds: int
    retry_base_seconds: int
    retry_max_seconds: int


@dataclass(frozen=True)
class AppConfig:
    telegram: TelegramConfig
    scheduler: SchedulerConfig
    providers: dict[str, ProviderConfig] = field(default_factory=dict)


_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "claude": {
        "model": "claude-sonnet-4-5-20250929",
        "wakeup_message": "hi",
        "reset_mode": ResetMode.CLOCK_ALIGNED_HOUR.value,
        "window_seconds": "18000",
        "wake_delay_seconds": "10",
        "weekly_window_seconds": "604800",
        "weekly_wake_delay_seconds": "10",
    },
    "codex": {
        "model": "gpt-5.1-codex-mini",
        "wakeup_message": "say hi",
        "reset_mode": ResetMode.ROLLING.value,
        "window_seconds": "18000",
        "wake_delay_seconds": "10",
        "weekly_window_seconds": "604800",
        "weekly_wake_delay_seconds": "10",
    },
}


def _normalize_env_aliases() -> None:
    """Normalize legacy environment variable names used by CLIs."""
    # Claude CLI expects CLAUDE_CODE_OAUTH_TOKEN. Keep backward compatibility
    # with older setup docs that used CLAUDE_AUTH_TOKEN.
    if "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ:
        legacy = os.environ.get("CLAUDE_AUTH_TOKEN")
        if legacy:
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = legacy


def _env(key: str, default: str | None = None) -> str:
    value = os.environ.get(key, default)
    if value is None:
        raise RuntimeError(f"Required environment variable {key} is not set")
    return value


def _env_int(key: str, default: int, *, minimum: int = 0) -> int:
    raw_value = os.environ.get(key)
    if raw_value is None:
        value = default
    else:
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise RuntimeError(
                f"Environment variable {key} must be an integer, got: {raw_value!r}"
            ) from exc

    if value < minimum:
        raise RuntimeError(f"Environment variable {key} must be >= {minimum}")
    return value


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    _normalize_env_aliases()

    telegram = TelegramConfig(
        bot_token=_env("TELEGRAM_BOT_TOKEN"),
        chat_id=_env("TELEGRAM_CHAT_ID"),
    )

    enabled = [
        name.strip()
        for name in _env("ENABLED_PROVIDERS", "claude,codex").split(",")
        if name.strip()
    ]

    providers: dict[str, ProviderConfig] = {}
    for name in enabled:
        defaults = _PROVIDER_DEFAULTS.get(name, {})
        prefix = name.upper()
        reset_mode_value = _env(
            f"{prefix}_RESET_MODE",
            defaults.get("reset_mode", ResetMode.ROLLING.value),
        )
        try:
            reset_mode = ResetMode(reset_mode_value)
        except ValueError as exc:
            raise RuntimeError(
                f"Unsupported {prefix}_RESET_MODE: {reset_mode_value!r}. "
                f"Expected one of: {[mode.value for mode in ResetMode]}"
            ) from exc

        providers[name] = ProviderConfig(
            name=name,
            model=_env(f"{prefix}_MODEL", defaults.get("model", "")),
            wakeup_message=_env(
                f"{prefix}_WAKEUP_MESSAGE",
                defaults.get("wakeup_message", "hi"),
            ),
            reset_mode=reset_mode,
            window_seconds=_env_int(
                f"{prefix}_WINDOW_SECONDS",
                int(defaults.get("window_seconds", "18000")),
                minimum=1,
            ),
            wake_delay_seconds=_env_int(
                f"{prefix}_WAKE_DELAY_SECONDS",
                int(defaults.get("wake_delay_seconds", "10")),
                minimum=0,
            ),
            weekly_window_seconds=_env_int(
                f"{prefix}_WEEKLY_WINDOW_SECONDS",
                int(defaults.get("weekly_window_seconds", str(7 * 24 * 60 * 60))),
                minimum=1,
            ),
            weekly_wake_delay_seconds=_env_int(
                f"{prefix}_WEEKLY_WAKE_DELAY_SECONDS",
                int(defaults.get("weekly_wake_delay_seconds", "10")),
                minimum=0,
            ),
        )

    scheduler = SchedulerConfig(
        state_path=_env("SCHEDULER_STATE_PATH", "data/scheduler_state.json"),
        auth_recheck_seconds=_env_int(
            "SCHEDULER_AUTH_RECHECK_SECONDS",
            60,
            minimum=1,
        ),
        retry_base_seconds=_env_int(
            "SCHEDULER_RETRY_BASE_SECONDS",
            60,
            minimum=1,
        ),
        retry_max_seconds=_env_int(
            "SCHEDULER_RETRY_MAX_SECONDS",
            3600,
            minimum=1,
        ),
    )

    if scheduler.retry_max_seconds < scheduler.retry_base_seconds:
        raise RuntimeError(
            "SCHEDULER_RETRY_MAX_SECONDS must be >= SCHEDULER_RETRY_BASE_SECONDS"
        )

    return AppConfig(
        telegram=telegram,
        scheduler=scheduler,
        providers=providers,
    )
