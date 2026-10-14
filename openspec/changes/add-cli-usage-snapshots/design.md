## Decisions
Pobudka alone owns credentials. Versioned JSON in external `pobudka-usage` volume is writable by Pobudka, read-only by Kindle Dash. Atomic replacement prevents partial reads. Provider entries contain primary/weekly percentages and UTC resets, attempted_at, updated_at, status and sanitized errors. Failures preserve last good windows/timestamps.

Usage polling is independent of wake scheduling with minimum 90-second cadence. Provider operations serialize including auth. Codex uses bounded initialized stdio RPC with stderr drainage and cleanup. Claude must prove local command execution and zero inference, preferring the structured assistant usage_report emitted by local /usage in JSON stream mode; text parsing is an isolated compatibility fallback. English locale and Asia/Jerusalem timezone are explicit.

## Migration
Validate compatibility/auth on ARM64 before cutover. Back up configs/state/override/image tags privately. Commit/push feature branches; fetch/checkout on C4 and rebuild. Preserve prod data/key mounts, add read-only snapshot mount, remove browser settings. Recreate one bot and dashboard; verify calendar, PNG, Kindle push and multiple cycles. Roll back using retained images/configs if acceptance fails.
