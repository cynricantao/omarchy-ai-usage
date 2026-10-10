# Security and privacy

Omarchy plugins are unsandboxed code running as your Unix user. Review the exact revision
before enabling it. There is no security certification or protection from malicious code
already running as the same user. Dependencies and mutable upstream CLI behavior remain
part of the trust boundary.

The collector retains allowlisted usage metadata, not prompts/responses/tool output or
credential values. Native session identifiers, model labels, timestamps, source overrides,
exports, backups and screenshots can still reveal private activity. Never commit or upload
runtime state. Generated state is outside the source checkout; private directories/files
are required and unsafe symlink/ownership/permission cases are refused without chmoding
foreign targets.

Remote quotas are disabled by default. Explicit opt-in permits native account clients and
a fixed-origin Command Code HTTPS adapter that reads existing authentication in memory.
No secret value or raw account/error response should enter logs, snapshots or exports.
Disabling consent prevents new scheduling; restart the service to cancel pending work.
No collector setup automatically edits another agent's configuration or installs hooks.

## Reporting

Do not post credentials, private logs, snapshots or reproduction data in public issues.
Use GitHub private vulnerability reporting if enabled, or initially ask for a private channel
without disclosing the vulnerability details. Tests/static scans are evidence, not proof
that every vulnerability has been eliminated.
