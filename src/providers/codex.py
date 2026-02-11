"""OpenAI Codex CLI provider implementation."""

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
_DEVICE_CODE_RE = re.compile(r"\b([A-Z0-9]{4,}(?:-[A-Z0-9]{2,})+)\b")
_DEVICE_URL_RE = re.compile(r"(https?://\S*(?:device|auth)\S*)", re.IGNORECASE)
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Pattern for parsing rate-limit reset time
_RATE_LIMIT_RE = re.compile(
    r"(?:try again|reset)\s+(?:in\s+)?(\d+\s*(?:hour|minute|day)\S*(?:\s+\d+\s*(?:hour|minute|day)\S*)*)",
    re.IGNORECASE,
)

_AUTH_ERROR_KEYWORDS = (
    "could not be refreshed",
    "refresh_token_reused",
    "not logged in",
    "not authenticated",
    "authentication required",
    "please log in",
    "login required",
    "unauthorized",
    "401 unauthorized",
    "missing bearer",
    "sign in again",
)

_RATE_LIMIT_KEYWORDS = (
    "usage limit",
    "rate limit",
)


class CodexProvider:
    """Provider that wraps the OpenAI Codex CLI."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self._device_auth_proc: asyncio.subprocess.Process | None = None

    @property
    def name(self) -> str:
        return "Codex"

    async def check_auth(self) -> AuthStatus:
        """Check auth via codex login status."""
        result = await run_cli("codex", "login", "status", timeout=10)
        text = f"{result.stdout} {result.stderr}".lower()

        if not result.ok:
            if any(kw in text for kw in _AUTH_ERROR_KEYWORDS):
                return AuthStatus.NOT_AUTHENTICATED
            return AuthStatus.ERROR

        if "logged in" in text:
            return AuthStatus.OK

        return AuthStatus.NOT_AUTHENTICATED

    async def send_wakeup(self) -> WakeupResult:
        """Send a wake-up message via Codex CLI."""
        result = await run_cli(
            "codex",
            "exec",
            self._config.wakeup_message,
            "--full-auto",
            "--json",
            "--skip-git-repo-check",
            "-m",
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
            "codex",
            "login",
            "--device-auth",
        )

        output = await self._read_initial_output(timeout=15)
        if output is None:
            await self.cancel_device_auth()
            return None

        cleaned = _strip_ansi(output)
        code_match = _DEVICE_CODE_RE.search(cleaned)
        url_match = _DEVICE_URL_RE.search(cleaned)

        if not code_match or not url_match:
            logger.warning(
                "Could not parse device code from Codex CLI output: %s",
                cleaned[:300],
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
                combined = _strip_ansi("".join(chunks))
                if _DEVICE_CODE_RE.search(combined) and _DEVICE_URL_RE.search(combined):
                    break
        except asyncio.TimeoutError:
            pass

        return "".join(chunks) if chunks else None

    def _parse_wakeup_result(self, result: CLIResult) -> WakeupResult:
        """Parse a wake-up response from codex exec --json JSONL output."""
        combined = f"{result.stdout} {result.stderr}"

        # Codex outputs JSONL -- parse each line, look for errors or completion
        has_error = False
        error_message = ""
        rate_limit_reset: str | None = None

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            event_type = event.get("type", "")

            if event_type in ("error", "turn.failed"):
                has_error = True
                # "error" events put message at top level;
                # "turn.failed" events nest it under "error.message"
                message = event.get("message", "")
                if not message and isinstance(event.get("error"), dict):
                    message = event["error"].get("message", str(event["error"]))
                if message:
                    error_message = message

        if has_error and error_message:
            # Check for auth errors
            lower = error_message.lower()
            if any(kw in lower for kw in _AUTH_ERROR_KEYWORDS):
                return WakeupResult(
                    success=False,
                    message=f"Auth error: {error_message}",
                    failure_kind=WakeupFailureKind.AUTH,
                )

            # Check for rate limits
            if any(kw in lower for kw in _RATE_LIMIT_KEYWORDS):
                rate_match = _RATE_LIMIT_RE.search(error_message)
                return WakeupResult(
                    success=False,
                    message=error_message[:300],
                    failure_kind=WakeupFailureKind.RATE_LIMIT,
                    rate_limit_reset=rate_match.group(1) if rate_match else None,
                )

            return WakeupResult(
                success=False,
                message=error_message[:300],
                failure_kind=WakeupFailureKind.TRANSIENT,
            )

        if not result.ok and not has_error:
            return WakeupResult(
                success=False,
                message=combined[:300],
                failure_kind=WakeupFailureKind.TRANSIENT,
            )

        return WakeupResult(success=True, message="OK")


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from CLI output."""
    return _ANSI_ESCAPE_RE.sub("", text)
