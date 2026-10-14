# CLI usage replacement validation — 2026-10-14

Both repos use branch `feat/browser-free-usage`. C4 is `odroid-c4`, ARM64. Pobudka owns credentials and a separate snapshot volume; Kindle Dash receives only read-only quota snapshots.

## Compatibility evidence

- Existing Claude Code **2.1.38** returns `Unknown skill: usage` with exit code zero and `is_error: false`; this is explicitly rejected.
- Candidate **2.1.300**, installed alongside the live CLI in the ARM64 Pobudka container, executes local `usage` with zero API duration, turns, tokens and cost.
- The existing environment OAuth token grants only inference. `/usage` returns cost/token totals without subscription quotas. The old stored credential has `expiresAt: 0` and no refresh token; removing the environment token still does not return quota windows.
- The user completed a fresh `claude auth login --claudeai` in an isolated C4 directory. It returns current session **0%**, weekly **94%**, reset **Oct 17, 1pm (Asia/Jerusalem)**. This matches the old dashboard's website data (weekly reset `2026-10-17T10:00:00...Z`). Missing primary reset remains null.
- Fresh-login and no-login/invalid-token/old-CLI outputs are sanitized fixtures under `tests/fixtures/usage`. Invalid-token behavior is a simulation, not a claimed live expiry of the new login. Unit tests also cover explicit expired-login errors.
- Codex **0.162.1** initialized stdio `account/rateLimits/read` succeeds using existing C4 credentials, without creating a thread/turn. A real missing-auth run through the implemented RPC client returns `auth_required` and cleans up its child.
- Codex's production plan returns a **10080-minute weekly window in `primary`**, with no 300-minute window. The old dashboard website response likewise stores a 604800-second window in `primary_window`, which its old renderer labels “5h”. New code maps by duration, places this under “7d”, and shows “--” for the missing 5h window.

The exact collector commands and snapshot schema are documented in README. See [Codex app-server protocol](https://learn.chatgpt.com/docs/app-server), [Claude commands](https://code.claude.com/docs/en/commands) and [Claude print mode](https://code.claude.com/docs/en/headless).

## Structured usage follow-up

At the user’s request, a research subagent checked the Claude Agent SDK. The pinned CLI itself emits structured `assistant.usage_report` data with `--output-format stream-json --verbose`, confirmed live on C4 with zero API duration/turns/tokens/cost. The report contains `rate_limits.limits[]` rows (`session`, `weekly_all`) with percentages and precise ISO reset timestamps. Collection now prefers this report, retains the tested text parser only when no report is emitted, and rejects malformed reports rather than silently falling back. Hooks/settings sources are disabled for reads and session persistence is off. Wake commands retain their existing options.

See [SDK research](claude-sdk-quota-research.md) for primary sources and experimental control-method tradeoffs. No SDK dependency or experimental control API is needed for the deployed collector.

## Rollback material

Private C4 backups: `/srv/homelab/apps/pobudka/backups/2026-10-14-cli-usage/`. Contains original environment files, Kindle Compose override, scheduler/auth archive, fresh Claude login archive and Kindle data archive. Access is restricted by the backup directory's mode 0700. No credentials are committed.

Retained image tags: `pobudka:rollback-pre-cli-usage` and `kindle-dash:rollback-pre-cli-usage`. Original source commits: Pobudka `06ec09e`, Kindle Dash `438a433`. Preserve the existing named auth/scheduler volumes and Kindle data/key mounts. Never use `down -v` during rollback.

For rollback, stop both services, restore their original environment/Compose override and browser-profile data from the private backup, check out the original source commits, retag the retained images to the original Compose image names (`pobudka-pobudka`, `repo-kindle-dash`) and recreate using `--no-build`. Restore the pre-cutover scheduler/auth archive into the same named volumes using a one-off container if necessary. Keep only one Telegram poller. The snapshot volume can remain unused.

## Deployment results

Native builds, final smoke checks and CPU measurements are recorded here after cutover verification.
