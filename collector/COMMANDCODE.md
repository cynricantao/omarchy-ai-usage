# Command Code usage

Detects `cmd`, `commandcode`, `command-code` or `cmdc` on the collector PATH. Reads usage
from supported v3 assistant-entry JSONL under the discovered `.commandcode/projects`.
A retained directory alone is not evidence that the executable is installed.

Fields: inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens. Total is input+output;
cache detail is subtracted from uncached input rather than added twice. Stable entry IDs
and timestamps reconcile cloned/forked copies. Unsupported versions fail closed.
Checkpoint/prompt sidecars and transcript content are not retained.

Local usage is not credit balance, subscription verification or an account-wide quota.
The separate quota adapter is disabled by default, reads existing authentication only after
consent, and requests fixed production-origin read-only endpoints. See [NATIVE-QUOTAS.md](NATIVE-QUOTAS.md).
