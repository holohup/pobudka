"""Claude Code CLI provider implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from src.config import ProviderConfig
from src.providers.base import (
    AuthStatus,
    DeviceCodeInfo,
    WakeupFailureKind,
    WakeupResult,
)
from src.providers.subprocess import CLIResult, run_cli, start_long_running

logger = logging.getLogger(__name__)

# Patterns for parsing device-code output
_DEVICE_CODE_RE = re.compile(r"(?:code|Code)[:\s]+([A-Z0-9-]{4,12})", re.IGNORECASE)
_DEVICE_URL_RE = re.compile(r"(https?://\S*device\S*)", re.IGNORECASE)

# Pattern for parsing rate-limit reset time
_RATE_LIMIT_RE = re.compile(
    r"(?:reset|try again)\s+(?:in\s+)?(\d+\s*(?:hour|minute|day)\S*(?:\s+\d+\s*(?:hour|minute|day)\S*)*)",
    re.IGNORECASE,
)

_AUTH_ERROR_KEYWORDS = (
    "invalid api key",
    "not authenticated",
    "authentication required",
    "please log in",
    "login required",
    "unauthorized",
)


class ClaudeProvider:
    """Provider that wraps the Claude Code CLI."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self._device_auth_proc: asyncio.subprocess.Process | None = None

    @property
    def name(self) -> str:
        return "Claude"

    async def check_auth(self) -> AuthStatus:
        """Check auth by sending a minimal request."""
        result = await run_cli(
            "claude",
            "-p",
            "hi",
            "--output-format",
            "json",
            "--max-turns",
            "1",
            timeout=30,
        )
        return self._parse_auth_status(result)

    async def send_wakeup(self) -> WakeupResult:
        """Send a wake-up message via Claude CLI."""
        result = await run_cli(
            "claude",
            "-p",
            self._config.wakeup_message,
            "--output-format",
            "json",
            "--max-turns",
            "1",
            "--model",
            self._config.model,
            timeout=60,
        )

        if result.returncode == -1:  # timeout
            return WakeupResult(
                success=False,
                message="Command timed out",
                failure_kind=WakeupFailureKind.TRANSIENT,
            )

        return self._parse_wakeup_result(result)

    async def start_device_auth(self) -> DeviceCodeInfo | None:
        """Start the device-code auth flow."""
        await self.cancel_device_auth()

        self._device_auth_proc = await start_long_running(
            "claude",
            "auth",
            "login",
            "--device",
        )

        # Read initial output to capture the code and URL.
        # The CLI prints the code/URL and then polls in the background.
        output = await self._read_initial_output(timeout=15)
        if output is None:
            await self.cancel_device_auth()
            return None

        code_match = _DEVICE_CODE_RE.search(output)
        url_match = _DEVICE_URL_RE.search(output)

        if not code_match or not url_match:
            logger.warning(
                "Could not parse device code from Claude CLI output: %s",
                output[:300],
            )
            await self.cancel_device_auth()
            return None

        return DeviceCodeInfo(code=code_match.group(1), url=url_match.group(1))

    async def wait_for_device_auth(self) -> bool:
        """Wait for the device-auth CLI process to complete."""
        if self._device_auth_proc is None:
            return False

        try:
            await asyncio.wait_for(self._device_auth_proc.wait(), timeout=300)
            success = self._device_auth_proc.returncode == 0
            self._device_auth_proc = None
            return success
        except asyncio.TimeoutError:
            await self.cancel_device_auth()
            return False

    async def cancel_device_auth(self) -> None:
        """Kill any running device-auth process."""
        if self._device_auth_proc is not None:
            try:
                self._device_auth_proc.kill()
                await self._device_auth_proc.wait()
            except ProcessLookupError:
                pass
            self._device_auth_proc = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _read_initial_output(self, timeout: int = 15) -> str | None:
        """Read from the device-auth process until we get enough output."""
        if self._device_auth_proc is None or self._device_auth_proc.stdout is None:
            return None

        chunks: list[str] = []
        try:
            while True:
                line = await asyncio.wait_for(
                    self._device_auth_proc.stdout.readline(),
                    timeout=timeout,
                )
                if not line:
                    break
                decoded = line.decode(errors="replace")
                chunks.append(decoded)
                # Stop once we see something that looks like a code or URL
                combined = "".join(chunks)
                if _DEVICE_CODE_RE.search(combined) and _DEVICE_URL_RE.search(combined):
                    break
        except asyncio.TimeoutError:
            pass

        return "".join(chunks) if chunks else None

    def _parse_auth_status(self, result: CLIResult) -> AuthStatus:
        """Determine auth status from a claude -p JSON response."""
        if result.returncode == -1:
            return AuthStatus.ERROR

        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            # Fall back to text matching on combined output
            combined = f"{result.stdout} {result.stderr}".lower()
            if any(kw in combined for kw in _AUTH_ERROR_KEYWORDS):
                return AuthStatus.NOT_AUTHENTICATED
            return AuthStatus.ERROR

        if data.get("is_error"):
            text = data.get("result", "").lower()
            if any(kw in text for kw in _AUTH_ERROR_KEYWORDS):
                return AuthStatus.NOT_AUTHENTICATED
            return AuthStatus.ERROR

        return AuthStatus.OK

    def _parse_wakeup_result(self, result: CLIResult) -> WakeupResult:
        """Parse a wake-up response from claude -p JSON output."""
        combined = f"{result.stdout} {result.stderr}"

        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            if not result.ok:
                return WakeupResult(
                    success=False,
                    message=combined[:300],
                    failure_kind=WakeupFailureKind.TRANSIENT,
                )
            return WakeupResult(success=True, message="OK (non-JSON response)")

        if data.get("is_error"):
            text = data.get("result", "")
            rate_match = _RATE_LIMIT_RE.search(text)
            if any(kw in text.lower() for kw in _AUTH_ERROR_KEYWORDS):
                return WakeupResult(
                    success=False,
                    message=f"Auth error: {text}",
                    failure_kind=WakeupFailureKind.AUTH,
                )
            if rate_match:
                return WakeupResult(
                    success=False,
                    message=text[:300],
                    failure_kind=WakeupFailureKind.RATE_LIMIT,
                    rate_limit_reset=rate_match.group(1),
                )
            return WakeupResult(
                success=False,
                message=text[:300],
                failure_kind=WakeupFailureKind.TRANSIENT,
            )

        return WakeupResult(
            success=True,
            message=data.get("result", "OK")[:300],
        )
