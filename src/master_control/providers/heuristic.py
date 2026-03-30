from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

from master_control.core.observations import ObservationFreshness
from master_control.core.process_leads import select_process_lead
from master_control.core.session_context import (
    RecentObservationContext,
    SessionContext,
    build_session_context,
)
from master_control.providers.base import ConversationMessage, ProviderRequest, ProviderResponse
from master_control.shared.planning import ExecutionPlan, PlanningDecision, PlanStep

SERVICE_NAME_RE = re.compile(
    r"(?:servi(?:co|ço)|service|unit|status)\s+(?:(?:do|da|de|of|for)\s+)?([A-Za-z0-9_@][A-Za-z0-9_.@-]*)",
    re.IGNORECASE,
)
SERVICE_CHECK_RE = re.compile(
    r"(?:verifique|verifica|verificar|cheque|checar|inspecione|inspecionar|como\s+(?:esta|está|ta))\s+(?:(?:o|a)\s+)?([A-Za-z0-9_@][A-Za-z0-9_.@-]*)",
    re.IGNORECASE,
)
SERVICE_STATE_RE = re.compile(
    r"\b(?:(?:o|a)\s+)?([A-Za-z0-9_@][A-Za-z0-9_.@-]*)\s+(?:caiu|parou|falhou|esta\s+rodando|está\s+rodando|ta\s+rodando|esta\s+falhando|está\s+falhando|ta\s+falhando)",
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
CONFIG_ARTIFACT_RE = re.compile(
    r"\b(?:arquivo|config|configuracao|ini|ya?ml|toml|conf|cfg)\b",
    re.IGNORECASE,
)
LEADING_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\s*"
)
LOG_PATTERN_DEFINITIONS = (
    (
        "restart_loop",
        "padrao de restart loop",
        8,
        (
            "main process exited",
            "control process exited",
            "failed with result 'exit-code'",
            "status=1/failure",
            "start request repeated too quickly",
            "scheduled restart job",
            "restart counter",
            "restarting too quickly",
            "service hold-off time over",
            "back-off restarting failed unit",
            "back-off",
            "backoff",
        ),
    ),
    (
        "timeout",
        "padrao de timeout",
        7,
        (
            "timed out",
            "timeout",
            "watchdog",
            "deadline exceeded",
            "deadline expired",
        ),
    ),
    (
        "dependency_failure",
        "padrao de falha de dependencia",
        7,
        (
            "dependency failed for",
            "dependency failed",
            "dependency job failed",
            "failed with result 'dependency'",
            "requires failed for",
        ),
    ),
    (
        "environment_failure",
        "padrao de falha de ambiente",
        7,
        (
            "failed to load environment",
            "environmentfile",
            "environment file",
            "failed at step exec",
            "failed at step chdir",
            "failed at step user",
            "working directory",
            "no such file or directory",
            "bad unit file setting",
            "exec format error",
            "is not executable",
            "not an executable",
            "invalid argument",
            "unknown directive",
            "unknown lvalue",
        ),
    ),
    (
        "permission_failure",
        "padrao de falha de permissao",
        7,
        (
            "permission denied",
            "access denied",
            "operation not permitted",
            "not permitted",
            "eacces",
            "eperm",
        ),
    ),
    (
        "connection_failure",
        "padrao de falha de conexao",
        6,
        (
            "connection refused",
            "connect() failed",
            "connect failed",
            "failed to connect",
            "refused connection",
        ),
    ),
    (
        "crash_failure",
        "padrao de falha critica",
        7,
        (
            "fatal",
            "panic",
            "segfault",
            "traceback",
            "crash",
            "oom",
            "out of memory",
            "core dumped",
        ),
    ),
    (
        "recovery",
        "sinal de recuperacao",
        0,
        (
            "reloaded successfully",
            "accepting connections",
            "listening on",
            "started successfully",
            "startup complete",
            "ready to serve",
            "ready for connections",
            "healthy",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class LogSignal:
    kind: str
    summary: str
    score: int
    index: int


@dataclass(slots=True)
class _LogPatternBucket:
    label: str
    count: int
    score: int
    example_rank: int
    index: int
    example: str


@dataclass(frozen=True, slots=True)
class _ConfigLineEntry:
    section: str | None
    line: str
    key: str | None


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
        logs_freshness = freshness_map.get("logs")
        config_freshness = freshness_map.get("config")
        last_intent = session_context.last_intent
        comparison_kind = _comparison_request_kind(normalized)
        candidate_service = _extract_service_name(message) or _guess_service_name_from_context(
            session_context,
            last_context,
        )
        context_unit = _string_or_none(last_context.get("unit"))
        context_service = _context_service_name(last_context)
        candidate_process = _extract_process_name(message) or _guess_process_name_from_context(
            session_context
        )
        explicit_path = _extract_path(message)
        config_path = explicit_path or _string_or_none(last_context.get("path"))
        config_context = session_context.config
        has_tracked_backup = bool(
            config_context is not None and config_context.path and config_context.backup_path
        )

        if _looks_like_performance_request(normalized):
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

            if (
                "process_to_unit" in available_tools
                and candidate_process
                and candidate_service is None
                and _needs_refresh(freshness_map, "process_unit")
            ):
                message_text = (
                    f"Vou correlacionar o processo `{candidate_process}` com um unit do systemd."
                )
                if "process_unit" in freshness_map and freshness_map["process_unit"].stale:
                    message_text = f"Vou atualizar a correlação do processo `{candidate_process}` com systemd antes de concluir."
                return _needs_tools_response(
                    message_text,
                    "Correlating the hottest process with a systemd unit is the next safe diagnostic step.",
                    kind="refresh_required",
                    intent="diagnose_performance",
                    steps=(
                        PlanStep(
                            tool_name="process_to_unit",
                            rationale="Correlate the hottest observed process with a systemd unit.",
                            arguments={"name": candidate_process, "limit": 3},
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

        if _looks_like_performance_comparison_request(
            normalized,
            last_intent=last_intent,
            has_performance_context=(
                session_context.memory is not None or session_context.processes is not None
            ),
        ):
            performance_comparison = _summarize_performance_comparison(
                session_context,
                request_kind=comparison_kind or "changed",
            )
            if performance_comparison is not None:
                return _complete_response(
                    performance_comparison,
                    "Recent performance observations were sufficient for a comparative follow-up.",
                    kind="evidence_sufficient",
                )

            comparison_steps: list[PlanStep] = []
            missing_tools: list[str] = []
            if _needs_comparable_refresh(session_context, "memory"):
                if "memory_usage" in available_tools:
                    comparison_steps.append(
                        PlanStep(
                            tool_name="memory_usage",
                            rationale="Refresh memory pressure before comparing with the previous reading.",
                        )
                    )
                else:
                    missing_tools.append("memory_usage")
            if _needs_comparable_refresh(session_context, "processes"):
                if "top_processes" in available_tools:
                    comparison_steps.append(
                        PlanStep(
                            tool_name="top_processes",
                            rationale="Refresh CPU-heavy processes before comparing with the previous reading.",
                            arguments={
                                "limit": _extract_int(message, default=5, min_value=1, max_value=10)
                            },
                        )
                    )
                else:
                    missing_tools.append("top_processes")

            if comparison_steps:
                decision_kind = (
                    "refresh_required"
                    if any(
                        _has_stale_recent_observation(session_context, key)
                        for key in ("memory", "processes")
                    )
                    else "inspection_request"
                )
                return _needs_tools_response(
                    "Vou atualizar memória e processos para comparar com a leitura anterior.",
                    "A comparative performance follow-up requires fresh or comparable host readings.",
                    kind=decision_kind,
                    intent="compare_performance",
                    steps=tuple(comparison_steps),
                )

            if missing_tools:
                missing_tool = missing_tools[0]
                return _blocked_response(
                    f"Entendi o pedido de comparação do desempenho, mas a tool segura `{missing_tool}` não está disponível neste runtime.",
                    "The runtime does not expose the safe tools required for this comparative performance follow-up.",
                    kind="missing_safe_tool",
                )

            return _blocked_response(
                "Entendi o pedido de comparação do desempenho, mas ainda não há leituras recentes suficientes para comparar com segurança.",
                "The request looks like a comparative performance follow-up, but no comparable host context was identified.",
                kind="unsupported_request",
            )

        if _looks_like_failed_services_request(normalized) and (
            "failed_services" in available_tools
        ):
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
        if _looks_like_failed_services_request(normalized):
            return _blocked_response(
                "Entendi que você quer listar serviços com falha, mas a tool segura `failed_services` não está disponível neste runtime.",
                "The runtime does not expose failed_services for this request.",
                kind="missing_safe_tool",
            )

        if _looks_like_process_unit_request(
            normalized,
            has_process_context=candidate_process is not None,
        ) and ("process_to_unit" in available_tools):
            pid = _extract_pid(message)
            if candidate_process or pid is not None:
                arguments: dict[str, object] = {"limit": 3}
                if pid is not None:
                    arguments["pid"] = pid
                elif candidate_process:
                    arguments["name"] = candidate_process
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
            return _blocked_response(
                "Entendi que você quer correlacionar um processo com systemd, mas ainda não consegui identificar qual processo deve ser correlacionado com segurança.",
                "The request looks like process correlation, but no concrete process target was identified.",
                kind="unsupported_request",
            )
        if _looks_like_process_unit_request(
            normalized,
            has_process_context=candidate_process is not None,
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

        if (
            _looks_like_contextual_log_request(
                normalized,
                has_context_unit=context_unit is not None,
            )
            and "read_journal" in available_tools
        ):
            lines = _extract_int(message, default=20, min_value=1, max_value=200)
            return _needs_tools_response(
                f"Vou consultar os logs recentes de `{context_unit}`.",
                "The contextual log follow-up still requires a journal read.",
                kind="inspection_request",
                intent="inspect_logs_follow_up",
                steps=(
                    PlanStep(
                        tool_name="read_journal",
                        rationale="Reuse the current tracked unit for a contextual log follow-up.",
                        arguments={
                            "unit": context_unit,
                            "lines": lines,
                        },
                    ),
                ),
            )
        if _looks_like_contextual_log_request(
            normalized, has_context_unit=context_unit is not None
        ):
            return _blocked_response(
                "Entendi que você quer aprofundar pelos logs do serviço atual, mas a tool segura `read_journal` não está disponível neste runtime.",
                "The runtime does not expose read_journal for this contextual follow-up.",
                kind="missing_safe_tool",
            )

        if _looks_like_service_cause_request(
            normalized,
            candidate_service=candidate_service,
            has_context_service=context_service is not None,
        ):
            unit = candidate_service or context_service
            if "read_journal" in available_tools and unit:
                lines = _extract_int(message, default=40, min_value=1, max_value=200)
                return _needs_tools_response(
                    f"Vou consultar os logs recentes de `{unit}` para investigar a falha.",
                    "Investigating the cause of a service failure requires a scoped journal read.",
                    kind="inspection_request",
                    intent="investigate_service_failure",
                    steps=(
                        PlanStep(
                            tool_name="read_journal",
                            rationale="Inspect recent journal entries for the affected service.",
                            arguments={
                                "unit": unit,
                                "lines": lines,
                            },
                        ),
                    ),
                )
            if unit:
                return _blocked_response(
                    "Entendi que você quer investigar a causa da falha do serviço, mas a tool segura `read_journal` não está disponível neste runtime.",
                    "The runtime does not expose read_journal for this service-failure investigation.",
                    kind="missing_safe_tool",
                )
            return _blocked_response(
                "Entendi a investigação de falha do serviço, mas ainda não consegui identificar qual serviço deve ser consultado com segurança.",
                "The request looks like a service failure investigation, but no concrete service target was identified.",
                kind="unsupported_request",
            )

        if _looks_like_log_comparison_request(
            normalized,
            last_intent=last_intent,
            has_log_context=context_unit is not None or logs_freshness is not None,
        ):
            log_comparison = _summarize_log_comparison(
                session_context,
                unit=context_unit or context_service or candidate_service,
                request_kind=comparison_kind or "changed",
            )
            if log_comparison is not None:
                return _complete_response(
                    log_comparison,
                    "Recent log observations were sufficient for a comparative follow-up.",
                    kind="evidence_sufficient",
                )

            unit = context_unit or context_service or candidate_service
            if "read_journal" in available_tools and unit:
                default_lines = _observation_returned_lines(logs_freshness, default=40)
                lines = _extract_int(message, default=default_lines, min_value=1, max_value=200)
                decision_kind = (
                    "refresh_required"
                    if logs_freshness is not None and logs_freshness.stale
                    else "inspection_request"
                )
                return _needs_tools_response(
                    f"Vou reler os logs recentes de `{unit}` para comparar com a leitura anterior.",
                    "A comparative log follow-up requires a fresh or comparable journal read.",
                    kind=decision_kind,
                    intent="compare_logs",
                    steps=(
                        PlanStep(
                            tool_name="read_journal",
                            rationale="Refresh journal entries so the current log read can be compared with the previous one.",
                            arguments={
                                "unit": unit,
                                "lines": lines,
                            },
                        ),
                    ),
                )
            if unit:
                return _blocked_response(
                    "Entendi o pedido de comparação dos logs, mas a tool segura `read_journal` não está disponível neste runtime.",
                    "The runtime does not expose read_journal for this comparative log follow-up.",
                    kind="missing_safe_tool",
                )
            return _blocked_response(
                "Entendi o pedido de comparação dos logs, mas ainda não há um serviço ou leitura recente identificados com segurança para comparar.",
                "The request looks like a comparative log follow-up, but no concrete log context was identified.",
                kind="unsupported_request",
            )

        if _looks_like_service_comparison_request(
            normalized,
            last_intent=last_intent,
            candidate_service=candidate_service,
            has_context_service=context_service is not None,
        ):
            service_name = candidate_service or context_service
            service_comparison = _summarize_service_comparison(
                session_context,
                service_name=service_name,
                request_kind=comparison_kind or "changed",
            )
            if service_comparison is not None:
                return _complete_response(
                    service_comparison,
                    "Recent service observations were sufficient for a comparative follow-up.",
                    kind="evidence_sufficient",
                )

            if "service_status" in available_tools and service_name:
                decision_kind = (
                    "refresh_required"
                    if "service" in freshness_map and freshness_map["service"].stale
                    else "inspection_request"
                )
                return _needs_tools_response(
                    f"Vou verificar novamente o serviço `{service_name}` para comparar com a leitura anterior.",
                    "A comparative service follow-up requires a fresh or comparable status check.",
                    kind=decision_kind,
                    intent="compare_service_status",
                    steps=(
                        PlanStep(
                            tool_name="service_status",
                            rationale="Refresh the service state so it can be compared with the previous observation.",
                            arguments=_with_service_scope({"name": service_name}, service_scope),
                        ),
                    ),
                )
            if service_name:
                return _blocked_response(
                    "Entendi o pedido de comparação do serviço, mas a tool segura `service_status` não está disponível neste runtime.",
                    "The runtime does not expose service_status for this comparative service follow-up.",
                    kind="missing_safe_tool",
                )
            return _blocked_response(
                "Entendi o pedido de comparação do serviço, mas ainda não consegui identificar qual serviço deve ser comparado com segurança.",
                "The request looks like a comparative service follow-up, but no concrete service target was identified.",
                kind="unsupported_request",
            )

        if _looks_like_log_focus_request(
            normalized,
            last_intent=last_intent,
            has_log_context=context_unit is not None or logs_freshness is not None,
        ):
            wants_root_cause = _looks_like_root_cause_summary_request(normalized)
            log_summary = None
            if logs_freshness is not None and not logs_freshness.stale:
                log_summary = _summarize_log_observation(
                    logs_freshness,
                    root_cause=wants_root_cause,
                )
            if log_summary:
                return _complete_response(
                    log_summary,
                    "Fresh journal observations were sufficient for a focused follow-up.",
                    kind="evidence_sufficient",
                )

            unit = context_unit or context_service or candidate_service
            if "read_journal" in available_tools and unit:
                default_lines = _observation_returned_lines(logs_freshness, default=40)
                lines = _extract_int(message, default=default_lines, min_value=1, max_value=200)
                message_text = f"Vou reler os logs recentes de `{unit}` e focar no essencial."
                if wants_root_cause:
                    message_text = f"Vou reler os logs recentes de `{unit}` para identificar a causa principal."
                decision_kind = (
                    "refresh_required"
                    if logs_freshness is not None and logs_freshness.stale
                    else "inspection_request"
                )
                return _needs_tools_response(
                    message_text,
                    "A focused log follow-up requires a fresh scoped journal read.",
                    kind=decision_kind,
                    intent="inspect_logs_follow_up",
                    steps=(
                        PlanStep(
                            tool_name="read_journal",
                            rationale="Refresh recent journal entries before summarizing the main signals.",
                            arguments={
                                "unit": unit,
                                "lines": lines,
                            },
                        ),
                    ),
                )
            if unit:
                return _blocked_response(
                    "Entendi que você quer um resumo focado dos logs, mas a tool segura `read_journal` não está disponível neste runtime.",
                    "The runtime does not expose read_journal for this focused log follow-up.",
                    kind="missing_safe_tool",
                )
            return _blocked_response(
                "Entendi o pedido de síntese dos logs, mas ainda não há um serviço ou leitura recente identificados com segurança para resumir.",
                "The request looks like a focused log follow-up, but no concrete log context was identified.",
                kind="unsupported_request",
            )

        if _looks_like_reload_request(
            normalized,
            candidate_service=candidate_service,
            has_context_service=context_service is not None,
        ) and ("reload_service" in available_tools):
            service_name = candidate_service or context_service
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
                "Entendi o pedido de recarga do serviço, mas ainda não consegui identificar qual serviço deve ser recarregado com segurança.",
                "The request looks like a reload request but no concrete service target was identified.",
                kind="unsupported_request",
            )

        if _looks_like_reload_request(
            normalized,
            candidate_service=candidate_service,
            has_context_service=context_service is not None,
        ):
            return _blocked_response(
                "Entendi o pedido de recarga do serviço, mas a tool segura `reload_service` não está disponível neste runtime.",
                "The runtime does not expose reload_service for this request.",
                kind="missing_safe_tool",
            )

        if _looks_like_restart_request(
            normalized,
            candidate_service=candidate_service,
            has_context_service=context_service is not None,
        ) and ("restart_service" in available_tools):
            service_name = candidate_service or context_service
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
                "Entendi o pedido de reinício do serviço, mas ainda não consegui identificar qual serviço deve ser reiniciado com segurança.",
                "The request looks like a restart request but no concrete service target was identified.",
                kind="unsupported_request",
            )

        if _looks_like_restart_request(
            normalized,
            candidate_service=candidate_service,
            has_context_service=context_service is not None,
        ):
            return _blocked_response(
                "Entendi o pedido de reinício do serviço, mas a tool segura `restart_service` não está disponível neste runtime.",
                "The runtime does not expose restart_service for this request.",
                kind="missing_safe_tool",
            )

        if _looks_like_service_status_request(
            normalized,
            candidate_service=candidate_service,
            has_context_service=context_service is not None,
        ) and ("service_status" in available_tools):
            service_name = candidate_service or context_service
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
                "Entendi que você quer inspecionar o serviço, mas ainda não consegui identificar qual serviço deve ser consultado com segurança.",
                "The request looks service-oriented but no concrete service target was identified.",
                kind="unsupported_request",
            )

        if _looks_like_service_status_request(
            normalized,
            candidate_service=candidate_service,
            has_context_service=context_service is not None,
        ):
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

        if _looks_like_disk_request(normalized) and ("disk_usage" in available_tools):
            return _needs_tools_response(
                f"Vou verificar o uso de disco em `{explicit_path or '/'}`.",
                "Inspecting filesystem usage requires a typed disk tool.",
                kind="inspection_request",
                intent="inspect_disk_usage",
                steps=(
                    PlanStep(
                        tool_name="disk_usage",
                        rationale="Inspect filesystem utilization for the requested path.",
                        arguments={"path": explicit_path or "/"},
                    ),
                ),
            )
        if _looks_like_disk_request(normalized):
            return _blocked_response(
                "Entendi que você quer inspecionar disco, mas a tool segura `disk_usage` não está disponível neste runtime.",
                "The runtime does not expose disk_usage for this request.",
                kind="missing_safe_tool",
            )

        if _looks_like_config_rollback_request(
            normalized,
            has_tracked_backup=has_tracked_backup,
        ) and ("restore_config_backup" in available_tools):
            if config_context is not None and config_context.path and config_context.backup_path:
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
        if _looks_like_config_rollback_request(normalized, has_tracked_backup=has_tracked_backup):
            return _blocked_response(
                "Entendi o pedido de rollback de configuração, mas a tool segura `restore_config_backup` não está disponível neste runtime.",
                "The runtime does not expose restore_config_backup for this request.",
                kind="missing_safe_tool",
            )

        if _looks_like_config_comparison_request(
            normalized,
            last_intent=last_intent,
            has_config_context=config_path is not None or config_freshness is not None,
        ):
            config_comparison = _summarize_config_comparison(
                session_context,
                path=config_path,
            )
            if config_comparison:
                return _complete_response(
                    config_comparison,
                    "Recent config observations were sufficient for a comparative follow-up.",
                    kind="evidence_sufficient",
                )

            if "read_config_file" in available_tools and config_path:
                decision_kind = (
                    "refresh_required"
                    if config_freshness is not None and config_freshness.stale
                    else "inspection_request"
                )
                return _needs_tools_response(
                    f"Vou reler `{config_path}` para comparar com a leitura anterior.",
                    "A comparative config follow-up requires a fresh or comparable config read.",
                    kind=decision_kind,
                    intent="compare_config",
                    steps=(
                        PlanStep(
                            tool_name="read_config_file",
                            rationale="Refresh the tracked managed file before comparing it with the previous read.",
                            arguments={"path": config_path},
                        ),
                    ),
                )
            if config_path:
                return _blocked_response(
                    "Entendi o pedido de comparação da configuração, mas a tool segura `read_config_file` não está disponível neste runtime.",
                    "The runtime does not expose read_config_file for this comparative config follow-up.",
                    kind="missing_safe_tool",
                )
            return _blocked_response(
                "Entendi o pedido de comparação da configuração, mas ainda não há um arquivo gerenciado identificado com segurança para comparar.",
                "The request looks like a comparative config follow-up, but no managed path was identified.",
                kind="unsupported_request",
            )

        if _looks_like_config_focus_request(
            normalized,
            last_intent=last_intent,
            has_config_context=config_path is not None or config_freshness is not None,
        ):
            config_summary = None
            if config_freshness is not None and not config_freshness.stale:
                config_summary = _summarize_config_observation(config_freshness)
            if config_summary:
                return _complete_response(
                    config_summary,
                    "Fresh config observations were sufficient for a focused follow-up.",
                    kind="evidence_sufficient",
                )

            if "read_config_file" in available_tools and config_path:
                decision_kind = (
                    "refresh_required"
                    if config_freshness is not None and config_freshness.stale
                    else "inspection_request"
                )
                return _needs_tools_response(
                    f"Vou reler `{config_path}` e destacar só o essencial.",
                    "A focused config follow-up requires a typed config read.",
                    kind=decision_kind,
                    intent="read_config_file",
                    steps=(
                        PlanStep(
                            tool_name="read_config_file",
                            rationale="Refresh the managed config file before summarizing the key lines.",
                            arguments={"path": config_path},
                        ),
                    ),
                )
            if config_path:
                return _blocked_response(
                    "Entendi que você quer um resumo focado da configuração, mas a tool segura `read_config_file` não está disponível neste runtime.",
                    "The runtime does not expose read_config_file for this focused config follow-up.",
                    kind="missing_safe_tool",
                )
            return _blocked_response(
                "Entendi o pedido de síntese da configuração, mas ainda não há um arquivo gerenciado identificado com segurança para resumir.",
                "The request looks like a focused config follow-up, but no managed path was identified.",
                kind="unsupported_request",
            )

        if _looks_like_config_read_request(
            normalized,
            has_explicit_path=explicit_path is not None,
            has_context_path=config_path is not None,
        ) and ("read_config_file" in available_tools):
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
                "Entendi que você quer ler uma configuração gerenciada, mas ainda não consegui identificar qual arquivo deve ser consultado com segurança.",
                "The request looks like a config read, but no concrete managed path was identified.",
                kind="unsupported_request",
            )
        if _looks_like_config_read_request(
            normalized,
            has_explicit_path=explicit_path is not None,
            has_context_path=config_path is not None,
        ):
            return _blocked_response(
                "Entendi que você quer ler uma configuração gerenciada, mas a tool segura `read_config_file` não está disponível neste runtime.",
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

        if _looks_like_process_request(normalized) and ("top_processes" in available_tools):
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
        if _looks_like_process_request(normalized):
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
    for pattern in (SERVICE_NAME_RE, SERVICE_CHECK_RE, SERVICE_STATE_RE):
        match = pattern.search(text)
        if not match:
            continue
        candidate = match.group(1)
        if _looks_like_service_candidate(candidate):
            return candidate
    return None


def _extract_journal_unit(text: str) -> str | None:
    match = JOURNAL_UNIT_RE.search(text)
    if not match:
        return None
    return match.group(1)


def _extract_process_name(text: str) -> str | None:
    match = PROCESS_NAME_RE.search(text)
    if not match:
        return None
    candidate = match.group(1)
    if not _looks_like_process_candidate(candidate):
        return None
    return candidate


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


def _as_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _comparison_request_kind(normalized: str) -> str | None:
    if _contains_any(
        normalized,
        (
            "piorou",
            "ficou pior",
            "deu uma piorada",
            "deu piorada",
            "ficou mais ruim",
            "esta pior agora",
            "está pior agora",
            "ta pior agora",
            "ta pior que antes",
            "está pior que antes",
            "esta pior que antes",
        ),
    ):
        return "worse"
    if _contains_any(
        normalized,
        (
            "melhorou",
            "ficou melhor",
            "deu uma melhorada",
            "deu melhorada",
            "melhorou um pouco",
            "esta melhor agora",
            "está melhor agora",
            "ta melhor agora",
            "melhor agora",
            "ta menos pior",
            "está menos pior",
            "esta menos pior",
            "ficou menos pior",
        ),
    ):
        return "better"
    if _contains_any(
        normalized,
        (
            "o que mudou",
            "qual a diferenca",
            "qual a diferença",
            "mudou desde",
            "mudou da ultima",
            "mudou da última",
            "comparando com a ultima",
            "comparando com a última",
            "desde a ultima leitura",
            "desde a última leitura",
            "desde a ultima vez",
            "desde a última vez",
            "mudou alguma coisa",
            "mudou algo",
            "mudou algo ai",
            "mudou alguma coisa ai",
            "continua igual",
            "continua a mesma coisa",
            "continua do mesmo jeito",
            "segue igual",
            "ta a mesma coisa",
            "tá a mesma coisa",
            "esta a mesma coisa",
            "está a mesma coisa",
            "ficou diferente",
            "ta diferente agora",
            "tá diferente agora",
            "esta diferente agora",
            "está diferente agora",
        ),
    ):
        return "changed"
    return None


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


def _looks_like_contextual_log_request(
    normalized: str,
    *,
    has_context_unit: bool,
) -> bool:
    if not has_context_unit:
        return False
    return _contains_any(
        normalized,
        (
            "o que aconteceu com ele",
            "o que houve com ele",
            "me mostra o que aconteceu com ele",
            "me mostre o que aconteceu com ele",
            "logs dele",
            "log dele",
            "journal dele",
            "logs desse servico",
            "log desse servico",
            "o que aconteceu com esse servico",
            "o que houve com esse servico",
        ),
    )


def _looks_like_log_comparison_request(
    normalized: str,
    *,
    last_intent: str | None,
    has_log_context: bool,
) -> bool:
    if not has_log_context or _comparison_request_kind(normalized) is None:
        return False
    if _contains_any(normalized, ("log", "logs", "journal")):
        return True
    return _is_log_intent(last_intent)


def _looks_like_performance_comparison_request(
    normalized: str,
    *,
    last_intent: str | None,
    has_performance_context: bool,
) -> bool:
    if not has_performance_context or _comparison_request_kind(normalized) is None:
        return False
    if _contains_any(normalized, ("log", "logs", "journal")):
        return False
    if CONFIG_ARTIFACT_RE.search(normalized):
        return False
    if _contains_any(
        normalized,
        (
            "host",
            "maquina",
            "máquina",
            "sistema",
            "servidor",
            "desempenho",
            "lento",
        ),
    ):
        return True
    return _is_performance_intent(last_intent)


def _looks_like_service_cause_request(
    normalized: str,
    *,
    candidate_service: str | None,
    has_context_service: bool,
) -> bool:
    service_reference = (
        candidate_service is not None
        or has_context_service
        or _contains_any(normalized, ("servico", "serviço", "service"))
    )
    if not service_reference:
        return False

    has_cause = _contains_any(
        normalized,
        (
            "por que",
            "porque",
            "motivo",
            "causa",
            "o que derrubou",
        ),
    )
    has_failure = _contains_any(
        normalized,
        (
            "caiu",
            "falhou",
            "parou",
            "instavel",
            "instável",
            "saiu do ar",
        ),
    )
    return has_cause and has_failure


def _looks_like_service_comparison_request(
    normalized: str,
    *,
    last_intent: str | None,
    candidate_service: str | None,
    has_context_service: bool,
) -> bool:
    if _comparison_request_kind(normalized) is None:
        return False
    if _contains_any(normalized, ("servico", "serviço", "service", "status")) and (
        candidate_service is not None or has_context_service
    ):
        return True
    return _is_service_intent(last_intent)


def _looks_like_root_cause_summary_request(normalized: str) -> bool:
    return _contains_any(
        normalized,
        (
            "causa principal",
            "motivo principal",
            "qual foi a causa",
            "qual foi o motivo",
            "o principal motivo",
            "o que derrubou",
        ),
    )


def _looks_like_focus_request(normalized: str) -> bool:
    return _contains_any(
        normalized,
        (
            "so o importante",
            "só o importante",
            "parte importante",
            "o essencial",
            "pontos principais",
            "principais pontos",
            "resuma",
            "resume",
            "resumo",
            "em poucas linhas",
            "mais importante",
            "foca no importante",
            "foco no importante",
        ),
    )


def _looks_like_log_focus_request(
    normalized: str,
    *,
    last_intent: str | None,
    has_log_context: bool,
) -> bool:
    if not has_log_context:
        return False
    if _looks_like_root_cause_summary_request(normalized):
        return True
    if _contains_any(normalized, ("log", "logs", "journal")) and _looks_like_focus_request(
        normalized
    ):
        return True
    return _is_log_intent(last_intent) and _looks_like_focus_request(normalized)


def _looks_like_config_focus_request(
    normalized: str,
    *,
    last_intent: str | None,
    has_config_context: bool,
) -> bool:
    if not has_config_context:
        return False
    if CONFIG_ARTIFACT_RE.search(normalized) and _looks_like_focus_request(normalized):
        return True
    return _is_config_intent(last_intent) and _looks_like_focus_request(normalized)


def _looks_like_config_comparison_request(
    normalized: str,
    *,
    last_intent: str | None,
    has_config_context: bool,
) -> bool:
    if not has_config_context or _comparison_request_kind(normalized) != "changed":
        return False
    if CONFIG_ARTIFACT_RE.search(normalized):
        return True
    return _is_config_intent(last_intent)


def _looks_like_performance_request(normalized: str) -> bool:
    if _contains_any(
        normalized,
        (
            "diagnostico",
            "diagnosticar",
            "lentidao",
            "slow host",
            "host lento",
        ),
    ):
        return True

    return _contains_any(
        normalized,
        (
            "host",
            "maquina",
            "computador",
            "pc",
            "sistema",
            "servidor",
        ),
    ) and _contains_any(
        normalized,
        (
            "lento",
            "travando",
            "arrastando",
            "pesado",
            "lerdo",
        ),
    )


def _looks_like_failed_services_request(normalized: str) -> bool:
    if _contains_any(
        normalized,
        (
            "servicos com falha",
            "servicos falhando",
            "failed services",
            "servicos failed",
            "servicos quebrados",
            "tem algum servico falhando",
            "tem algum servico quebrado",
            "algum servico falhou",
            "algum servico caiu",
            "quais unidades falharam",
            "unidades com falha",
            "failed units",
            "units failed",
        ),
    ):
        return True

    has_subject = _contains_any(
        normalized,
        (
            "servico",
            "servicos",
            "service",
            "services",
            "unit",
            "units",
            "unidade",
            "unidades",
        ),
    )
    has_failure = _contains_any(
        normalized,
        (
            "falha",
            "falhando",
            "falhou",
            "failed",
            "quebrado",
            "quebrada",
            "quebrados",
            "quebradas",
            "caiu",
            "caido",
            "caida",
            "caidos",
            "caidas",
            "down",
            "fora do ar",
            "parou",
            "parados",
            "paradas",
        ),
    )
    has_listing = _contains_any(
        normalized,
        (
            "quais",
            "listar",
            "lista",
            "mostre",
            "mostrar",
            "tem",
            "algum",
            "alguns",
            "existe",
            "existem",
        ),
    )
    return has_subject and has_failure and has_listing


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


def _looks_like_restart_request(
    normalized: str,
    *,
    candidate_service: str | None,
    has_context_service: bool,
) -> bool:
    if _contains_any(
        normalized,
        (
            "reiniciar",
            "reinicie",
            "reinicia",
            "restart",
        ),
    ):
        return candidate_service is not None or has_context_service
    return False


def _looks_like_reload_request(
    normalized: str,
    *,
    candidate_service: str | None,
    has_context_service: bool,
) -> bool:
    if _contains_any(
        normalized,
        (
            "recarregar",
            "recarregue",
            "recarrega",
            "reload",
        ),
    ):
        return candidate_service is not None or has_context_service
    return False


def _looks_like_service_status_request(
    normalized: str,
    *,
    candidate_service: str | None,
    has_context_service: bool,
) -> bool:
    if candidate_service and _contains_any(normalized, ("servico", "service", "status")):
        return True
    if candidate_service and _contains_any(
        normalized,
        (
            "verifique",
            "verifica",
            "verificar",
            "cheque",
            "checar",
            "inspecione",
            "inspecionar",
            "como esta",
            "como ta",
            "caiu",
            "parou",
            "falhou",
            "ta rodando",
            "esta rodando",
            "ta falhando",
            "esta falhando",
        ),
    ):
        return True
    if not has_context_service:
        return False
    return _contains_any(
        normalized,
        (
            "como ele esta",
            "como ele ta",
            "status dele",
            "o estado dele",
            "esse servico",
            "e ele",
        ),
    )


def _looks_like_disk_request(normalized: str) -> bool:
    if _contains_any(normalized, ("disco", "disk", "espaco", "espaço", "storage")):
        return True
    return _contains_any(
        normalized,
        (
            "armazenamento",
            "hd",
            "ssd",
            "espaco livre",
            "espaço livre",
            "sem espaco",
            "sem espaço",
            "lotado",
            "cheio",
        ),
    )


def _looks_like_process_request(normalized: str) -> bool:
    if _contains_any(normalized, ("processo", "processos", "cpu")):
        return True
    return _contains_any(
        normalized,
        (
            "consumindo cpu",
            "consome cpu",
            "comendo cpu",
            "gastando cpu",
            "usando cpu",
            "mais pesados",
            "mais pesado",
            "o que ta pesado",
            "o que esta pesado",
        ),
    )


def _looks_like_process_unit_request(
    normalized: str,
    *,
    has_process_context: bool,
) -> bool:
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
        return True
    if not has_process_context:
        return False
    return _contains_any(
        normalized,
        (
            "esse processo pertence",
            "de que servico ele e",
            "de que serviço ele é",
            "qual servico e esse processo",
            "qual serviço é esse processo",
            "a que servico ele pertence",
            "a que serviço ele pertence",
        ),
    )


def _looks_like_config_read_request(
    normalized: str,
    *,
    has_explicit_path: bool,
    has_context_path: bool,
) -> bool:
    has_read_action = _contains_any(
        normalized,
        (
            "abrir",
            "abra",
            "abre",
            "leia",
            "ler",
            "mostra",
            "mostrar",
            "conteudo",
            "conteúdo",
            "atual",
            "confere",
            "confira",
            "checa",
            "cheque",
            "inspeciona",
            "inspecione",
        ),
    )

    if CONFIG_ARTIFACT_RE.search(normalized):
        return has_explicit_path or has_context_path or has_read_action
    if has_explicit_path and has_read_action:
        return True
    if not has_context_path:
        return False
    return _contains_any(
        normalized,
        (
            "abre esse arquivo",
            "abra esse arquivo",
            "abrir esse arquivo",
            "abre ele",
            "abra ele",
            "me mostra a configuracao atual",
            "me mostra a configuração atual",
            "mostra a configuracao atual",
            "mostra a configuração atual",
            "me mostra a config atual",
            "mostra a config atual",
            "le esse arquivo",
            "leia esse arquivo",
            "conteudo atual",
            "conteúdo atual",
            "confere esse ini",
            "confira esse ini",
            "checa esse ini",
            "cheque esse ini",
            "confere essa config",
            "confira essa config",
        ),
    )


def _looks_like_config_rollback_request(
    normalized: str,
    *,
    has_tracked_backup: bool = False,
) -> bool:
    if _contains_any(
        normalized,
        (
            "rollback",
            "restaure o ultimo backup",
            "restaurar o ultimo backup",
            "desfaca a ultima mudanca",
            "desfazer a ultima mudanca",
            "volte a configuracao anterior",
            "reverte a ultima alteracao",
            "reverta a ultima alteracao",
            "reverter a ultima alteracao",
            "restaure a versao anterior",
            "restaurar a versao anterior",
        ),
    ):
        return True

    has_action = _contains_any(
        normalized,
        (
            "rollback",
            "reverte",
            "reverta",
            "reverter",
            "desfaz",
            "desfaca",
            "desfazer",
            "volta atras",
            "volte atras",
            "voltar atras",
            "restaura",
            "restaure",
            "restaurar",
        ),
    )
    has_explicit_target = _contains_any(
        normalized,
        (
            "ultima mudanca",
            "ultima alteracao",
            "ultimo backup",
            "versao anterior",
            "configuracao anterior",
        ),
    )
    if has_action and has_explicit_target:
        return True

    if not has_tracked_backup:
        return False

    return _contains_any(
        normalized,
        (
            "desfaz isso",
            "desfaca isso",
            "desfazer isso",
            "reverte isso",
            "reverta isso",
            "reverter isso",
            "volta atras",
            "volte atras",
            "voltar atras",
            "restaura isso",
            "restaure isso",
            "restaurar isso",
            "volta para antes",
            "voltar para antes",
        ),
    )


def _is_log_intent(intent: str | None) -> bool:
    return intent in {
        "inspect_logs",
        "inspect_logs_follow_up",
        "investigate_service_failure",
        "compare_logs",
    }


def _is_performance_intent(intent: str | None) -> bool:
    return intent in {
        "diagnose_performance",
        "compare_performance",
    }


def _is_service_intent(intent: str | None) -> bool:
    return intent in {
        "inspect_service_status",
        "inspect_service_status_follow_up",
        "compare_service_status",
    }


def _is_config_intent(intent: str | None) -> bool:
    return intent in {"read_config_file", "compare_config"}


def _guess_service_name_from_context(
    session_context: SessionContext,
    context: dict[str, str],
) -> str | None:
    unit = _context_service_name(context)
    if unit:
        return unit
    if session_context.service is not None:
        return session_context.service.name
    if session_context.process_unit is not None and _looks_like_service_unit(
        session_context.process_unit.unit
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


def _looks_like_service_candidate(value: str) -> bool:
    normalized = _normalize(value)
    return normalized not in {
        "host",
        "sistema",
        "maquina",
        "computador",
        "pc",
        "servidor",
        "ele",
        "isso",
        "servico",
        "service",
        "status",
        "logs",
        "journal",
        "caiu",
        "parou",
        "falhou",
        "rodando",
        "falhando",
        "ativo",
        "ativa",
    }


def _looks_like_process_candidate(value: str) -> bool:
    normalized = _normalize(value)
    return normalized not in {
        "pertence",
        "servico",
        "serviço",
        "service",
        "unit",
        "qual",
        "esse",
        "esse?",
    }


def _observation_returned_lines(
    freshness: ObservationFreshness | None,
    *,
    default: int,
) -> int:
    if freshness is None:
        return default
    returned_lines = freshness.value.get("returned_lines")
    if isinstance(returned_lines, int) and returned_lines > 0:
        return returned_lines
    return default


def _summarize_log_comparison(
    session_context: SessionContext,
    *,
    unit: str | None,
    request_kind: str,
) -> str | None:
    comparison_pair = _recent_comparable_pair(
        session_context,
        key="logs",
        target_key="unit",
        target_value=unit,
    )
    if comparison_pair is None:
        return None

    latest, previous = comparison_pair
    if latest.stale:
        return None

    latest_signal = _summarize_log_signal(latest.value)
    previous_signal = _summarize_log_signal(previous.value)
    if latest_signal is None or previous_signal is None:
        return None

    resolved_unit = (
        _string_or_none(latest.value.get("unit"))
        or _string_or_none(previous.value.get("unit"))
        or unit
        or "system"
    )
    if latest_signal == previous_signal:
        return (
            f"Nao houve mudanca relevante nos logs de `{resolved_unit}`: "
            f"o sinal principal continua sendo {latest_signal}."
        )

    latest_score = _log_signal_score(latest.value)
    previous_score = _log_signal_score(previous.value)
    trend = _comparison_trend(
        request_kind=request_kind,
        latest_score=latest_score,
        previous_score=previous_score,
        changed=latest_signal != previous_signal,
    )
    return f"{trend} nos logs de `{resolved_unit}`: antes {previous_signal}; agora {latest_signal}."


def _summarize_performance_comparison(
    session_context: SessionContext,
    *,
    request_kind: str,
) -> str | None:
    fragments: list[str] = []
    latest_score = 0
    previous_score = 0
    changed = False

    memory_comparison = _summarize_memory_comparison(session_context)
    if memory_comparison is not None:
        fragment, latest_memory_score, previous_memory_score, memory_changed = memory_comparison
        fragments.append(fragment)
        latest_score += latest_memory_score
        previous_score += previous_memory_score
        changed = changed or memory_changed

    process_comparison = _summarize_process_comparison(session_context)
    if process_comparison is not None:
        fragment, latest_process_score, previous_process_score, process_changed = process_comparison
        fragments.append(fragment)
        latest_score += latest_process_score
        previous_score += previous_process_score
        changed = changed or process_changed

    if not fragments:
        return None

    trend = _comparison_trend(
        request_kind=request_kind,
        latest_score=latest_score,
        previous_score=previous_score,
        changed=changed,
    )
    return f"{trend} no diagnóstico de desempenho: " + "; ".join(fragments) + "."


def _summarize_log_observation(
    freshness: ObservationFreshness,
    *,
    root_cause: bool,
) -> str | None:
    entry_texts = _extract_log_entry_texts(freshness.value.get("entries"))
    if not entry_texts:
        return None

    unit = _string_or_none(freshness.value.get("unit")) or "system"
    ranked_signals = _collect_log_signals(entry_texts)
    if not ranked_signals:
        return None

    if root_cause:
        return f"Sinal principal nos logs de `{unit}`: {ranked_signals[0].summary}."

    fragments = "; ".join(signal.summary for signal in ranked_signals[:2])
    return f"Pontos mais relevantes nos logs de `{unit}`: {fragments}."


def _summarize_service_comparison(
    session_context: SessionContext,
    *,
    service_name: str | None,
    request_kind: str,
) -> str | None:
    comparison_pair = _recent_comparable_pair(
        session_context,
        key="service",
        target_key="service",
        target_value=service_name,
    )
    if comparison_pair is None:
        return None

    latest, previous = comparison_pair
    if latest.stale:
        return None

    latest_service = _string_or_none(latest.value.get("service")) or service_name
    previous_service = _string_or_none(previous.value.get("service")) or latest_service
    if latest_service is None or previous_service != latest_service:
        return None

    latest_active = _string_or_none(latest.value.get("activestate")) or "desconhecido"
    latest_sub = _string_or_none(latest.value.get("substate")) or "desconhecido"
    previous_active = _string_or_none(previous.value.get("activestate")) or "desconhecido"
    previous_sub = _string_or_none(previous.value.get("substate")) or "desconhecido"
    if (latest_active, latest_sub) == (previous_active, previous_sub):
        return (
            f"Nao houve mudanca relevante no servico `{latest_service}`: "
            f"continua active={latest_active}, sub={latest_sub}."
        )

    trend = _comparison_trend(
        request_kind=request_kind,
        latest_score=_service_state_score(latest_active, latest_sub),
        previous_score=_service_state_score(previous_active, previous_sub),
        changed=True,
    )
    return (
        f"{trend} no servico `{latest_service}`: "
        f"antes active={previous_active}, sub={previous_sub}; "
        f"agora active={latest_active}, sub={latest_sub}."
    )


def _summarize_memory_comparison(
    session_context: SessionContext,
) -> tuple[str, int, int, bool] | None:
    comparison_pair = _recent_comparable_pair(session_context, key="memory")
    if comparison_pair is None:
        return None

    latest, previous = comparison_pair
    if latest.stale:
        return None

    latest_memory = _as_float(latest.value.get("memory_used_percent"))
    latest_swap = _as_float(latest.value.get("swap_used_percent"))
    previous_memory = _as_float(previous.value.get("memory_used_percent"))
    previous_swap = _as_float(previous.value.get("swap_used_percent"))
    if (
        latest_memory is None
        or latest_swap is None
        or previous_memory is None
        or previous_swap is None
    ):
        return None

    latest_summary = f"RAM {latest_memory:.1f}% e swap {latest_swap:.1f}%"
    previous_summary = f"RAM {previous_memory:.1f}% e swap {previous_swap:.1f}%"
    changed = latest_summary != previous_summary
    if changed:
        fragment = f"memória {previous_summary} -> {latest_summary}"
    else:
        fragment = f"memória continua {latest_summary}"
    return (
        fragment,
        _memory_pressure_score(latest_memory, latest_swap),
        _memory_pressure_score(previous_memory, previous_swap),
        changed,
    )


def _summarize_process_comparison(
    session_context: SessionContext,
) -> tuple[str, int, int, bool] | None:
    comparison_pair = _recent_comparable_pair(session_context, key="processes")
    if comparison_pair is None:
        return None

    latest, previous = comparison_pair
    if latest.stale:
        return None

    latest_process = _top_process_snapshot(latest.value)
    previous_process = _top_process_snapshot(previous.value)
    if latest_process is None or previous_process is None:
        return None

    latest_command, latest_cpu = latest_process
    previous_command, previous_cpu = previous_process
    changed = (latest_command, latest_cpu) != (previous_command, previous_cpu)
    if changed:
        fragment = (
            "processo mais quente "
            f"{previous_command}({previous_cpu:.1f}%) -> {latest_command}({latest_cpu:.1f}%)"
        )
    else:
        fragment = f"processo mais quente continua {latest_command}({latest_cpu:.1f}%)"
    return (
        fragment,
        _process_pressure_score(latest_cpu),
        _process_pressure_score(previous_cpu),
        changed,
    )


def _summarize_config_observation(freshness: ObservationFreshness) -> str | None:
    content = freshness.value.get("content")
    if not isinstance(content, str) or not content.strip():
        return None

    path = _string_or_none(freshness.value.get("path")) or "arquivo gerenciado"
    selected_lines = _select_config_focus_lines(content)
    if not selected_lines:
        return None
    fragments = "; ".join(_truncate_summary_fragment(line, max_chars=80) for line in selected_lines)
    return f"Trechos mais relevantes de `{path}`: {fragments}."


def _summarize_config_comparison(
    session_context: SessionContext,
    *,
    path: str | None,
) -> str | None:
    comparison_pair = _recent_config_content_pair(session_context, path=path)
    if comparison_pair is None:
        return None

    latest, previous = comparison_pair
    if latest.stale:
        return None

    latest_path = _string_or_none(latest.value.get("path"))
    previous_path = _string_or_none(previous.value.get("path"))
    resolved_path = latest_path or previous_path or path or "arquivo gerenciado"
    latest_content = latest.value.get("content")
    previous_content = previous.value.get("content")
    if not isinstance(latest_content, str) or not isinstance(previous_content, str):
        return None

    if latest_content == previous_content:
        return f"Nao houve mudanca relevante em `{resolved_path}` entre as duas últimas leituras."

    fragments = _build_config_change_fragments(previous_content, latest_content)
    if not fragments:
        return f"As mudanças em `{resolved_path}` ficaram restritas a comentários, espaços em branco ou reordenação."
    return f"Mudanças mais relevantes em `{resolved_path}`: {'; '.join(fragments)}."


def _extract_log_entry_texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for raw_entry in value:
        rendered = _render_log_entry(raw_entry)
        if rendered:
            items.append(rendered)
    return items


def _render_log_entry(entry: object) -> str | None:
    if isinstance(entry, str):
        normalized = " ".join(entry.split())
        return normalized or None
    if isinstance(entry, dict):
        timestamp = _string_or_none(entry.get("timestamp"))
        message = _string_or_none(entry.get("message"))
        if timestamp and message:
            return f"{timestamp}: {message}"
        return message
    return None


def _summarize_log_signal(value: dict[str, object]) -> str | None:
    signal = _primary_log_signal(value)
    return signal.summary if signal is not None else None


def _log_signal_score(value: dict[str, object]) -> int:
    signal = _primary_log_signal(value)
    return signal.score if signal is not None else 0


def _primary_log_signal(value: dict[str, object]) -> LogSignal | None:
    signals = _collect_log_signals(_extract_log_entry_texts(value.get("entries")))
    if not signals:
        return None
    return signals[0]


def _collect_log_signals(entry_texts: list[str]) -> list[LogSignal]:
    pattern_buckets: dict[str, _LogPatternBucket] = {}
    generic_signals: list[LogSignal] = []

    for index, text in enumerate(entry_texts):
        kind, label, pattern_score = _classify_log_pattern(text)
        summary = _log_signal_excerpt(text)
        score = max(pattern_score, _log_entry_score(text))
        example_rank = _log_pattern_example_rank(kind, text)
        if kind is None or label is None:
            generic_signals.append(
                LogSignal(
                    kind="generic",
                    summary=summary,
                    score=score,
                    index=index,
                )
            )
            continue

        bucket = pattern_buckets.get(kind)
        if bucket is None:
            pattern_buckets[kind] = _LogPatternBucket(
                label=label,
                count=1,
                score=score,
                example_rank=example_rank,
                index=index,
                example=summary,
            )
            continue

        bucket.count += 1
        current_score = bucket.score
        current_rank = bucket.example_rank
        current_index = bucket.index
        if (score, example_rank, index) >= (current_score, current_rank, current_index):
            bucket.score = score
            bucket.example_rank = example_rank
            bucket.index = index
            bucket.example = summary

    signals = [
        LogSignal(
            kind=kind,
            summary=_format_log_pattern_summary(
                label=bucket.label,
                count=bucket.count,
                example=bucket.example,
            ),
            score=bucket.score + (1 if bucket.count > 1 else 0),
            index=bucket.index,
        )
        for kind, bucket in pattern_buckets.items()
    ]
    signals.extend(generic_signals)
    signals.sort(
        key=lambda item: (item.score, item.kind != "generic", item.index),
        reverse=True,
    )
    return signals


def _classify_log_pattern(text: str) -> tuple[str | None, str | None, int]:
    normalized = _normalize(text)
    for kind, label, score, terms in LOG_PATTERN_DEFINITIONS:
        if any(term in normalized for term in terms):
            return kind, label, score
    return None, None, 0


def _format_log_pattern_summary(*, label: str, count: int, example: str) -> str:
    if count > 1:
        return f"{label} ({count} entradas): {example}"
    return f"{label}: {example}"


def _log_pattern_example_rank(kind: str | None, text: str) -> int:
    if kind is None:
        return 0

    normalized = _normalize(text)
    if kind == "restart_loop":
        if "start request repeated too quickly" in normalized:
            return 3
        if any(
            term in normalized
            for term in (
                "scheduled restart job",
                "restart counter",
                "restarting too quickly",
                "service hold-off time over",
                "back-off restarting failed unit",
            )
        ):
            return 2
        if any(
            term in normalized
            for term in (
                "main process exited",
                "control process exited",
                "failed with result 'exit-code'",
                "status=1/failure",
            )
        ):
            return 1
    if kind == "dependency_failure":
        if "dependency failed for" in normalized:
            return 2
        if "failed with result 'dependency'" in normalized:
            return 1
    if kind == "environment_failure":
        if any(
            term in normalized
            for term in (
                "failed to load environment",
                "failed at step exec",
                "failed at step chdir",
                "failed at step user",
            )
        ):
            return 2
        if any(
            term in normalized
            for term in (
                "no such file or directory",
                "bad unit file setting",
                "exec format error",
                "invalid argument",
            )
        ):
            return 1
    return 0


def _log_signal_excerpt(text: str) -> str:
    without_timestamp = LEADING_TIMESTAMP_RE.sub("", text, count=1).strip()
    candidate = without_timestamp or text
    return _truncate_summary_fragment(candidate, max_chars=120)


def _top_process_snapshot(value: dict[str, object]) -> tuple[str, float] | None:
    processes = value.get("processes")
    if not isinstance(processes, list):
        return None

    best_command: str | None = None
    best_cpu: float | None = None
    for item in processes:
        if not isinstance(item, dict):
            continue
        command = _string_or_none(item.get("command"))
        cpu = _as_float(item.get("cpu_percent"))
        if command is None or cpu is None:
            continue
        if best_cpu is None or cpu > best_cpu:
            best_command = command
            best_cpu = cpu
    if best_command is None or best_cpu is None:
        return None
    return best_command, best_cpu


def _recent_config_content_pair(
    session_context: SessionContext,
    *,
    path: str | None,
) -> tuple[RecentObservationContext, RecentObservationContext] | None:
    items = session_context.recent_observations.get("config", ())
    if not items:
        return None

    resolved_path = path
    if resolved_path is None:
        for item in items:
            candidate_path = _string_or_none(item.value.get("path"))
            content = item.value.get("content")
            if candidate_path is not None and isinstance(content, str) and content.strip():
                resolved_path = candidate_path
                break
    if resolved_path is None:
        return None

    comparable: list[RecentObservationContext] = []
    for item in items:
        if _string_or_none(item.value.get("path")) != resolved_path:
            continue
        content = item.value.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        comparable.append(item)
        if len(comparable) >= 2:
            break
    if len(comparable) < 2:
        return None
    return comparable[0], comparable[1]


def _build_config_change_fragments(previous_content: str, latest_content: str) -> list[str]:
    previous_entries = _normalize_config_entries(previous_content)
    latest_entries = _normalize_config_entries(latest_content)
    if previous_entries == latest_entries:
        return []

    fragments: list[str] = []
    overflow_count = 0
    section_order = _ordered_config_sections(previous_entries, latest_entries)
    for section in section_order:
        fragment, total_change_count, shown_change_count = _summarize_config_section_changes(
            section,
            previous_entries,
            latest_entries,
        )
        if fragment is None or total_change_count == 0:
            continue
        if len(fragments) < 4:
            fragments.append(fragment)
            overflow_count += max(0, total_change_count - shown_change_count)
            continue
        overflow_count += total_change_count

    if overflow_count > 0:
        if len(fragments) >= 4:
            fragments = fragments[:3]
        fragments.append(f"+{overflow_count} mudanças adicionais")
    return fragments


def _normalize_config_entries(content: str) -> list[_ConfigLineEntry]:
    entries: list[_ConfigLineEntry] = []
    current_section: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip() or None
            continue
        entries.append(
            _ConfigLineEntry(
                section=current_section,
                line=line,
                key=_config_line_key(line),
            )
        )
    return entries


def _ordered_config_sections(
    previous_entries: list[_ConfigLineEntry],
    latest_entries: list[_ConfigLineEntry],
) -> list[str | None]:
    ordered: list[str | None] = []
    seen: set[str | None] = set()
    for entry in (*previous_entries, *latest_entries):
        if entry.section in seen:
            continue
        ordered.append(entry.section)
        seen.add(entry.section)
    return ordered


def _summarize_config_section_changes(
    section: str | None,
    previous_entries: list[_ConfigLineEntry],
    latest_entries: list[_ConfigLineEntry],
) -> tuple[str | None, int, int]:
    previous_section_entries = [entry for entry in previous_entries if entry.section == section]
    latest_section_entries = [entry for entry in latest_entries if entry.section == section]
    if not previous_section_entries and not latest_section_entries:
        return None, 0, 0

    label = _format_config_section_label(section)
    if not previous_section_entries:
        added_lines = [
            _truncate_summary_fragment(entry.line, max_chars=80) for entry in latest_section_entries
        ]
        if not added_lines:
            return f"{label} adicionada", 1, 1
        shown_lines = ", ".join(added_lines[:2])
        return f"{label} adicionada: {shown_lines}", len(added_lines), min(len(added_lines), 2)

    if not latest_section_entries:
        removed_lines = [
            _truncate_summary_fragment(entry.line, max_chars=80)
            for entry in previous_section_entries
        ]
        if not removed_lines:
            return f"{label} removida", 1, 1
        shown_lines = ", ".join(removed_lines[:2])
        return f"{label} removida: {shown_lines}", len(removed_lines), min(len(removed_lines), 2)

    change_items = _compare_config_section_entries(previous_section_entries, latest_section_entries)
    if not change_items:
        return None, 0, 0
    shown_items = ", ".join(change_items[:2])
    if section is None:
        return shown_items, len(change_items), min(len(change_items), 2)
    return f"{label}: {shown_items}", len(change_items), min(len(change_items), 2)


def _compare_config_section_entries(
    previous_entries: list[_ConfigLineEntry],
    latest_entries: list[_ConfigLineEntry],
) -> list[str]:
    change_items: list[str] = []

    previous_keyed: dict[str, _ConfigLineEntry] = {}
    latest_keyed: dict[str, _ConfigLineEntry] = {}
    ordered_keys: list[str] = []
    previous_unkeyed: list[str] = []
    latest_unkeyed: list[str] = []

    for entry in previous_entries:
        if entry.key is None:
            previous_unkeyed.append(entry.line)
            continue
        scoped_key = entry.key
        if scoped_key not in previous_keyed:
            ordered_keys.append(scoped_key)
        previous_keyed[scoped_key] = entry

    for entry in latest_entries:
        if entry.key is None:
            latest_unkeyed.append(entry.line)
            continue
        scoped_key = entry.key
        if scoped_key not in previous_keyed and scoped_key not in latest_keyed:
            ordered_keys.append(scoped_key)
        latest_keyed[scoped_key] = entry

    for scoped_key in ordered_keys:
        previous_entry = previous_keyed.get(scoped_key)
        latest_entry = latest_keyed.get(scoped_key)
        if previous_entry is not None and latest_entry is not None:
            fragment = _format_config_line_change(previous_entry.line, latest_entry.line)
            if fragment:
                change_items.append(fragment)
            continue
        if previous_entry is not None:
            change_items.append(
                f"removido {_truncate_summary_fragment(previous_entry.line, max_chars=80)}"
            )
            continue
        if latest_entry is not None:
            change_items.append(
                f"adicionado {_truncate_summary_fragment(latest_entry.line, max_chars=80)}"
            )

    change_items.extend(_compare_unkeyed_config_lines(previous_unkeyed, latest_unkeyed))
    return change_items


def _compare_unkeyed_config_lines(previous_lines: list[str], latest_lines: list[str]) -> list[str]:
    if previous_lines == latest_lines:
        return []

    fragments: list[str] = []
    matcher = difflib.SequenceMatcher(a=previous_lines, b=latest_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_lines = previous_lines[i1:i2]
        new_lines = latest_lines[j1:j2]
        shared = min(len(old_lines), len(new_lines))
        for index in range(shared):
            fragments.append(_format_replaced_config_line(old_lines[index], new_lines[index]))
        for line in old_lines[shared:]:
            fragments.append(f"removido {_truncate_summary_fragment(line, max_chars=80)}")
        for line in new_lines[shared:]:
            fragments.append(f"adicionado {_truncate_summary_fragment(line, max_chars=80)}")
    return fragments


def _format_config_section_label(section: str | None) -> str:
    if section is None:
        return "raiz"
    return f"[{section}]"


def _format_config_line_change(previous_line: str, latest_line: str) -> str | None:
    if previous_line == latest_line:
        return None
    previous_key = _config_line_key(previous_line)
    latest_key = _config_line_key(latest_line)
    previous_fragment = _truncate_summary_fragment(previous_line, max_chars=80)
    latest_fragment = _truncate_summary_fragment(latest_line, max_chars=80)
    if previous_key and previous_key == latest_key:
        return f"{previous_fragment} -> {latest_fragment}"
    return _format_replaced_config_line(previous_fragment, latest_fragment)


def _format_replaced_config_line(previous_line: str, latest_line: str) -> str:
    previous_fragment = _truncate_summary_fragment(previous_line, max_chars=80)
    latest_fragment = _truncate_summary_fragment(latest_line, max_chars=80)
    return f"substituído {previous_fragment} por {latest_fragment}"


def _config_line_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped
    for separator in ("=", ":"):
        if separator in stripped:
            return stripped.split(separator, maxsplit=1)[0].strip()
    return None


def _log_entry_score(text: str) -> int:
    normalized = _normalize(text)
    score = 0
    for term in (
        "failed",
        "failure",
        "erro",
        "error",
        "fatal",
        "denied",
        "refused",
        "timeout",
        "timed out",
        "unable",
        "cannot",
        "nao foi possivel",
        "não foi possível",
        "panic",
        "crash",
        "segfault",
        "oom",
        "killed",
        "exited",
        "not found",
        "permission",
        "operation not permitted",
        "connection refused",
        "restart counter",
        "repeated too quickly",
        "dependency failed",
        "failed with result 'dependency'",
        "failed to load environment",
        "environment file",
        "failed at step exec",
        "failed at step chdir",
        "no such file or directory",
        "bad unit file setting",
        "watchdog",
        "traceback",
    ):
        if term in normalized:
            score += 2
    for term in (
        "warn",
        "warning",
        "falhou",
        "parou",
        "restart",
        "scheduled restart job",
        "exception",
    ):
        if term in normalized:
            score += 1
    return score


def _select_config_focus_lines(content: str) -> list[str]:
    selected: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        if line.startswith("[") and line.endswith("]"):
            selected.append(line)
            continue
        if "=" in line or ":" in line:
            selected.append(line)
            continue
        if len(line) <= 80:
            selected.append(line)
        if len(selected) >= 4:
            break
    return selected[:4]


def _truncate_summary_fragment(text: str, *, max_chars: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _latest_recent_observation(
    session_context: SessionContext,
    key: str,
) -> RecentObservationContext | None:
    items = session_context.recent_observations.get(key, ())
    if not items:
        return None
    return items[0]


def _has_stale_recent_observation(session_context: SessionContext, key: str) -> bool:
    latest = _latest_recent_observation(session_context, key)
    return latest.stale if latest is not None else False


def _recent_comparable_pair(
    session_context: SessionContext,
    *,
    key: str,
    target_key: str | None = None,
    target_value: str | None = None,
) -> tuple[RecentObservationContext, RecentObservationContext] | None:
    items = session_context.recent_observations.get(key, ())
    if len(items) < 2:
        return None
    if target_key is None:
        return items[0], items[1]

    resolved_target = target_value
    if resolved_target is None:
        resolved_target = _string_or_none(items[0].value.get(target_key))
    if resolved_target is None:
        return None

    comparable = [
        item for item in items if _string_or_none(item.value.get(target_key)) == resolved_target
    ]
    if len(comparable) < 2:
        return None
    return comparable[0], comparable[1]


def _comparison_trend(
    *,
    request_kind: str,
    latest_score: int,
    previous_score: int,
    changed: bool,
) -> str:
    if not changed:
        return "Nao houve mudanca relevante"
    if latest_score < previous_score:
        if request_kind == "worse":
            return "Nao piorou, melhorou"
        return "Melhorou"
    if latest_score > previous_score:
        if request_kind == "better":
            return "Nao melhorou, piorou"
        return "Piorou"
    return "Mudou"


def _needs_comparable_refresh(session_context: SessionContext, key: str) -> bool:
    latest = _latest_recent_observation(session_context, key)
    if latest is None:
        return True
    if latest.stale:
        return True
    return len(session_context.recent_observations.get(key, ())) < 2


def _memory_pressure_score(memory_used: float, swap_used: float) -> int:
    if memory_used >= 90 or swap_used >= 20:
        return 4
    if memory_used >= 80 or swap_used >= 10:
        return 3
    if memory_used >= 70:
        return 2
    if memory_used >= 60:
        return 1
    return 0


def _process_pressure_score(cpu_percent: float) -> int:
    if cpu_percent >= 90:
        return 2
    if cpu_percent >= 80:
        return 1
    return 0


def _service_state_score(active_state: str, sub_state: str) -> int:
    active = _normalize(active_state)
    sub = _normalize(sub_state)
    if active == "failed" or sub == "failed":
        return 4
    if active in {"inactive", "deactivating"}:
        return 3
    if sub in {"dead", "exited"}:
        return 2
    if active in {"activating", "reloading"}:
        return 1
    if active == "active" and sub == "running":
        return 0
    return 1


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
            fragments.append(f"correlacao: {query_name} -> {process_unit.unit}{scope_text}")

    if session_context.service is not None:
        service = session_context.service
        if service.active_state and service.sub_state:
            fragments.append(
                f"serviço: {service.name}: active={service.active_state}, sub={service.sub_state}"
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
