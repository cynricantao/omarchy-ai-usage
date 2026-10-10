# Usage adapters

The collector owns persistence, stable-ID reconciliation and scheduling. Local adapters read existing usage records without writing agent sources or retaining prompts, responses, tool output or credential values. JSONL records can contain content while being parsed in memory; only selected usage/identity fields are retained. Native session identifiers and source identities are sensitive metadata.

- **Hermes:** read-only SQLite usage projections. Canonical uncached input, output, cache-read and cache-write are disjoint. Reasoning is already within output. Multi-request historical rows remain undated. Source route identity is hashed; arbitrary endpoint strings are not emitted.
- **Codex:** bounded replay of native session JSONL. Cached input is subtracted from total input when known. Exact Hermes-origin rollouts are excluded; ambiguous origins are diagnosed, not inferred from model names.
- **Claude Code:** assistant-message usage keyed by native stable IDs, with streaming revisions reconciled. Route/provider cannot be established from a model name alone.
- **Antigravity:** read-only SQLite generation protobuf metadata, counting one usage record per generation rather than duplicated steps. Supported fields are version-specific.
- **OpenCode:** supported v1 SQLite message schema, SQL projections rather than returning message/part payloads. Unknown schemas fail closed.
- **Command Code:** v3 assistant-entry JSONL. Total is input + output; cache detail is not added twice. Cloned entries are deduplicated by stable identity/timestamp. Prompt and checkpoint sidecars are excluded.
- **DSH:** v4 JSONL/Zstandard logs, native exact totals or sum of recorded disjoint fields, excluding inherited seeded history. Missing cache buckets remain unknown.

Traversal and parsing are bounded; hitting limits reports incomplete coverage, not zero consumption. SQL values use parameters and source databases use read-only/query-only connections. Failures return fixed diagnostic codes rather than raw records or exception bodies.

## Optional quotas

Remote quota scheduling defaults off. After explicit `remote_quotas:true` consent:

- Codex runs `codex app-server --listen stdio://` with account-read methods only. The native client handles sign-in; emails and unselected response fields are discarded. An overall deadline, stdout limit and exact owned-process-group cleanup bound the exchange.
- Antigravity runs the native zero-turn `/usage` export. Stdout is streamed with a size limit and overall deadline, not unbounded capture. Human response text is not persisted.
- Command Code reads existing authentication and queries its fixed production HTTPS origin. Redirects/proxies are disabled; bodies/timeouts are bounded. It does open a credential file if needed; the secret remains in memory and is never logged or persisted.

No local token totals imply subscription quota. See [NATIVE-QUOTAS.md](NATIVE-QUOTAS.md).
