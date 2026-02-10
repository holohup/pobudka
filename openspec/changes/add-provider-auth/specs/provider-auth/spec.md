## ADDED Requirements

### Requirement: Provider Authentication Abstraction
The system SHALL define a provider interface (protocol or ABC) that all LLM providers MUST implement. The interface SHALL include methods for checking authentication status, sending wake-up requests, querying provider status, and requesting re-authentication.

#### Scenario: Provider interface is implemented by Claude provider
- **WHEN** the Claude provider is instantiated
- **THEN** it SHALL implement `check_auth()`, `send_wakeup()`, `get_status()`, and `request_reauth()`
- **AND** it SHALL use the Claude Code CLI (`claude`) for all provider interactions

#### Scenario: Provider interface is implemented by Codex provider
- **WHEN** the Codex provider is instantiated
- **THEN** it SHALL implement `check_auth()`, `send_wakeup()`, `get_status()`, and `request_reauth()`
- **AND** it SHALL use the OpenAI Codex CLI (`codex`) for all provider interactions

### Requirement: CLI-Based Wake-Up Requests
The system SHALL send wake-up requests by executing official provider CLI tools as subprocesses. The wake-up request SHALL be a minimal message that triggers the provider's subscription rate-limit window to start.

#### Scenario: Claude wake-up via CLI
- **WHEN** the scheduler triggers a Claude wake-up
- **THEN** the system SHALL execute `claude -p "hi"` as an async subprocess
- **AND** capture the exit code and output to determine success or failure
- **AND** report the result via Telegram

#### Scenario: Codex wake-up via CLI
- **WHEN** the scheduler triggers a Codex wake-up
- **THEN** the system SHALL execute `codex exec "say hi" --full-auto` as an async subprocess
- **AND** capture the exit code and output to determine success or failure
- **AND** report the result via Telegram

#### Scenario: Wake-up failure due to expired auth
- **WHEN** a wake-up command fails with an authentication error
- **THEN** the system SHALL detect the auth failure from the CLI output or exit code
- **AND** trigger the re-authentication flow for that provider
- **AND** notify the user via Telegram that re-authentication is required

### Requirement: Authentication State Detection
The system SHALL detect whether each provider has a valid authentication session before attempting wake-up requests. Detection SHALL be performed by invoking the CLI tool and analyzing the result.

#### Scenario: Valid auth detected on startup
- **WHEN** the service starts and a provider's auth directory contains valid session data
- **THEN** `check_auth()` SHALL return success
- **AND** the provider SHALL be marked as ready for wake-up scheduling

#### Scenario: Missing auth detected on startup
- **WHEN** the service starts and a provider's auth directory is empty or missing
- **THEN** `check_auth()` SHALL return failure
- **AND** the system SHALL send a Telegram notification with re-auth instructions
- **AND** the provider SHALL NOT be scheduled for wake-ups until auth is resolved

#### Scenario: Auth expires during operation
- **WHEN** a previously valid auth session expires (e.g., refresh token expired)
- **THEN** the next `send_wakeup()` or `check_auth()` call SHALL detect the failure
- **AND** the system SHALL trigger the re-authentication flow

### Requirement: Device-Code Authentication via Telegram
The system SHALL use the device-code OAuth flow (supported by both CLIs) as the primary authentication method. The service runs the device-auth command inside the container, captures the code and URL from stdout, and sends them to the user via Telegram. No port exposure is required.

#### Scenario: Claude device-code auth via Telegram
- **WHEN** Claude authentication is missing or expired
- **THEN** the system SHALL execute `claude auth login --device` as an async subprocess
- **AND** parse the device code and verification URL from the CLI output
- **AND** send a Telegram message: "Open {url} and enter code: {code}"
- **AND** wait for the CLI to detect successful authorization
- **AND** confirm success via Telegram when auth is complete

#### Scenario: Codex device-code auth via Telegram
- **WHEN** Codex authentication is missing or expired
- **THEN** the system SHALL execute `codex login --device-auth` as an async subprocess
- **AND** parse the user code and verification URL from the CLI output
- **AND** send a Telegram message: "Open {url} and enter code: {code}"
- **AND** wait for the CLI to detect successful authorization
- **AND** confirm success via Telegram when auth is complete

#### Scenario: Device-code flow fails, fallback to manual copy
- **WHEN** the device-code CLI command fails or times out
- **THEN** the system SHALL send a Telegram message with manual instructions:
  - For Claude: "Run `claude` on a machine with a browser, then copy `~/.claude/` to the Docker volume"
  - For Codex: "Run `codex auth login` on a machine with a browser, then copy `~/.codex/auth.json` to the Docker volume"
- **AND** the system SHALL periodically re-check auth status and confirm via Telegram when auth is restored

#### Scenario: User triggers manual auth check via Telegram
- **WHEN** the user sends `/check_auth <provider>` via Telegram after completing manual re-authentication
- **THEN** the system SHALL immediately run `check_auth()` for that provider
- **AND** report the result via Telegram

#### Scenario: User triggers device-code auth via Telegram
- **WHEN** the user sends `/auth <provider>` via Telegram
- **THEN** the system SHALL initiate the device-code flow for that provider
- **AND** send the code and URL back via Telegram

### Requirement: Auth Persistence Across Restarts
The system SHALL persist provider authentication state across container restarts by mounting provider-specific directories as Docker volumes.

#### Scenario: Auth survives container restart
- **WHEN** the container is restarted
- **THEN** provider auth directories (`~/.claude/`, `~/.codex/`) SHALL be available via volume mounts
- **AND** previously valid auth sessions SHALL continue to work without re-authentication

### Requirement: Provider Configuration via Environment
The system SHALL load provider configuration from environment variables (`.env` file). Each provider SHALL have its own configuration section.

#### Scenario: Provider list loaded from .env
- **WHEN** the service starts
- **THEN** it SHALL read the list of enabled providers from the `ENABLED_PROVIDERS` environment variable
- **AND** load provider-specific settings (e.g., model name, wake-up command customization) from provider-prefixed env vars

#### Scenario: Missing required configuration
- **WHEN** a required environment variable is missing for an enabled provider
- **THEN** the service SHALL log an error and notify via Telegram
- **AND** the provider SHALL be disabled until the configuration is corrected

### Requirement: Docker Environment with CLI Tools
The Docker image SHALL include both the Claude Code CLI and OpenAI Codex CLI, along with their runtime dependencies (Node.js 22+).

#### Scenario: Docker image contains required CLIs
- **WHEN** the Docker image is built
- **THEN** `claude --version` SHALL execute successfully
- **AND** `codex --help` SHALL execute successfully
- **AND** Python 3.13 SHALL be available as the default Python interpreter
