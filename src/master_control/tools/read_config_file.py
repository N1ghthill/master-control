from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from master_control.config_manager import ConfigManager
from master_control.tools.base import (
    RiskLevel,
    Tool,
    ToolArgumentError,
    ToolSpec,
    get_string_argument,
)


class ReadConfigFileTool(Tool):
    spec = ToolSpec(
        name="read_config_file",
        description="Read a managed configuration file from an allowlisted target.",
        risk=RiskLevel.READ_ONLY,
        arguments=("path",),
    )

    def __init__(self, manager: ConfigManager) -> None:
        self.manager = manager

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        path = get_string_argument(arguments, "path", required=True)
        if path is None:
            raise ToolArgumentError("Argument 'path' is required.")
        return self.manager.read_text(path)
