## Context
`add-provider-auth` established provider wrappers and Telegram-driven device auth, but scheduler logic is still missing. Pobudka needs deterministic timing so each provider gets a wake-up request immediately after its usage window resets.

Providers have different reset semantics:
- Codex: rolling windows (next reset depends on the last successful wake-up timestamp).
- Claude: clock-aligned windows (window anchor is rounded to a wall-clock boundary before adding duration).

The scheduler must remain reliable across container restarts and network/auth failures.

## Goals / Non-Goals
- Goals:
  - Schedule wake-ups automatically per provider using provider-specific policy.
  - Recover scheduling state after restart without losing timing context.
  - Handle auth/rate-limit/transient failures differently.
  - Provide Telegram visibility and manual override controls.
- Non-Goals:
  - Building a generic cron engine.
  - Supporting multi-user or multi-tenant scheduling.
  - Querying provider-internal quota APIs (not available in current CLIs).

## Decisions

### Decision 1: Per-provider worker tasks
Use one async worker task per enabled provider instead of a shared priority queue.

Why:
- Simpler control flow and easier debugging for a two-provider personal service.
- Natural failure isolation (one provider failure does not block others).
- Straightforward cancellation on shutdown.

Worker loop:
1. Load `next_run_at` from persisted state or compute default.
2. Sleep until due time.
3. Run `provider.send_wakeup()`.
4. Classify result and compute next run.
5. Persist state and notify Telegram when needed.

### Decision 2: Explicit schedule policy in config
Add policy fields per provider:
- `RESET_MODE`: `rolling` | `clock_aligned_hour`
- `WINDOW_SECONDS`: positive integer
- `WAKE_DELAY_SECONDS`: non-negative integer (default `2`) to avoid firing before reset edge

Computation:
- `rolling`: `next_run = success_at + window + wake_delay`
- `clock_aligned_hour`: `anchor = floor(success_at to hour)`; `next_run = anchor + window + wake_delay`

### Decision 3: Structured wake-up outcome classification
Scheduler decisions should not rely on parsing free-form message strings. Extend wake-up results with a machine-readable failure kind.

Proposed enum:
- `none` (success)
- `auth`
- `rate_limit`
- `transient`

Provider implementations keep provider-specific parsing, but emit normalized outcome type.

### Decision 4: Persist scheduler state with atomic writes
Persist state at `data/scheduler_state.json` after each wake attempt and after significant transitions (pause/resume).

State shape:
- `schema_version`
- `providers.<name>.next_run_at` (ISO-8601 UTC)
- `providers.<name>.last_success_at` (ISO-8601 UTC or null)
- `providers.<name>.last_attempt_at` (ISO-8601 UTC or null)
- `providers.<name>.consecutive_failures`
- `providers.<name>.paused_reason` (`auth_required` | null)
- `providers.<name>.backoff_until` (ISO-8601 UTC or null)

Write strategy:
- Write to `scheduler_state.json.tmp` then `os.replace` to avoid partial writes.

### Decision 5: Failure-specific scheduling policy
On each wake attempt:
- Success:
  - clear failure counters and pause status
  - compute next run by reset policy
- Auth failure:
  - mark provider paused (`auth_required`)
  - trigger `bot.run_device_auth(provider)` once
  - do not schedule regular wake-ups until auth becomes valid
- Rate-limit response with parseable reset duration:
  - schedule `next_run = now + parsed_reset + wake_delay`
- Transient failure:
  - apply exponential backoff (`base=60s`, `max=3600s`)
  - keep provider active

### Decision 6: Telegram observability and manual controls
Add commands:
- `/schedule`: show provider state (`next_run_at`, `last_success_at`, pause/backoff status)
- `/wake <provider>`: run immediate wake-up and recompute schedule

Notifications:
- send alerts on auth pause, repeated transient failures, and successful recovery after pause.

## Risks / Trade-offs
- Clock-aligned assumptions may drift if provider behavior changes.
  - Mitigation: config-driven reset mode and window values.
- Human-readable reset parsing from CLI error text may be unstable.
  - Mitigation: fallback to configured window + backoff when parsing fails.
- State corruption risk in mounted volume.
  - Mitigation: atomic writes + startup fallback to recompute defaults.

## Migration Plan
1. Introduce scheduler data model/config and unit tests.
2. Implement provider worker loop and persistence.
3. Integrate with `main.py` lifecycle.
4. Add bot commands and notifications.
5. Validate behavior with mocked provider responses and restart recovery tests.

## Open Questions
1. Should `/schedule` include historical failure logs or only current state?
2. Should wake-up success notifications be periodic-only (e.g., once per day) to reduce chat noise?
