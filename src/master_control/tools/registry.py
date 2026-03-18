from __future__ import annotations

from pathlib import Path

from master_control.config_manager import ConfigManager
from master_control.executor.command_runner import CommandRunner
from master_control.tools.base import Tool
from master_control.tools.disk_usage import DiskUsageTool
from master_control.tools.memory_usage import MemoryUsageTool
from master_control.tools.read_journal import ReadJournalTool
from master_control.tools.read_config_file import ReadConfigFileTool
from master_control.tools.reload_service import ReloadServiceTool
from master_control.tools.restore_config_backup import RestoreConfigBackupTool
from master_control.tools.restart_service import RestartServiceTool
from master_control.tools.service_status import ServiceStatusTool
from master_control.tools.system_info import SystemInfoTool
from master_control.tools.top_processes import TopProcessesTool
from master_control.tools.write_config_file import WriteConfigFileTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def list_specs(self):
        return [self._tools[name].spec for name in sorted(self._tools)]


def build_default_registry(state_dir: Path) -> ToolRegistry:
    runner = CommandRunner()
    config_manager = ConfigManager(state_dir, runner)
    registry = ToolRegistry()
    registry.register(SystemInfoTool())
    registry.register(DiskUsageTool())
    registry.register(MemoryUsageTool())
    registry.register(TopProcessesTool(runner))
    registry.register(ServiceStatusTool(runner))
    registry.register(ReadConfigFileTool(config_manager))
    registry.register(WriteConfigFileTool(config_manager))
    registry.register(RestoreConfigBackupTool(config_manager))
    registry.register(ReloadServiceTool(runner))
    registry.register(RestartServiceTool(runner))
    registry.register(ReadJournalTool(runner))
    return registry
