from __future__ import annotations

from collections import OrderedDict
from typing import Any

from master_control.agent.planner import ExecutionPlan


SUMMARY_ORDER = (
    "current_focus",
    "tracked_unit",
    "tracked_path",
    "last_intent",
    "last_user_request",
    "host",
    "memory",
    "disk",
    "service",
    "config",
    "logs",
    "processes",
    "last_assistant_reply",
)
MAX_SUMMARY_LINES = 10
MAX_VALUE_CHARS = 180


def update_session_summary(
    existing_summary: str | None,
    *,
    user_input: str,
    plan: ExecutionPlan | None,
    executions: list[dict[str, object]],
    assistant_message: str,
) -> str:
    summary = parse_session_summary(existing_summary)

    summary["last_user_request"] = _truncate(user_input)
    summary["last_assistant_reply"] = _truncate(_first_paragraph(assistant_message))

    if plan is not None:
        summary["last_intent"] = _truncate(plan.intent)
        if plan.steps:
            first_step = plan.steps[0]
            summary["current_focus"] = _truncate(first_step.rationale)
            tracked_unit = _extract_tracked_unit(first_step.arguments)
            if tracked_unit:
                summary["tracked_unit"] = _truncate(tracked_unit)
            tracked_path = _extract_tracked_path(first_step.arguments)
            if tracked_path:
                summary["tracked_path"] = _truncate(tracked_path)

    for execution in executions:
        _apply_execution_summary(summary, execution)

    return _render_summary(summary)


def parse_session_summary(existing_summary: str | None) -> OrderedDict[str, str]:
    parsed: OrderedDict[str, str] = OrderedDict()
    if not existing_summary:
        return parsed

    for line in existing_summary.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", maxsplit=1)
        normalized_key = key.strip()
        value = raw_value.strip()
        if not normalized_key or not value:
            continue
        parsed[normalized_key] = value
    return parsed


def _render_summary(summary: OrderedDict[str, str]) -> str:
    ordered_items: list[tuple[str, str]] = []
    seen_keys = set()

    for key in SUMMARY_ORDER:
        value = summary.get(key)
        if value:
            ordered_items.append((key, value))
            seen_keys.add(key)

    for key, value in summary.items():
        if key in seen_keys or not value:
            continue
        ordered_items.append((key, value))

    lines = [f"{key}: {value}" for key, value in ordered_items[:MAX_SUMMARY_LINES]]
    return "\n".join(lines)


def _apply_execution_summary(
    summary: OrderedDict[str, str],
    execution: dict[str, object],
) -> None:
    if not execution.get("ok"):
        return

    tool_name = execution.get("tool")
    result = execution.get("result")
    if not isinstance(tool_name, str) or not isinstance(result, dict):
        return

    if tool_name == "system_info":
        hostname = result.get("hostname")
        kernel = result.get("kernel")
        if hostname and kernel:
            summary["host"] = _truncate(f"{hostname}, kernel {kernel}")
        return

    if tool_name == "memory_usage":
        memory_used_percent = result.get("memory_used_percent")
        swap_used_percent = result.get("swap_used_percent")
        if memory_used_percent is not None and swap_used_percent is not None:
            summary["memory"] = _truncate(
                f"memory {memory_used_percent}% used, swap {swap_used_percent}% used"
            )
        return

    if tool_name == "disk_usage":
        path = result.get("path")
        used_percent = result.get("used_percent")
        if isinstance(path, str):
            summary["tracked_path"] = _truncate(path)
        if path is not None and used_percent is not None:
            summary["disk"] = _truncate(f"{path} is {used_percent}% used")
        return

    if tool_name == "service_status":
        service = result.get("service")
        active_state = result.get("activestate")
        sub_state = result.get("substate")
        if isinstance(service, str):
            summary["tracked_unit"] = _truncate(service)
        if service and active_state and sub_state:
            summary["service"] = _truncate(f"{service}: active={active_state}, sub={sub_state}")
        return

    if tool_name == "read_journal":
        unit = result.get("unit") or "system"
        returned_lines = result.get("returned_lines")
        if isinstance(unit, str) and unit:
            summary["tracked_unit"] = _truncate(unit)
        if returned_lines is not None:
            summary["logs"] = _truncate(f"{unit}: last journal read returned {returned_lines} lines")
        return

    if tool_name == "top_processes":
        processes = result.get("processes")
        if not isinstance(processes, list) or not processes:
            return
        commands: list[str] = []
        for item in processes[:3]:
            if not isinstance(item, dict):
                continue
            command = item.get("command")
            cpu_percent = item.get("cpu_percent")
            if isinstance(command, str):
                if isinstance(cpu_percent, (int, float)):
                    commands.append(f"{command}({cpu_percent}%)")
                else:
                    commands.append(command)
        if commands:
            summary["processes"] = _truncate(", ".join(commands))
        return

    if tool_name in {"read_config_file", "write_config_file", "restore_config_backup"}:
        path = result.get("path")
        if isinstance(path, str) and path:
            summary["tracked_path"] = _truncate(path)
            summary["config"] = _truncate(f"{tool_name}: {path}")
        return

    if tool_name in {"restart_service", "reload_service"}:
        service = result.get("service")
        post_state = result.get("post_restart") or result.get("post_reload")
        if isinstance(service, str) and service:
            summary["tracked_unit"] = _truncate(service)
        if isinstance(service, str) and isinstance(post_state, dict):
            active_state = post_state.get("activestate")
            sub_state = post_state.get("substate")
            if active_state and sub_state:
                summary["service"] = _truncate(
                    f"{service}: active={active_state}, sub={sub_state}"
                )


def _extract_tracked_unit(arguments: dict[str, object]) -> str | None:
    for key in ("unit", "name"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_tracked_path(arguments: dict[str, object]) -> str | None:
    value = arguments.get("path")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _first_paragraph(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0] if lines else ""


def _truncate(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= MAX_VALUE_CHARS:
        return normalized
    return normalized[: MAX_VALUE_CHARS - 3].rstrip() + "..."
