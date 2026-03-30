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


class RestoreConfigBackupTool(Tool):
    spec = ToolSpec(
        name="restore_config_backup",
        description="Restore a managed configuration file from a managed backup path.",
        risk=RiskLevel.PRIVILEGED,
        arguments=("path", "backup_path"),
    )

    def __init__(self, manager: ConfigManager) -> None:
        self.manager = manager

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        path = get_string_argument(arguments, "path", required=True)
        backup_path = get_string_argument(arguments, "backup_path", required=True)
        if path is None:
            raise ToolArgumentError("Argument 'path' is required.")
        if backup_path is None:
            raise ToolArgumentError("Argument 'backup_path' is required.")
        return self.manager.restore_backup(path, backup_path)
