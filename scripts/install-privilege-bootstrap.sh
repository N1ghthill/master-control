#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

SRC_EXEC="${REPO_ROOT}/mastercontrol/runtime/root_exec.py"
SRC_ACTIONS="${REPO_ROOT}/config/privilege/actions.json"
SRC_POLICY="${REPO_ROOT}/config/polkit/io.mastercontrol.rootexec.policy"

DST_EXEC="/usr/lib/mastercontrol/root-exec"
DST_ACTIONS="/etc/mastercontrol/actions.json"
DST_POLICY="/usr/share/polkit-1/actions/io.mastercontrol.rootexec.policy"
DST_LOG_DIR="/var/log/mastercontrol"

echo "[1/5] Validating source files..."
[[ -f "${SRC_EXEC}" ]] || { echo "Missing ${SRC_EXEC}"; exit 1; }
[[ -f "${SRC_ACTIONS}" ]] || { echo "Missing ${SRC_ACTIONS}"; exit 1; }
[[ -f "${SRC_POLICY}" ]] || { echo "Missing ${SRC_POLICY}"; exit 1; }

echo "[2/5] Installing privileged executor..."
install -d -m 0755 /usr/lib/mastercontrol
install -m 0755 "${SRC_EXEC}" "${DST_EXEC}"

echo "[3/5] Installing action allowlist..."
install -d -m 0755 /etc/mastercontrol
install -m 0644 "${SRC_ACTIONS}" "${DST_ACTIONS}"

echo "[4/5] Installing polkit policy..."
install -d -m 0755 /usr/share/polkit-1/actions
install -m 0644 "${SRC_POLICY}" "${DST_POLICY}"

echo "[5/5] Preparing audit directory..."
install -d -m 0750 "${DST_LOG_DIR}"

echo
echo "Privilege bootstrap installed."
echo "Test:"
echo "  pkexec ${DST_EXEC} list-actions"
echo "  pkexec ${DST_EXEC} exec --action dns.unbound.flush_negative"
