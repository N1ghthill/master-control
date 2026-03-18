from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from master_control.executor.command_runner import CommandExecutionError, CommandRunner
from master_control.tools.base import RiskLevel, Tool, ToolSpec, get_int_argument


class TopProcessesTool(Tool):
    spec = ToolSpec(
        name="top_processes",
        description="Return the top processes sorted by CPU usage.",
        risk=RiskLevel.READ_ONLY,
        arguments=("limit",),
    )

    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        limit = get_int_argument(arguments, "limit", default=5, min_value=1, max_value=20)
        assert limit is not None

        try:
            result = self.runner.run(
                [
                    "ps",
                    "-eo",
                    "pid=,ppid=,%cpu=,%mem=,comm=",
                    "--sort=-%cpu",
                ],
                timeout_s=3.0,
            )
        except CommandExecutionError as exc:
            return {
                "status": "unavailable",
                "reason": str(exc),
                "processes": [],
            }

        if result.returncode != 0:
            return {
                "status": "error",
                "reason": (result.stderr or result.stdout).strip(),
                "processes": [],
            }

        processes: list[dict[str, object]] = []
        for line in result.stdout.splitlines()[:limit]:
            parts = line.split(None, maxsplit=4)
            if len(parts) != 5:
                continue
            pid, ppid, cpu, mem, command = parts
            processes.append(
                {
                    "pid": int(pid),
                    "ppid": int(ppid),
                    "cpu_percent": float(cpu),
                    "memory_percent": float(mem),
                    "command": command,
                }
            )

        return {
            "status": "ok",
            "limit": limit,
            "processes": processes,
        }
