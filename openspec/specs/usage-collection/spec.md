# usage-collection Specification

## Purpose
TBD - created by archiving change add-cli-usage-snapshots. Update Purpose after archive.
## Requirements
### Requirement: Browser-free subscription collection
The system SHALL collect quota windows using authenticated local CLIs without inference or browser processes.

#### Scenario: Local usage read
- **WHEN** polling runs
- **THEN** Claude executes validated local `/usage` and Codex executes initialized account/rateLimits/read over stdio
- **AND** wake timers and prompts retain existing semantics

### Requirement: Durable snapshots and credential ownership
Pobudka SHALL publish atomic versioned snapshots and serialize operations sharing provider credentials.

#### Scenario: Collection fails
- **WHEN** collection or auth fails
- **THEN** the snapshot retains last good windows and timestamps with an explicit error
- **AND** auth failures use the existing guarded Telegram auth flow

### Requirement: Dashboard snapshot consumption
Kindle Dash SHALL consume snapshots read-only and retain its cache/render/push/calendar pipeline without browser dependencies.

#### Scenario: Producer unavailable
- **WHEN** a snapshot is stale, malformed or missing
- **THEN** last good data remains with a visible stale/error state
- **AND** calendar and heartbeat pushes continue

