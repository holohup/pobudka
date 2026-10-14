# Change: Replace Kindle Dash browser collection with CLI snapshots

## Why
Firefox collection causes recurring CPU bursts on C4. Pobudka already owns provider CLI authentication.

## What Changes
- Add independent bounded usage polling in Pobudka; publish atomic normalized snapshots to a dedicated shared volume.
- Validate Claude local `/usage` and Codex stdio rate-limit RPC without inference; serialize credential operations.
- Kindle Dash consumes snapshots read-only, preserves freshness/errors and renders/pushes as before.
- Remove browser code, dependencies, processes, auth routes and ports.

## Impact
- New usage-collection capability, Docker and dashboard changes; wake semantics remain unchanged.
- Implementation and conditional cutover explicitly authorized by user via HANDOFF-remove-firefox.md on 2026-10-14.
