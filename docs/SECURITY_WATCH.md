# Continuous Security Watch

## What it is

`mc-security-watch` is a local host watcher for MasterControl.

- It performs periodic incremental sweeps.
- It reuses persisted `system_events`.
- It emits prioritized alerts into SQLite (`security_alerts`).
- It supports local alert lifecycle actions: list, acknowledge and temporary silence.
- It builds local incident playbooks from the same persisted alerts and events.
- It maintains a persistent incident ledger with activity trail.
- It version-controls its own SQLite schema through `security_watch_meta`.
- It can prune retained data without touching active incidents or their activity trail.
- It only permits bounded containment when the requested service action correlates with an active service incident.

## Signal sources

- `journald`
- `udevadm info --export-db`
- `dbus/login1` via `busctl` with `loginctl` fallback

## What it writes

- SQLite database:
  - `~/.local/share/mastercontrol/mastercontrol.db`
  - `security_alerts`
  - `security_silences`
  - `incidents`
- `incident_activity`
- `security_watch_meta`
- system journal:
  - `journalctl -u mastercontrol-security-watch.service`

## Operator-facing actions

MasterControl can expose the alert store directly in chat or TUI:

- `security.alerts.list`
- `security.alerts.ack`
- `security.alerts.silence`
- `security.incident.list`
- `security.incident.show`
- `security.incident.resolve`
- `security.incident.dismiss`
- `security.incident.plan`

Controlled incident containment also exists through `mod_security`, but it does not introduce a new raw privileged primitive. Instead, it only allows an existing allowlisted service action to proceed after validating:

- there is an active matching incident in the same domain,
- the requested target unit is explicitly correlated from persisted incident evidence,
- policy and operator approval still allow the mutation.

Current bounded remediations:

- `service` incidents: correlated service restart/start/stop as before
- `security/auth` incidents: `ssh.service` restart only
- `network` incidents: restart of correlated network stack services such as `NetworkManager.service` or `systemd-resolved.service`

These actions can be scoped by:

- `alert_id`
- `category`
- `severity`
- `fingerprint`
- `incident_id`

These actions are local-only and operate on the MC database, not on the host itself.

The TUI status header also shows a cached summary of active unresolved alerts and active incidents so the operator can see current vigilance pressure without triggering a fresh sweep on every render.
When `mastercontrol` opens the TUI, the operator also gets a navigable incident panel with list + detail for the selected active incident.

## Lifecycle and retention

- Current schema version: `3`
- Local pruning is available through the watcher engine and CLI flags:
  - `--prune`
  - `--prune-only`
  - `--system-event-retention-days`
  - `--alert-retention-days`
  - `--incident-retention-days`
  - `--activity-retention-days`
  - `--silence-retention-days`
- Pruning removes expired historical data from:
  - `system_events`
  - `security_alerts`
  - `security_silences`
  - `incidents`
  - `incident_activity`
- Active incidents (`open`, `contained`) and their referenced alert/activity rows are preserved.
- Operator semantics for `ack`, `silence`, `resolve`, `dismiss` and `contain` are documented in `docs/INCIDENT_OPERATIONS.md`.
- Current validated host profile on Debian Testing:
  - `system_events=7d`
  - `security_alerts=21d`
  - `incidents=60d`
  - `incident_activity=90d`
  - `security_silences=14d`

## Install

```bash
/home/irving/ruas/repos/master-control/scripts/install-security-watch-timer.sh
```

Example with custom cadence:

```bash
/home/irving/ruas/repos/master-control/scripts/install-security-watch-timer.sh \
  --operator-id irving \
  --interval-sec 180 \
  --window-hours 12 \
  --dedupe-minutes 45 \
  --prune \
  --alert-retention-days 45
```

Generate units without installing:

```bash
/home/irving/ruas/repos/master-control/scripts/install-security-watch-timer.sh \
  --operator-id irving \
  --output-dir /tmp/mc-units
systemd-analyze verify /tmp/mc-units/mastercontrol-security-watch.service /tmp/mc-units/mastercontrol-security-watch.timer
```

## Verify

```bash
systemctl status mastercontrol-security-watch.timer
systemctl list-timers mastercontrol-security-watch.timer
journalctl -u mastercontrol-security-watch.service -n 50 --no-pager
./scripts/mc-security-watch --prune-only --db-path /tmp/mastercontrol-watch.db
```

## Safety model

- Read-only local analysis.
- No privilege bypass.
- Uses `systemd` hardening and restricted write path.
- Alert deduplication reduces repeated noise for the same signal set.
- Temporary silences suppress new repeated alerts for the same fingerprint until expiration.
- The event monitor ignores journald entries emitted by `mc-security-watch` and other MasterControl units so the watcher does not self-trigger on its own status JSON.
- Successful `pkexec`/`sudo` session-open events do not count as `security.auth.anomaly` unless there are actual auth-failure markers in the evidence.
- Explicit incident resolve/dismiss closes linked open alert rows locally so stale evidence does not reopen the same incident immediately.
- Incident containment blocks when no active correlated unit is found.
- `auth` and `network` remediations remain intentionally narrow and only reuse existing service actions.
