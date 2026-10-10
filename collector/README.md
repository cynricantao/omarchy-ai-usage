# Collector

The Python 3.14+ standard-library backend for [AI Usage](../README.md).

This folder is source code only. Runtime state belongs outside the repository:
`$XDG_DATA_HOME/token-activity/{usage.sqlite3,snapshot.json,spool,activity,backups}`;
configuration belongs in `$XDG_CONFIG_HOME/token-activity/settings.json`.
Defaults are `~/.local/share` and `~/.config`. Do not commit any runtime state.

Run `python3 install.py --help` for explicit setup. Setup does not edit Omarchy bar layout or Hermes configuration. Remote quota reads are opt-in via `remote_quotas:true`; no credential values or transcript content are persisted. Usage/session/source metadata and exports nevertheless remain private.

See the root README for installation, removal, limitations, and consent boundaries;
[CONTRACT.md](CONTRACT.md) for data semantics;
[ADAPTERS.md](ADAPTERS.md) for source readers;
[NATIVE-QUOTAS.md](NATIVE-QUOTAS.md) for remote clients.

Verification is synthetic and separate from real-account and rendered desktop acceptance.
