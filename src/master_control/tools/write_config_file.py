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


class WriteConfigFileTool(Tool):
    spec = ToolSpec(
        name="write_config_file",
        description="Write a managed configuration file with backup and validation.",
        risk=RiskLevel.PRIVILEGED,
        arguments=("path", "content"),
    )

    def __init__(self, manager: ConfigManager) -> None:
        self.manager = manager

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        path = get_string_argument(arguments, "path", required=True)
        raw_content = arguments.get("content")
        if not isinstance(raw_content, str):
            raise ToolArgumentError("Argument 'content' must be a string.")
        if raw_content == "":
            raise ToolArgumentError("Argument 'content' cannot be empty.")
        assert path is not None
        return self.manager.write_text(path, raw_content)
