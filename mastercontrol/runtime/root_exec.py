#!/usr/bin/env python3
"""Allowlisted privileged executor for MasterControl bootstrap."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_ETC_ACTIONS = Path("/etc/mastercontrol/actions.json")
DEFAULT_REPO_ACTIONS = (
    Path(__file__).resolve().parents[2] / "config" / "privilege" / "actions.json"
)
DEFAULT_AUDIT_LOG = Path("/var/log/mastercontrol/root-exec.log")


def utc_now() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat()


def parse_kv(items: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in items:
        if "=" not in raw:
            raise ValueError(f"Invalid --arg format '{raw}', expected KEY=VALUE")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("Argument key cannot be empty")
        if key in result:
            raise ValueError(f"Duplicate argument key '{key}'")
        result[key] = value
    return result


def resolve_actions_file(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    if DEFAULT_ETC_ACTIONS.exists():
        return DEFAULT_ETC_ACTIONS
    return DEFAULT_REPO_ACTIONS


def load_actions(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Actions file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if "actions" not in data or not isinstance(data["actions"], dict):
        raise ValueError("Invalid actions file: missing object 'actions'")
    return data


def validate_action_args(action_id: str, spec: dict[str, Any], args: dict[str, str]) -> dict[str, str]:
    args_spec = spec.get("args", {})
    if not isinstance(args_spec, dict):
        raise ValueError(f"Action '{action_id}' has invalid args schema")

    unknown = set(args) - set(args_spec)
    if unknown:
        unknown_str = ", ".join(sorted(unknown))
        raise ValueError(f"Action '{action_id}' does not allow args: {unknown_str}")

    clean: dict[str, str] = {}
    for key, key_spec in args_spec.items():
        if not isinstance(key_spec, dict):
            raise ValueError(f"Action '{action_id}' arg '{key}' spec must be object")
        required = bool(key_spec.get("required", False))
        pattern = key_spec.get("pattern")
        value = args.get(key)

        if required and value is None:
            raise ValueError(f"Action '{action_id}' missing required arg '{key}'")
        if value is None:
            continue
        if pattern and not re.fullmatch(pattern, value):
            raise ValueError(
                f"Action '{action_id}' arg '{key}' failed pattern validation"
            )
        clean[key] = value

    return clean


def build_command(action_id: str, spec: dict[str, Any], args: dict[str, str]) -> list[str]:
    command = spec.get("command")
    if not isinstance(command, list) or not command:
        raise ValueError(f"Action '{action_id}' has invalid command list")

    rendered: list[str] = []
    for token in command:
        if not isinstance(token, str):
            raise ValueError(f"Action '{action_id}' command token must be string")
        try:
            rendered.append(token.format(**args))
        except KeyError as exc:
            raise ValueError(
                f"Action '{action_id}' command references unknown arg '{exc.args[0]}'"
            ) from exc

    return rendered


def requester_identity() -> dict[str, str]:
    return {
        "user": os.environ.get("USER", ""),
        "pkexec_uid": os.environ.get("PKEXEC_UID", ""),
        "sudo_user": os.environ.get("SUDO_USER", ""),
        "tty": os.environ.get("TTY", ""),
    }


def append_audit_log(entry: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(entry, ensure_ascii=True) + "\n")


def exec_action(
    actions_file: Path,
    action_id: str,
    args: dict[str, str],
    request_id: str | None,
    dry_run: bool,
    audit_log: Path,
) -> tuple[dict[str, Any], int]:
    data = load_actions(actions_file)
    actions = data["actions"]
    spec = actions.get(action_id)
    if spec is None:
        return {"ok": False, "error": f"unknown action '{action_id}'"}, 2
    if not isinstance(spec, dict):
        return {"ok": False, "error": f"invalid spec for action '{action_id}'"}, 2

    clean_args = validate_action_args(action_id, spec, args)
    command = build_command(action_id, spec, clean_args)
    timeout_sec = int(spec.get("timeout_sec", 30))
    risk = str(spec.get("risk", "unknown"))
    started = time.monotonic()
    ts = utc_now()

    if dry_run:
        payload = {
            "ok": True,
            "dry_run": True,
            "action_id": action_id,
            "risk": risk,
            "timeout_sec": timeout_sec,
            "command": command,
            "request_id": request_id or "",
        }
        return payload, 0

    if os.geteuid() != 0:
        return {
            "ok": False,
            "error": "root privileges required",
            "hint": "run via pkexec or root broker",
        }, 126

    proc = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_sec,
    )
    duration_ms = int((time.monotonic() - started) * 1000)

    payload = {
        "ok": proc.returncode == 0,
        "action_id": action_id,
        "risk": risk,
        "request_id": request_id or "",
        "returncode": proc.returncode,
        "duration_ms": duration_ms,
        "command": command,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }

    audit = {
        "ts_utc": ts,
        "event": "root_action",
        "action_id": action_id,
        "request_id": request_id or "",
        "risk": risk,
        "requester": requester_identity(),
        "returncode": proc.returncode,
        "duration_ms": duration_ms,
        "command": command,
        "ok": proc.returncode == 0,
    }
    append_audit_log(audit, audit_log)
    return payload, proc.returncode


def list_actions(actions_file: Path) -> dict[str, Any]:
    data = load_actions(actions_file)
    actions = data["actions"]
    rendered = []
    for action_id in sorted(actions.keys()):
        item = actions[action_id]
        rendered.append(
            {
                "action_id": action_id,
                "risk": item.get("risk", "unknown"),
                "args": sorted((item.get("args") or {}).keys()),
            }
        )
    return {"version": data.get("version", None), "actions": rendered}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="root-exec",
        description="MasterControl allowlisted privileged executor",
    )
    p.add_argument(
        "--actions-file",
        default=None,
        help="Path to actions.json (default: /etc/mastercontrol/actions.json)",
    )
    p.add_argument(
        "--audit-log",
        default=str(DEFAULT_AUDIT_LOG),
        help=f"Audit log path (default: {DEFAULT_AUDIT_LOG})",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Force JSON output",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("exec", help="Execute allowlisted action")
    pe.add_argument("--action", required=True, help="Action ID")
    pe.add_argument("--arg", action="append", default=[], help="Action arg KEY=VALUE")
    pe.add_argument("--request-id", default="", help="Correlation ID for audit")
    pe.add_argument("--dry-run", action="store_true", help="Validate only")

    sub.add_parser("list-actions", help="List available actions")
    return p


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=True))
        return
    print(json.dumps(payload, indent=2, ensure_ascii=True))


def main() -> int:
    args = parser().parse_args()
    actions_file = resolve_actions_file(args.actions_file)
    audit_log = Path(args.audit_log)
    as_json = bool(args.json)

    try:
        if args.cmd == "list-actions":
            payload = list_actions(actions_file)
            emit(payload, as_json=as_json)
            return 0

        if args.cmd == "exec":
            kv = parse_kv(args.arg)
            payload, rc = exec_action(
                actions_file=actions_file,
                action_id=args.action,
                args=kv,
                request_id=args.request_id or "",
                dry_run=bool(args.dry_run),
                audit_log=audit_log,
            )
            emit(payload, as_json=as_json)
            return rc

        print("Unknown command")
        return 1
    except subprocess.TimeoutExpired:
        payload = {"ok": False, "error": "command timeout"}
        emit(payload, as_json=as_json)
        return 124
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": str(exc)}
        emit(payload, as_json=as_json)
        return 1


if __name__ == "__main__":
    sys.exit(main())
