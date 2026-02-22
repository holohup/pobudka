# Pobudka

> *"Pobudka" — Polish for "wake up"*

**Keep your LLM provider sessions warm and tokens fresh.**

A Telegram-controlled automation bot that periodically pings Claude and Codex CLI services to prevent authentication sessions from expiring, keeping your AI assistants ready 24/7.

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-supported-brightgreen?logo=docker)](https://www.docker.com/)

## ✨ Features

- 🔄 **Automated Wake-up Scheduling** — Dual-cycle timer system (5-hour + 7-day) to keep tokens active
- 📱 **Telegram Control** — Full bot interface for monitoring, scheduling, and manual controls
- 🔐 **Built-in Auth Management** — Device-code authentication flow for Claude and Codex
- 🎯 **Timezone Scheduling** — Schedule wake-ups in Israel time (`Asia/Jerusalem`)
- 🐳 **Docker Ready** — Single container deployment with persistent auth state in named volumes
- 📊 **Status Monitoring** — Real-time provider status, scheduling information, and failure tracking
- 🛡️ **Smart Retry Logic** — Exponential backoff for transient failures with configurable limits
- 💾 **State Persistence** — All timers, auth state, and failure counters survive container restarts

## 🏗️ Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Telegram Bot   │────▶│   Scheduler     │────▶│   Providers     │
│                 │     │                 │     │                 │
│  - Commands     │     │  - 5h Timer     │     │  - Claude       │
│  - Auth Flow    │     │  - 7d Timer     │     │  - Codex        │
│  - Notifications│     │  - State Persist│     │  - CLI Wake-up  │
│  - Access Ctrl  │     │  - Backoff Logic│     │  - Auth Checks  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Key Components:**

- `src/main.py` — Application entry point, orchestration of bot and scheduler
- `src/bot.py` — Telegram bot interface with command handlers
- `src/scheduler.py` — Wake-up scheduling logic with dual-cycle timers
- `src/config.py` — Environment configuration loader
- `src/providers/` — Provider implementations (Claude, Codex)

## 🚀 How It Works

**The Problem:** Many LLM CLI tools (like Claude Code and OpenAI Codex) use OAuth-based authentication with session expiration. After inactivity, sessions timeout, requiring you to re-authenticate before using the tool.

**The Solution:** Pobudka acts as a "session keeper" that sends minimal wake-up prompts at configurable intervals, keeping your authentication tokens fresh without consuming significant API quota.

### Dual-Cycle System

The scheduler maintains **two independent timers** per provider:

1. **5-hour timer** (`next_run_at`) — Frequent pings to keep short sessions alive
   - Claude mode: `clock_aligned_hour` (anchors to current UTC hour before adding window)
   - Codex mode: `rolling` (success time + window + delay)
   
2. **7-day timer** (`weekly_next_run_at`) — Weekly wake-up to prevent long-term token expiration
   - Both providers: `rolling` mode (success + weekly_window + weekly_delay)

The worker loop wakes when **either timer** becomes due (minimum delay of both).

### Wake Attempt Outcomes

- **Success:** Clears pause/backoff/failure counters, updates due timers, notifies on manual wake or recovery
- **Auth Failure:** Sets `paused_reason=auth_required`, schedules future attempts, triggers auth flow once per episode
- **Rate Limit:** Parses reset duration from provider output or falls back to 5h window
- **Transient Failure:** Applies exponential backoff: `retry = min(base * 2^(failures-1), max)`

### Access Control

The bot responds only to **one Telegram chat ID** (`TELEGRAM_CHAT_ID`). Messages from any other chat are ignored by command handlers.

## 📋 Requirements

- Docker and Docker Compose
- Telegram bot token
- Claude and/or Codex API credentials

## 🛠️ Installation

### 1. Clone the Repository

```bash
git clone https://github.com/holohup/pobudka.git
cd pobudka
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Telegram bot configuration
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Enabled providers (comma-separated)
ENABLED_PROVIDERS=claude,codex

# Claude provider
CLAUDE_MODEL=claude-sonnet-4-5-20250929
CLAUDE_WAKEUP_MESSAGE=hi

# Codex provider
CODEX_MODEL=gpt-5.1-codex-mini
CODEX_WAKEUP_MESSAGE=say hi
```

### 3. Start with Docker Compose

```bash
docker compose up -d --build
```

The bot will start immediately, check auth status, and begin its scheduling cycles.

## 💬 Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` `/menu` `/help` | Show command menu |
| `/status` | Show auth status for all enabled providers |
| `/schedule` | Display current schedule state (next 5h, next 7d, failures, pause state) |
| `/wake <provider>` | Trigger immediate wake-up attempt |
| `/wake <provider> HH:MM` | Schedule next wake at Israel time (`Asia/Jerusalem`) |
| `/auth <provider>` | Start device-code authentication flow |
| `/check_auth [provider]` | Verify auth status for one provider or all |

**Example usage:**
```
/wake claude              # Immediate wake-up for Claude
/wake codex 14:30          # Next wake at 14:30 Israel time
/schedule                 # View current schedule status
/auth claude              # Start Claude auth flow
```

## ⚙️ Configuration

### Scheduler Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SCHEDULER_STATE_PATH` | `data/scheduler_state.json` | State file location |
| `SCHEDULER_AUTH_RECHECK_SECONDS` | `60` | Auth recheck interval (not currently used) |
| `SCHEDULER_RETRY_BASE_SECONDS` | `60` | Base retry backoff for transient failures |
| `SCHEDULER_RETRY_MAX_SECONDS` | `3600` | Maximum retry backoff (1 hour) |

### Provider Settings

Each provider supports these settings:

| Variable | Description |
|----------|-------------|
| `<PROVIDER>_MODEL` | Model identifier |
| `<PROVIDER>_WAKEUP_MESSAGE` | Message to send on wake-up |
| `<PROVIDER>_RESET_MODE` | `rolling` or `clock_aligned_hour` |
| `<PROVIDER>_WINDOW_SECONDS` | Wake-up window size (default: 18000 = 5 hours) |
| `<PROVIDER>_WAKE_DELAY_SECONDS` | Delay after window start (default: 10) |
| `<PROVIDER>_WEEKLY_WINDOW_SECONDS` | Weekly cycle size (default: 604800 = 7 days) |
| `<PROVIDER>_WEEKLY_WAKE_DELAY_SECONDS` | Weekly wake delay (default: 10) |

### Auth Token Environment Variables

**Claude:**
- `CLAUDE_CODE_OAUTH_TOKEN` — Preferred (generated by `claude setup-token`)
- `CLAUDE_AUTH_TOKEN` — Legacy alias (auto-mapped by config loader)

**Codex:**
- Token managed internally via `codex login --device-auth`

## 🐳 Docker Deployment

### Build from Source

```bash
docker compose build --no-cache
docker compose up -d
```

### View Logs

```bash
docker compose logs -f
```

### Restart Service

```bash
docker compose restart
```

### Stop Service

```bash
docker compose down
```

### Inspect Container Status

```bash
docker compose ps
```

## 📁 Project Structure

```
pobudka/
├── src/
│   ├── main.py              # Application entry point
│   ├── bot.py               # Telegram bot interface
│   ├── scheduler.py         # Wake-up scheduling logic
│   ├── config.py            # Configuration management
│   └── providers/
│       ├── base.py          # Provider abstraction
│       ├── claude.py        # Claude provider
│       ├── codex.py         # Codex provider
│       ├── subprocess.py    # Subprocess runner
│       └── registry.py      # Provider registry
├── data/
│   └── scheduler_state.json # Persisted state (timers, auth, failures)
├── tests/
│   ├── test_*.py            # Unit and integration tests
│   └── test_docker_integration.py  # Docker integration tests
├── docker-compose.yml       # Docker Compose configuration
├── Dockerfile               # Docker image definition
├── requirements.txt         # Python dependencies
└── .env.example             # Environment template
```

### Named Volumes

The following Docker named volumes store persistent data:

- `root-home` — Home-level auth metadata persistence
- `claude-auth` — CLI auth persistence for Claude (`/root/.claude`)
- `codex-auth` — CLI auth persistence for Codex (`/root/.codex`)

## 🧪 Testing

Run the default test suite:

```bash
pytest -q
```

Run Docker integration tests:

```bash
RUN_DOCKER_INTEGRATION=1 pytest -q tests/test_docker_integration.py
```

Run full suite including Docker integration:

```bash
RUN_DOCKER_INTEGRATION=1 pytest -q
```

## 📖 Troubleshooting

### Bot not responding?

1. Check Telegram bot token is correct in `.env`
2. Verify your chat ID matches `TELEGRAM_CHAT_ID`
3. Check logs: `docker compose logs -f`
4. Ensure only one bot instance is running (two instances will conflict on Telegram long polling)

### Authentication failing?

**Claude:**
1. Use `/auth claude` to start device-code flow
2. Copy the full single-line URL generated by the CLI (wrapped URLs with line breaks cause "missing scope" errors)
3. Follow the URL and enter the code
4. Check status with `/check_auth claude`
5. If device auth unsupported, run fallback: `docker compose exec -it pobudka claude setup-token`

**Codex:**
1. Use `/auth codex` to start device-code flow
2. Follow the URL and enter the code
3. Check status with `/check_auth codex`
4. If you see "model is not supported with ChatGPT account", set `CODEX_MODEL` to `gpt-5.1-codex-mini` in `.env`
5. If you see "Not inside a trusted directory", this is handled automatically by `--skip-git-repo-check`

### Timers resetting after restart?

- State is persisted in `data/scheduler_state.json`
- Ensure the `./data` directory is properly mounted
- If editing state manually, stop the container first (in-memory state overwrites file edits on shutdown)
- Check that `SCHEDULER_STATE_PATH` points to a persisted location

### Scheduler edits getting reverted?

- If editing `data/scheduler_state.json` manually, stop container first
- During shutdown, in-memory state is persisted and can overwrite manual file edits done while running

### Deployment Notes

- Keep only **one active bot instance** at a time
- Two environments running with the same Telegram bot token will cause long polling conflicts
- Before starting prod, stop any local instance using the same token
- On new architecture hosts (e.g., Raspberry Pi), always run a full rebuild (`--build`) so native dependencies and CLI tooling are built for the target platform

### Data Migration

To migrate to another host, preserve:
- `.env` (contains bot token/chat id/provider config)
- `data/scheduler_state.json` (scheduler state)
- Contents of named volumes (`root-home`, `claude-auth`, `codex-auth`), or re-authenticate in the new container

## 📜 License

MIT License — see [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📧 Support

For issues and questions, please open a GitHub issue.
