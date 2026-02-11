"""Async subprocess wrapper for CLI execution."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60


@dataclass
class CLIResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


async def run_cli(
    *args: str,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> CLIResult:
    """Run a CLI command and capture output.

    Args:
        *args: Command and arguments.
        timeout: Seconds before killing the process.
        env: Optional environment variable overrides.

    Returns:
        CLIResult with returncode, stdout, and stderr.
    """
    cmd_str = " ".join(args)
    logger.debug("Running: %s", cmd_str)

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("Command timed out after %ds: %s", timeout, cmd_str)
        return CLIResult(returncode=-1, stdout="", stderr=f"Timed out after {timeout}s")

    stdout = stdout_bytes.decode(errors="replace").strip()
    stderr = stderr_bytes.decode(errors="replace").strip()

    logger.debug(
        "Command finished (rc=%d): %s\nstdout: %s\nstderr: %s",
        proc.returncode or 0,
        cmd_str,
        stdout[:200],
        stderr[:200],
    )

    return CLIResult(
        returncode=proc.returncode or 0,
        stdout=stdout,
        stderr=stderr,
    )


async def start_long_running(
    *args: str,
    env: dict[str, str] | None = None,
) -> asyncio.subprocess.Process:
    """Start a long-running subprocess (e.g., device-code auth flow).

    The caller is responsible for reading output and managing the process
    lifecycle.
    """
    logger.debug("Starting long-running: %s", " ".join(args))
    return await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
