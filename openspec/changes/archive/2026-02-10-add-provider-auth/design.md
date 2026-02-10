## Context
Pobudka must send minimal requests to LLM providers to restart subscription rate-limit windows. The 5-hour rolling windows are tracked by the **consumer subscription system** (Claude Pro/Max, ChatGPT Plus/Pro), which is separate from the API-key-based pay-per-token system. This means we must authenticate the same way the official CLI tools do.

Two official CLI tools exist:
- **Claude Code CLI** (`claude`): Node.js-based, authenticates via OAuth to claude.ai, stores session in `~/.claude/`
- **OpenAI Codex CLI** (`codex`): Node.js/Rust hybrid, authenticates via OAuth on port 1455, stores tokens in `~/.codex/auth.json`

### Key research findings

**Anthropic (Claude):**
- `claude -p "hi"` sends a one-shot message in print mode and exits -- this is the wake-up command
- OAuth session is obtained via `claude` (interactive, opens browser) or `/login` command
- **Device-code flow supported:** `claude auth login --device` generates an 8-character code and a URL (`https://claude.ai/device`). User enters the code on any browser (phone, laptop). CLI auto-detects completion.
- `claude auth status` checks current login state
- API keys (`ANTHROPIC_API_KEY`) are permanent, never expire -- but usage goes against pay-per-token billing, NOT subscription billing
- Rate-limit headers (`anthropic-ratelimit-*`) are returned on API responses but only reflect API-tier limits, not subscription windows
- No known public API to query subscription-level remaining usage
- `claude -p "hi" --output-format json` returns structured JSON with `is_error`, `result`, `total_cost_usd`, and `usage` fields. On auth failure: `{"is_error":true,"result":"Invalid API key · Fix external API key",...}`
- Rate-limit error messages from both CLIs include reset time text (e.g., "Your limit will reset in X hours Y minutes") which can be parsed to determine remaining window time

**OpenAI (Codex):**
- `codex exec "say hi" --full-auto` sends a one-shot agentic command -- this is the wake-up command
- OAuth flow uses localhost:1455 callback, stores `access_token` + `refresh_token` in `~/.codex/auth.json`
- **Device-code flow supported (v0.76.0+):** `codex login --device-auth` generates a user code and a verification URL (`https://openai.com/device`). User enters the code on any browser. CLI polls and auto-completes.
- **Headless paste-code fallback:** `codex login --headless` generates an OAuth URL; user visits it, gets an authorization code, and pastes it back into the CLI prompt.
- Refresh tokens are used automatically; access tokens are short-lived (minutes/hours)
- `OPENAI_API_KEY` is separate billing -- does NOT count against ChatGPT subscription
- `codex login status` reports auth type (e.g., "Logged in using ChatGPT") but NOT remaining usage
- `codex exec "say hi" --full-auto --json` outputs JSONL events; on auth failure returns `{"type":"error","message":"Your access token could not be refreshed..."}` and `{"type":"turn.failed",...}`
- Known issue: refresh tokens can fail with `"code":"refresh_token_reused"` error, requiring a full re-login

## Goals / Non-Goals
- **Goals:**
  - Authenticate with both providers using their official CLI tools
  - Detect expired/missing auth and guide user through re-auth via Telegram
  - Persist auth state across container restarts via volume mounts
  - Support adding new providers with minimal code changes
- **Non-Goals:**
  - Reverse-engineer internal OAuth APIs (we delegate to CLIs)
  - Support API-key-based wake-ups as primary method (won't reset subscription windows)
  - Build a web UI for authentication

## Decisions

### Decision 1: Shell out to official CLIs instead of reimplementing OAuth
- **Why:** The OAuth flows for both providers are undocumented internal APIs. The CLIs already handle token storage, refresh, and error recovery. Reimplementing would be fragile and require constant maintenance.
- **Trade-off:** Larger Docker image (Node.js + CLIs), dependency on third-party CLI stability.
- **Alternatives considered:**
  - Pure Python OAuth implementation: Rejected -- undocumented flows, high maintenance burden
  - Browser automation (Playwright): Rejected -- heavy, fragile, possible ToS violation
  - API keys only: Rejected -- doesn't reset subscription windows (core purpose defeated)

### Decision 2: Device-code auth orchestrated via Telegram
- **Why:** Both CLIs support device-code / headless OAuth flows that don't require a browser on the same machine. The container runs the CLI's device-auth command, captures the code + URL, and forwards them to the user via Telegram. The user completes auth on any device (phone, laptop). No port exposure needed.
- **Primary flow (device-code):**
  1. Service detects missing/expired auth for a provider
  2. Runs the device-auth CLI command inside the container (`claude auth login --device` or `codex login --device-auth`)
  3. Captures the device code and verification URL from CLI stdout
  4. Sends them to the user via Telegram: "Open https://claude.ai/device and enter code: ABCD-1234"
  5. CLI polls automatically and completes auth; service detects success
- **Fallback (manual file copy):**
  1. If device-code flow fails or is unsupported by a future provider, user can authenticate on a local machine and copy auth files to the Docker volume mount
  2. User sends `/check_auth <provider>` via Telegram to trigger verification

### Decision 3: Volume-mount auth directories
- **Why:** Auth tokens must survive container restarts. Both CLIs store auth in well-known directories.
- **Mounts:**
  - `~/.claude/` for Claude Code sessions
  - `~/.codex/` for Codex CLI tokens (including `auth.json`)
- **Alternative considered:** Copy tokens into a single JSON file managed by pobudka. Rejected -- CLIs expect their own directory structure for token refresh.

### Decision 4: Provider interface abstraction
- **Why:** Need to support multiple providers with different CLIs, auth flows, and rate-limit policies.
- **Pattern:** Python ABC/Protocol with methods: `check_auth()`, `send_wakeup()`, `get_status()`, `request_reauth()`
- **Each provider implements:** CLI command construction, output parsing, error detection

## Risks / Trade-offs
- **CLI breaking changes:** Provider CLIs may change flags, output format, or auth storage between versions. Mitigation: pin CLI versions in Dockerfile, add version checks.
- **OAuth token expiry:** Refresh tokens have unknown lifetimes and may expire without warning. Mitigation: proactive auth checks before each wake-up, immediate Telegram alerts on failure.
- **Docker image size:** Adding Node.js + CLIs increases image size significantly. Mitigation: use multi-stage build or slim base images, accept trade-off given single-user use case.
- **Device-code flow parsing:** The service must parse device codes and URLs from CLI stdout, which is not a stable interface. Output format may change between CLI versions. Mitigation: regex-based parsing with fallback to manual copy flow; pin CLI versions.

## Resolved Questions
1. ~~Should we support in-container OAuth callbacks?~~ **No.** Container is behind firewalls, no port exposure possible. Use device-code flow (no ports needed) with manual file copy as fallback.
2. ~~Should we pin specific CLI versions or use latest?~~ **Pin to current latest.** Claude Code v2.1.38, Codex CLI v0.87.0. Update manually when needed.
3. ~~Can `codex status` report subscription-level remaining limits?~~ **No dedicated status command exists for either CLI.** `codex login status` only reports auth type ("Logged in using ChatGPT"), not remaining usage. Neither CLI exposes a "check my remaining quota" command. However, when a rate limit IS hit, both CLIs output a human-readable message with reset time (e.g., "Your limit will reset in X hours Y minutes"). The service can parse these messages to extract reset timing.

## CLI Output Parsing Reference (tested on local CLIs)

### Claude (`claude -p "hi" --output-format json`)
- Success: `{"is_error":false, "result":"hi! how can i help you...", "total_cost_usd":0.12, ...}`
- Auth failure: `{"is_error":true, "result":"Invalid API key · Fix external API key", ...}`
- Rate limit: text in `result` field contains reset time info (needs empirical testing at limit)

### Codex (`codex exec "say hi" --full-auto --json`)
- Success: JSONL stream ending with a completion event
- Auth failure: `{"type":"error","message":"Your access token could not be refreshed..."}`
- Refresh token reuse: error with `"code":"refresh_token_reused"` -- requires full re-login
- Rate limit: `{"type":"error","message":"You've hit your usage limit. Try again in X hours Y minutes."}`

## Open Questions
1. What are the exact refresh token lifetimes for each provider? (Need empirical testing)
2. Exact format of rate-limit-hit messages from both CLIs (need to hit the limit to capture the real output for parser development)
