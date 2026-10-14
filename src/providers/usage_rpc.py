"""One-shot Codex account RPC over stdio, with bounded process lifetime."""

from __future__ import annotations

import asyncio
import json
import os
import signal

from src.providers.usage import UsageError


async def read_codex_rate_limits(timeout: float = 40) -> dict:
    """Initialize app-server and read account quotas without creating a turn."""
    proc = await asyncio.create_subprocess_exec(
        "codex",
        "app-server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        limit=1024 * 1024,
    )

    async def drain_stderr() -> None:
        while await proc.stderr.read(8192):
            pass  # Do not publish account identifiers or diagnostic credentials.

    drain = asyncio.create_task(drain_stderr())

    async def send(message: dict) -> None:
        proc.stdin.write((json.dumps(message) + "\n").encode())
        await proc.stdin.drain()

    async def response(ident: int) -> dict:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                raise UsageError("rpc_error", "Codex app-server closed before response")
            try:
                message = json.loads(raw)
            except ValueError as exc:
                raise UsageError(
                    "invalid_output", "Invalid JSON from Codex app-server"
                ) from exc
            if not isinstance(message, dict):
                raise UsageError("invalid_output", "Invalid Codex RPC envelope")
            if message.get("id") != ident:
                # Notifications are expected. Decline server requests explicitly.
                if "id" in message and "method" in message:
                    await send(
                        {
                            "id": message["id"],
                            "error": {
                                "code": -32601,
                                "message": "Unsupported client request",
                            },
                        }
                    )
                continue
            if "error" in message:
                detail = str(message["error"]).lower()
                code = (
                    "auth_required"
                    if any(
                        s in detail
                        for s in (
                            "auth",
                            "login",
                            "logged in",
                            "401",
                            "expired",
                            "refresh",
                        )
                    )
                    else "rpc_error"
                )
                raise UsageError(
                    code,
                    "Codex account RPC failed; check /auth codex"
                    if code == "auth_required"
                    else "Codex account RPC failed",
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise UsageError("invalid_output", "Missing Codex RPC result")
            return result

    try:
        async with asyncio.timeout(timeout):
            await send(
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "pobudka_usage", "version": "0.1.0"}
                    },
                }
            )
            await response(1)
            await send({"method": "initialized", "params": {}})
            await send({"id": 2, "method": "account/rateLimits/read"})
            return await response(2)
    except TimeoutError as exc:
        raise UsageError("timeout", "Codex quota read timed out") from exc
    finally:
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except TimeoutError:
            pass
        # Kill any remaining process-group children, even if parent has exited.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        await drain
