# Change: Add provider authentication and CLI-based wake-up architecture

## Why
Pobudka needs to authenticate with LLM providers (Anthropic Claude, OpenAI Codex) to send wake-up requests that reset **subscription-level** rate-limit windows. The 5-hour rolling windows apply to consumer subscriptions (Claude Pro/Max, ChatGPT Plus/Pro), not to API-key-based pay-per-token usage. This means the service must authenticate the same way the official CLI tools do -- via OAuth sessions -- not via API keys.

The key architectural insight is that rather than reimplementing provider-specific OAuth flows and API calls in Python, the service can install the official CLI tools (`claude`, `codex`) inside the Docker container and shell out to them for both authentication and sending wake-up messages. Python handles orchestration, scheduling, Telegram communication, and error handling.

## What Changes
- Define a provider authentication abstraction that wraps CLI tools
- Anthropic (Claude): use `claude -p "hi"` with OAuth session stored in `~/.claude/`
- OpenAI (Codex): use `codex exec "say hi" --full-auto` with OAuth session stored in `~/.codex/auth.json`
- Device-code auth via Telegram: service runs `claude auth login --device` or `codex login --device-auth` inside the container, captures the code+URL, and sends them to the user via Telegram. User completes auth on any browser (phone/laptop). No port exposure needed.
- Fallback: manual auth file copy to Docker volume mounts when device-code flow is unavailable
- Auth state detection: check if CLI tools have valid sessions before attempting wake-ups
- Re-authentication flow: detect auth failures, automatically initiate device-code flow, send code via Telegram

## Impact
- Affected specs: `provider-auth` (new)
- Affected code: Dockerfile (install Node.js + CLIs), provider abstraction layer, Telegram bot handlers
- Docker image size increases (Node.js runtime + CLI tools required)
- Requires volume mounts for `~/.claude/` and `~/.codex/` to persist auth across container restarts
