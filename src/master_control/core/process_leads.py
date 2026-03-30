from __future__ import annotations

from master_control.core.session_context import (
    ProcessEntryContext,
    ProcessesContext,
    TrackedEntities,
)

GENERIC_SESSION_COMMANDS = frozenset(
    {
        "bash",
        "fish",
        "java",
        "node",
        "nodejs",
        "perl",
        "python",
        "python3",
        "ruby",
        "sh",
        "tmux",
        "tmux: server",
        "zsh",
    }
)
SERVICE_LEAD_CPU_RATIO = 0.8
MIN_SERVICE_LEAD_CPU = 40.0


def select_process_lead(
    processes: ProcessesContext | None,
    *,
    tracked: TrackedEntities | None = None,
) -> ProcessEntryContext | None:
    if processes is None or not processes.items:
        return None

    tracked_command = _tracked_unit_command(tracked)
    if tracked_command is not None:
        for item in processes.items:
            if _command_matches_unit(item.command, tracked_command):
                return item

    leader = processes.items[0]
    leader_cpu = leader.cpu_percent
    if leader_cpu is None or not is_generic_session_command(leader.command):
        return leader

    preferred_candidates = [
        item for item in processes.items[1:] if _is_more_operator_useful_lead(item, leader_cpu)
    ]
    if preferred_candidates:
        return max(
            preferred_candidates,
            key=lambda item: (item.cpu_percent or 0.0, item.occurrences or 1),
        )
    return leader


def is_generic_session_command(command: str | None) -> bool:
    if not isinstance(command, str) or not command:
        return False
    base_name = command.rsplit("/", maxsplit=1)[-1].strip().lower()
    return base_name in GENERIC_SESSION_COMMANDS


def _is_more_operator_useful_lead(item: ProcessEntryContext, leader_cpu: float) -> bool:
    if item.cpu_percent is None or item.cpu_percent < MIN_SERVICE_LEAD_CPU:
        return False
    if is_generic_session_command(item.command):
        return False
    return item.cpu_percent >= leader_cpu * SERVICE_LEAD_CPU_RATIO


def _tracked_unit_command(tracked: TrackedEntities | None) -> str | None:
    if tracked is None or not tracked.unit:
        return None
    unit = tracked.unit
    if unit.endswith(".service"):
        return unit[: -len(".service")]
    if "." in unit:
        return None
    return unit


def _command_matches_unit(command: str, unit_name: str) -> bool:
    normalized_command = command.strip().lower()
    normalized_unit = unit_name.strip().lower()
    return normalized_command == normalized_unit or normalized_command.startswith(
        f"{normalized_unit}-"
    )
