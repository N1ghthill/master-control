from __future__ import annotations

import os
import re
import shutil
from typing import Any

from master_control.executor.command_runner import CommandExecutionError, CommandRunner
from master_control.tools.base import ToolArgumentError, ToolError

UNIT_NAME_RE = re.compile(r"^[A-Za-z0-9@_.:][A-Za-z0-9@_.:-]*$")
SERVICE_SCOPES = {"system", "user"}
USER_SCOPE_ENV_KEYS = ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")


def validate_unit_name(unit_name: str, *, label: str = "unit") -> str:
    normalized = unit_name.strip()
    if not normalized:
        raise ToolArgumentError(f"Argument '{label}' cannot be empty.")
    if normalized.startswith("-") or not UNIT_NAME_RE.fullmatch(normalized):
        raise ToolArgumentError(
            f"Argument '{label}' must be a valid systemd unit name without shell syntax."
        )
    return normalized


def validate_service_name(service_name: str) -> str:
    normalized = validate_unit_name(service_name, label="name")
    if "." in normalized and not normalized.endswith(".service"):
        raise ToolArgumentError("Argument 'name' must reference a service unit name.")
    return normalized


def validate_service_scope(scope_name: str | None) -> str:
    normalized = (scope_name or "system").strip().lower()
    if normalized not in SERVICE_SCOPES:
        raise ToolArgumentError("Argument 'scope' must be either 'system' or 'user'.")
    return normalized


def ensure_systemctl_available() -> None:
    if shutil.which("systemctl") is None:
        raise ToolError("systemctl not found on PATH.")


def read_service_state(
    runner: CommandRunner,
    service_name: str,
    *,
    scope: str = "system",
) -> dict[str, Any]:
    ensure_systemctl_available()
    normalized_scope = validate_service_scope(scope)
    try:
        result = runner.run(
            build_systemctl_command(
                normalized_scope,
                [
                    "show",
                    service_name,
                    "--no-pager",
                    "--property=Id,LoadState,ActiveState,SubState,UnitFileState,Description,FragmentPath,CanReload,MainPID",
                ],
            ),
            timeout_s=3.0,
            env=build_systemctl_env(normalized_scope),
        )
    except CommandExecutionError as exc:
        raise ToolError(str(exc)) from exc

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip()
        raise ToolError(stderr or f"Failed to inspect `{service_name}`.")

    payload: dict[str, Any] = {
        "service": service_name,
        "scope": normalized_scope,
    }
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        payload[key.lower()] = value
    missing_fields = [
        field
        for field in ("id", "loadstate", "activestate", "substate")
        if not isinstance(payload.get(field), str) or not str(payload[field]).strip()
    ]
    if missing_fields:
        missing_text = ", ".join(missing_fields)
        raise ToolError(
            f"systemctl returned incomplete metadata for `{service_name}`: missing {missing_text}."
        )
    return payload


def run_service_action(
    runner: CommandRunner,
    action: str,
    service_name: str,
    *,
    scope: str = "system",
) -> dict[str, Any]:
    normalized_scope = validate_service_scope(scope)
    preflight = read_service_state(runner, service_name, scope=normalized_scope)
    load_state = preflight.get("loadstate")
    if load_state == "not-found":
        raise ToolError(f"Service `{service_name}` was not found.")
    if action == "reload" and preflight.get("canreload") == "no":
        raise ToolError(
            f"Service `{service_name}` does not support reload in `{normalized_scope}` scope."
        )

    try:
        result = runner.run(
            build_systemctl_command(
                normalized_scope,
                [
                    action,
                    service_name,
                    "--no-pager",
                    *(build_systemctl_action_flags(normalized_scope)),
                ],
            ),
            timeout_s=10.0,
            env=build_systemctl_env(normalized_scope),
        )
    except CommandExecutionError as exc:
        raise ToolError(str(exc)) from exc

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip()
        raise ToolError(stderr or f"Failed to {action} `{service_name}`.")

    post_action = read_service_state(runner, service_name, scope=normalized_scope)
    return {
        "status": "ok",
        "service": service_name,
        "scope": normalized_scope,
        "action": action,
        "preflight": preflight,
        "post_action": post_action,
    }


def build_systemctl_command(scope: str, parts: list[str]) -> list[str]:
    command = ["systemctl"]
    if scope == "user":
        command.append("--user")
    command.extend(parts)
    return command


def build_systemctl_env(scope: str) -> dict[str, str] | None:
    if scope != "user":
        return None

    env: dict[str, str] = {}
    missing: list[str] = []
    for key in USER_SCOPE_ENV_KEYS:
        value = os.getenv(key)
        if value:
            env[key] = value
        else:
            missing.append(key)

    home = os.getenv("HOME")
    if home:
        env["HOME"] = home

    if missing:
        missing_text = ", ".join(missing)
        raise ToolError(
            f"user-scoped systemd commands require these environment variables: {missing_text}"
        )
    return env


def build_systemctl_action_flags(scope: str) -> tuple[str, ...]:
    if scope == "system":
        return ("--no-ask-password",)
    return ()
