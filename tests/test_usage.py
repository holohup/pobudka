"""Quota parsing, snapshot durability, auth coordination and process behavior."""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.providers.managed import ManagedProvider
from src.providers.subprocess import run_cli
from src.providers.usage import (
    SubscriptionUsage,
    UsageError,
    UsageWindow,
    parse_claude_usage,
    parse_codex_usage,
    parse_reset,
)
from src.providers.usage_rpc import read_codex_rate_limits
from src.usage import UsagePublisher

FIXTURES = Path(__file__).parent / "fixtures/usage"
NOW = datetime(2026, 10, 14, 19, tzinfo=UTC)


def claude_fixture():
    return json.loads((FIXTURES / "claude-2.1.300.json").read_text())


def test_claude_live_fixture_and_handoff():
    data = claude_fixture()
    for separator in (",", " at"):
        data["result"] = data["result"].replace("Oct 17,", f"Oct 17{separator}")
        usage = parse_claude_usage(data, NOW)
        assert usage.primary == UsageWindow(0, None)
        assert usage.weekly == UsageWindow(94, "2026-10-17T10:00:00+00:00")


@pytest.mark.parametrize(
    "text,code",
    [
        ("Unknown skill: usage", "incompatible_cli"),
        ("OAuth token expired; please run /login", "auth_required"),
        ("Not logged in", "auth_required"),
        (
            "You are currently using your subscription to power your Claude Code usage",
            "auth_required",
        ),
        ("Current week (all models): bananas", "invalid_output"),
        ("Changed output with no known quota fields", "invalid_output"),
    ],
)
def test_claude_errors(text, code):
    data = claude_fixture()
    data["result"] = text
    with pytest.raises(UsageError) as caught:
        parse_claude_usage(data, NOW)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "field,value",
    [
        ("local_command", "other"),
        ("duration_api_ms", 1),
        ("total_cost_usd", 0.01),
        ("num_turns", 1),
        ("usage", {"input_tokens": 1}),
        ("modelUsage", {"model": {"inputTokens": 1}}),
    ],
)
def test_claude_rejects_inference(field, value):
    data = claude_fixture()
    data[field] = value
    with pytest.raises(UsageError):
        parse_claude_usage(data, NOW)


@pytest.mark.parametrize(
    "text,now,expected",
    [
        (
            "Jan 2 at 12am (Asia/Jerusalem)",
            datetime(2026, 12, 31, tzinfo=UTC),
            "2027-01-01T22:00:00+00:00",
        ),
        ("tomorrow at 1pm (Asia/Jerusalem)", NOW, "2026-10-15T10:00:00+00:00"),
        ("in 2 hours 5 minutes", NOW, "2026-10-14T21:05:00+00:00"),
        ("Oct 27, 2026 at 1:30pm (Asia/Jerusalem)", NOW, "2026-10-27T11:30:00+00:00"),
        ("Oct 17 at 12pm (UTC)", NOW, "2026-10-17T12:00:00+00:00"),
    ],
)
def test_reset_dates(text, now, expected):
    assert parse_reset(text, now) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Oct 25 at 1:30am (Asia/Jerusalem)",
        "Mar 27, 2026 at 2:30am (Asia/Jerusalem)",
        "Oct 40 at 1pm",
        "Oct 17 at 25:70",
        "Oct 17 at 1pm (Unknown/Zone)",
        "soon",
    ],
)
def test_reset_rejects_ambiguous_or_invalid(text):
    with pytest.raises(UsageError):
        parse_reset(text, NOW)


def test_codex_live_weekly_in_primary_position():
    usage = parse_codex_usage(json.loads((FIXTURES / "codex-0.162.1.json").read_text()))
    assert usage.primary is None
    assert usage.weekly.used_percent == 24
    assert usage.weekly.resets_at == datetime.fromtimestamp(1792472384, UTC).isoformat()


def test_codex_selects_bucket_and_duration():
    primary = {"usedPercent": 12, "windowDurationMins": 300, "resetsAt": None}
    weekly = {"usedPercent": 50, "windowDurationMins": 10080, "resetsAt": 1792472384}
    usage = parse_codex_usage(
        {
            "rateLimitsByLimitId": {
                "other": {"primary": weekly},
                "codex": {"primary": weekly, "secondary": primary},
            }
        }
    )
    assert usage.primary == UsageWindow(12, None)
    assert usage.weekly.used_percent == 50
    assert (
        parse_codex_usage({"rateLimits": {"primary": None, "secondary": None}})
        == SubscriptionUsage()
    )
    with pytest.raises(UsageError):
        parse_codex_usage({"rateLimitsByLimitId": {"other": {}}})
    with pytest.raises(UsageError):
        parse_codex_usage({"rateLimits": {"primary": {**primary, "usedPercent": 101}}})


@pytest.mark.asyncio
async def test_publisher_retains_last_good_and_recovers(tmp_path):
    provider = SimpleNamespace(
        read_usage=AsyncMock(
            side_effect=[
                SubscriptionUsage(UsageWindow(42)),
                UsageError("auth_required", "Login required"),
                SubscriptionUsage(UsageWindow(43)),
            ]
        )
    )
    auth = AsyncMock()
    publisher = UsagePublisher(
        {"claude": provider}, auth, str(tmp_path / "snapshot.json"), 1
    )
    assert publisher.interval == 90
    await publisher.collect("claude")
    good = dict(publisher.entries["claude"])
    await publisher.collect("claude")
    failed = json.loads((tmp_path / "snapshot.json").read_text())["providers"]["claude"]
    assert failed["primary"] == good["primary"]
    assert failed["updated_at"] == good["updated_at"]
    assert failed["status"] == "error"
    auth.assert_awaited_once_with("claude")
    restored = UsagePublisher(
        {"claude": provider}, auth, str(tmp_path / "snapshot.json")
    )
    assert restored.entries["claude"]["primary"]["used_percent"] == 42
    await publisher.collect("claude")
    assert publisher.entries["claude"]["error"] is None
    assert publisher.entries["claude"]["primary"]["used_percent"] == 43


@pytest.mark.asyncio
async def test_login_blocks_usage_and_wakeup():
    raw = SimpleNamespace(
        name="test",
        start_device_auth=AsyncMock(return_value=object()),
        cancel_device_auth=AsyncMock(),
        wait_for_device_auth=AsyncMock(return_value=True),
        read_usage=AsyncMock(return_value=SubscriptionUsage()),
        send_wakeup=AsyncMock(),
    )
    provider = ManagedProvider(raw)
    await provider.start_device_auth()
    read = asyncio.create_task(provider.read_usage())
    wake = asyncio.create_task(provider.send_wakeup())
    await asyncio.sleep(0.01)
    raw.read_usage.assert_not_called()
    raw.send_wakeup.assert_not_called()
    await provider.wait_for_device_auth()
    await asyncio.gather(read, wake)
    raw.read_usage.assert_awaited_once()
    raw.send_wakeup.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_cli_cancel_kills_children(tmp_path):
    pidfile = tmp_path / "pid"
    script = f"import subprocess,time,pathlib; p=subprocess.Popen(['sleep','300']);pathlib.Path({str(pidfile)!r}).write_text(str(p.pid));time.sleep(300)"
    task = asyncio.create_task(run_cli(sys.executable, "-c", script))
    for _ in range(100):
        if pidfile.exists():
            break
        await asyncio.sleep(0.01)
    assert pidfile.exists()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    pid = int(pidfile.read_text())
    stat = Path(f"/proc/{pid}/stat")
    assert not stat.exists() or stat.read_text().split()[2] == "Z"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,code",
    [
        ("ok", None),
        ("error", "auth_required"),
        ("invalid", "invalid_output"),
        ("timeout", "timeout"),
        ("eof", "rpc_error"),
    ],
)
async def test_codex_rpc_sequence_notifications_and_cleanup(
    tmp_path, monkeypatch, mode, code
):
    # A real child process catches protocol/lifetime errors that mocks miss.
    cli = tmp_path / "codex"
    pidfile = tmp_path / "server.pid"
    cli.write_text(f"""#!{sys.executable}
import sys,json,time,os,pathlib
pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()))
a=json.loads(input());assert a['method']=='initialize'
sys.stderr.write('diagnostic'*50000);sys.stderr.flush()
print(json.dumps({{"id":"server-request","method":"unsupported/client/request","params":{{}}}}),flush=True)
reply=json.loads(input());assert reply['id']=='server-request' and 'error' in reply
print(json.dumps({{"method":"account/updated","params":{{}}}}),flush=True)
print(json.dumps({{"id":a['id'],"result":{{}}}}),flush=True)
assert json.loads(input())['method']=='initialized'
b=json.loads(input());assert b['method']=='account/rateLimits/read'
mode={mode!r}
if mode=='timeout':time.sleep(300)
elif mode=='eof':sys.exit(0)
elif mode=='invalid':print('not-json',flush=True)
elif mode=='error':print(json.dumps({{"id":b['id'],"error":{{"code":-1,"message":"Not logged in"}}}}),flush=True)
else:print(json.dumps({{"id":b['id'],"result":{{"rateLimits":{{"primary":None}}}}}}),flush=True)
sys.stdin.read()
""")
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    if code:
        with pytest.raises(UsageError) as caught:
            await read_codex_rate_limits(timeout=0.3)
        assert caught.value.code == code
    else:
        assert (await read_codex_rate_limits())["rateLimits"]["primary"] is None
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)


def test_actual_missing_invalid_and_old_claude_outputs():
    failures = json.loads((FIXTURES / "claude-failures.json").read_text())
    for name, envelope in failures.items():
        with pytest.raises(UsageError) as caught:
            parse_claude_usage(envelope, NOW)
        assert caught.value.code == (
            "incompatible_cli" if name == "old-cli" else "auth_required"
        )


@pytest.mark.asyncio
async def test_rpc_cancellation_reaps_server(tmp_path, monkeypatch):
    cli = tmp_path / "codex"
    pidfile = tmp_path / "pid"
    cli.write_text(
        f"#!{sys.executable}\nimport os,pathlib,time\npathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()))\ntime.sleep(300)\n"
    )
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    task = asyncio.create_task(read_codex_rate_limits())
    for _ in range(100):
        if pidfile.exists():
            break
        await asyncio.sleep(0.01)
    assert pidfile.exists()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)


def test_claude_structured_stream_prefers_machine_fields():
    from src.providers.usage import parse_claude_stream

    rows = [
        json.loads(line)
        for line in (FIXTURES / "claude-2.1.300-stream.jsonl").read_text().splitlines()
    ]
    rows[-1]["result"] = "Changed human-readable presentation"
    usage = parse_claude_stream("\n".join(map(json.dumps, rows)), NOW)
    assert usage.primary == UsageWindow(0, None)
    assert usage.weekly == UsageWindow(94, "2026-10-17T10:00:00+00:00")
    rows[1]["usage_report"]["rate_limits"]["limits"].append(
        {"kind": "weekly_scoped", "percent": 70, "resets_at": None, "scope": "sonnet"}
    )
    assert parse_claude_stream("\n".join(map(json.dumps, rows)), NOW) == usage


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("tokens", "inference_detected"),
        ("cost", "inference_detected"),
        ("null_limits", "auth_required"),
        ("bad_reset", "invalid_output"),
        ("duplicate", "invalid_output"),
    ],
)
def test_structured_stream_rejects_invalid_data(mutation, code):
    from src.providers.usage import parse_claude_stream

    rows = [
        json.loads(line)
        for line in (FIXTURES / "claude-2.1.300-stream.jsonl").read_text().splitlines()
    ]
    report = rows[1]["usage_report"]
    if mutation == "tokens":
        rows[-1]["usage"]["input_tokens"] = 1
    elif mutation == "cost":
        report["session"]["total_cost_usd"] = 1
    elif mutation == "null_limits":
        report["rate_limits"] = None
    elif mutation == "bad_reset":
        report["rate_limits"]["limits"][0]["resets_at"] = "2026-10-17T10:00:00"
    else:
        report["rate_limits"]["limits"].append(report["rate_limits"]["limits"][0])
    with pytest.raises(UsageError) as caught:
        parse_claude_stream("\n".join(map(json.dumps, rows)), NOW)
    assert caught.value.code == code


def test_stream_text_fallback_and_missing_final_result():
    from src.providers.usage import parse_claude_stream

    fixture = claude_fixture()
    assert parse_claude_stream(json.dumps(fixture), NOW).weekly.used_percent == 94
    for bad in (
        "garbage",
        "[]",
        '{"type":"assistant"}',
        json.dumps(fixture) + "\n" + json.dumps(fixture),
    ):
        with pytest.raises(UsageError):
            parse_claude_stream(bad, NOW)
