from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from master_control.executor.command_runner import CommandRunner
from master_control.tools.base import (
    RiskLevel,
    Tool,
    ToolArgumentError,
    ToolError,
    ToolSpec,
    get_string_argument,
)
from master_control.tools.service_actions import (
    read_service_state,
    validate_service_name,
    validate_service_scope,
)


class ServiceStatusTool(Tool):
    spec = ToolSpec(
        name="service_status",
        description="Inspect a systemd service status by unit name and optional scope.",
        risk=RiskLevel.READ_ONLY,
        arguments=("name", "scope"),
    )

    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        service_name = get_string_argument(arguments, "name", required=True)
        scope_name = validate_service_scope(get_string_argument(arguments, "scope"))
        if service_name is None:
            raise ToolArgumentError("Argument 'name' is required.")
        normalized_name = validate_service_name(service_name)

        try:
            payload = read_service_state(self.runner, normalized_name, scope=scope_name)
        except ToolError as exc:
            return {
                "status": "unavailable",
                "service": normalized_name,
                "scope": scope_name,
                "reason": str(exc),
            }
        return {
            "status": "ok",
            **payload,
        }
