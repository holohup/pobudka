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

Both branches were pushed to GitHub, fetched on C4 and rebuilt natively for ARM64. Code deployed: Pobudka `7b17440`, Kindle Dash `66ab4d2` (later documentation commits do not change the image). The native suites passed **87 Pobudka tests** (one opt-in Docker test skipped because the native image was being tested directly) and **307 Kindle Dash tests**. Both built images were audited: no browser binaries or Selenium/Playwright modules.

Cutover completed at 19:54 UTC. The one-off native smoke used the persisted credentials without Telegram polling: both `check_auth` calls returned OK and both actual `send_wakeup` calls succeeded. CLI usage reads took 6.800 seconds for Claude and 1.196 seconds for Codex in that smoke. Claude returned 0% primary / 94% weekly; Codex 25% weekly and null primary. The bot then restarted as the sole Telegram poller.

The recreated bot retained both providers' `next_run_at`, `weekly_next_run_at`, `last_success_at` and failure counts exactly as saved at shutdown. CLI credentials and scheduler data remain in the original named volumes. The inference-only environment overrides were removed after private backup; the verified full Claude login is persisted in the existing auth/home volumes. Old website profiles were moved into the private backup directory.

Live checks passed: health `ok`, both provider snapshots fresh, producer usage mount writable and dashboard mount read-only, no provider auth mounts in Kindle Dash, only port 8080 exposed by the dashboard. Calendar status was OK with two events; PNG was 600×800 grayscale. The Kindle's temporary and persistent PNG MD5s matched the producer PNG, and its actual 600×800 framebuffer contained the new quota rows and calendar.

An isolated new-image missing-auth scenario exercised both real collectors twice: each returned `auth_required`, retained seeded last-good data/timestamps and triggered the scheduler's auth callback once per provider. No Telegram polling or model prompt ran in that scenario. The populated production credential stores were not altered.

Image sizes: Kindle Dash 984,459,136 → 246,077,217 bytes. Upgrading Claude increased Pobudka's image from 1,238,041,838 to approximately 1.50 GB; the combined image footprint still decreased.

The existing scheduled Claude wake ran naturally at **20:04:44 UTC**, succeeded at 20:04:53, cleared its prior failures, and advanced both timers according to the unchanged configuration. Both dashboard providers transitioned to idle after five unchanged reads and completed their next five-minute idle polls at about 20:09:47 / 20:09:56 UTC.

## CPU and process observation

Collected **900 one-second cgroup CPU samples before and 900 after**, covering multiple complete polling cycles. CPU percentages use 100% for one full CPU core; C4 has four cores. The post-cutover period includes regular quota reads, calendar/render/SSH activity and the naturally scheduled Claude wake. Raw samples and process observations are retained with the private backup.

| Container | Before mean / peak | After mean / peak |
| --- | --- | --- |
| Kindle Dash | 46.892% / 389.632% | 0.893% / 78.993% |
| Pobudka | 3.401% / 198.418% | 11.617% / 198.444% |
| Combined | 50.293% / 389.632% | 12.510% / 198.543% |

The before-Pobudka samples include compatibility probes, so the clean conservative comparison is **12.510% for both new services versus 46.892% for the old dashboard alone**. Cgroups isolate container CPU accounting; collection has moved into Pobudka and remains measurable. Dashboard-only CPU fell about 98%, but native CLI startups still create CPU bursts. This is not a zero-cost collector.

A separate one-second process observer scanned both runtime cgroups over the same post-cutover period: **zero browser-process observations**, **zero long-lived CLI PIDs** (threshold 50 seconds), at most one observed native CLI process. Docker init reaps grandchildren; idle process listings contain only the bot/init and dashboard app/prefetch/calendar/SSH processes. Final health, fresh snapshots, PNG and calendar checks all passed.

The private backup also retains `rollback.sh` and its helper for restoring the original source/image/config/data while keeping the newest CLI credentials (refresh tokens may have rotated). The rollback script was prepared and syntax-checked; the successful cutover did not require executing rollback.
