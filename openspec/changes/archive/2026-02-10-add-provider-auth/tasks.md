## 1. Docker Setup
- [x] 1.1 Create Dockerfile with Python 3.13 + Node.js 22 base
- [x] 1.2 Install Claude Code CLI (`curl -fsSL https://claude.ai/install.sh | bash`)
- [x] 1.3 Install OpenAI Codex CLI (`npm install -g @openai/codex`)
- [x] 1.4 Create docker-compose.yml with volume mounts for `~/.claude/`, `~/.codex/`, `.env`, and state JSON
- [x] 1.5 Verify both CLIs are callable from within the container

## 2. Provider Abstraction
- [x] 2.1 Define provider protocol/ABC: `check_auth()`, `send_wakeup()`, `get_status()`, `request_reauth()`
- [x] 2.2 Implement async subprocess wrapper for CLI execution with timeout and output capture
- [x] 2.3 Implement Claude provider: `claude -p "hi"` for wake-up, exit code / output parsing for auth status
- [x] 2.4 Implement Codex provider: `codex exec "say hi" --full-auto` for wake-up, parse output for auth status
- [x] 2.5 Implement provider registry loaded from `.env` configuration

## 3. Auth Detection and Device-Code Re-auth Flow
- [x] 3.1 Implement auth check for Claude (`claude auth status` or attempt `claude -p "hi"` and detect auth errors)
- [x] 3.2 Implement auth check for Codex (attempt command or check `~/.codex/auth.json` existence and validity)
- [x] 3.3 Implement device-code auth orchestrator: run CLI device-auth command, parse code+URL from stdout, forward via Telegram, wait for completion
- [x] 3.4 Implement Claude device-code flow: `claude auth login --device` stdout parsing (8-char code + `https://claude.ai/device` URL)
- [x] 3.5 Implement Codex device-code flow: `codex login --device-auth` stdout parsing (user code + `https://openai.com/device` URL)
- [x] 3.6 Implement fallback: Telegram notification with manual file-copy instructions when device-code flow fails
- [x] 3.7 Implement `/auth <provider>` Telegram command to trigger device-code flow on demand
- [x] 3.8 Implement `/check_auth <provider>` Telegram command for manual auth verification
- [x] 3.9 Implement auth state persistence check on startup

## 4. Configuration
- [x] 4.1 Define `.env` schema: Telegram bot token, enabled providers list, per-provider settings
- [x] 4.2 Create settings classes (pydantic or dataclass) for provider configuration
- [x] 4.3 Document `.env.example` with all required and optional variables

## 5. Testing
- [x] 5.1 Unit tests for provider abstraction with mocked subprocess calls
- [x] 5.2 Unit tests for auth detection logic (mock CLI outputs for success/failure/expired scenarios)
- [x] 5.3 Integration test: verify Dockerfile builds and CLIs are accessible
