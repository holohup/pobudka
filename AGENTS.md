<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

## Pobudka Project Guide

### Purpose
- `pobudka` is a Telegram-controlled scheduler that keeps provider CLI sessions "warm" by sending periodic minimal wake-up prompts.
- Current providers: `claude` (Claude Code CLI) and `codex` (OpenAI Codex CLI).

### High-Level Architecture
- Entry point: `src/main.py`
- Config loader: `src/config.py`
- Telegram interface: `src/bot.py`
- Scheduling core and state persistence: `src/scheduler.py`
- Provider implementations: `src/providers/claude.py`, `src/providers/codex.py`
- Provider registry: `src/providers/registry.py`

### Access Control
- The bot responds only to one Telegram chat id: `TELEGRAM_CHAT_ID`.
- Messages from any other chat are ignored by command handlers.

### Telegram Commands
- `/start` - show command menu.
- `/help` - show command menu.
- `/menu` - show command menu.
- `/status` - check auth status for all enabled providers.
- `/auth <provider>` - start device auth flow (or return fallback manual instructions).
- `/check_auth [provider]` - verify auth for one provider or all providers.
- `/schedule` - print scheduler state (`next_5h`, `next_7d`, `last_ok`, failures, pause state).
- `/wake <provider>` - run immediate wake attempt.
- `/wake <provider> HH:MM` - schedule next wake at Israel time (`Asia/Jerusalem`).

### Scheduler Behavior
- Scheduler keeps two independent timers per provider:
- `next_run_at` for the 5-hour cycle.
- `weekly_next_run_at` for the 7-day cycle.
- Worker loop wakes when either timer becomes due (minimum delay of both).

### Timing Rules
- Default provider window: `18000` seconds (5 hours).
- Default weekly window: `604800` seconds (7 days).
- Default safety offset: `10` seconds on both 5h and 7d windows.
- Claude 5h mode: `clock_aligned_hour` (anchors to the current UTC hour before adding window + delay).
- Codex 5h mode: `rolling` (success time + window + delay).
- Weekly mode for both: always rolling (`success + weekly_window + weekly_delay`).

### Manual Schedule (`/wake <provider> HH:MM`)
- Parses `HH:MM` in `Asia/Jerusalem`.
- Reloads `.env` config in-process before scheduling.
- If provided time is earlier than "now" in Israel timezone, schedules for the next day.
- Writes the same target timestamp to both `next_run_at` and `weekly_next_run_at`.
- Persists state and restarts that provider worker task.

### Wake Attempt Outcomes
- Success:
- clears pause/backoff/failure counters.
- updates due timers (`next_run_at`, `weekly_next_run_at`) based on provider config.
- notifies Telegram on manual wake or recovery from previous failures.
- Auth failure:
- sets `paused_reason=auth_required`.
- schedules future next attempts (5h and weekly windows, with delays).
- triggers provider auth flow once per auth-failure episode (`auth_request_sent` guard).
- Rate limit:
- parses reset duration from provider output when possible.
- otherwise falls back to provider 5h window.
- schedules both timers from parsed/fallback reset plus delays.
- Transient failure:
- applies exponential backoff:
- `retry = min(SCHEDULER_RETRY_BASE_SECONDS * 2^(failures-1), SCHEDULER_RETRY_MAX_SECONDS)`.
- sets both timers to `backoff_until`.

### Auth Flows

#### Claude
- Primary check: `claude -p "hi" --output-format json --max-turns 1`.
- Device auth support depends on CLI version exposing `claude auth ...`.
- If unsupported, bot returns fallback:
- `docker compose exec -it pobudka claude setup-token`
- Token env used by CLI: `CLAUDE_CODE_OAUTH_TOKEN`.
- Backward-compatible alias: `CLAUDE_AUTH_TOKEN` (auto-mapped by config loader).

#### Codex
- Primary check: `codex login status`.
- Device auth command: `codex login --device-auth`.
- Wake command uses:
- `codex exec <message> --full-auto --json --skip-git-repo-check -m <model>`.
- Current default model: `gpt-5.1-codex-mini`.

### Environment Configuration (`.env`)
- Required:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- Optional global:
- `ENABLED_PROVIDERS` (default `claude,codex`)
- `SCHEDULER_STATE_PATH` (default `data/scheduler_state.json`)
- `SCHEDULER_RETRY_BASE_SECONDS` (default `60`)
- `SCHEDULER_RETRY_MAX_SECONDS` (default `3600`)
- `SCHEDULER_AUTH_RECHECK_SECONDS` exists but is currently not used by runtime logic.
- Provider-specific:
- `CLAUDE_MODEL`, `CLAUDE_WAKEUP_MESSAGE`, `CLAUDE_RESET_MODE`, `CLAUDE_WINDOW_SECONDS`, `CLAUDE_WAKE_DELAY_SECONDS`, `CLAUDE_WEEKLY_WINDOW_SECONDS`, `CLAUDE_WEEKLY_WAKE_DELAY_SECONDS`
- `CODEX_MODEL`, `CODEX_WAKEUP_MESSAGE`, `CODEX_RESET_MODE`, `CODEX_WINDOW_SECONDS`, `CODEX_WAKE_DELAY_SECONDS`, `CODEX_WEEKLY_WINDOW_SECONDS`, `CODEX_WEEKLY_WAKE_DELAY_SECONDS`
- Auth token env:
- `CLAUDE_CODE_OAUTH_TOKEN` (preferred)
- `CLAUDE_AUTH_TOKEN` (legacy alias, auto-normalized)

### Persistent Data and What To Transfer
- Host-side file:
- `.env` (contains bot token/chat id/provider config).
- Host-side scheduler state:
- `data/scheduler_state.json`.
- Docker named volumes (auth/session persistence):
- `root-home` mounted at `/root`
- `claude-auth` mounted at `/root/.claude`
- `codex-auth` mounted at `/root/.codex`
- For migration to another host, preserve:
- `.env`
- `data/scheduler_state.json`
- contents of named volumes above (or re-authenticate inside new container).

### Docker Runtime
- Compose service: `pobudka` with `restart: unless-stopped`.
- Image base: `python:3.13-slim-bookworm`.
- Node runtime: Node.js `22.x`.
- CLI pins:
- `@anthropic-ai/claude-code@2.1.38`
- `@openai/codex@0.87.0`

### Operations
- Start/update service:
- `docker compose up -d --build`
- Stop:
- `docker compose down`
- Inspect status:
- `docker compose ps`
- Inspect logs:
- `docker compose logs -f`

### Deployment Notes (Prod Host)
- Keep only one active bot instance at a time (Telegram long polling conflict if two environments run simultaneously with same bot token).
- Before starting prod, stop local instance if it uses the same Telegram bot token.
- On new architecture hosts (for example Raspberry Pi), always run a full rebuild (`--build`) so native dependencies and CLI tooling are built for target platform.

### Troubleshooting
- Claude OAuth "missing scope" or "unknown scope":
- usually caused by malformed wrapped URL copied with line breaks.
- Always use the full single-line URL generated by CLI.
- Codex model error ("model is not supported with ChatGPT account"):
- set `CODEX_MODEL` to a supported model in `.env` (current default is `gpt-5.1-codex-mini`).
- Codex "Not inside a trusted directory":
- handled by `--skip-git-repo-check` in wake command.
- Scheduler edits getting reverted:
- if editing `data/scheduler_state.json` manually, stop container first.
- During shutdown, in-memory state is persisted and can overwrite manual file edits done while running.

### Testing
- Fast suite:
- `pytest -q`
- Docker integration only:
- `RUN_DOCKER_INTEGRATION=1 pytest -q tests/test_docker_integration.py`
- Full suite:
- `RUN_DOCKER_INTEGRATION=1 pytest -q`
