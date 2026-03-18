from __future__ import annotations

import re
import unicodedata

from master_control.agent.observations import ObservationFreshness
from master_control.agent.planner import ExecutionPlan, PlanningDecision, PlanStep
from master_control.agent.process_leads import select_process_lead
from master_control.agent.session_context import SessionContext, build_session_context
from master_control.providers.base import ConversationMessage, ProviderRequest, ProviderResponse

SERVICE_NAME_RE = re.compile(
    r"(?:servi(?:co|ço)|service|unit|status)\s+(?:(?:do|da|de|of|for)\s+)?([A-Za-z0-9_@][A-Za-z0-9_.@-]*)",
    re.IGNORECASE,
)
JOURNAL_UNIT_RE = re.compile(
    r"(?:logs?|journal)\s+(?:(?:do|da|de|of|for)\s+)?([A-Za-z0-9_@][A-Za-z0-9_.@-]*)",
    re.IGNORECASE,
)
PROCESS_NAME_RE = re.compile(
    r"(?:processo|process)\s+(?:(?:do|da|de|of|for)\s+)?([A-Za-z0-9_.@/-]+)",
    re.IGNORECASE,
)
PID_RE = re.compile(r"\bpid\s+(\d+)\b", re.IGNORECASE)
PATH_RE = re.compile(r"(/[^\s,;:]+)")
INTEGER_RE = re.compile(r"\b(\d{1,3})\b")


class HeuristicProvider:
    name = "heuristic"

    def plan(self, request: ProviderRequest) -> ProviderResponse:
        available_tools = {spec.name for spec in request.available_tools}
        message = request.user_message.strip()
        normalized = _normalize(message)
        session_context = request.session_context or build_session_context(
            request.session_summary,
            request.observation_freshness,
        )
        last_context = _extract_context(request.conversation_history, session_context)
        service_scope = _resolve_service_scope(normalized, last_context)
        freshness_map = {item.key: item for item in request.observation_freshness}
        candidate_service = _extract_service_name(message) or _guess_service_name_from_context(
            session_context,
            last_context,
        )

        if _contains_any(normalized, ("diagnostico", "diagnosticar", "lento", "lentidao", "slow")):
            if "memory_usage" in available_tools and _needs_refresh(freshness_map, "memory"):
                message_text = "Vou começar verificando a memória do sistema."
                if "memory" in freshness_map and freshness_map["memory"].stale:
                    message_text = (
                        "Vou atualizar os dados de memória antes de continuar o diagnóstico."
                    )
                return _needs_tools_response(
                    message_text,
                    "Refreshing memory data is the next safe diagnostic step.",
                    kind="refresh_required",
                    intent="diagnose_performance",
                    steps=(
                        PlanStep(
                            tool_name="memory_usage",
                            rationale="Check memory pressure before deeper diagnosis.",
                        ),
                    ),
                )

            if "top_processes" in available_tools and _needs_refresh(freshness_map, "processes"):
                message_text = "Agora vou verificar os processos com maior uso de CPU."
                if "processes" in freshness_map and freshness_map["processes"].stale:
                    message_text = (
                        "Vou atualizar a lista de processos antes de seguir com o diagnóstico."
                    )
                return _needs_tools_response(
                    message_text,
                    "Refreshing process activity is the next safe diagnostic step.",
                    kind="refresh_required",
                    intent="diagnose_performance",
                    steps=(
                        PlanStep(
                            tool_name="top_processes",
                            rationale="Inspect the highest CPU consumers.",
                            arguments={
                                "limit": _extract_int(message, default=5, min_value=1, max_value=10)
                            },
                        ),
                    ),
                )

            process_name = _guess_process_name_from_context(session_context)
            if (
                "process_to_unit" in available_tools
                and process_name
                and candidate_service is None
                and _needs_refresh(freshness_map, "process_unit")
            ):
                message_text = (
                    f"Vou correlacionar o processo `{process_name}` com um unit do systemd."
                )
                if "process_unit" in freshness_map and freshness_map["process_unit"].stale:
                    message_text = (
                        f"Vou atualizar a correlação do processo `{process_name}` com systemd antes de concluir."
                    )
                return _needs_tools_response(
                    message_text,
                    "Correlating the hottest process with a systemd unit is the next safe diagnostic step.",
                    kind="refresh_required",
                    intent="diagnose_performance",
                    steps=(
                        PlanStep(
                            tool_name="process_to_unit",
                            rationale="Correlate the hottest observed process with a systemd unit.",
                            arguments={"name": process_name, "limit": 3},
                        ),
                    ),
                )

            if (
                "service_status" in available_tools
                and candidate_service
                and _needs_refresh(freshness_map, "service")
            ):
                message_text = (
                    f"Vou correlacionar isso com o estado do serviço `{candidate_service}`."
                )
                if "service" in freshness_map and freshness_map["service"].stale:
                    message_text = f"Vou atualizar o estado do serviço `{candidate_service}` antes de concluir."
                return _needs_tools_response(
                    message_text,
                    "Refreshing the related service state is the next safe diagnostic step.",
                    kind="refresh_required",
                    intent="diagnose_performance",
                    steps=(
                        PlanStep(
                            tool_name="service_status",
                            rationale=(
                                "Inspect the explicitly referenced or previously tracked service."
                            ),
                            arguments=_with_service_scope(
                                {"name": candidate_service}, service_scope
                            ),
                        ),
                    ),
                )

            return _complete_response(
                _build_diagnostic_summary(session_context),
                "The diagnostic summary is already sufficient.",
            )

        if _contains_any(
            normalized,
            (
                "servicos com falha",
                "serviços com falha",
                "servicos falhando",
                "serviços falhando",
                "failed services",
                "servicos failed",
                "serviços failed",
            ),
        ) and ("failed_services" in available_tools):
            return _needs_tools_response(
                "Vou listar os serviços em estado de falha.",
                "Listing failed services requires a typed tool step.",
                kind="inspection_request",
                intent="inspect_failed_services",
                steps=(
                    PlanStep(
                        tool_name="failed_services",
                        rationale="List failed systemd services for the requested scope.",
                        arguments=_with_service_scope(
                            {"limit": _extract_int(message, default=10, min_value=1, max_value=20)},
                            service_scope,
                        ),
                    ),
                ),
            )
        if _contains_any(
            normalized,
            (
                "servicos com falha",
                "serviços com falha",
                "servicos falhando",
                "serviços falhando",
                "failed services",
            ),
        ):
            return _blocked_response(
                "Entendi que você quer listar serviços com falha, mas a tool segura `failed_services` não está disponível neste runtime.",
                "The runtime does not expose failed_services for this request.",
                kind="missing_safe_tool",
            )

        if _contains_any(
            normalized,
            (
                "qual unit do processo",
                "qual unidade do processo",
                "servico relacionado ao processo",
                "serviço relacionado ao processo",
                "correlacionar processo",
                "correlacione o processo",
                "processo pertence",
            ),
        ) and ("process_to_unit" in available_tools):
            process_name = _extract_process_name(message) or _guess_process_name_from_context(
                session_context
            )
            pid = _extract_pid(message)
            if process_name or pid is not None:
                arguments: dict[str, object] = {"limit": 3}
                if pid is not None:
                    arguments["pid"] = pid
                elif process_name:
                    arguments["name"] = process_name
                return _needs_tools_response(
                    "Vou correlacionar o processo com um unit do systemd.",
                    "Correlating the process with a systemd unit requires a typed tool step.",
                    kind="inspection_request",
                    intent="inspect_process_unit",
                    steps=(
                        PlanStep(
                            tool_name="process_to_unit",
                            rationale="Correlate the requested process with a systemd unit.",
                            arguments=arguments,
                        ),
                    ),
                )
        if _contains_any(
            normalized,
            (
                "qual unit do processo",
                "qual unidade do processo",
                "servico relacionado ao processo",
                "serviço relacionado ao processo",
                "correlacionar processo",
                "correlacione o processo",
                "processo pertence",
            ),
        ):
            return _blocked_response(
                "Entendi que você quer correlacionar um processo com systemd, mas a tool segura `process_to_unit` não está disponível neste runtime.",
                "The runtime does not expose process_to_unit for this request.",
                kind="missing_safe_tool",
            )

        if _contains_any(normalized, ("visao geral", "visao do sistema", "health", "saude geral")):
            steps = []
            if "system_info" in available_tools:
                steps.append(
                    PlanStep(
                        tool_name="system_info",
                        rationale="Collect basic host metadata.",
                    )
                )
            if "disk_usage" in available_tools:
                steps.append(
                    PlanStep(
                        tool_name="disk_usage",
                        rationale="Inspect root filesystem usage.",
                        arguments={"path": "/"},
                    )
                )
            if "memory_usage" in available_tools:
                steps.append(
                    PlanStep(
                        tool_name="memory_usage",
                        rationale="Inspect memory pressure.",
                    )
                )
            if steps:
                return _needs_tools_response(
                    "Vou montar um resumo rápido do host.",
                    "Collecting baseline host signals requires tool execution.",
                    kind="diagnostic_step",
                    intent="host_overview",
                    steps=tuple(steps),
                )
            return _blocked_response(
                "Ainda não há ferramentas disponíveis para montar essa visão geral.",
                "No host overview tools are available.",
                kind="missing_safe_tool",
            )

        if (
            _contains_any(normalized, ("log", "logs", "journal"))
            and "read_journal" in available_tools
        ):
            unit = _extract_journal_unit(message) or last_context.get("unit")
            lines = _extract_int(message, default=20, min_value=1, max_value=200)
            return _needs_tools_response(
                "Vou ler as entradas recentes do journal.",
                "Reading the journal is the next safe diagnostic step.",
                kind="inspection_request",
                intent="inspect_logs",
                steps=(
                    PlanStep(
                        tool_name="read_journal",
                        rationale="Read recent journal entries for the requested scope.",
                        arguments={
                            "lines": lines,
                            **({"unit": unit} if unit else {}),
                        },
                    ),
                ),
            )
        if _contains_any(normalized, ("log", "logs", "journal")):
            return _blocked_response(
                "Entendi que você quer inspecionar logs, mas a tool segura `read_journal` não está disponível neste runtime.",
                "The runtime does not expose read_journal for this request.",
                kind="missing_safe_tool",
            )

        if _contains_any(normalized, ("recarregar", "recarregue", "reload")) and (
            "reload_service" in available_tools
        ):
            service_name = _extract_service_name(message) or _context_service_name(last_context)
            if service_name:
                return _needs_tools_response(
                    f"Posso recarregar o serviço `{service_name}` com confirmação explícita.",
                    "The requested service reload still requires a typed tool step.",
                    kind="inspection_request",
                    intent="reload_service",
                    steps=(
                        PlanStep(
                            tool_name="reload_service",
                            rationale="Reload the requested service after explicit confirmation.",
                            arguments=_with_service_scope({"name": service_name}, service_scope),
                        ),
                    ),
                )
            return _blocked_response(
                "Entendi o pedido de recarga do serviço, mas a tool segura `reload_service` não está disponível neste runtime.",
                "The runtime does not expose reload_service for this request.",
                kind="missing_safe_tool",
            )

        if _contains_any(normalized, ("reiniciar", "reinicie", "restart")) and (
            "restart_service" in available_tools
        ):
            service_name = _extract_service_name(message) or _context_service_name(last_context)
            if service_name:
                return _needs_tools_response(
                    f"Posso reiniciar o serviço `{service_name}` com confirmação explícita.",
                    "The requested service restart still requires a typed tool step.",
                    kind="inspection_request",
                    intent="restart_service",
                    steps=(
                        PlanStep(
                            tool_name="restart_service",
                            rationale="Restart the requested service after explicit confirmation.",
                            arguments=_with_service_scope({"name": service_name}, service_scope),
                        ),
                    ),
                )
            return _blocked_response(
                "Entendi o pedido de reinício do serviço, mas a tool segura `restart_service` não está disponível neste runtime.",
                "The runtime does not expose restart_service for this request.",
                kind="missing_safe_tool",
            )

        if _contains_any(normalized, ("servico", "serviço", "service", "status")) and (
            "service_status" in available_tools
        ):
            service_name = _extract_service_name(message) or _context_service_name(last_context)
            if service_name:
                return _needs_tools_response(
                    f"Vou verificar o status do serviço `{service_name}`.",
                    "Checking service state requires a typed tool step.",
                    kind="inspection_request",
                    intent="inspect_service_status",
                    steps=(
                        PlanStep(
                            tool_name="service_status",
                            rationale="Check the unit state in systemd.",
                            arguments=_with_service_scope({"name": service_name}, service_scope),
                        ),
                    ),
                )
            return _blocked_response(
                "Entendi que você quer inspecionar o serviço, mas a tool segura `service_status` não está disponível neste runtime.",
                "The runtime does not expose service_status for this request.",
                kind="missing_safe_tool",
            )

        if _looks_like_log_follow_up(normalized) and "read_journal" in available_tools:
            unit = last_context.get("unit")
            if unit:
                lines = _extract_int(message, default=20, min_value=1, max_value=200)
                return _needs_tools_response(
                    f"Vou continuar a inspeção dos logs de `{unit}`.",
                    "The follow-up log request still requires a journal read.",
                    kind="inspection_request",
                    intent="inspect_logs_follow_up",
                    steps=(
                        PlanStep(
                            tool_name="read_journal",
                            rationale="Reuse the last referenced unit from session history.",
                            arguments={
                                "unit": unit,
                                "lines": lines,
                            },
                        ),
                    ),
                )

        if _looks_like_service_follow_up(normalized) and "service_status" in available_tools:
            unit = _context_service_name(last_context)
            if unit:
                return _needs_tools_response(
                    f"Vou continuar a inspeção do serviço `{unit}`.",
                    "The follow-up service request still requires a status check.",
                    kind="inspection_request",
                    intent="inspect_service_status_follow_up",
                    steps=(
                        PlanStep(
                            tool_name="service_status",
                            rationale="Reuse the last referenced unit from session history.",
                            arguments=_with_service_scope({"name": unit}, service_scope),
                        ),
                    ),
                )

        if _contains_any(normalized, ("disco", "disk", "espaco", "espaço", "storage")) and (
            "disk_usage" in available_tools
        ):
            path = _extract_path(message) or "/"
            return _needs_tools_response(
                f"Vou verificar o uso de disco em `{path}`.",
                "Inspecting filesystem usage requires a typed disk tool.",
                kind="inspection_request",
                intent="inspect_disk_usage",
                steps=(
                    PlanStep(
                        tool_name="disk_usage",
                        rationale="Inspect filesystem utilization for the requested path.",
                        arguments={"path": path},
                    ),
                ),
            )
        if _contains_any(normalized, ("disco", "disk", "espaco", "espaço", "storage")):
            return _blocked_response(
                "Entendi que você quer inspecionar disco, mas a tool segura `disk_usage` não está disponível neste runtime.",
                "The runtime does not expose disk_usage for this request.",
                kind="missing_safe_tool",
            )

        if _looks_like_config_rollback_request(normalized) and (
            "restore_config_backup" in available_tools
        ):
            config_context = session_context.config
            if (
                config_context is not None
                and config_context.path
                and config_context.backup_path
            ):
                return _needs_tools_response(
                    f"Posso restaurar o último backup de `{config_context.path}` com confirmação explícita.",
                    "Rolling back the last managed config change requires a typed restore step.",
                    kind="inspection_request",
                    intent="restore_config_backup",
                    steps=(
                        PlanStep(
                            tool_name="restore_config_backup",
                            rationale="Restore the last tracked managed backup for this file.",
                            arguments={
                                "path": config_context.path,
                                "backup_path": config_context.backup_path,
                            },
                        ),
                    ),
                )
            return _blocked_response(
                "Ainda não encontrei um backup rastreado nesta sessão para executar esse rollback com segurança.",
                "No tracked config backup is available in the current session context.",
                kind="unsupported_request",
            )
        if _looks_like_config_rollback_request(normalized):
            return _blocked_response(
                "Entendi o pedido de rollback de configuração, mas a tool segura `restore_config_backup` não está disponível neste runtime.",
                "The runtime does not expose restore_config_backup for this request.",
                kind="missing_safe_tool",
            )

        if _contains_any(normalized, ("arquivo", "config", "configuracao", "configuração")) and (
            "read_config_file" in available_tools
        ):
            config_path = _extract_path(message) or _string_or_none(last_context.get("path"))
            if config_path:
                return _needs_tools_response(
                    f"Vou ler o arquivo gerenciado `{config_path}`.",
                    "Reading the requested managed file requires a typed tool step.",
                    kind="inspection_request",
                    intent="read_config_file",
                    steps=(
                        PlanStep(
                            tool_name="read_config_file",
                            rationale="Read the requested managed configuration file.",
                            arguments={"path": config_path},
                        ),
                    ),
                )
            return _blocked_response(
                "Entendi que você quer ler um arquivo gerenciado, mas a tool segura `read_config_file` não está disponível neste runtime.",
                "The runtime does not expose read_config_file for this request.",
                kind="missing_safe_tool",
            )

        if _contains_any(normalized, ("memoria", "memória", "ram", "swap")) and (
            "memory_usage" in available_tools
        ):
            return _needs_tools_response(
                "Vou verificar a memória do sistema.",
                "Inspecting memory usage requires a typed tool step.",
                kind="inspection_request",
                intent="inspect_memory",
                steps=(
                    PlanStep(
                        tool_name="memory_usage",
                        rationale="Inspect RAM and swap usage.",
                    ),
                ),
            )
        if _contains_any(normalized, ("memoria", "memória", "ram", "swap")):
            return _blocked_response(
                "Entendi que você quer inspecionar memória, mas a tool segura `memory_usage` não está disponível neste runtime.",
                "The runtime does not expose memory_usage for this request.",
                kind="missing_safe_tool",
            )

        if _contains_any(normalized, ("processo", "processos", "cpu")) and (
            "top_processes" in available_tools
        ):
            limit = _extract_int(message, default=5, min_value=1, max_value=20)
            return _needs_tools_response(
                "Vou listar os processos com maior uso de CPU.",
                "Inspecting CPU-heavy processes requires a typed tool step.",
                kind="inspection_request",
                intent="inspect_processes",
                steps=(
                    PlanStep(
                        tool_name="top_processes",
                        rationale="Show the most CPU-intensive processes.",
                        arguments={"limit": limit},
                    ),
                ),
            )
        if _contains_any(normalized, ("processo", "processos", "cpu")):
            return _blocked_response(
                "Entendi que você quer inspecionar processos, mas a tool segura `top_processes` não está disponível neste runtime.",
                "The runtime does not expose top_processes for this request.",
                kind="missing_safe_tool",
            )

        if _contains_any(normalized, ("sistema", "host", "hostname")) and (
            "system_info" in available_tools
        ):
            return _needs_tools_response(
                "Vou coletar as informações básicas do host.",
                "Collecting host metadata requires a typed tool step.",
                kind="inspection_request",
                intent="inspect_system_info",
                steps=(
                    PlanStep(
                        tool_name="system_info",
                        rationale="Collect basic host metadata.",
                    ),
                ),
            )
        if _contains_any(normalized, ("sistema", "host", "hostname")):
            return _blocked_response(
                "Entendi que você quer inspecionar o host, mas a tool segura `system_info` não está disponível neste runtime.",
                "The runtime does not expose system_info for this request.",
                kind="missing_safe_tool",
            )

        return _blocked_response(
            message=(
                "Ainda não consegui mapear esse pedido para uma ação segura. "
                "Posso inspecionar memória, disco, processos, status de serviço, logs do journal e informações básicas do host."
            ),
            reason="The request does not map to a supported safe tool flow.",
        )

    def diagnostics(self) -> dict[str, object]:
        return {
            "name": self.name,
            "available": True,
            "mode": "local",
        }


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    without_marks = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return without_marks.lower()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    normalized_terms = tuple(_normalize(term) for term in terms)
    return any(term in text for term in normalized_terms)


def _extract_int(
    text: str,
    *,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    match = INTEGER_RE.search(text)
    if not match:
        return default

    parsed = int(match.group(1))
    if parsed < min_value:
        return min_value
    if parsed > max_value:
        return max_value
    return parsed


def _extract_path(text: str) -> str | None:
    match = PATH_RE.search(text)
    return match.group(1) if match else None


def _extract_explicit_service_scope(normalized_text: str) -> str | None:
    if any(
        token in normalized_text
        for token in ("servico de usuario", "servico do usuario", "user service", "service user")
    ):
        return "user"
    return None


def _resolve_service_scope(normalized_text: str, context: dict[str, str]) -> str:
    explicit_scope = _extract_explicit_service_scope(normalized_text)
    if explicit_scope is not None:
        return explicit_scope
    context_scope = context.get("scope")
    if context_scope in {"system", "user"}:
        return context_scope
    return "system"


def _with_service_scope(arguments: dict[str, object], scope: str) -> dict[str, object]:
    if scope == "user":
        return {
            **arguments,
            "scope": "user",
        }
    return arguments


def _extract_service_name(text: str) -> str | None:
    match = SERVICE_NAME_RE.search(text)
    if not match:
        return None
    return match.group(1)


def _extract_journal_unit(text: str) -> str | None:
    match = JOURNAL_UNIT_RE.search(text)
    if not match:
        return None
    return match.group(1)


def _extract_process_name(text: str) -> str | None:
    match = PROCESS_NAME_RE.search(text)
    if not match:
        return None
    return match.group(1)


def _extract_pid(text: str) -> int | None:
    match = PID_RE.search(text)
    if not match:
        return None
    return int(match.group(1))


def _extract_history_context(
    conversation_history: tuple[ConversationMessage, ...],
) -> dict[str, str]:
    for message in reversed(conversation_history):
        if message.role != "user":
            continue
        scope = _extract_explicit_service_scope(_normalize(message.content))
        unit = _extract_journal_unit(message.content) or _extract_service_name(message.content)
        path = _extract_path(message.content)
        if unit:
            context = {"unit": unit}
            if scope is not None:
                context["scope"] = scope
            return context
        if path:
            return {"path": path}
    return {}


def _extract_structured_context(session_context: SessionContext) -> dict[str, str]:
    context: dict[str, str] = {}
    tracked = session_context.tracked
    unit = tracked.unit
    if unit is None and session_context.service is not None:
        unit = session_context.service.name
    if unit is None and session_context.process_unit is not None:
        unit = session_context.process_unit.unit
    if unit is None and session_context.logs is not None:
        unit = session_context.logs.unit
    if unit:
        context["unit"] = unit

    scope = tracked.scope
    if scope is None and session_context.service is not None:
        scope = session_context.service.scope
    if scope is None and session_context.process_unit is not None:
        scope = session_context.process_unit.scope
    if scope in {"system", "user"}:
        context["scope"] = scope

    path = tracked.path
    if path is None and session_context.disk is not None:
        path = session_context.disk.path
    if path:
        context["path"] = path
    return context


def _extract_context(
    conversation_history: tuple[ConversationMessage, ...],
    session_context: SessionContext,
) -> dict[str, str]:
    history_context = _extract_history_context(conversation_history)
    structured_context = _extract_structured_context(session_context)
    return {
        **history_context,
        **structured_context,
    }


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _looks_like_log_follow_up(normalized: str) -> bool:
    return _contains_any(
        normalized,
        (
            "mesmos logs",
            "mais linhas",
            "agora",
            "de novo",
            "novamente",
        ),
    )


def _looks_like_service_follow_up(normalized: str) -> bool:
    return _contains_any(
        normalized,
        (
            "mesmo servico",
            "mesmo serviço",
            "de novo",
            "novamente",
            "agora",
        ),
    )


def _looks_like_config_rollback_request(normalized: str) -> bool:
    return _contains_any(
        normalized,
        (
            "rollback",
            "restaure o ultimo backup",
            "restaure o último backup",
            "restaurar o ultimo backup",
            "restaurar o último backup",
            "desfaca a ultima mudanca",
            "desfaça a última mudança",
            "desfazer a ultima mudanca",
            "desfazer a última mudança",
            "volte a configuracao anterior",
            "volte a configuração anterior",
        ),
    )


def _guess_service_name_from_context(
    session_context: SessionContext,
    context: dict[str, str],
) -> str | None:
    unit = _context_service_name(context)
    if unit:
        return unit
    if session_context.service is not None:
        return session_context.service.name
    if (
        session_context.process_unit is not None
        and _looks_like_service_unit(session_context.process_unit.unit)
    ):
        return session_context.process_unit.unit
    return None


def _guess_process_name_from_context(session_context: SessionContext) -> str | None:
    selected_process = select_process_lead(
        session_context.processes,
        tracked=session_context.tracked,
    )
    if selected_process is not None:
        return selected_process.command
    if session_context.process_unit is not None:
        return session_context.process_unit.query_name
    return None


def _context_service_name(context: dict[str, str]) -> str | None:
    unit = context.get("unit")
    if _looks_like_service_unit(unit):
        return unit
    return None


def _looks_like_service_unit(value: str | None) -> bool:
    if not value:
        return False
    return "." not in value or value.endswith(".service")


def _build_diagnostic_summary(session_context: SessionContext) -> str:
    fragments: list[str] = []
    if session_context.memory is not None:
        memory_used = session_context.memory.memory_used_percent
        swap_used = session_context.memory.swap_used_percent
        if memory_used is not None and swap_used is not None:
            fragments.append(f"memória: memory {memory_used}% used, swap {swap_used}% used")

    if session_context.processes is not None and session_context.processes.items:
        process_fragments: list[str] = []
        for item in session_context.processes.items:
            if item.cpu_percent is None:
                process_fragments.append(item.command)
            else:
                process_fragments.append(f"{item.command}({item.cpu_percent}%)")
        if process_fragments:
            fragments.append(f"processos: {', '.join(process_fragments)}")

    if session_context.process_unit is not None:
        process_unit = session_context.process_unit
        if process_unit.unit:
            query_name = process_unit.query_name or "processo principal"
            scope_text = f" ({process_unit.scope})" if process_unit.scope else ""
            fragments.append(
                f"correlacao: {query_name} -> {process_unit.unit}{scope_text}"
            )

    if session_context.service is not None:
        service = session_context.service
        if service.active_state and service.sub_state:
            fragments.append(
                "serviço: "
                f"{service.name}: active={service.active_state}, sub={service.sub_state}"
            )

    if not fragments:
        return "Ainda preciso coletar mais sinais antes de concluir o diagnóstico."

    return "Resumo do diagnóstico: " + " | ".join(fragments) + "."


def _needs_refresh(
    freshness_map: dict[str, ObservationFreshness],
    key: str,
) -> bool:
    entry = freshness_map.get(key)
    if entry is None:
        return True
    return entry.stale


def _needs_tools_response(
    message: str,
    reason: str,
    *,
    kind: str | None = None,
    intent: str,
    steps: tuple[PlanStep, ...],
) -> ProviderResponse:
    return ProviderResponse(
        message=message,
        plan=ExecutionPlan(intent=intent, steps=steps),
        decision=PlanningDecision(state="needs_tools", kind=kind, reason=reason),
    )


def _complete_response(message: str, reason: str, *, kind: str | None = None) -> ProviderResponse:
    return ProviderResponse(
        message=message,
        plan=None,
        decision=PlanningDecision(state="complete", kind=kind, reason=reason),
    )


def _blocked_response(message: str, reason: str, *, kind: str | None = None) -> ProviderResponse:
    return ProviderResponse(
        message=message,
        plan=None,
        decision=PlanningDecision(state="blocked", kind=kind, reason=reason),
    )
