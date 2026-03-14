#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Install MasterControl privilege broker (systemd socket activation, system scope).

Usage:
  install-privilege-broker.sh [--operator-id USER] [--repo-root PATH] [--socket-group GROUP] [--socket-path PATH]
                              [--output-dir PATH] [--no-enable]

Defaults:
  --operator-id   : current user
  --repo-root     : repository root inferred from script path
  --socket-group  : same value as --operator-id
  --socket-path   : /run/mastercontrol/privilege-broker.sock

Examples:
  ./scripts/install-privilege-broker.sh
  ./scripts/install-privilege-broker.sh --operator-id irving
  ./scripts/install-privilege-broker.sh --output-dir /tmp/mc-units
EOF
}

operator_id="$(id -un)"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
socket_group=""
socket_path="/run/mastercontrol/privilege-broker.sock"
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
    --socket-group)
      shift
      socket_group="${1:-}"
      ;;
    --socket-path)
      shift
      socket_path="${1:-}"
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
if [[ -z "${socket_group}" ]]; then
  socket_group="${operator_id}"
fi
if [[ -z "${socket_path}" ]]; then
  echo "Invalid --socket-path"
  exit 1
fi
if [[ -n "${output_dir}" ]]; then
  output_dir="$(realpath -m "${output_dir}")"
fi

if [[ ! -x "${repo_root}/scripts/mc-privilege-broker" ]]; then
  echo "Missing executable ${repo_root}/scripts/mc-privilege-broker"
  echo "Run chmod +x scripts/mc-privilege-broker first or verify repo path."
  exit 1
fi
if [[ ! -x "${repo_root}/scripts/install-privilege-bootstrap.sh" ]]; then
  echo "Missing bootstrap installer ${repo_root}/scripts/install-privilege-bootstrap.sh"
  exit 1
fi
if ! id "${operator_id}" >/dev/null 2>&1; then
  echo "Operator user not found: ${operator_id}"
  exit 1
fi
if ! getent group "${socket_group}" >/dev/null 2>&1; then
  echo "Socket group not found: ${socket_group}"
  exit 1
fi

if [[ -z "${output_dir}" && "${EUID}" -ne 0 ]]; then
  exec pkexec bash "$0" \
    --operator-id "${operator_id}" \
    --repo-root "${repo_root}" \
    --socket-group "${socket_group}" \
    --socket-path "${socket_path}" \
    $( [[ "${enable_units}" == "false" ]] && printf '%s ' --no-enable )
fi

if [[ -z "${output_dir}" ]]; then
  echo "[1/5] Ensuring privilege bootstrap is installed..."
  bash "${repo_root}/scripts/install-privilege-bootstrap.sh"
else
  echo "[1/3] Generating unit files without touching host system directories..."
fi

if [[ -z "${output_dir}" ]]; then
  echo "[2/5] Preparing broker state directories..."
  install -d -m 0755 /etc/systemd/system
  install -d -m 0750 /var/log/mastercontrol
  install -d -m 0750 /var/lib/mastercontrol
  install -d -m 0755 /run/mastercontrol
  unit_service="/etc/systemd/system/mastercontrol-privilege-broker.service"
  unit_socket="/etc/systemd/system/mastercontrol-privilege-broker.socket"
else
  mkdir -p "${output_dir}"
  unit_service="${output_dir}/mastercontrol-privilege-broker.service"
  unit_socket="${output_dir}/mastercontrol-privilege-broker.socket"
fi

echo "[3/5] Writing systemd service..."
cat > "${unit_service}" <<EOF
[Unit]
Description=MasterControl Privilege Broker
Requires=mastercontrol-privilege-broker.socket
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${repo_root}
Environment=PYTHONUNBUFFERED=1
ExecStart=${repo_root}/scripts/mc-privilege-broker serve --socket ${socket_path} --actions-file /etc/mastercontrol/actions.json --audit-log /var/log/mastercontrol/privilege-broker.log --approval-db /var/lib/mastercontrol/privilege-broker.db
RuntimeDirectory=mastercontrol
StateDirectory=mastercontrol
LogsDirectory=mastercontrol
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ProtectControlGroups=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
ReadWritePaths=/etc/mastercontrol

[Install]
WantedBy=multi-user.target
EOF

echo "[4/5] Writing systemd socket..."
cat > "${unit_socket}" <<EOF
[Unit]
Description=MasterControl Privilege Broker Socket

[Socket]
ListenStream=${socket_path}
SocketMode=0660
SocketUser=root
SocketGroup=${socket_group}
DirectoryMode=0750
RemoveOnStop=true
Accept=no

[Install]
WantedBy=sockets.target
EOF

chmod 0644 "${unit_service}" "${unit_socket}"

if [[ -z "${output_dir}" ]]; then
  echo "[5/5] Reloading and enabling socket..."
  systemctl daemon-reload
  if [[ "${enable_units}" == "true" ]]; then
    systemctl enable --now mastercontrol-privilege-broker.socket
  fi
fi

echo
if [[ -n "${output_dir}" ]]; then
  echo "Generated unit files:"
else
  echo "Installed unit files:"
fi
echo "  ${unit_service}"
echo "  ${unit_socket}"
echo
if [[ -n "${output_dir}" ]]; then
  echo "Validate with:"
  echo "  systemd-analyze verify ${unit_service} ${unit_socket}"
else
  if [[ "${enable_units}" == "true" ]]; then
    echo "Check status:"
    echo "  systemctl status mastercontrol-privilege-broker.socket"
    echo "  systemctl status mastercontrol-privilege-broker.service"
    echo "  ss -xl | grep privilege-broker.sock"
    echo "  journalctl -u mastercontrol-privilege-broker.service -n 50 --no-pager"
  else
    echo "Units were written but not enabled. To enable later:"
    echo "  systemctl daemon-reload"
    echo "  systemctl enable --now mastercontrol-privilege-broker.socket"
  fi
fi
