from __future__ import annotations

import os
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
        collector_pid = os.getpid()

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

        parsed_processes: list[dict[str, object]] = []
        excluded_process_count = 0
        for line in result.stdout.splitlines():
            item = _parse_process_line(line)
            if item is None:
                continue
            if _should_exclude_process(item, collector_pid=collector_pid):
                excluded_process_count += 1
                continue
            parsed_processes.append(item)
            if len(parsed_processes) >= limit:
                break

        return {
            "status": "ok",
            "limit": limit,
            "excluded_process_count": excluded_process_count,
            "processes": parsed_processes,
        }


def _parse_process_line(line: str) -> dict[str, object] | None:
    parts = line.split(None, maxsplit=4)
    if len(parts) != 5:
        return None
    raw_pid, raw_ppid, raw_cpu, raw_mem, command = parts
    try:
        pid = int(raw_pid)
        ppid = int(raw_ppid)
        cpu_percent = float(raw_cpu)
        memory_percent = float(raw_mem)
    except ValueError:
        return None
    return {
        "pid": pid,
        "ppid": ppid,
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "command": command,
    }


def _should_exclude_process(
    item: dict[str, object],
    *,
    collector_pid: int,
) -> bool:
    pid = item.get("pid")
    ppid = item.get("ppid")
    command = item.get("command")
    if pid == collector_pid:
        return True
    if ppid == collector_pid:
        return True
    return command == "ps"
