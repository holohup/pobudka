# scheduler Specification

## Purpose
TBD - created by archiving change add-wakeup-scheduler. Update Purpose after archive.
## Requirements
### Requirement: Provider Scheduling Policy
The system SHALL support per-provider reset policy configuration to compute the next wake-up timestamp after a successful wake-up.

#### Scenario: Rolling reset policy computes next run from success timestamp
- **GIVEN** provider `codex` is configured with `RESET_MODE=rolling` and `WINDOW_SECONDS=18000`
- **WHEN** a wake-up succeeds at `2026-02-10T10:13:00Z`
- **THEN** the next scheduled run SHALL be `2026-02-10T15:13:00Z` plus configured wake delay

#### Scenario: Clock-aligned policy computes next run from hourly anchor
- **GIVEN** provider `claude` is configured with `RESET_MODE=clock_aligned_hour` and `WINDOW_SECONDS=18000`
- **WHEN** a wake-up succeeds at `2026-02-10T10:13:00Z`
- **THEN** the scheduler SHALL floor the timestamp to `2026-02-10T10:00:00Z`
- **AND** the next scheduled run SHALL be `2026-02-10T15:00:00Z` plus configured wake delay

### Requirement: Scheduler Runtime Lifecycle
The system SHALL run a continuous scheduler loop for each enabled provider and execute wake-ups when provider jobs become due.

#### Scenario: Scheduler starts provider loops on service startup
- **WHEN** the service starts with enabled providers in configuration
- **THEN** the scheduler SHALL create one asynchronous worker per enabled provider
- **AND** each worker SHALL schedule its next wake-up using persisted state or default policy rules

#### Scenario: Scheduler stops cleanly on service shutdown
- **WHEN** the service receives shutdown
- **THEN** scheduler worker tasks SHALL be cancelled gracefully
- **AND** no wake-up subprocess SHALL be left running by the scheduler

### Requirement: Wake-Up Result Classification
The system SHALL normalize provider wake-up outcomes into machine-readable categories so scheduler decisions do not depend on free-form strings.

#### Scenario: Auth failure outcome pauses scheduling
- **WHEN** `send_wakeup()` returns a failure categorized as `auth`
- **THEN** the scheduler SHALL mark the provider as paused for auth
- **AND** it SHALL trigger Telegram-guided re-authentication for that provider
- **AND** it SHALL not schedule regular wake-ups for the provider until auth is restored

#### Scenario: Rate-limit outcome uses provider reset hint
- **WHEN** `send_wakeup()` returns a failure categorized as `rate_limit` with a parseable reset duration
- **THEN** the scheduler SHALL set the next run to current time plus parsed duration and wake delay
- **AND** it SHALL persist this next run timestamp

#### Scenario: Transient failure outcome retries with backoff
- **WHEN** `send_wakeup()` returns a failure categorized as `transient`
- **THEN** the scheduler SHALL increment the provider failure counter
- **AND** schedule a retry using exponential backoff bounded by configured maximum delay

### Requirement: Scheduler State Persistence
The system SHALL persist scheduler state to disk so wake-up timing survives restarts.

#### Scenario: Scheduler persists state after wake attempts
- **WHEN** a provider wake attempt finishes
- **THEN** the scheduler SHALL write provider state including `next_run_at`, `last_attempt_at`, and failure metadata to `data/scheduler_state.json`
- **AND** the write SHALL be atomic (temporary file plus replace)

#### Scenario: Scheduler recovers overdue providers after restart
- **WHEN** the service restarts and persisted `next_run_at` is in the past
- **THEN** the scheduler SHALL trigger that provider wake-up immediately
- **AND** it SHALL compute and persist a new `next_run_at`

#### Scenario: Corrupt scheduler state falls back to policy defaults
- **WHEN** `data/scheduler_state.json` is unreadable or invalid
- **THEN** the scheduler SHALL log a warning
- **AND** initialize provider schedules from configured policy defaults

### Requirement: Telegram Scheduler Visibility and Control
The system SHALL expose scheduler state and manual trigger controls through Telegram commands.

#### Scenario: User requests schedule snapshot
- **WHEN** the user sends `/schedule`
- **THEN** the bot SHALL return each provider's next scheduled run, last successful wake-up, and pause/backoff status

#### Scenario: User forces immediate wake-up
- **WHEN** the user sends `/wake <provider>`
- **THEN** the scheduler SHALL execute an immediate wake-up attempt for that provider
- **AND** it SHALL recalculate the provider's next schedule based on the wake-up result

#### Scenario: Provider recovers after auth pause
- **WHEN** a paused provider successfully re-authenticates and completes its next wake-up
- **THEN** the scheduler SHALL clear paused state and failure counters
- **AND** the bot SHALL send a Telegram recovery notification

