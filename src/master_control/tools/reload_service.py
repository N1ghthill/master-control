from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from master_control.executor.command_runner import CommandRunner
from master_control.tools.base import (
    RiskLevel,
    Tool,
    ToolArgumentError,
    ToolSpec,
    get_string_argument,
)
from master_control.tools.service_actions import (
    run_service_action,
    validate_service_name,
    validate_service_scope,
)


class ReloadServiceTool(Tool):
    spec = ToolSpec(
        name="reload_service",
        description="Reload a systemd service after explicit confirmation, with optional scope.",
        risk=RiskLevel.MUTATING_SAFE,
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
        result = run_service_action(
            self.runner,
            "reload",
            normalized_name,
            scope=scope_name,
        )
        return {
            "status": result["status"],
            "service": result["service"],
            "scope": result["scope"],
            "action": result["action"],
            "preflight": result["preflight"],
            "post_reload": result["post_action"],
        }
