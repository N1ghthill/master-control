from __future__ import annotations

import json
from dataclasses import dataclass, field

MAX_CONFIG_EXCERPT_CHARS = 240
MAX_CONFIG_EXCERPT_LINES = 6


@dataclass(frozen=True, slots=True)
class ToolResultView:
    planner_summary: str
    rendered_summary: str
    summary_updates: dict[str, str] = field(default_factory=dict)


def build_tool_result_view(
    tool_name: str,
    arguments: dict[str, object],
    result: dict[str, object],
) -> ToolResultView:
    argument_text = json.dumps(arguments, sort_keys=True)

    if tool_name == "system_info":
        hostname = _string_or_none(result.get("hostname"), default="desconhecido")
        kernel = _string_or_none(result.get("kernel"), default="desconhecido")
        platform = _string_or_none(result.get("platform"), default="desconhecida")
        user = _string_or_none(result.get("user"), default="desconhecido")
        return ToolResultView(
            planner_summary=f"{tool_name}({argument_text}) -> hostname={hostname}, kernel={kernel}",
            rendered_summary=(
                "Host: {hostname}. Kernel: {kernel}. Plataforma: {platform}. Usuário atual: {user}."
            ).format(
                hostname=hostname,
                kernel=kernel,
                platform=platform,
                user=user,
            ),
            summary_updates={"host": f"{hostname}, kernel {kernel}"},
        )

    if tool_name == "disk_usage":
        path = _string_or_default(result.get("path"), "/")
        used_percent = result.get("used_percent")
        rendered_summary = (
            "Disco em {path}: {used_percent}% usado ({used} usados de {total}, {free} livres)."
        ).format(
            path=path,
            used_percent=used_percent,
            used=_human_bytes(_coerce_int(result.get("used_bytes"))),
            total=_human_bytes(_coerce_int(result.get("total_bytes"))),
            free=_human_bytes(_coerce_int(result.get("free_bytes"))),
        )
        summary_updates = {"tracked_path": path}
        if used_percent is not None:
            summary_updates["disk"] = f"{path} is {used_percent}% used"
        return ToolResultView(
            planner_summary=f"{tool_name}({argument_text}) -> used={used_percent}%",
            rendered_summary=rendered_summary,
            summary_updates=summary_updates,
        )

    if tool_name == "memory_usage":
        memory_used_percent = result.get("memory_used_percent")
        swap_used_percent = result.get("swap_used_percent")
        summary_updates = {}
        if memory_used_percent is not None and swap_used_percent is not None:
            summary_updates["memory"] = (
                f"memory {memory_used_percent}% used, swap {swap_used_percent}% used"
            )
        return ToolResultView(
            planner_summary=(
                f"{tool_name}({argument_text}) -> memory={memory_used_percent}%, "
                f"swap={swap_used_percent}%"
            ),
            rendered_summary=(
                "Memória usada: {mem_percent}% ({mem_used} de {mem_total}). "
                "Swap usada: {swap_percent}% ({swap_used} de {swap_total})."
            ).format(
                mem_percent=memory_used_percent,
                mem_used=_human_bytes(_coerce_int(result.get("memory_used_bytes"))),
                mem_total=_human_bytes(_coerce_int(result.get("memory_total_bytes"))),
                swap_percent=swap_used_percent,
                swap_used=_human_bytes(_coerce_int(result.get("swap_used_bytes"))),
                swap_total=_human_bytes(_coerce_int(result.get("swap_total_bytes"))),
            ),
            summary_updates=summary_updates,
        )

    if tool_name == "top_processes":
        status = _string_or_default(result.get("status"), "ok")
        if status != "ok":
            reason = _string_or_none(result.get("reason"), default="motivo desconhecido")
            return ToolResultView(
                planner_summary=_planner_status_summary(
                    tool_name,
                    argument_text,
                    status=status,
                    reason=reason,
                ),
                rendered_summary=(
                    "Nao foi possivel coletar os processos no momento: "
                    f"{reason}."
                ),
            )

        processes = _group_process_rows(result.get("processes"), limit=5)
        if not processes:
            return ToolResultView(
                planner_summary=f"{tool_name}({argument_text}) -> no_processes",
                rendered_summary="Nenhum processo relevante foi retornado.",
            )
        items = []
        commands: list[str] = []
        for item in processes[:3]:
            command = item.get("command")
            cpu = item.get("cpu_percent")
            if isinstance(command, str):
                items.append(f"{command}({cpu}%)")
                commands.append(f"{command}({cpu}%)")
        planner_summary = f"{tool_name}({argument_text}) -> {', '.join(items)}"
        rendered_summary = "Top processos por CPU: {}.".format(
            ", ".join(
                _render_grouped_process(item)
                for item in processes[: min(5, len(processes))]
                if isinstance(item, dict)
                and isinstance(item.get("command"), str)
                and item.get("cpu_percent") is not None
            )
        )
        summary_updates = {"processes": ", ".join(commands)} if commands else {}
        return ToolResultView(
            planner_summary=planner_summary,
            rendered_summary=rendered_summary,
            summary_updates=summary_updates,
        )

    if tool_name == "process_to_unit":
        status = _string_or_default(result.get("status"), "ok")
        if status != "ok":
            reason = _string_or_none(result.get("reason"), default="motivo desconhecido")
            return ToolResultView(
                planner_summary=_planner_status_summary(
                    tool_name,
                    argument_text,
                    status=status,
                    reason=reason,
                ),
                rendered_summary=(
                    "Nao foi possivel correlacionar o processo com systemd no momento: "
                    f"{reason}."
                ),
            )

        primary_match = result.get("primary_match")
        summary_updates = {}
        if isinstance(primary_match, dict):
            unit = _string_or_none(primary_match.get("unit"))
            command = _string_or_none(primary_match.get("command"), default="processo")
            scope = _string_or_none(primary_match.get("scope"))
            if unit:
                scope_text = f" ({scope})" if scope else ""
                if unit:
                    summary_updates["tracked_unit"] = unit
                if scope:
                    summary_updates["tracked_scope"] = scope
                return ToolResultView(
                    planner_summary=(
                        f"{tool_name}({argument_text}) -> unit={unit}, scope={scope or '-'}"
                    ),
                    rendered_summary=(
                        f"O processo `{command}` foi correlacionado com `{unit}`{scope_text}."
                    ),
                    summary_updates=summary_updates,
                )

        query = result.get("query")
        if isinstance(query, dict):
            query_name = query.get("name")
            pid = query.get("pid")
            if isinstance(query_name, str) and query_name:
                return ToolResultView(
                    planner_summary=f"{tool_name}({argument_text}) -> no_unit_match",
                    rendered_summary=(
                        f"Nao encontrei um unit systemd claro para o processo `{query_name}`."
                    ),
                )
            if isinstance(pid, int):
                return ToolResultView(
                    planner_summary=f"{tool_name}({argument_text}) -> no_unit_match",
                    rendered_summary=f"Nao encontrei um unit systemd claro para `pid={pid}`.",
                )
        return ToolResultView(
            planner_summary=f"{tool_name}({argument_text}) -> no_unit_match",
            rendered_summary="Nao encontrei um unit systemd claro para o processo inspecionado.",
            )

    if tool_name == "service_status":
        status = _string_or_default(result.get("status"), "ok")
        if status != "ok":
            service = _string_or_default(
                result.get("service"),
                _argument_string(arguments, "name", "serviço"),
            )
            scope = _string_or_none(result.get("scope"))
            reason = _string_or_none(result.get("reason"), default="motivo desconhecido")
            scope_text = f" ({scope})" if scope else ""
            return ToolResultView(
                planner_summary=_planner_status_summary(
                    tool_name,
                    argument_text,
                    status=status,
                    reason=reason,
                ),
                rendered_summary=(
                    f"Nao foi possivel consultar o serviço{scope_text} `{service}`: {reason}."
                ),
            )

        service = _string_or_default(
            result.get("service"),
            _argument_string(arguments, "name", "serviço"),
        )
        scope = _string_or_none(result.get("scope"))
        active = _string_or_none(result.get("activestate"), default="desconhecido")
        sub = _string_or_none(result.get("substate"), default="desconhecido")
        unit_file_state = _string_or_none(result.get("unitfilestate"), default="desconhecido")
        scope_text = f" ({scope})" if scope else ""
        summary_updates = {"tracked_unit": service}
        if scope:
            summary_updates["tracked_scope"] = scope
        if service and active and sub:
            summary_updates["service"] = f"{service}: active={active}, sub={sub}"
        return ToolResultView(
            planner_summary=(
                f"{tool_name}({argument_text}) -> active={active}, sub={sub}, scope={scope or '-'}"
            ),
            rendered_summary=(
                f"Serviço{scope_text} `{service}`: active={active}, sub={sub}, "
                f"unit_file_state={unit_file_state}."
            ),
            summary_updates=summary_updates,
        )

    if tool_name == "read_journal":
        status = _string_or_default(result.get("status"), "ok")
        if status != "ok":
            reason = _string_or_none(result.get("reason"), default="motivo desconhecido")
            return ToolResultView(
                planner_summary=_planner_status_summary(
                    tool_name,
                    argument_text,
                    status=status,
                    reason=reason,
                ),
                rendered_summary=f"Nao foi possivel ler o journal no momento: {reason}.",
            )

        entries = result.get("entries", [])
        unit = _string_or_none(result.get("unit"))
        returned_lines = result.get("returned_lines")
        summary_updates = {}
        tracked_unit = unit or "system"
        summary_updates["tracked_unit"] = tracked_unit
        if returned_lines is not None:
            summary_updates["logs"] = f"{tracked_unit}: last journal read returned {returned_lines} lines"
        if not isinstance(entries, list) or not entries:
            return ToolResultView(
                planner_summary=(
                    f"{tool_name}({argument_text}) -> lines={returned_lines or 0}, unit={unit or 'system'}"
                ),
                rendered_summary="Nenhuma entrada de journal foi retornada.",
                summary_updates=summary_updates,
            )
        selected = entries[-min(5, len(entries)) :]
        rendered_entries = "\n".join(f"- {entry}" for entry in selected)
        return ToolResultView(
            planner_summary=(
                f"{tool_name}({argument_text}) -> lines={returned_lines or len(entries)}, unit={unit or 'system'}"
            ),
            rendered_summary=f"Entradas recentes do journal:\n{rendered_entries}",
            summary_updates=summary_updates,
        )

    if tool_name == "failed_services":
        status = _string_or_default(result.get("status"), "ok")
        scope = _string_or_none(result.get("scope"))
        if status != "ok":
            reason = _string_or_none(result.get("reason"), default="motivo desconhecido")
            scope_text = f" ({scope})" if scope else ""
            return ToolResultView(
                planner_summary=_planner_status_summary(
                    tool_name,
                    argument_text,
                    status=status,
                    reason=reason,
                ),
                rendered_summary=f"Nao foi possivel listar serviços com falha{scope_text}: {reason}.",
            )

        units = result.get("units")
        if not isinstance(units, list) or not units:
            return ToolResultView(
                planner_summary=(
                    f"{tool_name}({argument_text}) -> count={result.get('unit_count', 0)}, scope={scope or '-'}"
                ),
                rendered_summary=f"Nenhum serviço em falha foi encontrado{f' ({scope})' if scope else ''}.",
            )

        summary_updates = {}
        if len(units) == 1 and isinstance(units[0], dict):
            unit = _string_or_none(units[0].get("unit"))
            active_state = _string_or_none(units[0].get("active_state"))
            sub_state = _string_or_none(units[0].get("sub_state"))
            if unit:
                summary_updates["tracked_unit"] = unit
            if scope:
                summary_updates["tracked_scope"] = scope
            if unit and active_state and sub_state:
                summary_updates["service"] = f"{unit}: active={active_state}, sub={sub_state}"

        summary = ", ".join(
            f"{item['unit']}({item['active_state']}/{item['sub_state']})"
            for item in units[: min(5, len(units))]
            if isinstance(item, dict)
            and isinstance(item.get("unit"), str)
            and isinstance(item.get("active_state"), str)
            and isinstance(item.get("sub_state"), str)
        )
        return ToolResultView(
            planner_summary=(
                f"{tool_name}({argument_text}) -> count={result.get('unit_count', len(units))}, scope={scope or '-'}"
            ),
            rendered_summary=f"Serviços em falha{f' ({scope})' if scope else ''}: {summary}.",
            summary_updates=summary_updates,
        )

    if tool_name == "read_config_file":
        path = _string_or_default(result.get("path"), _argument_string(arguments, "path", "arquivo"))
        line_count = _coerce_int(result.get("line_count"))
        target = _string_or_default(result.get("target"), "managed")
        content = _string_or_none(result.get("content"))
        excerpt = _build_config_excerpt(content)
        planner_parts = [f"path={path}", f"target={target}", f"lines={line_count}"]
        if excerpt:
            planner_parts.append(f"excerpt={excerpt!r}")
        rendered_summary = f"Arquivo `{path}` lido com sucesso ({line_count} linhas)."
        if excerpt:
            rendered_summary = f"{rendered_summary} Trecho: {excerpt}"
        return ToolResultView(
            planner_summary=f"{tool_name}({argument_text}) -> {', '.join(planner_parts)}",
            rendered_summary=rendered_summary,
            summary_updates={
                "tracked_path": path,
                "config": f"{tool_name}: {path}",
                "config_target": target,
            },
        )

    if tool_name == "write_config_file":
        path = _string_or_default(result.get("path"), _argument_string(arguments, "path", "arquivo"))
        backup_path = _string_or_none(result.get("backup_path"))
        changed = bool(result.get("changed", False))
        validation = result.get("validation")
        validation_kind = _string_or_none(validation.get("kind")) if isinstance(validation, dict) else None
        planner_summary = (
            f"{tool_name}({argument_text}) -> path={path}, changed={str(changed).lower()}"
        )
        if validation_kind:
            planner_summary += f", validation={validation_kind}"
        if not changed:
            rendered_summary = f"Arquivo `{path}` já estava no conteúdo desejado."
        elif backup_path:
            rendered_summary = f"Arquivo `{path}` atualizado com backup em `{backup_path}`."
        else:
            rendered_summary = f"Arquivo `{path}` criado e validado."
        summary_updates = {
            "tracked_path": path,
            "config": f"{tool_name}: {path}",
            "config_target": _string_or_default(result.get("target"), "managed"),
        }
        if validation_kind:
            summary_updates["config_validation"] = validation_kind
        if backup_path:
            summary_updates["last_backup_path"] = backup_path
        return ToolResultView(
            planner_summary=planner_summary,
            rendered_summary=rendered_summary,
            summary_updates=summary_updates,
        )

    if tool_name == "restore_config_backup":
        path = _string_or_default(result.get("path"), _argument_string(arguments, "path", "arquivo"))
        restored_from = _string_or_none(result.get("restored_from"), default="backup desconhecido")
        config_target = _string_or_none(result.get("target"))
        rollback_backup_path = _string_or_none(result.get("rollback_backup_path"))
        validation = result.get("validation")
        validation_kind = _string_or_none(validation.get("kind")) if isinstance(validation, dict) else None
        rendered_summary = f"Arquivo `{path}` restaurado a partir de `{restored_from}`."
        if rollback_backup_path:
            rendered_summary = (
                f"{rendered_summary} Backup de rollback atual em `{rollback_backup_path}`."
            )
        summary_updates = {
            "tracked_path": path,
            "config": f"{tool_name}: {path}",
        }
        if config_target:
            summary_updates["config_target"] = config_target
        if validation_kind:
            summary_updates["config_validation"] = validation_kind
        if rollback_backup_path:
            summary_updates["last_backup_path"] = rollback_backup_path
        return ToolResultView(
            planner_summary=f"{tool_name}({argument_text}) -> path={path}, restored_from={restored_from}",
            rendered_summary=rendered_summary,
            summary_updates=summary_updates,
        )

    if tool_name == "restart_service":
        service = _string_or_default(
            result.get("service"),
            _argument_string(arguments, "name", "serviço"),
        )
        scope = _string_or_none(result.get("scope"))
        post_restart = result.get("post_restart")
        summary_updates = {"tracked_unit": service}
        if scope:
            summary_updates["tracked_scope"] = scope
        if not isinstance(post_restart, dict):
            return ToolResultView(
                planner_summary=f"{tool_name}({argument_text}) -> ok",
                rendered_summary=f"Serviço{f' ({scope})' if scope else ''} `{service}` reiniciado.",
                summary_updates=summary_updates,
            )
        active = _string_or_none(post_restart.get("activestate"), default="desconhecido")
        sub = _string_or_none(post_restart.get("substate"), default="desconhecido")
        summary_updates["service"] = f"{service}: active={active}, sub={sub}"
        return ToolResultView(
            planner_summary=(
                f"{tool_name}({argument_text}) -> post active={active}, sub={sub}, scope={scope or '-'}"
            ),
            rendered_summary=(
                f"Serviço{f' ({scope})' if scope else ''} `{service}` reiniciado. "
                f"Estado atual: active={active}, sub={sub}."
            ),
            summary_updates=summary_updates,
        )

    if tool_name == "reload_service":
        service = _string_or_default(
            result.get("service"),
            _argument_string(arguments, "name", "serviço"),
        )
        scope = _string_or_none(result.get("scope"))
        post_reload = result.get("post_reload")
        summary_updates = {"tracked_unit": service}
        if scope:
            summary_updates["tracked_scope"] = scope
        if not isinstance(post_reload, dict):
            return ToolResultView(
                planner_summary=f"{tool_name}({argument_text}) -> ok",
                rendered_summary=f"Serviço{f' ({scope})' if scope else ''} `{service}` recarregado.",
                summary_updates=summary_updates,
            )
        active = _string_or_none(post_reload.get("activestate"), default="desconhecido")
        sub = _string_or_none(post_reload.get("substate"), default="desconhecido")
        summary_updates["service"] = f"{service}: active={active}, sub={sub}"
        return ToolResultView(
            planner_summary=(
                f"{tool_name}({argument_text}) -> post active={active}, sub={sub}, scope={scope or '-'}"
            ),
            rendered_summary=(
                f"Serviço{f' ({scope})' if scope else ''} `{service}` recarregado. "
                f"Estado atual: active={active}, sub={sub}."
            ),
            summary_updates=summary_updates,
        )

    return ToolResultView(
        planner_summary=f"{tool_name}({argument_text}) -> ok",
        rendered_summary=json.dumps(result, indent=2, sort_keys=True),
    )


def _planner_status_summary(
    tool_name: str,
    argument_text: str,
    *,
    status: str,
    reason: str | None = None,
) -> str:
    summary = f"{tool_name}({argument_text}) -> status={status}"
    if reason:
        summary += f", reason={reason}"
    return summary


def _string_or_none(value: object, *, default: str | None = None) -> str | None:
    if isinstance(value, str) and value:
        return value
    return default


def _string_or_default(value: object, default: str) -> str:
    resolved = _string_or_none(value)
    return resolved if resolved is not None else default


def _argument_string(arguments: dict[str, object], key: str, default: str) -> str:
    value = arguments.get(key)
    return _string_or_default(value, default)


def _coerce_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _group_process_rows(value: object, *, limit: int) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows_by_command: dict[str, dict[str, object]] = {}
    ordered_commands: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        command = _string_or_none(item.get("command"))
        if command is None:
            continue
        existing = rows_by_command.get(command)
        if existing is None:
            if len(ordered_commands) >= limit:
                continue
            grouped_item = dict(item)
            grouped_item["occurrences"] = 1
            rows_by_command[command] = grouped_item
            ordered_commands.append(command)
            continue
        existing["occurrences"] = _coerce_int(existing.get("occurrences"), default=1) + 1
        existing_cpu = existing.get("cpu_percent")
        next_cpu = item.get("cpu_percent")
        if isinstance(existing_cpu, (int, float)) and isinstance(next_cpu, (int, float)):
            if next_cpu > existing_cpu:
                existing["cpu_percent"] = next_cpu
        elif isinstance(next_cpu, (int, float)):
            existing["cpu_percent"] = next_cpu
    return [rows_by_command[command] for command in ordered_commands[:limit]]


def _render_grouped_process(item: dict[str, object]) -> str:
    command = _string_or_default(item.get("command"), "processo")
    cpu_percent = item.get("cpu_percent")
    occurrences = _coerce_int(item.get("occurrences"), default=1)
    repeated_text = f" x{occurrences}" if occurrences > 1 else ""
    return f"{command}{repeated_text} ({cpu_percent}% CPU)"


def _build_config_excerpt(content: str | None) -> str | None:
    if content is None:
        return None
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return None
    excerpt = " | ".join(lines[:MAX_CONFIG_EXCERPT_LINES])
    truncated = len(lines) > MAX_CONFIG_EXCERPT_LINES or len(excerpt) > MAX_CONFIG_EXCERPT_CHARS
    if len(excerpt) > MAX_CONFIG_EXCERPT_CHARS:
        excerpt = excerpt[: MAX_CONFIG_EXCERPT_CHARS - 3].rstrip() + "..."
        truncated = False
    if truncated:
        excerpt = f"{excerpt} ..."
    return excerpt


def _human_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TiB"
