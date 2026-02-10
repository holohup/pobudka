"""Docker integration checks for CLI availability in the built image."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

RUN_FLAG = "RUN_DOCKER_INTEGRATION"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _format_command(cmd: list[str]) -> str:
    return " ".join(cmd)


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_ok(result: subprocess.CompletedProcess[str], cmd: list[str]) -> None:
    if result.returncode == 0:
        return

    stdout_tail = result.stdout[-2000:].strip()
    stderr_tail = result.stderr[-2000:].strip()
    raise AssertionError(
        f"Command failed ({result.returncode}): {_format_command(cmd)}\n"
        f"STDOUT tail:\n{stdout_tail}\n\n"
        f"STDERR tail:\n{stderr_tail}"
    )


def _skip_if_integration_disabled() -> None:
    if os.environ.get(RUN_FLAG) != "1":
        pytest.skip(f"set {RUN_FLAG}=1 to run Docker integration checks")


def _skip_if_docker_unavailable(root: Path) -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker binary not found")

    info = _run(["docker", "info", "--format", "{{.ServerVersion}}"], cwd=root)
    if info.returncode != 0:
        pytest.skip("docker daemon is not reachable")


def test_dockerfile_builds_and_clis_are_accessible() -> None:
    _skip_if_integration_disabled()
    root = _project_root()
    _skip_if_docker_unavailable(root)

    tag = f"pobudka-it-{uuid.uuid4().hex[:12]}"

    build_cmd = ["docker", "build", "-t", tag, "."]
    claude_cmd = ["docker", "run", "--rm", tag, "claude", "--version"]
    codex_cmd = ["docker", "run", "--rm", tag, "codex", "--help"]

    build = _run(build_cmd, cwd=root)
    _assert_ok(build, build_cmd)

    try:
        claude = _run(claude_cmd, cwd=root)
        _assert_ok(claude, claude_cmd)
        assert (claude.stdout or claude.stderr).strip()

        codex = _run(codex_cmd, cwd=root)
        _assert_ok(codex, codex_cmd)
        combined = f"{codex.stdout}\n{codex.stderr}"
        assert "codex" in combined.lower()
    finally:
        _run(["docker", "image", "rm", "-f", tag], cwd=root)
