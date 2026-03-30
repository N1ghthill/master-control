from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from master_control.executor.command_runner import CommandExecutionError, CommandRunner
from master_control.tools.base import (
    RiskLevel,
    Tool,
    ToolArgumentError,
    ToolSpec,
    get_int_argument,
    get_string_argument,
)

PROC_ROOT = Path("/proc")
UNIT_SEGMENT_RE = re.compile(
    r"^[A-Za-z0-9@_.:-]+\.(?:service|scope|socket|mount|slice|target|timer)$"
)


class ProcessToUnitTool(Tool):
    spec = ToolSpec(
        name="process_to_unit",
        description="Correlate a process name or pid with the owning systemd unit when available.",
        risk=RiskLevel.READ_ONLY,
        arguments=("name", "pid", "limit"),
    )

    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def invoke(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        process_name = get_string_argument(arguments, "name", default=None)
        pid = get_int_argument(arguments, "pid", default=None, min_value=1)
        limit = get_int_argument(arguments, "limit", default=3, min_value=1, max_value=20)
        if limit is None:
            raise ToolArgumentError("Argument 'limit' is required.")

        if process_name is None and pid is None:
            raise ToolArgumentError("Argument 'name' or 'pid' is required.")
        if process_name is not None and pid is not None:
            raise ToolArgumentError("Use either 'name' or 'pid', not both.")

        try:
            if pid is not None:
                candidates = self._query_candidates_by_pid(pid)
            else:
                if process_name is None:
                    raise ToolArgumentError("Argument 'name' is required when 'pid' is omitted.")
                candidates = self._query_candidates_by_name(process_name, limit)
        except CommandExecutionError as exc:
            return {
                "status": "unavailable",
                "query": {
                    "name": process_name,
                    "pid": pid,
                    "limit": limit,
                },
                "reason": str(exc),
                "matched_process_count": 0,
                "resolved_count": 0,
                "primary_match": None,
                "units": [],
                "correlations": [],
            }

        correlations = [self._correlate_candidate(item) for item in candidates]
        units = _aggregate_units(correlations)
        primary_match = next(
            (
                {
                    "pid": item["pid"],
                    "command": item["command"],
                    "unit": item["unit"],
                    "scope": item["scope"],
                }
                for item in correlations
                if isinstance(item.get("unit"), str) and item["unit"]
            ),
            None,
        )
        return {
            "status": "ok",
            "query": {
                "name": process_name,
                "pid": pid,
                "limit": limit,
            },
            "matched_process_count": len(candidates),
            "resolved_count": len(units),
            "primary_match": primary_match,
            "units": units,
            "correlations": correlations,
        }

    def _query_candidates_by_name(self, process_name: str, limit: int) -> list[dict[str, object]]:
        result = self.runner.run(
            [
                "ps",
                "-eo",
                "pid=,%cpu=,comm=",
                "--sort=-%cpu",
            ],
            timeout_s=3.0,
        )
        if result.returncode != 0:
            raise CommandExecutionError((result.stderr or result.stdout).strip() or "ps failed.")

        candidates: list[dict[str, object]] = []
        for line in result.stdout.splitlines():
            parts = line.split(None, maxsplit=2)
            if len(parts) != 3:
                continue
            raw_pid, raw_cpu, command = parts
            if command != process_name:
                continue
            candidates.append(
                {
                    "pid": int(raw_pid),
                    "cpu_percent": float(raw_cpu),
                    "command": command,
                }
            )
            if len(candidates) >= limit:
                break
        return candidates

    def _query_candidates_by_pid(self, pid: int) -> list[dict[str, object]]:
        result = self.runner.run(
            [
                "ps",
                "-p",
                str(pid),
                "-o",
                "pid=,%cpu=,comm=",
            ],
            timeout_s=3.0,
        )
        if result.returncode != 0:
            raise CommandExecutionError((result.stderr or result.stdout).strip() or "ps failed.")

        candidates: list[dict[str, object]] = []
        for line in result.stdout.splitlines():
            parts = line.split(None, maxsplit=2)
            if len(parts) != 3:
                continue
            raw_pid, raw_cpu, command = parts
            candidates.append(
                {
                    "pid": int(raw_pid),
                    "cpu_percent": float(raw_cpu),
                    "command": command,
                }
            )
        return candidates

    def _correlate_candidate(self, candidate: dict[str, object]) -> dict[str, object]:
        raw_pid = candidate.get("pid")
        if not isinstance(raw_pid, int):
            raise ToolArgumentError("Process correlation candidate is missing a valid pid.")
        pid = raw_pid
        command = str(candidate["command"])
        cpu_percent = candidate.get("cpu_percent")
        cgroup_path = _read_primary_cgroup_path(pid)
        unit = _extract_unit_from_cgroup_path(cgroup_path)
        scope = _scope_from_cgroup_path(cgroup_path)
        return {
            "pid": pid,
            "command": command,
            "cpu_percent": float(cpu_percent) if isinstance(cpu_percent, float) else cpu_percent,
            "unit": unit,
            "scope": scope,
            "cgroup_path": cgroup_path,
        }


def _read_primary_cgroup_path(pid: int) -> str | None:
    try:
        lines = (PROC_ROOT / str(pid) / "cgroup").read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None

    for line in lines:
        parts = line.split(":", maxsplit=2)
        if len(parts) != 3:
            continue
        path = parts[2].strip()
        if path:
            return path
    return None


def _extract_unit_from_cgroup_path(cgroup_path: str | None) -> str | None:
    if not cgroup_path:
        return None
    for segment in reversed([part for part in cgroup_path.split("/") if part]):
        if UNIT_SEGMENT_RE.fullmatch(segment):
            return segment
    return None


def _scope_from_cgroup_path(cgroup_path: str | None) -> str | None:
    if not cgroup_path:
        return None
    if "/user.slice/" in cgroup_path or cgroup_path.startswith("/user.slice/"):
        return "user"
    return "system"


def _aggregate_units(correlations: list[dict[str, object]]) -> list[dict[str, object]]:
    aggregated: OrderedDict[tuple[str, str | None], dict[str, object]] = OrderedDict()
    for item in correlations:
        unit = item.get("unit")
        if not isinstance(unit, str) or not unit:
            continue
        scope = item.get("scope")
        normalized_scope = scope if isinstance(scope, str) and scope else None
        key = (unit, normalized_scope)
        entry = aggregated.get(key)
        if entry is None:
            entry = {
                "unit": unit,
                "scope": normalized_scope,
                "pid_count": 0,
                "pids": [],
                "commands": [],
            }
            aggregated[key] = entry
        pid_count = cast(int, entry["pid_count"])
        pids = cast(list[object], entry["pids"])
        commands = cast(list[object], entry["commands"])
        entry["pid_count"] = pid_count + 1
        entry["pids"] = [*pids, item["pid"]]
        command = item.get("command")
        if isinstance(command, str) and command not in commands:
            entry["commands"] = [*commands, command]
    return list(aggregated.values())
