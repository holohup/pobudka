# Claude SDK subscription quota research

Researched 2026-10-14. Scope: read remaining Claude subscription quotas and reset times without submitting a model request. Research used official documentation, official repositories, and Anthropic's published npm package. No credentials were read and no model inference was triggered by this research task.

## Finding and recommendation

**Yes: the current TypeScript Claude Agent SDK has a dedicated structured quota read.** It is explicitly experimental, rather than a stable public quota API. SDK **0.3.300** matches Claude Code **2.1.300**. Its query method is named `usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET`, introduced in 0.3.169. [Official release](https://github.com/anthropics/claude-agent-sdk-typescript/releases/tag/v0.3.300), [official changelog](https://github.com/anthropics/claude-agent-sdk-typescript/blob/v0.3.300/CHANGELOG.md).

**For Pobudka, use the structured `usage_report` emitted by the installed CLI's local `/usage` command in stream JSON.** During this research, the parent deployment agent confirmed that route on C4 with the fresh stored login and zero inference. It removes human-text parsing without adding an SDK dependency. Retain the validated text parser as compatibility fallback. The dedicated SDK method remains an option if named windows are later needed, subject to its experimental contract.

## Three different meanings of usage

| Interface | Relevant data | Suitable for periodic subscription quota reads? |
| --- | --- | --- |
| Agent SDK experimental `get_usage` control request | Structured subscription windows and resets | Yes, subject to pinning and a zero-inference runtime check |
| Agent SDK `rate_limit_event` | Status changes for one applicable window; optional utilization/reset | Useful during existing work, insufficient as a complete periodic snapshot |
| Anthropic API client SDK | API organization/workspace request/token limits and usage | Different quota pool from Claude subscription windows |

The Agent SDK exposes Claude Code's agent runtime. The Anthropic client SDK accesses the Claude API directly. API response headers include request/token remaining counts and RFC 3339 resets, and the API also has organization/workspace Rate Limits endpoints; these are not a documented route to a Claude.ai subscriber's five-hour/weekly allowances. [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [API rate limits](https://platform.claude.com/docs/en/api/rate-limits).

## Dedicated structured read

Inspecting `sdk.d.ts` in Anthropic's [published 0.3.300 npm artifact](https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.300.tgz) shows:

- Return type: `SDKControlGetUsageResponse`.
- `subscription_type`: string or null; `rate_limits_available`: boolean.
- `rate_limits.five_hour`, `seven_day`, `seven_day_oauth_apps`, `seven_day_opus`, `seven_day_sonnet`: optional nullable windows, each with nullable `utilization` (percentage, **0–100**) and `resets_at` (ISO 8601).
- `model_scoped`: optional per-model weekly windows with `display_name`.
- `extra_usage`: optional billing-period spend details.
- `session`: current-session cost, API duration, model usage and other totals.
- `behaviors`: approximate local transcript attribution; `skipBehaviors: true` skips scanning recent transcripts and leaves this null.

Compute remaining percentage as `100 - utilization` only when the percentage is valid. There is no promised remaining-message count. Preserve absent windows and missing resets as null.

The method forwards a `get_usage` control request, rather than submitting a user message. Auth refresh and a network quota request can still occur: inference-free does not mean network-free. The package explicitly warns that this API may change or disappear in any release. Pin it and validate its returned shape. [Published implementation and declarations](https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.300.tgz).

## Initialization without a prompt

The published `sdk.mjs` starts the subprocess, its output reader, and the initialize control exchange independently of user input. An async input iterator can remain open while yielding **zero messages**. The quota control request can then run after initialization. Calling `query()` with an ordinary string instead would submit a user message. Cleanup closes the transport and terminates the subprocess. [Published SDK implementation](https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.300.tgz).

This is a candidate runtime probe, derived from source inspection; this research subagent did **not** execute it against credentials. Install the exact package in a disposable test directory and run under an external timeout. `CLAUDE_BIN` should select the tested 2.1.300 native executable. Use the existing stored login through the CLI's normal configuration directory; do not extract bearer tokens.

```js
import { query } from '@anthropic-ai/claude-agent-sdk';

let release;
const held = new Promise(resolve => { release = resolve; });
async function* noMessages() { await held; }

const q = query({
  prompt: noMessages(),
  options: {
    cwd: '/tmp',
    pathToClaudeCodeExecutable: process.env.CLAUDE_BIN,
    settingSources: [],
    settings: { disableAllHooks: true },
    tools: [],
    mcpServers: {},
    strictMcpConfig: true,
    permissionMode: 'default',
    persistSession: false,
  },
});

try {
  await q.supportedCommands(); // Wait for initialization; no user message.
  const data = await q
    .usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET({
      skipBehaviors: true,
    });
  if (data.session.total_cost_usd !== 0 ||
      data.session.total_api_duration_ms !== 0 ||
      Object.keys(data.session.model_usage).length !== 0) {
    throw new Error('Unexpected model usage during quota read');
  }
  console.log(JSON.stringify(data));
} finally {
  q.close();
  release();
  await q.return();
}
```

The guard verifies reported usage after the operation; it is not a preventive model-network firewall. No user message is yielded. Disable startup hooks and avoid resuming a previous session, because hooks and resumed background work can inject turns. This source-derived sequence still needs live confirmation of authentication, returned windows, zero session usage and process cleanup.

## A potentially simpler CLI route

Since SDK/CLI parity version 0.3.273/2.1.273, the assistant message for headless `/usage` can carry a `usage_report` sibling. The documented type has `rate_limits.limits[]` rows with `kind`, `group`, `percent`, `resets_at`, optional `scope`, `severity`, and `is_active`. Classify by `kind`, such as `session` or `weekly_all`, instead of localized labels. The report deliberately relays current server rows, omitting cached/header-derived substitutes. Null rows may mean an older server response or failed collection. [Official changelog](https://github.com/anthropics/claude-agent-sdk-typescript/blob/v0.3.300/CHANGELOG.md), [published `SDKUsageReport` declaration](https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.300.tgz).

The parent agent live-tested `claude -p /usage --output-format stream-json --verbose` against Claude Code 2.1.300 on C4 using the isolated fresh login. It reported:

- `usage_report.session`: zero cost and API duration, empty model usage.
- `rate_limits.limits`: `session`, 0% used, null reset; `weekly_all`, 94% used, reset `2026-10-17T10:00:00.723842+00:00`.
- Final result: `local_command: "usage"`, zero turns, tokens, API duration and cost.

These are runtime observations supplied by the parent deployment agent, not independently re-run by the research subagent. They confirm the structured CLI route works for this account. Add `--no-session-persistence` to avoid retaining quota-only transcripts, and retain the final-result zero-inference checks before accepting the report. Keep slash commands enabled: `/usage` requires their dispatch.

The existing [project validation record](cli-usage-validation.md) and [sanitized 2.1.300 fixture](../tests/fixtures/usage/claude-2.1.300.json) also establish that plain JSON `/usage` succeeds locally with zero inference and returns session/weekly percentages plus a human-formatted weekly reset. Plain JSON's final result does not contain the assistant stream's `usage_report`; consuming the stream preserves that structured data.

## Rate-limit events are not a complete meter

Python `RateLimitInfo` exposes `status`, optional `resets_at`, `rate_limit_type`, `utilization`, and overage fields; its utilization is a **fraction, 0–1**, unlike the structured usage response's percentage. The event represents rate-limit state changes. It does not promise simultaneous snapshots of every window. A missing utilization is unknown, not zero. [Official Python types](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py).

A historical issue describes normal allowed events omitting utilization at low usage. Treat that as corroborating a limitation, not as a current-version guarantee or an endorsed API contract. [Issue in Anthropic's tracker](https://github.com/anthropics/claude-code/issues/50518).

The inspected Python client's public methods include `get_context_usage()` but no subscription `get_usage()` wrapper. Context usage measures the context window, not remaining plan allowance. Implementing the experimental control request through a private Python `_query` member would introduce additional dependence on SDK internals. [Official Python client](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/client.py).

## Authentication and scope

The structured response marks limits unavailable for API-key/cloud-provider sessions or missing profile scope. Pobudka's existing validation independently found that an inference-only environment OAuth token overrides stored login and returns no subscription windows; a fresh full `claude auth login --claudeai` fixes collection. Retain this full login inside Pobudka and publish only sanitized snapshots. The SDK method does not require the dashboard to read or refresh credentials itself. [Published quota response declarations](https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.300.tgz), [local auth validation](cli-usage-validation.md).

Anthropic's current subscriber help page, updated October 7, explicitly says subscription limits remain usable with the Agent SDK and `claude -p`. The developer quickstart separately directs third-party product developers to API-key authentication. This personal dashboard does not need to add a product login flow or duplicate credential storage. [Current subscriber guidance](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), [developer quickstart](https://code.claude.com/docs/en/agent-sdk/quickstart).

## Evidence boundaries

Official documentation and the exact npm artifact establish that a structured read exists; static source establishes the intended control-message sequence. This research does not claim the experimental SDK path has passed a live account test. Claude Code 2.1.300 is distributed as a native executable rather than a readable `cli.js`, so the server-side control handler was not independently audited here. The structured CLI `/usage` runtime evidence above comes from the parent deployment agent's live C4 test; the plain JSON evidence is also captured in the main task's validation record.

Artifact SHA-256 values, for reproducing the inspection:

- `sdk.d.ts`: `9ebce26cc46cea565330280703f180801556956ef8f2b52b86e6da947546633d`
- `sdk.mjs`: `c1ccee152f98ff6899c2989b6151086e5d0ff34aedd93bd98cc4576619c41d5f`
