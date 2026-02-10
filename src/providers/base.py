"""Base provider protocol and shared types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol


class AuthStatus(Enum):
    OK = auto()
    NOT_AUTHENTICATED = auto()
    EXPIRED = auto()
    ERROR = auto()


class WakeupFailureKind(str, Enum):
    NONE = "none"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TRANSIENT = "transient"


@dataclass
class WakeupResult:
    success: bool
    message: str
    failure_kind: WakeupFailureKind = WakeupFailureKind.NONE
    rate_limit_reset: str | None = None
    """Human-readable reset time parsed from CLI output, if available."""


@dataclass
class DeviceCodeInfo:
    code: str
    url: str


class Provider(Protocol):
    """Interface that all LLM providers must implement."""

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        ...

    async def check_auth(self) -> AuthStatus:
        """Check whether the provider has a valid authentication session."""
        ...

    async def send_wakeup(self) -> WakeupResult:
        """Send a minimal request to restart the rate-limit window."""
        ...

    async def start_device_auth(self) -> DeviceCodeInfo | None:
        """Start device-code auth flow. Returns code+URL or None on failure."""
        ...

    async def wait_for_device_auth(self) -> bool:
        """Wait for the running device-auth process to complete.

        Returns True if auth succeeded.
        """
        ...

    async def cancel_device_auth(self) -> None:
        """Cancel a running device-auth process, if any."""
        ...
