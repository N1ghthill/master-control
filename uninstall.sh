#!/usr/bin/env bash
set -euo pipefail

DEFAULT_PREFIX="${HOME}/.local/share/master-control"
DEFAULT_BIN_DIR="${HOME}/.local/bin"
DEFAULT_STATE_DIR="${HOME}/.local/state/master-control"
MC_WRAPPER_MARKER="# master-control-wrapper: managed"

PREFIX="$DEFAULT_PREFIX"
BIN_DIR="$DEFAULT_BIN_DIR"
STATE_DIR="$DEFAULT_STATE_DIR"
PURGE_STATE=0
REMOVE_TIMER=0

CUSTOM_PREFIX=0
CUSTOM_BIN_DIR=0
CUSTOM_STATE_DIR=0

usage() {
  cat <<'EOF'
Usage: ./uninstall.sh [options]

Remove the user-local Master Control installation created by `install.sh`.

Options:
  --prefix DIR        Installation root. Default: ~/.local/share/master-control
  --bin-dir DIR       Directory that contains the `mc` wrapper. Default: ~/.local/bin
  --state-dir DIR     MC state directory. Default: ~/.local/state/master-control
  --purge-state       Remove the MC state directory after uninstall.
  --remove-timer      Force removal of the reconcile timer even if no manifest exists.
  --help              Show this help.
EOF
}

fail() {
  echo "uninstall.sh: $*" >&2
  exit 1
}

wrapper_is_mc_managed() {
  local wrapper_path="$1"
  if [[ ! -f "$wrapper_path" && ! -L "$wrapper_path" ]]; then
    return 1
  fi
  grep -Fq "$MC_WRAPPER_MARKER" "$wrapper_path" 2>/dev/null
}

safe_rm_rf() {
  local path="$1"
  if [[ -z "$path" || "$path" == "/" ]]; then
    fail "refusing to remove unsafe path: $path"
  fi
  rm -rf "$path"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)
      PREFIX="$2"
      CUSTOM_PREFIX=1
      shift 2
      ;;
    --bin-dir)
      BIN_DIR="$2"
      CUSTOM_BIN_DIR=1
      shift 2
      ;;
    --state-dir)
      STATE_DIR="$2"
      CUSTOM_STATE_DIR=1
      shift 2
      ;;
    --purge-state)
      PURGE_STATE=1
      shift
      ;;
    --remove-timer)
      REMOVE_TIMER=1
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

PREFIX="${PREFIX/#\~/$HOME}"
BIN_DIR="${BIN_DIR/#\~/$HOME}"
STATE_DIR="${STATE_DIR/#\~/$HOME}"
MANIFEST_PATH="$PREFIX/install-manifest.env"
DB_PATH="$STATE_DIR/mc.sqlite3"
VENV_DIR="$PREFIX/venv"
WRAPPER_PATH="$BIN_DIR/mc"
TIMER_SCOPE="user"
TIMER_INSTALLED=0

if [[ -f "$MANIFEST_PATH" ]]; then
  # shellcheck disable=SC1090
  source "$MANIFEST_PATH"
  PREFIX="${MC_INSTALL_PREFIX:-$PREFIX}"
  BIN_DIR="${MC_INSTALL_BIN_DIR:-$BIN_DIR}"
  STATE_DIR="${MC_INSTALL_STATE_DIR:-$STATE_DIR}"
  DB_PATH="${MC_INSTALL_DB_PATH:-$DB_PATH}"
  VENV_DIR="${MC_INSTALL_VENV_DIR:-$VENV_DIR}"
  WRAPPER_PATH="${MC_INSTALL_WRAPPER_PATH:-$WRAPPER_PATH}"
  TIMER_SCOPE="${MC_INSTALL_TIMER_SCOPE:-$TIMER_SCOPE}"
  TIMER_INSTALLED="${MC_INSTALL_TIMER_INSTALLED:-$TIMER_INSTALLED}"
fi

if [[ "$CUSTOM_PREFIX" -eq 1 ]]; then
  PREFIX="${PREFIX/#\~/$HOME}"
  MANIFEST_PATH="$PREFIX/install-manifest.env"
fi
if [[ "$CUSTOM_BIN_DIR" -eq 1 ]]; then
  BIN_DIR="${BIN_DIR/#\~/$HOME}"
  WRAPPER_PATH="$BIN_DIR/mc"
fi
if [[ "$CUSTOM_STATE_DIR" -eq 1 ]]; then
  STATE_DIR="${STATE_DIR/#\~/$HOME}"
  DB_PATH="$STATE_DIR/mc.sqlite3"
fi

if [[ "$REMOVE_TIMER" -eq 1 || "$TIMER_INSTALLED" == "1" ]]; then
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    if ! MC_STATE_DIR="$STATE_DIR" MC_DB_PATH="$DB_PATH" \
      "$VENV_DIR/bin/python" -m master_control reconcile-timer remove --scope "$TIMER_SCOPE"
    then
      echo "warning: could not remove reconcile timer automatically" >&2
    fi
  else
    echo "warning: installed virtualenv is unavailable; skipping timer removal" >&2
  fi
fi

if [[ -f "$WRAPPER_PATH" || -L "$WRAPPER_PATH" ]]; then
  if wrapper_is_mc_managed "$WRAPPER_PATH"; then
    rm -f "$WRAPPER_PATH"
  else
    echo "warning: wrapper at $WRAPPER_PATH is not managed by Master Control; leaving it in place" >&2
  fi
fi

if [[ -d "$VENV_DIR" ]]; then
  safe_rm_rf "$VENV_DIR"
fi

if [[ -f "$MANIFEST_PATH" ]]; then
  rm -f "$MANIFEST_PATH"
fi

if [[ -d "$PREFIX" ]]; then
  rmdir "$PREFIX" 2>/dev/null || true
fi

if [[ "$PURGE_STATE" -eq 1 && -d "$STATE_DIR" ]]; then
  safe_rm_rf "$STATE_DIR"
fi

echo "Removed Master Control installation"
echo "wrapper:   $WRAPPER_PATH"
echo "venv:      $VENV_DIR"
if [[ "$PURGE_STATE" -eq 1 ]]; then
  echo "state_dir: removed $STATE_DIR"
else
  echo "state_dir: kept $STATE_DIR"
fi
