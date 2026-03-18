from __future__ import annotations

import re
from dataclasses import dataclass, field

from master_control.agent.observations import ObservationFreshness
from master_control.agent.session_summary import parse_session_summary

DISK_USAGE_RE = re.compile(r"^(?P<path>.+?) is (?P<percent>\d+(?:\.\d+)?)% used$")
MEMORY_RE = re.compile(
    r"^memory (?P<memory>\d+(?:\.\d+)?)% used, swap (?P<swap>\d+(?:\.\d+)?)% used$"
)
SERVICE_RE = re.compile(r"^(?P<service>.+?): active=(?P<active>[^,]+), sub=(?P<sub>.+)$")
PROCESS_RE = re.compile(r"(?P<command>[^,(]+)\((?P<cpu>\d+(?:\.\d+)?)%\)")


@dataclass(frozen=True, slots=True)
class TrackedEntities:
    unit: str | None = None
    scope: str | None = None
    path: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.unit:
            payload["unit"] = self.unit
        if self.scope:
            payload["scope"] = self.scope
        if self.path:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True, slots=True)
class MemoryContext:
    memory_used_percent: float | None = None
    swap_used_percent: float | None = None
    stale: bool | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.memory_used_percent is not None:
            payload["memory_used_percent"] = self.memory_used_percent
        if self.swap_used_percent is not None:
            payload["swap_used_percent"] = self.swap_used_percent
        if self.stale is not None:
            payload["stale"] = self.stale
        return payload


@dataclass(frozen=True, slots=True)
class DiskContext:
    path: str | None = None
    used_percent: float | None = None
    stale: bool | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.path:
            payload["path"] = self.path
        if self.used_percent is not None:
            payload["used_percent"] = self.used_percent
        if self.stale is not None:
            payload["stale"] = self.stale
        return payload


@dataclass(frozen=True, slots=True)
class ServiceContext:
    name: str
    scope: str | None = None
    active_state: str | None = None
    sub_state: str | None = None
    stale: bool | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"name": self.name}
        if self.scope:
            payload["scope"] = self.scope
        if self.active_state:
            payload["active_state"] = self.active_state
        if self.sub_state:
            payload["sub_state"] = self.sub_state
        if self.stale is not None:
            payload["stale"] = self.stale
        return payload


@dataclass(frozen=True, slots=True)
class ProcessEntryContext:
    command: str
    cpu_percent: float | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"command": self.command}
        if self.cpu_percent is not None:
            payload["cpu_percent"] = self.cpu_percent
        return payload


@dataclass(frozen=True, slots=True)
class ProcessesContext:
    items: tuple[ProcessEntryContext, ...] = ()
    stale: bool | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.items:
            payload["items"] = [item.as_dict() for item in self.items]
        if self.stale is not None:
            payload["stale"] = self.stale
        return payload


@dataclass(frozen=True, slots=True)
class ProcessUnitContext:
    query_name: str | None = None
    pid: int | None = None
    unit: str | None = None
    scope: str | None = None
    attempted: bool = False
    no_match: bool = False
    stale: bool | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.query_name:
            payload["query_name"] = self.query_name
        if self.pid is not None:
            payload["pid"] = self.pid
        if self.unit:
            payload["unit"] = self.unit
        if self.scope:
            payload["scope"] = self.scope
        if self.attempted:
            payload["attempted"] = self.attempted
        if self.no_match:
            payload["no_match"] = self.no_match
        if self.stale is not None:
            payload["stale"] = self.stale
        return payload


@dataclass(frozen=True, slots=True)
class LogContext:
    unit: str | None = None
    returned_lines: int | None = None
    stale: bool | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.unit:
            payload["unit"] = self.unit
        if self.returned_lines is not None:
            payload["returned_lines"] = self.returned_lines
        if self.stale is not None:
            payload["stale"] = self.stale
        return payload


@dataclass(frozen=True, slots=True)
class FailedServiceEntryContext:
    unit: str
    active_state: str | None = None
    sub_state: str | None = None
    description: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"unit": self.unit}
        if self.active_state:
            payload["active_state"] = self.active_state
        if self.sub_state:
            payload["sub_state"] = self.sub_state
        if self.description:
            payload["description"] = self.description
        return payload


@dataclass(frozen=True, slots=True)
class FailedServicesContext:
    scope: str | None = None
    items: tuple[FailedServiceEntryContext, ...] = ()
    stale: bool | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.scope:
            payload["scope"] = self.scope
        if self.items:
            payload["items"] = [item.as_dict() for item in self.items]
        if self.stale is not None:
            payload["stale"] = self.stale
        return payload


@dataclass(frozen=True, slots=True)
class ConfigContext:
    path: str | None = None
    target: str | None = None
    validation_kind: str | None = None
    backup_path: str | None = None
    stale: bool | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.path:
            payload["path"] = self.path
        if self.target:
            payload["target"] = self.target
        if self.validation_kind:
            payload["validation_kind"] = self.validation_kind
        if self.backup_path:
            payload["backup_path"] = self.backup_path
        if self.stale is not None:
            payload["stale"] = self.stale
        return payload


@dataclass(frozen=True, slots=True)
class SessionContext:
    tracked: TrackedEntities = field(default_factory=TrackedEntities)
    last_intent: str | None = None
    memory: MemoryContext | None = None
    disk: DiskContext | None = None
    service: ServiceContext | None = None
    processes: ProcessesContext | None = None
    process_unit: ProcessUnitContext | None = None
    logs: LogContext | None = None
    failed_services: FailedServicesContext | None = None
    config: ConfigContext | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        tracked = self.tracked.as_dict()
        if tracked:
            payload["tracked"] = tracked
        if self.last_intent:
            payload["last_intent"] = self.last_intent
        if self.memory is not None:
            memory = self.memory.as_dict()
            if memory:
                payload["memory"] = memory
        if self.disk is not None:
            disk = self.disk.as_dict()
            if disk:
                payload["disk"] = disk
        if self.service is not None:
            service = self.service.as_dict()
            if service:
                payload["service"] = service
        if self.processes is not None:
            processes = self.processes.as_dict()
            if processes:
                payload["processes"] = processes
        if self.process_unit is not None:
            process_unit = self.process_unit.as_dict()
            if process_unit:
                payload["process_unit"] = process_unit
        if self.logs is not None:
            logs = self.logs.as_dict()
            if logs:
                payload["logs"] = logs
        if self.failed_services is not None:
            failed_services = self.failed_services.as_dict()
            if failed_services:
                payload["failed_services"] = failed_services
        if self.config is not None:
            config = self.config.as_dict()
            if config:
                payload["config"] = config
        return payload


def build_session_context(
    session_summary: str | None,
    observation_freshness: tuple[ObservationFreshness, ...] | list[ObservationFreshness] = (),
) -> SessionContext:
    summary = parse_session_summary(session_summary)
    freshness_by_key = {item.key: item for item in observation_freshness}

    memory = _build_memory_context(summary, freshness_by_key.get("memory"))
    disk = _build_disk_context(summary, freshness_by_key.get("disk"))
    service = _build_service_context(summary, freshness_by_key.get("service"))
    processes = _build_processes_context(summary, freshness_by_key.get("processes"))
    process_unit = _build_process_unit_context(freshness_by_key.get("process_unit"))
    logs = _build_logs_context(freshness_by_key.get("logs"))
    failed_services = _build_failed_services_context(freshness_by_key.get("failed_services"))
    config = _build_config_context(summary, freshness_by_key.get("config"))

    tracked_scope = _valid_scope(summary.get("tracked_scope"))
    if tracked_scope is None and service is not None:
        tracked_scope = service.scope
    if tracked_scope is None and process_unit is not None:
        tracked_scope = process_unit.scope
    if tracked_scope is None and failed_services is not None:
        tracked_scope = failed_services.scope

    tracked_unit = _non_empty(summary.get("tracked_unit"))
    if tracked_unit is None and service is not None:
        tracked_unit = service.name
    if tracked_unit is None and process_unit is not None:
        tracked_unit = process_unit.unit
    if tracked_unit is None and logs is not None:
        tracked_unit = logs.unit
    if tracked_unit is None and failed_services is not None and len(failed_services.items) == 1:
        tracked_unit = failed_services.items[0].unit

    tracked_path = _non_empty(summary.get("tracked_path"))
    if tracked_path is None:
        config_freshness = freshness_by_key.get("config")
        tracked_path = _extract_path_from_freshness(config_freshness)
    if tracked_path is None and disk is not None:
        tracked_path = disk.path
    if tracked_path is None and config is not None:
        tracked_path = config.path

    return SessionContext(
        tracked=TrackedEntities(unit=tracked_unit, scope=tracked_scope, path=tracked_path),
        last_intent=_non_empty(summary.get("last_intent")),
        memory=memory,
        disk=disk,
        service=service,
        processes=processes,
        process_unit=process_unit,
        logs=logs,
        failed_services=failed_services,
        config=config,
    )


def _build_memory_context(
    summary: dict[str, str],
    freshness: ObservationFreshness | None,
) -> MemoryContext | None:
    if freshness is not None:
        memory_used = _as_float(freshness.value.get("memory_used_percent"))
        swap_used = _as_float(freshness.value.get("swap_used_percent"))
        if memory_used is not None or swap_used is not None:
            return MemoryContext(
                memory_used_percent=memory_used,
                swap_used_percent=swap_used,
                stale=freshness.stale,
            )

    summary_value = summary.get("memory")
    if summary_value:
        match = MEMORY_RE.match(summary_value)
        if match:
            return MemoryContext(
                memory_used_percent=float(match.group("memory")),
                swap_used_percent=float(match.group("swap")),
            )
    return None


def _build_disk_context(
    summary: dict[str, str],
    freshness: ObservationFreshness | None,
) -> DiskContext | None:
    if freshness is not None:
        path = _non_empty(freshness.value.get("path"))
        used_percent = _as_float(freshness.value.get("used_percent"))
        if path is not None or used_percent is not None:
            return DiskContext(
                path=path,
                used_percent=used_percent,
                stale=freshness.stale,
            )

    summary_value = summary.get("disk")
    if summary_value:
        match = DISK_USAGE_RE.match(summary_value)
        if match:
            return DiskContext(
                path=match.group("path"),
                used_percent=float(match.group("percent")),
            )
    return None


def _build_service_context(
    summary: dict[str, str],
    freshness: ObservationFreshness | None,
) -> ServiceContext | None:
    tracked_scope = _valid_scope(summary.get("tracked_scope"))
    summary_service_name: str | None = None
    summary_active_state: str | None = None
    summary_sub_state: str | None = None
    summary_value = summary.get("service")
    if summary_value:
        match = SERVICE_RE.match(summary_value)
        if match:
            summary_service_name = match.group("service")
            summary_active_state = match.group("active")
            summary_sub_state = match.group("sub")

    if freshness is not None:
        service = _non_empty(freshness.value.get("service"))
        scope = _valid_scope(freshness.value.get("scope")) or tracked_scope
        active_state = _non_empty(freshness.value.get("activestate"))
        sub_state = _non_empty(freshness.value.get("substate"))
        if active_state is None or sub_state is None:
            post_state = freshness.value.get("post_restart") or freshness.value.get("post_reload")
            if isinstance(post_state, dict):
                active_state = active_state or _non_empty(post_state.get("activestate"))
                sub_state = sub_state or _non_empty(post_state.get("substate"))
                scope = scope or _valid_scope(post_state.get("scope"))
        if service is None and summary_service_name is not None:
            service = summary_service_name
        if active_state is None:
            active_state = summary_active_state
        if sub_state is None:
            sub_state = summary_sub_state
        if service is not None:
            return ServiceContext(
                name=service,
                scope=scope,
                active_state=active_state,
                sub_state=sub_state,
                stale=freshness.stale,
            )

    if summary_service_name is not None:
        return ServiceContext(
            name=summary_service_name,
            scope=tracked_scope,
            active_state=summary_active_state,
            sub_state=summary_sub_state,
        )
    return None


def _build_processes_context(
    summary: dict[str, str],
    freshness: ObservationFreshness | None,
) -> ProcessesContext | None:
    if freshness is not None:
        items = _extract_process_items(freshness.value.get("processes"))
        if items:
            return ProcessesContext(items=items, stale=freshness.stale)

    summary_value = summary.get("processes")
    if summary_value:
        items = tuple(
            ProcessEntryContext(
                command=match.group("command").strip(),
                cpu_percent=float(match.group("cpu")),
            )
            for match in PROCESS_RE.finditer(summary_value)
            if match.group("command").strip()
        )
        if items:
            return ProcessesContext(items=items)
    return None


def _build_logs_context(freshness: ObservationFreshness | None) -> LogContext | None:
    if freshness is None:
        return None
    unit = _non_empty(freshness.value.get("unit"))
    returned_lines = _as_int(freshness.value.get("returned_lines"))
    if unit is None and returned_lines is None:
        return None
    return LogContext(unit=unit, returned_lines=returned_lines, stale=freshness.stale)


def _build_failed_services_context(
    freshness: ObservationFreshness | None,
) -> FailedServicesContext | None:
    if freshness is None:
        return None
    scope = _valid_scope(freshness.value.get("scope"))
    units_value = freshness.value.get("units")
    items: list[FailedServiceEntryContext] = []
    seen_units: set[str] = set()
    if isinstance(units_value, list):
        for raw_item in units_value[:5]:
            if not isinstance(raw_item, dict):
                continue
            unit = _non_empty(raw_item.get("unit"))
            if unit is None or unit in seen_units:
                continue
            seen_units.add(unit)
            items.append(
                FailedServiceEntryContext(
                    unit=unit,
                    active_state=_non_empty(raw_item.get("active_state")),
                    sub_state=_non_empty(raw_item.get("sub_state")),
                    description=_non_empty(raw_item.get("description")),
                )
            )
    if scope is None and not items:
        return None
    return FailedServicesContext(scope=scope, items=tuple(items), stale=freshness.stale)


def _build_config_context(
    summary: dict[str, str],
    freshness: ObservationFreshness | None,
) -> ConfigContext | None:
    if freshness is not None:
        path = _non_empty(freshness.value.get("path"))
        target = _non_empty(freshness.value.get("target"))
        validation_kind = None
        validation = freshness.value.get("validation")
        if isinstance(validation, dict):
            validation_kind = _non_empty(validation.get("kind"))
        backup_path = _non_empty(freshness.value.get("backup_path"))
        rollback_backup_path = _non_empty(freshness.value.get("rollback_backup_path"))
        restored_from = _non_empty(freshness.value.get("restored_from"))
        resolved_backup_path = rollback_backup_path or backup_path or restored_from
        if (
            path is not None
            or target is not None
            or validation_kind is not None
            or resolved_backup_path is not None
        ):
            return ConfigContext(
                path=path,
                target=target,
                validation_kind=validation_kind,
                backup_path=resolved_backup_path,
                stale=freshness.stale,
            )

    path = _non_empty(summary.get("tracked_path"))
    target = _non_empty(summary.get("config_target"))
    validation_kind = _non_empty(summary.get("config_validation"))
    backup_path = _non_empty(summary.get("last_backup_path"))
    if path is None and target is None and validation_kind is None and backup_path is None:
        return None
    return ConfigContext(
        path=path,
        target=target,
        validation_kind=validation_kind,
        backup_path=backup_path,
    )


def _build_process_unit_context(
    freshness: ObservationFreshness | None,
) -> ProcessUnitContext | None:
    if freshness is None:
        return None
    primary_match = freshness.value.get("primary_match")
    query = freshness.value.get("query")
    query_name = None
    query_pid = None
    if isinstance(query, dict):
        query_name = _non_empty(query.get("name"))
        query_pid = _as_int(query.get("pid"))
    resolved_count = _as_int(freshness.value.get("resolved_count"))
    if not isinstance(primary_match, dict):
        if query_name is None and query_pid is None:
            return None
        return ProcessUnitContext(
            query_name=query_name,
            pid=query_pid,
            attempted=True,
            no_match=resolved_count == 0,
            stale=freshness.stale,
        )
    unit = _non_empty(primary_match.get("unit"))
    scope = _valid_scope(primary_match.get("scope"))
    pid = _as_int(primary_match.get("pid")) or query_pid
    if unit is None and pid is None and query_name is None:
        return None
    return ProcessUnitContext(
        query_name=query_name,
        pid=pid,
        unit=unit,
        scope=scope,
        attempted=True,
        no_match=unit is None and resolved_count == 0,
        stale=freshness.stale,
    )


def _extract_process_items(value: object) -> tuple[ProcessEntryContext, ...]:
    if not isinstance(value, list):
        return ()
    items_by_command: dict[str, ProcessEntryContext] = {}
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        command = _non_empty(item.get("command"))
        if command is None:
            continue
        next_entry = ProcessEntryContext(
            command=command,
            cpu_percent=_as_float(item.get("cpu_percent")),
        )
        existing = items_by_command.get(command)
        if existing is None:
            items_by_command[command] = next_entry
            continue
        existing_cpu = existing.cpu_percent
        next_cpu = next_entry.cpu_percent
        if existing_cpu is None or (next_cpu is not None and next_cpu > existing_cpu):
            items_by_command[command] = next_entry
    return tuple(items_by_command.values())


def _extract_path_from_freshness(freshness: ObservationFreshness | None) -> str | None:
    if freshness is None:
        return None
    return _non_empty(freshness.value.get("path"))


def _non_empty(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def _valid_scope(value: object) -> str | None:
    if value in {"system", "user"}:
        return str(value)
    return None


def _as_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None
