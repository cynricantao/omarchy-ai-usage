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
`/alpha/billing/credits` supplies `windowLimits.fiveHour/weekly`, used/cap and reset time.
Origin is fixed at `https://api.commandcode.ai`; custom/staging origins, redirects and proxies
are refused. Monthly credit balance is not the same metric as these quota windows.
Do not send interactive-only `/usage` text as a model prompt.

## Scheduling and evidence

Reads are independent of local scanning, approximately every 15 minutes plus jitter and
backoff. Failure retains the last valid observation and its age, without fabricated zeroes.
Provider-scoped writes preserve other providers' rows. Disabling consent prevents new
scheduling; restart the collector to end pending requests. Tests use synthetic JSON-RPC/CLI
and HTTP boundaries. They do not assert that a live account is authenticated.
