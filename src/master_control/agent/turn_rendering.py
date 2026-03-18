from __future__ import annotations

import json
from typing import cast

from master_control.agent.planner import PlanningDecision
from master_control.agent.recommendation_sync import RecommendationSyncResult
from master_control.providers.base import ProviderResponse


def render_chat_response(
    provider_response: ProviderResponse,
    executions: list[dict[str, object]],
) -> str:
    sections = [provider_response.message]
    rendered_results = collect_rendered_execution_summaries(executions)
    if rendered_results:
        sections.extend(rendered_results)
    return "\n\n".join(sections)


def apply_turn_decision_guidance(
    message: str,
    executions: list[dict[str, object]],
    turn_decision: PlanningDecision,
) -> str:
    if turn_decision.state == "blocked" and turn_decision.kind == "awaiting_confirmation":
        pending_execution = next(
            (execution for execution in executions if execution.get("pending_confirmation")),
            None,
        )
        if isinstance(pending_execution, dict):
            approval = pending_execution.get("approval")
            if isinstance(approval, dict):
                cli_command = approval.get("cli_command")
                chat_command = approval.get("chat_command")
                summary = approval.get("summary")
                if (
                    isinstance(cli_command, str) and cli_command and cli_command in message
                ) or (
                    isinstance(chat_command, str) and chat_command and chat_command in message
                ):
                    if isinstance(summary, str) and summary.strip():
                        return (
                            f"{message}\n\nAção pendente de confirmação explícita. "
                            f"{summary.strip()}"
                        )
                    return f"{message}\n\nAção pendente de confirmação explícita."
                command_parts: list[str] = []
                if isinstance(cli_command, str) and cli_command.strip():
                    command_parts.append(f"CLI: `{cli_command}`")
                if isinstance(chat_command, str) and chat_command.strip():
                    command_parts.append(f"Chat: `{chat_command}`")
                if command_parts:
                    prefix = "Ação pendente de confirmação explícita."
                    if isinstance(summary, str) and summary.strip():
                        prefix = f"{prefix} {summary.strip()}"
                    return (
                        f"{message}\n\n{prefix} "
                        + " ".join(command_parts)
                    )
        return f"{message}\n\nAção pendente de confirmação explícita."

    if turn_decision.state == "blocked" and turn_decision.kind == "missing_safe_tool":
        return (
            f"{message}\n\nEste runtime não expõe a tool segura necessária para esse pedido. "
            "Use `mc tools` para conferir as capabilities disponíveis."
        )

    if turn_decision.state == "blocked" and turn_decision.kind == "execution_failed":
        return (
            f"{message}\n\nO turno foi interrompido porque uma execução falhou antes da conclusão."
        )

    if turn_decision.state == "needs_tools" and turn_decision.kind == "refresh_required":
        return f"{message}\n\nO agente ainda precisa atualizar sinais do host antes de concluir."

    return message


def collect_rendered_execution_summaries(
    executions: list[dict[str, object]],
) -> list[str]:
    rendered_results = [render_execution_summary(execution) for execution in executions]
    return [item for item in rendered_results if item]


def append_recommendations_to_message(
    message: str,
    sync: RecommendationSyncResult,
) -> str:
    highlighted = [*sync.new, *sync.reopened]
    if not highlighted:
        return message

    lines: list[str] = []
    for item in highlighted[:2]:
        line = f"- [#{item['id']} {item['status']}] {item['message']}"
        evidence = item.get("evidence_summary")
        if isinstance(evidence, str) and evidence.strip():
            line += f" Evidência: {evidence.strip()}."
        action_summary = item.get("action_summary")
        if isinstance(action_summary, str) and action_summary.strip():
            line += f" Ação sugerida: {action_summary.strip()}"
        next_step = item.get("next_step")
        if isinstance(next_step, dict):
            cli_command = next_step.get("cli_command")
            if isinstance(cli_command, str) and cli_command.strip():
                line += f" Próximo passo: `{cli_command.strip()}`"
        lines.append(line)
    rendered = "\n".join(lines)
    return f"{message}\n\nRecomendações da sessão:\n{rendered}"


def render_execution_summary(execution: dict[str, object]) -> str:
    arguments = _coerce_mapping(execution.get("arguments"))
    if not execution.get("ok"):
        if execution.get("pending_confirmation"):
            approval = execution.get("approval")
            if isinstance(approval, dict):
                cli_command = approval.get("cli_command")
                chat_command = approval.get("chat_command")
                summary = approval.get("summary")
                prefix = (
                    summary.strip()
                    if isinstance(summary, str) and summary.strip()
                    else f"A execução de `{execution['tool']}` exige confirmação explícita antes de prosseguir."
                )
                return (
                    f"{prefix} "
                    f"CLI: `{cli_command}`. Chat: `{chat_command}`."
                )
            return f"A execução de `{execution['tool']}` exige confirmação explícita antes de prosseguir."
        return f"Falha em `{execution['tool']}`: {execution.get('error', 'erro desconhecido')}."

    tool_name = str(execution["tool"])
    result = execution["result"]
    assert isinstance(result, dict)

    if tool_name == "system_info":
        return (
            "Host: {hostname}. Kernel: {kernel}. Plataforma: {platform}. Usuário atual: {user}."
        ).format(
            hostname=result["hostname"],
            kernel=result["kernel"],
            platform=result["platform"],
            user=result["user"],
        )

    if tool_name == "disk_usage":
        return (
            "Disco em {path}: {used_percent}% usado ({used} usados de {total}, {free} livres)."
        ).format(
            path=result["path"],
            used_percent=result["used_percent"],
            used=_human_bytes(int(result["used_bytes"])),
            total=_human_bytes(int(result["total_bytes"])),
            free=_human_bytes(int(result["free_bytes"])),
        )

    if tool_name == "memory_usage":
        return (
            "Memória usada: {mem_percent}% ({mem_used} de {mem_total}). "
            "Swap usada: {swap_percent}% ({swap_used} de {swap_total})."
        ).format(
            mem_percent=result["memory_used_percent"],
            mem_used=_human_bytes(int(result["memory_used_bytes"])),
            mem_total=_human_bytes(int(result["memory_total_bytes"])),
            swap_percent=result["swap_used_percent"],
            swap_used=_human_bytes(int(result["swap_used_bytes"])),
            swap_total=_human_bytes(int(result["swap_total_bytes"])),
        )

    if tool_name == "top_processes":
        if result.get("status") != "ok":
            return (
                "Nao foi possivel coletar os processos no momento: "
                f"{result.get('reason', 'motivo desconhecido')}."
            )
        processes = result.get("processes", [])
        if not processes:
            return "Nenhum processo relevante foi retornado."
        assert isinstance(processes, list)
        summary = ", ".join(
            f"{item['command']} ({item['cpu_percent']}% CPU)"
            for item in processes[: min(5, len(processes))]
        )
        return f"Top processos por CPU: {summary}."

    if tool_name == "process_to_unit":
        if result.get("status") != "ok":
            return (
                "Nao foi possivel correlacionar o processo com systemd no momento: "
                f"{result.get('reason', 'motivo desconhecido')}."
            )
        primary_match = result.get("primary_match")
        if isinstance(primary_match, dict):
            unit = primary_match.get("unit")
            command = primary_match.get("command")
            scope = primary_match.get("scope")
            if isinstance(unit, str) and unit:
                scope_text = f" ({scope})" if isinstance(scope, str) and scope else ""
                return (
                    f"O processo `{command}` foi correlacionado com `{unit}`{scope_text}."
                )
        query = result.get("query")
        if isinstance(query, dict):
            query_name = query.get("name")
            pid = query.get("pid")
            if isinstance(query_name, str) and query_name:
                return f"Nao encontrei um unit systemd claro para o processo `{query_name}`."
            if isinstance(pid, int):
                return f"Nao encontrei um unit systemd claro para `pid={pid}`."
        return "Nao encontrei um unit systemd claro para o processo inspecionado."

    if tool_name == "service_status":
        if result.get("status") != "ok":
            service = result.get("service", arguments.get("name", "serviço"))
            scope = result.get("scope")
            scope_text = f" ({scope})" if isinstance(scope, str) and scope else ""
            return (
                f"Nao foi possivel consultar o serviço{scope_text} `{service}`: "
                f"{result.get('reason', 'motivo desconhecido')}."
            )
        active = result.get("activestate", "desconhecido")
        sub = result.get("substate", "desconhecido")
        unit_file_state = result.get("unitfilestate", "desconhecido")
        service = result.get("service", arguments.get("name", "serviço"))
        scope = result.get("scope")
        scope_text = f" ({scope})" if isinstance(scope, str) and scope else ""
        return (
            f"Serviço{scope_text} `{service}`: active={active}, sub={sub}, "
            f"unit_file_state={unit_file_state}."
        )

    if tool_name == "read_journal":
        if result.get("status") != "ok":
            return (
                "Nao foi possivel ler o journal no momento: "
                f"{result.get('reason', 'motivo desconhecido')}."
            )
        entries = result.get("entries", [])
        if not entries:
            return "Nenhuma entrada de journal foi retornada."
        assert isinstance(entries, list)
        selected = entries[-min(5, len(entries)) :]
        rendered_entries = "\n".join(f"- {entry}" for entry in selected)
        return f"Entradas recentes do journal:\n{rendered_entries}"

    if tool_name == "failed_services":
        if result.get("status") != "ok":
            scope = result.get("scope")
            scope_text = f" ({scope})" if isinstance(scope, str) and scope else ""
            return (
                f"Nao foi possivel listar serviços com falha{scope_text}: "
                f"{result.get('reason', 'motivo desconhecido')}."
            )
        scope = result.get("scope")
        scope_text = f" ({scope})" if isinstance(scope, str) and scope else ""
        units = result.get("units")
        if not isinstance(units, list) or not units:
            return f"Nenhum serviço em falha foi encontrado{scope_text}."
        summary = ", ".join(
            f"{item['unit']}({item['active_state']}/{item['sub_state']})"
            for item in units[: min(5, len(units))]
            if isinstance(item, dict)
            and isinstance(item.get("unit"), str)
            and isinstance(item.get("active_state"), str)
            and isinstance(item.get("sub_state"), str)
        )
        return f"Serviços em falha{scope_text}: {summary}."

    if tool_name == "read_config_file":
        path = result.get("path", arguments.get("path", "arquivo"))
        line_count = result.get("line_count", 0)
        return f"Arquivo `{path}` lido com sucesso ({line_count} linhas)."

    if tool_name == "write_config_file":
        path = result.get("path", arguments.get("path", "arquivo"))
        backup_path = result.get("backup_path")
        changed = result.get("changed", False)
        if not changed:
            return f"Arquivo `{path}` já estava no conteúdo desejado."
        if backup_path:
            return f"Arquivo `{path}` atualizado com backup em `{backup_path}`."
        return f"Arquivo `{path}` criado e validado."

    if tool_name == "restore_config_backup":
        path = result.get("path", arguments.get("path", "arquivo"))
        restored_from = result.get("restored_from")
        return f"Arquivo `{path}` restaurado a partir de `{restored_from}`."

    if tool_name == "restart_service":
        service = result.get("service", arguments.get("name", "serviço"))
        scope = result.get("scope")
        scope_text = f" ({scope})" if isinstance(scope, str) and scope else ""
        post_restart = result.get("post_restart")
        if not isinstance(post_restart, dict):
            return f"Serviço{scope_text} `{service}` reiniciado."
        active = post_restart.get("activestate", "desconhecido")
        sub = post_restart.get("substate", "desconhecido")
        return (
            f"Serviço{scope_text} `{service}` reiniciado. "
            f"Estado atual: active={active}, sub={sub}."
        )

    if tool_name == "reload_service":
        service = result.get("service", arguments.get("name", "serviço"))
        scope = result.get("scope")
        scope_text = f" ({scope})" if isinstance(scope, str) and scope else ""
        post_reload = result.get("post_reload")
        if not isinstance(post_reload, dict):
            return f"Serviço{scope_text} `{service}` recarregado."
        active = post_reload.get("activestate", "desconhecido")
        sub = post_reload.get("substate", "desconhecido")
        return (
            f"Serviço{scope_text} `{service}` recarregado. "
            f"Estado atual: active={active}, sub={sub}."
        )

    return json.dumps(result, indent=2, sort_keys=True)


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


def _coerce_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return {}
