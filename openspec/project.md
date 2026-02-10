# Project Context

## Purpose
Pobudka ("wake-up" in Russian) is a background service that keeps personal-use LLM provider rate-limit windows active by automatically sending minimal requests ("hi") right after each rate-limit period resets. This maximizes the usable portion of paid plans (5-hour rolling windows, weekly limits, etc.) so the developer doesn't have to wait for resets when starting their workday.

The service communicates with the user via a Telegram bot (aiogram) for status updates, error reporting, authentication flows, and runtime configuration.

**Key goals:**
- Automatically restart rate-limit windows the moment they expire
- Support multiple LLM providers with different reset policies (clock-aligned vs. rolling)
- Provide a Telegram interface for monitoring, alerts, and two-way interaction
- Run as a single Docker container with minimal dependencies

## Tech Stack
- **Language:** Python 3.13
- **Package manager:** pip (with requirements.txt or pyproject.toml)
- **Async runtime:** asyncio (built-in)
- **Telegram bot:** aiogram
- **HTTP client:** aiohttp or httpx (for LLM provider API calls)
- **Configuration:** Environment variables via `.env` file (mounted into Docker container)
- **State persistence:** JSON file (mounted volume) as fallback when provider APIs can't report current state
- **Containerization:** Docker + docker-compose
- **Linting/formatting:** Ruff
- **Testing:** pytest
- **License:** MIT

## Project Conventions

### Code Style
- **Formatter/linter:** Ruff (replaces black, flake8, isort)
- **Type hints:** Use type hints on all public functions and class attributes
- **Naming:** snake_case for functions/variables, PascalCase for classes, UPPER_SNAKE_CASE for constants
- **Imports:** Sorted by Ruff (isort-compatible), grouped as stdlib / third-party / local
- **Docstrings:** Google-style docstrings for public APIs
- **Line length:** 88 characters (Ruff default)
- **Async:** Prefer `async`/`await` throughout; avoid blocking calls in the event loop

### Architecture Patterns
- **Monolith service:** Single Python process running in one Docker container
- **Provider abstraction:** Each LLM provider implements a common interface (protocol/ABC) for authentication, sending wake-up requests, and querying rate-limit status
- **Settings/config:** A settings class per provider (loaded from `.env`) plus a registry of active providers
- **Scheduler:** An async scheduler that tracks per-provider reset times and triggers wake-up requests at the right moment
- **Telegram integration:** aiogram-based bot for:
  - Receiving status reports and error alerts
  - Sending commands to the service (e.g., force wake, check status)
  - Handling authentication flows (links, tokens) for providers
- **Expandability:** New providers are added by creating a new provider config and implementing the provider interface -- no changes to core logic required

### Testing Strategy
- **Framework:** pytest
- **Async tests:** pytest-asyncio for testing async code
- **Structure:** `tests/` directory mirroring `src/` (or project root) structure
- **Mocking:** Use `unittest.mock` / `pytest-mock` for external API calls (LLM providers, Telegram)
- **Coverage:** Aim for high coverage on scheduler logic and provider interface implementations
- **No live API calls in tests:** All provider interactions are mocked

### Git Workflow
- **Branching:** GitHub Flow -- feature branches off `main`, pull requests, merge to `main`
- **Commits:** Conventional commits enforced (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`)
- **Branch naming:** kebab-case, descriptive (e.g., `feat/add-claude-provider`, `fix/timer-drift`)
- **PRs:** Required for all changes to `main`
- **Remote:** `origin` at `git@github.com:holohup/pobudka.git`

## Domain Context

### LLM Provider Rate Limits
- **Anthropic (Claude):** Rate-limit windows are clock-aligned -- the 5-hour window starts at the beginning of the hour when usage begins. Weekly limits follow a similar pattern.
- **OpenAI (Codex):** Rate-limit windows are rolling -- the 5-hour window starts exactly when usage begins, and the weekly limit follows the same rolling pattern.
- **General pattern:** Each provider has its own reset policy. The service must track when each window was activated and send a wake-up request as soon as the window expires (ideally within seconds of reset).
- **Exact policies:** Must be researched per provider, as they may change. The service should be configurable to adapt.

### Telegram Bot Interaction
- The user creates a Telegram bot and provides the API token via `.env`
- The bot sends the user:
  - Alerts when a wake-up request fails
  - Status updates (e.g., "Claude 5h window reset, wake-up sent successfully")
  - Time remaining until each provider's next reset (on request or at startup)
  - Authentication links/tokens when a provider requires re-authentication
- The user can send commands to:
  - Check current status of all providers
  - Force an immediate wake-up for a specific provider
  - Adjust settings at runtime

### Key Terminology
- **Wake-up / ping:** Sending a minimal request to an LLM provider to start or restart a rate-limit window
- **Provider:** An LLM API service (e.g., Claude, Codex) with its own authentication and rate-limit policy
- **Window:** A rate-limit period (e.g., 5-hour, weekly) that starts on usage and expires after a set duration
- **Reset:** The moment a rate-limit window expires and a new one can begin

## Important Constraints
- **Personal use only:** This is a single-user service; no multi-tenancy
- **Minimal dependencies:** Prefer stdlib + well-known async libraries; avoid heavy frameworks
- **No secrets in repo:** All API keys, tokens, and credentials live in `.env` (gitignored)
- **Container-first:** Must run reliably in Docker; `.env` file is volume-mounted
- **Graceful degradation:** If a provider's API is unreachable, log the error, alert via Telegram, and retry -- don't crash the service
- **State recovery:** On startup, query providers for current rate-limit state if their APIs support it; otherwise, fall back to persisted JSON state file

## External Dependencies
- **Anthropic API:** Claude model access and rate-limit information
- **OpenAI API:** Codex model access and rate-limit information
- **Telegram Bot API:** Via aiogram for user communication
- **Docker Hub:** Base Python image for containerization
