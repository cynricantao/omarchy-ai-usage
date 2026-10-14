# Command Code usage

Detects `cmd`, `commandcode`, `command-code` or `cmdc` on the collector PATH. Reads usage
from supported v3 assistant-entry JSONL under the discovered `.commandcode/projects`.
A retained directory alone is not evidence that the executable is installed.

Fields: inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens. Total is input+output;
cache detail is subtracted from uncached input rather than added twice. Stable entry IDs
and timestamps reconcile cloned/forked copies. Unsupported versions fail closed.
Checkpoint/prompt sidecars and transcript content are not retained.

The displayed usage unions local CLI session records with provider-attributed usage routed
through Command Code by other local tools (e.g. Hermes records `billing_provider=commandcode`),
deduplicated by the shared ledger; it is not credit balance or subscription verification.
The separate quota adapter is disabled by default, reads existing authentication only after
consent, requests fixed production-origin read-only endpoints, and reports the account's
5-hour, weekly and subscription-backed monthly credit meters. See [NATIVE-QUOTAS.md](NATIVE-QUOTAS.md).
