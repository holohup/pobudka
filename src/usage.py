"""Independent quota polling and atomic, credential-free publication."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from src.providers.base import Provider
from src.providers.usage import UsageError, utc_iso

logger = logging.getLogger(__name__)


class UsagePublisher:
    """Publish per-provider last good data separately from wake scheduler state."""

    def __init__(
        self,
        providers: dict[str, Provider],
        request_auth: Callable[[str], Awaitable[None]],
        path: str | None = None,
        interval: int | None = None,
    ) -> None:
        self.providers = providers
        self.request_auth = request_auth
        self.path = Path(
            path or os.environ.get("USAGE_SNAPSHOT_PATH", "/usage/snapshot.json")
        )
        self.interval = max(
            90,
            interval
            if interval is not None
            else int(os.environ.get("USAGE_POLL_SECONDS", "90")),
        )
        self.entries: dict[str, dict] = {}
        self._task: asyncio.Task | None = None
        try:
            saved = json.loads(self.path.read_text())
            if saved.get("schema_version") == 1:
                self.entries = {
                    name: entry
                    for name, entry in saved["providers"].items()
                    if name in providers and isinstance(entry, dict)
                }
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass

    async def start(self) -> None:
        """Start one bounded sequential collector loop."""
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel active collection and wait for subprocess cleanup."""
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def collect(self, name: str) -> None:
        """Update one entry, retaining successful data on any failure."""
        entry = dict(self.entries.get(name, {}))
        now = utc_iso(datetime.now(UTC))
        started = time.monotonic()
        auth_required = False
        try:
            # Includes waiting for an active login/wake; never overlap credentials.
            async with asyncio.timeout(45):
                result = await self.providers[name].read_usage()
            entry.update(asdict(result), updated_at=now, status="ok", error=None)
        except Exception as exc:  # noqa: BLE001 - isolate provider failures
            code = (
                exc.code
                if isinstance(exc, UsageError)
                else (
                    "timeout" if isinstance(exc, TimeoutError) else "collection_error"
                )
            )
            message = (
                str(exc)
                if isinstance(exc, UsageError)
                else "Usage collection failed; see Pobudka logs"
            )
            logger.warning("Usage collection failed provider=%s code=%s", name, code)
            entry.update(status="error", error={"code": code, "message": message})
            auth_required = code == "auth_required"
        entry.update(
            attempted_at=now, duration_seconds=round(time.monotonic() - started, 3)
        )
        self.entries[name] = entry
        self.publish()
        if auth_required:
            await self.request_auth(name)

    def publish(self) -> None:
        """Replace snapshot atomically, including an fsync before rename."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "published_at": utc_iso(datetime.now(UTC)),
            "providers": self.entries,
        }
        name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.path.parent, delete=False
            ) as stream:
                name = stream.name
                json.dump(payload, stream)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o644)
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    async def _run(self) -> None:
        while True:
            started = time.monotonic()
            for name in self.providers:
                try:
                    await self.collect(name)
                except Exception:
                    logger.exception("Usage publication failed provider=%s", name)
            await asyncio.sleep(max(1, self.interval - (time.monotonic() - started)))
