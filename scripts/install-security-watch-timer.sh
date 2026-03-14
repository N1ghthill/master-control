#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Install MasterControl security watch timer (systemd system scope).

Usage:
  install-security-watch-timer.sh [--operator-id USER] [--repo-root PATH] [--interval-sec N] [--window-hours N] [--dedupe-minutes N]
                                  [--prune|--no-prune]
                                  [--system-event-retention-days N] [--alert-retention-days N]
                                  [--incident-retention-days N] [--activity-retention-days N]
                                  [--silence-retention-days N]
                                  [--output-dir PATH] [--no-enable]

Defaults:
  --operator-id     : current user
  --repo-root       : repository root inferred from script path
  --interval-sec    : 120
  --window-hours    : 6
  --dedupe-minutes  : 30
  --prune           : enabled
  --system-event-retention-days : 14
  --alert-retention-days        : 30
  --incident-retention-days     : 90
  --activity-retention-days     : 120
  --silence-retention-days      : 30

Examples:
  ./scripts/install-security-watch-timer.sh
  ./scripts/install-security-watch-timer.sh --operator-id irving --interval-sec 180 --window-hours 12
  ./scripts/install-security-watch-timer.sh --output-dir /tmp/mc-units
EOF
}

operator_id="$(id -un)"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
interval_sec="120"
window_hours="6"
dedupe_minutes="30"
prune_enabled="true"
system_event_retention_days="14"
alert_retention_days="30"
incident_retention_days="90"
activity_retention_days="120"
silence_retention_days="30"
output_dir=""
enable_units="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --operator-id)
      shift
      operator_id="${1:-}"
      ;;
    --repo-root)
      shift
      repo_root="${1:-}"
      ;;
    --interval-sec)
      shift
      interval_sec="${1:-}"
      ;;
    --window-hours)
      shift
      window_hours="${1:-}"
      ;;
    --dedupe-minutes)
      shift
      dedupe_minutes="${1:-}"
      ;;
    --prune)
      prune_enabled="true"
      ;;
    --no-prune)
      prune_enabled="false"
      ;;
    --system-event-retention-days)
      shift
      system_event_retention_days="${1:-}"
      ;;
    --alert-retention-days)
      shift
      alert_retention_days="${1:-}"
      ;;
    --incident-retention-days)
      shift
      incident_retention_days="${1:-}"
      ;;
    --activity-retention-days)
      shift
      activity_retention_days="${1:-}"
      ;;
    --silence-retention-days)
      shift
      silence_retention_days="${1:-}"
      ;;
    --output-dir)
      shift
      output_dir="${1:-}"
      ;;
    --no-enable)
      enable_units="false"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
  shift || true
done

if [[ -z "${operator_id}" ]]; then
  echo "Invalid --operator-id"
  exit 1
fi
for value_name in \
  interval_sec \
  window_hours \
  dedupe_minutes \
  system_event_retention_days \
  alert_retention_days \
  incident_retention_days \
  activity_retention_days \
  silence_retention_days
do
  value="${!value_name}"
  if ! [[ "${value}" =~ ^[0-9]+$ ]]; then
    echo "Invalid --${value_name//_/-}"
    exit 1
  fi
done
if [[ -n "${output_dir}" ]]; then
  output_dir="$(realpath -m "${output_dir}")"
fi
if [[ ! -x "${repo_root}/scripts/mc-security-watch" ]]; then
  echo "Missing executable ${repo_root}/scripts/mc-security-watch"
  echo "Run chmod +x scripts/mc-security-watch first or verify repo path."
  exit 1
fi
if ! id "${operator_id}" >/dev/null 2>&1; then
  echo "Operator user not found: ${operator_id}"
  exit 1
fi

if [[ -z "${output_dir}" && "${EUID}" -ne 0 ]]; then
  exec pkexec bash "$0" \
    --operator-id "${operator_id}" \
    --repo-root "${repo_root}" \
    --interval-sec "${interval_sec}" \
    --window-hours "${window_hours}" \
    --dedupe-minutes "${dedupe_minutes}" \
    $( [[ "${prune_enabled}" == "true" ]] && printf '%s ' --prune || printf '%s ' --no-prune ) \
    --system-event-retention-days "${system_event_retention_days}" \
    --alert-retention-days "${alert_retention_days}" \
    --incident-retention-days "${incident_retention_days}" \
    --activity-retention-days "${activity_retention_days}" \
    --silence-retention-days "${silence_retention_days}" \
    $( [[ "${enable_units}" == "false" ]] && printf '%s ' --no-enable )
fi

if [[ -n "${output_dir}" ]]; then
  mkdir -p "${output_dir}"
  unit_service="${output_dir}/mastercontrol-security-watch.service"
  unit_timer="${output_dir}/mastercontrol-security-watch.timer"
else
  unit_service="/etc/systemd/system/mastercontrol-security-watch.service"
  unit_timer="/etc/systemd/system/mastercontrol-security-watch.timer"
fi

exec_start="${repo_root}/scripts/mc-security-watch --window-hours ${window_hours} --dedupe-minutes ${dedupe_minutes}"
if [[ "${prune_enabled}" == "true" ]]; then
  exec_start+=" --prune"
  exec_start+=" --system-event-retention-days ${system_event_retention_days}"
  exec_start+=" --alert-retention-days ${alert_retention_days}"
  exec_start+=" --incident-retention-days ${incident_retention_days}"
  exec_start+=" --activity-retention-days ${activity_retention_days}"
  exec_start+=" --silence-retention-days ${silence_retention_days}"
fi

cat > "${unit_service}" <<EOF
[Unit]
Description=MasterControl Security Watch Sweep
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${operator_id}
Group=${operator_id}
WorkingDirectory=${repo_root}
Environment=PYTHONUNBUFFERED=1
ExecStart=${exec_start}
Nice=5
IOSchedulingClass=best-effort
IOSchedulingPriority=6
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/${operator_id}/.local/share/mastercontrol
PrivateTmp=yes
NoNewPrivileges=yes
EOF

cat > "${unit_timer}" <<EOF
[Unit]
Description=Run MasterControl security watch periodically

[Timer]
OnBootSec=2m
OnUnitActiveSec=${interval_sec}
RandomizedDelaySec=20s
Persistent=true
AccuracySec=15s
Unit=mastercontrol-security-watch.service

[Install]
WantedBy=timers.target
EOF

chmod 0644 "${unit_service}" "${unit_timer}"

if [[ -z "${output_dir}" ]]; then
  systemctl daemon-reload
  if [[ "${enable_units}" == "true" ]]; then
    systemctl enable --now mastercontrol-security-watch.timer
  fi
fi

echo
if [[ -n "${output_dir}" ]]; then
  echo "Generated unit files:"
else
  echo "Installed unit files:"
fi
echo "  ${unit_service}"
echo "  ${unit_timer}"
echo
if [[ "${prune_enabled}" == "true" ]]; then
  echo "Pruning config:"
  echo "  system_events=${system_event_retention_days}d"
  echo "  security_alerts=${alert_retention_days}d"
  echo "  incidents=${incident_retention_days}d"
  echo "  incident_activity=${activity_retention_days}d"
  echo "  security_silences=${silence_retention_days}d"
  echo
fi
if [[ -n "${output_dir}" ]]; then
  echo "Validate with:"
  echo "  systemd-analyze verify ${unit_service} ${unit_timer}"
else
  if [[ "${enable_units}" == "true" ]]; then
    echo "Check status:"
    echo "  systemctl status mastercontrol-security-watch.timer"
    echo "  systemctl list-timers mastercontrol-security-watch.timer"
    echo "  journalctl -u mastercontrol-security-watch.service -n 50 --no-pager"
  else
    echo "Units were written but not enabled. To enable later:"
    echo "  systemctl daemon-reload"
    echo "  systemctl enable --now mastercontrol-security-watch.timer"
  fi
fi
