#!/usr/bin/env bash
set -euo pipefail

DEFAULT_PREFIX="${HOME}/.local/share/master-control"
DEFAULT_BIN_DIR="${HOME}/.local/bin"
DEFAULT_STATE_DIR="${HOME}/.local/state/master-control"
MC_WRAPPER_MARKER="# master-control-wrapper: managed"

PREFIX="$DEFAULT_PREFIX"
BIN_DIR="$DEFAULT_BIN_DIR"
STATE_DIR="$DEFAULT_STATE_DIR"
PYTHON_BIN="${PYTHON:-python3}"
PROVIDER=""
INSTALL_TIMER=0
TIMER_SCOPE="user"

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Install Master Control into an isolated virtual environment and create a user-local `mc` wrapper.

Options:
  --prefix DIR          Installation root. Default: ~/.local/share/master-control
  --bin-dir DIR         Directory where the `mc` wrapper will be written. Default: ~/.local/bin
  --state-dir DIR       MC state directory. Default: ~/.local/state/master-control
  --python PATH         Python interpreter to use. Default: python3
  --provider NAME       Default MC_PROVIDER value for the wrapper.
  --install-timer       Install the reconcile timer after bootstrap.
  --timer-scope SCOPE   Timer scope for `--install-timer`. Default: user
  --help                Show this help.
EOF
}

fail() {
  echo "install.sh: $*" >&2
  exit 1
}

wrapper_is_mc_managed() {
  local wrapper_path="$1"
  if [[ ! -f "$wrapper_path" && ! -L "$wrapper_path" ]]; then
    return 1
  fi
  grep -Fq "$MC_WRAPPER_MARKER" "$wrapper_path" 2>/dev/null
}

ensure_wrapper_path_is_safe() {
  local wrapper_path="$1"
  if [[ -e "$wrapper_path" || -L "$wrapper_path" ]]; then
    if ! wrapper_is_mc_managed "$wrapper_path"; then
      fail "refusing to overwrite existing wrapper at $wrapper_path because it is not managed by Master Control"
    fi
  fi
}

check_python_version() {
  "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 13) else 1)'
}

venv_failure_looks_like_missing_prereq() {
  local venv_log="$1"
  grep -Eqi 'ensurepip is not available|No module named ensurepip|python3(\.[0-9]+)?-venv' "$venv_log"
}

render_venv_install_hint() {
  PYTHONPATH="$REPO_ROOT/src" "$PYTHON_BIN" -m master_control.bootstrap_prereqs --install-hint --python-bin "$PYTHON_BIN" 2>/dev/null || true
}

create_virtualenv() {
  local venv_dir="$1"
  local venv_log
  venv_log="$(mktemp)"
  if "$PYTHON_BIN" -m venv "$venv_dir" >"$venv_log" 2>&1; then
    rm -f "$venv_log"
    return 0
  fi

  rm -rf "$venv_dir"
  if "$PYTHON_BIN" -m virtualenv --help >/dev/null 2>&1; then
    echo "install.sh: stdlib venv unavailable; falling back to virtualenv" >&2
    rm -f "$venv_log"
    "$PYTHON_BIN" -m virtualenv "$venv_dir"
    return 0
  fi

  cat "$venv_log" >&2
  if venv_failure_looks_like_missing_prereq "$venv_log"; then
    local install_hint
    install_hint="$(render_venv_install_hint)"
    if [[ -n "$install_hint" ]]; then
      echo "install.sh: Python is present, but stdlib venv support is unavailable; $install_hint" >&2
    fi
  fi
  rm -f "$venv_log"
  fail "could not create a virtual environment with \`$PYTHON_BIN -m venv\` and \`virtualenv\` is unavailable"
}

write_wrapper() {
  local wrapper_path="$1"
  local venv_dir="$2"
  local state_dir="$3"
  local db_path="$4"
  local provider="$5"

  cat >"$wrapper_path" <<EOF
#!/usr/bin/env bash
$MC_WRAPPER_MARKER
set -euo pipefail
export MC_STATE_DIR="$state_dir"
export MC_DB_PATH="$db_path"
EOF

  if [[ -n "$provider" ]]; then
    cat >>"$wrapper_path" <<EOF
export MC_PROVIDER="$provider"
EOF
  fi

  cat >>"$wrapper_path" <<EOF
exec "$venv_dir/bin/mc" "\$@"
EOF
  chmod 755 "$wrapper_path"
}

write_manifest() {
  local manifest_path="$1"
  local prefix="$2"
  local bin_dir="$3"
  local state_dir="$4"
  local db_path="$5"
  local venv_dir="$6"
  local wrapper_path="$7"
  local provider="$8"
  local timer_installed="$9"
  local timer_scope="${10}"

  cat >"$manifest_path" <<EOF
MC_INSTALL_PREFIX="$prefix"
MC_INSTALL_BIN_DIR="$bin_dir"
MC_INSTALL_STATE_DIR="$state_dir"
MC_INSTALL_DB_PATH="$db_path"
MC_INSTALL_VENV_DIR="$venv_dir"
MC_INSTALL_WRAPPER_PATH="$wrapper_path"
MC_INSTALL_PROVIDER="$provider"
MC_INSTALL_TIMER_INSTALLED="$timer_installed"
MC_INSTALL_TIMER_SCOPE="$timer_scope"
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)
      PREFIX="$2"
      shift 2
      ;;
    --bin-dir)
      BIN_DIR="$2"
      shift 2
      ;;
    --state-dir)
      STATE_DIR="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --provider)
      PROVIDER="$2"
      shift 2
      ;;
    --install-timer)
      INSTALL_TIMER=1
      shift
      ;;
    --timer-scope)
      TIMER_SCOPE="$2"
      shift 2
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

case "$TIMER_SCOPE" in
  user|system)
    ;;
  *)
    fail "invalid timer scope: $TIMER_SCOPE"
    ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX/#\~/$HOME}"
BIN_DIR="${BIN_DIR/#\~/$HOME}"
STATE_DIR="${STATE_DIR/#\~/$HOME}"
VENV_DIR="$PREFIX/venv"
DB_PATH="$STATE_DIR/mc.sqlite3"
WRAPPER_PATH="$BIN_DIR/mc"
MANIFEST_PATH="$PREFIX/install-manifest.env"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "python interpreter not found: $PYTHON_BIN"
check_python_version || fail "Master Control currently requires Python 3.13 or newer"

mkdir -p "$PREFIX" "$BIN_DIR" "$STATE_DIR"
ensure_wrapper_path_is_safe "$WRAPPER_PATH"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  create_virtualenv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install "$REPO_ROOT"

write_wrapper "$WRAPPER_PATH" "$VENV_DIR" "$STATE_DIR" "$DB_PATH" "$PROVIDER"
"$WRAPPER_PATH" doctor

if [[ "$INSTALL_TIMER" -eq 1 ]]; then
  "$WRAPPER_PATH" reconcile-timer install --scope "$TIMER_SCOPE"
fi

write_manifest \
  "$MANIFEST_PATH" \
  "$PREFIX" \
  "$BIN_DIR" \
  "$STATE_DIR" \
  "$DB_PATH" \
  "$VENV_DIR" \
  "$WRAPPER_PATH" \
  "$PROVIDER" \
  "$INSTALL_TIMER" \
  "$TIMER_SCOPE"

echo "Installed Master Control"
echo "wrapper:   $WRAPPER_PATH"
echo "venv:      $VENV_DIR"
echo "state_dir: $STATE_DIR"
echo "report:    $MANIFEST_PATH"

case ":$PATH:" in
  *":$BIN_DIR:"*)
    ;;
  *)
    echo "note: add $BIN_DIR to PATH to invoke \`mc\` directly"
    ;;
esac
