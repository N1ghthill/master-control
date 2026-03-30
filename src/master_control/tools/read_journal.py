from __future__ import annotations

import shutil
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
from master_control.tools.service_actions import validate_unit_name


class ReadJournalTool(Tool):
    spec = ToolSpec(
        name="read_journal",
        description="Read recent journal entries, optionally filtered by unit.",
        risk=RiskLevel.READ_ONLY,
        arguments=("unit", "lines"),
    )

    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        lines = get_int_argument(arguments, "lines", default=50, min_value=1, max_value=200)
        raw_unit = get_string_argument(arguments, "unit", default=None)
        if lines is None:
            raise ToolArgumentError("Argument 'lines' is required.")
        unit = None
        if raw_unit is not None:
            unit = validate_unit_name(raw_unit, label="unit")

        if shutil.which("journalctl") is None:
            return {
                "status": "unavailable",
                "unit": unit,
                "requested_lines": lines,
                "reason": "journalctl not found on PATH.",
                "entries": [],
            }

        command = [
            "journalctl",
            "-q",
            "--no-pager",
            "--output=short-iso",
            "-n",
            str(lines),
        ]
        if unit:
            command.extend(["-u", unit])

        try:
            result = self.runner.run(command, timeout_s=5.0)
        except CommandExecutionError as exc:
            return {
                "status": "unavailable",
                "unit": unit,
                "requested_lines": lines,
                "reason": str(exc),
                "entries": [],
            }

        if result.returncode != 0:
            return {
                "status": "error",
                "unit": unit,
                "requested_lines": lines,
                "reason": (result.stderr or result.stdout).strip(),
                "entries": [],
            }

        entries = [
            line
            for line in result.stdout.splitlines()
            if line.strip() and line.strip() != "-- No entries --"
        ]
        return {
            "status": "ok",
            "unit": unit,
            "requested_lines": lines,
            "returned_lines": len(entries),
            "truncated": result.truncated_stdout,
            "entries": entries,
        }
