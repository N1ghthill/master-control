from __future__ import annotations

from collections import OrderedDict

from master_control.agent.tool_result_views import build_tool_result_view
from master_control.shared.planning import ExecutionPlan
from master_control.shared.session_summary import parse_session_summary

SUMMARY_ORDER = (
    "current_focus",
    "tracked_unit",
    "tracked_scope",
    "tracked_path",
    "last_intent",
    "last_user_request",
    "host",
    "memory",
    "disk",
    "service",
    "config",
    "config_target",
    "config_validation",
    "last_backup_path",
    "logs",
    "processes",
    "last_assistant_reply",
)
MAX_SUMMARY_LINES = 13
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
            tracked_unit = _extract_tracked_unit(first_step.tool_name, first_step.arguments)
            if tracked_unit:
                summary["tracked_unit"] = _truncate(tracked_unit)
            tracked_scope = _extract_tracked_scope(first_step.tool_name, first_step.arguments)
            if tracked_scope:
                summary["tracked_scope"] = tracked_scope
            tracked_path = _extract_tracked_path(first_step.arguments)
            if tracked_path:
                summary["tracked_path"] = _truncate(tracked_path)

    for execution in executions:
        _apply_execution_summary(summary, execution)

    return _render_summary(summary)


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
    arguments = execution.get("arguments")
    result = execution.get("result")
    if not isinstance(tool_name, str) or not isinstance(result, dict):
        return
    resolved_arguments = arguments if isinstance(arguments, dict) else {}
    view = build_tool_result_view(tool_name, resolved_arguments, result)
    for key, value in view.summary_updates.items():
        if isinstance(value, str) and value:
            summary[key] = _truncate(value)


def _extract_tracked_unit(tool_name: str, arguments: dict[str, object]) -> str | None:
    candidate_keys = ["unit"]
    if tool_name in {
        "service_status",
        "restart_service",
        "reload_service",
        "failed_services",
    }:
        candidate_keys.append("name")
    for key in candidate_keys:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_tracked_path(arguments: dict[str, object]) -> str | None:
    value = arguments.get("path")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _extract_tracked_scope(tool_name: str, arguments: dict[str, object]) -> str | None:
    if tool_name not in {
        "service_status",
        "restart_service",
        "reload_service",
        "failed_services",
    }:
        return None
    value = arguments.get("scope")
    if isinstance(value, str) and value in {"system", "user"}:
        return value
    return None


def _first_paragraph(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0] if lines else ""


def _truncate(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= MAX_VALUE_CHARS:
        return normalized
    return normalized[: MAX_VALUE_CHARS - 3].rstrip() + "..."
