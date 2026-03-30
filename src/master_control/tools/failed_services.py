from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from master_control.executor.command_runner import CommandExecutionError, CommandRunner
from master_control.tools.base import (
    RiskLevel,
    Tool,
    ToolArgumentError,
    ToolSpec,
    get_int_argument,
    get_string_argument,
)
from master_control.tools.service_actions import (
    build_systemctl_command,
    build_systemctl_env,
    ensure_systemctl_available,
    validate_service_scope,
)


class FailedServicesTool(Tool):
    spec = ToolSpec(
        name="failed_services",
        description="List failed systemd services for the requested scope.",
        risk=RiskLevel.READ_ONLY,
        arguments=("scope", "limit"),
    )

    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        scope = validate_service_scope(get_string_argument(arguments, "scope"))
        limit = get_int_argument(arguments, "limit", default=10, min_value=1, max_value=50)
        if limit is None:
            raise ToolArgumentError("Argument 'limit' is required.")

        try:
            ensure_systemctl_available()
            result = self.runner.run(
                build_systemctl_command(
                    scope,
                    [
                        "list-units",
                        "--type=service",
                        "--state=failed",
                        "--all",
                        "--no-legend",
                        "--no-pager",
                        "--plain",
                    ],
                ),
                timeout_s=5.0,
                env=build_systemctl_env(scope),
            )
        except (CommandExecutionError, RuntimeError) as exc:
            return {
                "status": "unavailable",
                "scope": scope,
                "limit": limit,
                "reason": str(exc),
                "unit_count": 0,
                "units": [],
            }

        if result.returncode != 0:
            return {
                "status": "error",
                "scope": scope,
                "limit": limit,
                "reason": (result.stderr or result.stdout).strip(),
                "unit_count": 0,
                "units": [],
            }

        units = _parse_failed_service_lines(result.stdout, limit)
        return {
            "status": "ok",
            "scope": scope,
            "limit": limit,
            "unit_count": len(units),
            "units": units,
        }


def _parse_failed_service_lines(stdout: str, limit: int) -> list[dict[str, object]]:
    units: list[dict[str, object]] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, maxsplit=4)
        if len(parts) < 4:
            continue
        description = parts[4] if len(parts) == 5 else ""
        units.append(
            {
                "unit": parts[0],
                "load_state": parts[1],
                "active_state": parts[2],
                "sub_state": parts[3],
                "description": description,
            }
        )
        if len(units) >= limit:
            break
    return units
