# 🤖 Pobudka

> *"Pobudka" - Polish for "wake up"*

**Keep your LLM providers awake and tokens fresh.** A Telegram-based automation bot that periodically pings Claude and Codex services to prevent sessions from expiring, keeping your AI assistants ready 24/7.

## ✨ Features

- 🔄 **Automated Wake-up Scheduling** - Dual-cycle timer system (5-hour + 7-day) to keep tokens active
- 📱 **Telegram Control** - Full bot interface for monitoring and manual controls
- 🔐 **Built-in Auth Management** - Device-code authentication flow for Claude and Codex
- 🎯 **Israel Time Scheduling** - Schedule wake-ups in your local timezone
- 🐳 **Docker Ready** - Single container deployment with persistent auth state
- 📊 **Status Monitoring** - Real-time provider status and scheduling information

## 🏗️ Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Telegram Bot   │────▶│   Scheduler     │────▶│   Providers     │
│                 │     │                 │     │                 │
│  - Commands     │     │  - 5h Timer     │     │  - Claude       │
│  - Auth Flow    │     │  - 7d Timer     │     │  - Codex        │
│  - Notifications│     │  - State Persist│     │  - Wake-up      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## 🚀 How It Works

1. **Scheduled Wake-ups**: The scheduler triggers periodic wake-up calls to your LLM providers
2. **Dual-Cycle System**:
   - **5-hour timer**: Frequent pings to keep short sessions alive
   - **7-day timer**: Weekly wake-up to prevent long-term token expiration
3. **Auth Management**: Automatic device-code auth when providers report authentication issues
4. **State Persistence**: All timers and auth state survive container restarts

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
docker compose up -d
```

The bot will start immediately and begin its scheduling cycles.

## 💬 Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` `/menu` `/help` | Show command menu |
| `/status` | Show auth status for all providers |
| `/schedule` | Display current schedule state (Israel time) |
| `/wake <provider>` | Trigger immediate wake-up |
| `/wake <provider> HH:MM` | Schedule next wake in Israel time |
| `/weeklywake <provider> DD.MM HH:MM` | Schedule weekly wake (e.g., `/weeklywake codex 24.02 09:00`) |
| `/auth <provider>` | Start device-code authentication |
| `/check_auth [provider]` | Verify auth status |

**Example usage:**
```
/wake claude              # Immediate wake-up for Claude
/wake codex 14:30          # Next wake at 14:30 Israel time
/weeklywake codex 24.02 09:00  # Weekly wake on Feb 24 at 09:00
/schedule                 # View current schedule status
```

## ⚙️ Configuration

### Scheduler Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SCHEDULER_STATE_PATH` | `data/scheduler_state.json` | State file location |
| `SCHEDULER_AUTH_RECHECK_SECONDS` | `60` | Auth recheck interval |
| `SCHEDULER_RETRY_BASE_SECONDS` | `60` | Base retry backoff |
| `SCHEDULER_RETRY_MAX_SECONDS` | `3600` | Max retry backoff |

### Provider Settings

Each provider supports these settings:

| Variable | Description |
|----------|-------------|
| `<PROVIDER>_MODEL` | Model identifier |
| `<PROVIDER>_WAKEUP_MESSAGE` | Message to send on wake-up |
| `<PROVIDER>_RESET_MODE` | `rolling` or `clock_aligned_hour` |
| `<PROVIDER>_WINDOW_SECONDS` | Wake-up window size |
| `<PROVIDER>_WAKE_DELAY_SECONDS` | Delay after window start |
| `<PROVIDER>_WEEKLY_WINDOW_SECONDS` | Weekly cycle size (default: 604800 = 7 days) |
| `<PROVIDER>_WEEKLY_WAKE_DELAY_SECONDS` | Weekly wake delay |

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

## 📁 Project Structure

```
pobudka/
├── src/
│   ├── main.py           # Application entry point
│   ├── bot.py            # Telegram bot interface
│   ├── scheduler.py      # Wake-up scheduling logic
│   ├── config.py         # Configuration management
│   └── providers/
│       ├── base.py       # Provider abstraction
│       ├── claude.py     # Claude provider
│       ├── codex.py      # Codex provider
│       └── ...
├── data/
│   └── scheduler_state.json  # Persisted state
├── docker-compose.yml
├── Dockerfile
└── .env.example
```

## 🧪 Testing

Run the default test suite:

```bash
pytest -q
```

Run Docker integration tests:

```bash
RUN_DOCKER_INTEGRATION=1 pytest -q tests/test_docker_integration.py
```

## 📖 Troubleshooting

### Bot not responding?
1. Check Telegram bot token is correct
2. Verify your chat ID is authorized
3. Check logs: `docker compose logs -f`

### Authentication failing?
1. Use `/auth <provider>` to start device-code flow
2. Follow the URL and enter the code
3. Check status with `/check_auth <provider>`

### Timers resetting after restart?
- State is persisted in `data/scheduler_state.json`
- Ensure the `./data` volume is properly mounted

### Weekly timer being overridden?
- Manual `/weeklywake` settings are now preserved across restarts
- Check that `SCHEDULER_STATE_PATH` points to a persisted location

## 📜 License

MIT License - see LICENSE file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📧 Support

For issues and questions, please open a GitHub issue.
