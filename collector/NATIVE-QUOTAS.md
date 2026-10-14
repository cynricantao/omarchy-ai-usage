# Optional genuine quota windows

Default: **disabled**. Enable only after reading the root privacy notice:
`token-activity configure '{"remote_quotas":true}'`.

Quota reads may contact account providers using existing authentication. No model turn, purchase, credential refresh request or billing mutation is intentionally submitted. Native CLI internals still own their runtime files and behavior; upstream CLI changes require review.

## Codex

Native app-server calls: `initialize`, `initialized`, `account/read` with refresh disabled,
`account/rateLimits/read`, and optional `account/usage/read`.
Account-wide usage is not added to local token history. Account identities are opaque hashes;
other account fields including email are discarded. Missing windows stay unavailable.

## Antigravity

`agy --print /usage --output-format json --print-timeout 10s`, with disabled stdin,
suppressed stderr, bounded stdout and a 15-second overall deadline. Accept only SUCCESS,
zero turns and a structured usage command. Quotas come from `command.data.groups[].buckets[]`.
Shared provider/model groups remain shared; GPT-OSS is not a separate ChatGPT allowance.
A custom history directory does not select a different signed-in quota account.

## Command Code

Existing `COMMAND_CODE_API_KEY` or the selected Command Code home's `auth.json` supplies
an in-memory bearer key. GET `/alpha/whoami` determines the organization; GET
`/alpha/billing/credits` supplies `windowLimits.fiveHour/weekly` used/cap/reset readings and
credit balances; GET `/alpha/billing/subscriptions` supplies the active plan id and period end.
Origin is fixed at `https://api.commandcode.ai`; custom/staging origins, redirects and proxies
are refused. The monthly meter mirrors the provider's published plan arithmetic: pool =
max(plan allowance, monthly balance) + purchased + free; used percent = (pool - remaining)/pool;
reset = subscription period end. Plan allowances come from the provider's CLI plan table,
resolved by longest prefix; inactive subscriptions, unknown plans and missing readings fail
closed with no monthly row. Do not send interactive-only `/usage` text as a model prompt.

## Claude Code

Claude Code reads its own account windows from the first-party endpoint
`GET https://api.anthropic.com/api/oauth/usage` with the existing OAuth bearer token
(timeout bounded, no redirects). The structured `limits` array supplies an explicit integer
`percent` for the `session` (5-hour) and `weekly_all` (weekly) windows; otherwise the
top-level `five_hour` and `seven_day` objects supply `utilization`, a percentage of the
window (0-100) in percent-shaped payloads and a 0-1 fraction in older fraction-only
payloads, plus an ISO 8601 `resets_at`. Both map onto the standard `5-hour limit`/`Weekly
limit` rows (300/10080 minutes, source `readonly_oauth_usage`). Authentication stays in
memory from `CLAUDE_CODE_OAUTH_TOKEN` or the selected home's `.credentials.json`; no
refresh request, model call or credential write occurs, and Bedrock, Vertex or
custom-endpoint environments fail closed. A home with no stored credential fails closed as
`unauthorized`, which clears the retained percentages for that provider so a signed-out
tool reads Unavailable instead of a stale meter. Missing or invalid readings remain unknown.

## Scheduling and evidence

Reads are independent of local scanning, approximately every 15 minutes plus jitter and
backoff. Failure retains the last valid observation and its age, without fabricated zeroes.
Provider-scoped writes preserve other providers' rows. Disabling consent prevents new
scheduling; restart the collector to end pending requests. Tests use synthetic JSON-RPC/CLI
and HTTP boundaries. They do not assert that a live account is authenticated.
