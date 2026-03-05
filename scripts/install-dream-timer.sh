#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Install MasterControl nightly dream timer (systemd system scope).

Usage:
  install-dream-timer.sh [--operator-id USER] [--repo-root PATH] [--time HH:MM] [--window-days N]

Defaults:
  --operator-id : current user
  --repo-root   : repository root inferred from script path
  --time        : 03:00
  --window-days : 30

Examples:
  ./scripts/install-dream-timer.sh
  ./scripts/install-dream-timer.sh --operator-id irving --time 02:30 --window-days 14
EOF
}

operator_id="$(id -un)"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
run_time="03:00"
window_days="30"

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
    --time)
      shift
      run_time="${1:-}"
      ;;
    --window-days)
      shift
      window_days="${1:-}"
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
if [[ ! "${run_time}" =~ ^[0-2][0-9]:[0-5][0-9]$ ]]; then
  echo "Invalid --time format. Use HH:MM"
  exit 1
fi
if [[ "${run_time%%:*}" -gt 23 ]]; then
  echo "Invalid hour in --time"
  exit 1
fi
if ! [[ "${window_days}" =~ ^[0-9]+$ ]]; then
  echo "Invalid --window-days"
  exit 1
fi
if [[ ! -x "${repo_root}/scripts/mc-dream" ]]; then
  echo "Missing executable ${repo_root}/scripts/mc-dream"
  echo "Run chmod +x scripts/mc-dream first or verify repo path."
  exit 1
fi
if ! id "${operator_id}" >/dev/null 2>&1; then
  echo "Operator user not found: ${operator_id}"
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  exec pkexec bash "$0" --operator-id "${operator_id}" --repo-root "${repo_root}" --time "${run_time}" --window-days "${window_days}"
fi

unit_service="/etc/systemd/system/mastercontrol-dream.service"
unit_timer="/etc/systemd/system/mastercontrol-dream.timer"

cat > "${unit_service}" <<EOF
[Unit]
Description=MasterControl Dream Insight Job
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${operator_id}
Group=${operator_id}
WorkingDirectory=${repo_root}
Environment=PYTHONUNBUFFERED=1
ExecStart=${repo_root}/scripts/mc-dream --operator-id ${operator_id} --window-days ${window_days}
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/${operator_id}/.local/share/mastercontrol
PrivateTmp=yes
NoNewPrivileges=yes
EOF

cat > "${unit_timer}" <<EOF
[Unit]
Description=Run MasterControl Dream nightly

[Timer]
OnCalendar=*-*-* ${run_time}:00
RandomizedDelaySec=20m
Persistent=true
AccuracySec=1m
Unit=mastercontrol-dream.service

[Install]
WantedBy=timers.target
EOF

chmod 0644 "${unit_service}" "${unit_timer}"

systemctl daemon-reload
systemctl enable --now mastercontrol-dream.timer

echo
echo "Installed and enabled:"
echo "  ${unit_service}"
echo "  ${unit_timer}"
echo
echo "Check status:"
echo "  systemctl status mastercontrol-dream.timer"
echo "  systemctl list-timers mastercontrol-dream.timer"
echo "  journalctl -u mastercontrol-dream.service -n 50 --no-pager"

