# Change: Add provider wake-up scheduler

## Why
The project now has provider authentication and wake-up commands, but it still lacks the core scheduling behavior that makes Pobudka useful day to day. Without a scheduler, wake-ups depend on manual `/auth` and ad-hoc commands instead of running automatically at provider reset boundaries.

A dedicated scheduler proposal is needed to define timer policy, retry behavior, persistence, and Telegram observability before implementation.

## What Changes
- Add a scheduler service that runs continuously and manages wake-up timing per provider.
- Add per-provider schedule policy configuration (rolling vs clock-aligned reset rules plus window duration).
- Add scheduler state persistence (`data/scheduler_state.json`) for restart recovery.
- Add structured wake-up outcome handling for success, rate-limit, auth-failure, and transient errors.
- Add retry with exponential backoff for transient failures.
- Add Telegram scheduler controls and visibility (`/schedule`, `/wake <provider>`).

## Impact
- Affected specs: `scheduler` (new capability)
- Affected code:
  - `src/main.py` (start/stop scheduler alongside bot)
  - `src/scheduler.py` (new)
  - `src/config.py` (`.env` schedule policy fields)
  - `src/bot.py` (scheduler status and manual trigger commands)
  - `src/providers/base.py`, `src/providers/claude.py`, `src/providers/codex.py` (structured wake-up outcome classification)
  - `tests/` (scheduler unit tests + provider outcome tests)
- Operational impact:
  - New persisted file mounted through `./data` volume
  - More frequent Telegram notifications (configurable)
