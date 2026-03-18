from __future__ import annotations

import re
import unicodedata

from master_control.agent.planner import ExecutionPlan, PlanStep
from master_control.agent.observations import ObservationFreshness
from master_control.agent.session_summary import parse_session_summary
from master_control.providers.base import ConversationMessage, ProviderRequest, ProviderResponse


SERVICE_NAME_RE = re.compile(
    r"(?:servi(?:co|ço)|service|unit|status)\s+(?:(?:do|da|de|of|for)\s+)?([A-Za-z0-9_.@-]+)",
    re.IGNORECASE,
)
JOURNAL_UNIT_RE = re.compile(
    r"(?:logs?|journal)\s+(?:(?:do|da|de|of|for)\s+)?([A-Za-z0-9_.@-]+)",
    re.IGNORECASE,
)
PATH_RE = re.compile(r"(/[^\s,;:]+)")
INTEGER_RE = re.compile(r"\b(\d{1,3})\b")


class HeuristicProvider:
    name = "heuristic"

    def plan(self, request: ProviderRequest) -> ProviderResponse:
        available_tools = {spec.name for spec in request.available_tools}
        message = request.user_message.strip()
        normalized = _normalize(message)
        service_scope = _extract_service_scope(normalized)
        last_context = _extract_context(request.conversation_history, request.session_summary)
        summary_map = parse_session_summary(request.session_summary)
        freshness_map = {item.key: item for item in request.observation_freshness}

        if _contains_any(normalized, ("diagnostico", "diagnosticar", "lento", "lentidao", "slow")):
            if "memory_usage" in available_tools and _needs_refresh(freshness_map, "memory"):
                message_text = "Vou começar verificando a memória do sistema."
                if "memory" in freshness_map and freshness_map["memory"].stale:
                    message_text = "Vou atualizar os dados de memória antes de continuar o diagnóstico."
                return ProviderResponse(
                    message=message_text,
                    plan=ExecutionPlan(
                        intent="diagnose_performance",
                        steps=(
                            PlanStep(
                                tool_name="memory_usage",
                                rationale="Check memory pressure before deeper diagnosis.",
                            ),
                        ),
                    ),
                )

            if "top_processes" in available_tools and _needs_refresh(freshness_map, "processes"):
                message_text = "Agora vou verificar os processos com maior uso de CPU."
                if "processes" in freshness_map and freshness_map["processes"].stale:
                    message_text = "Vou atualizar a lista de processos antes de seguir com o diagnóstico."
                return ProviderResponse(
                    message=message_text,
                    plan=ExecutionPlan(
                        intent="diagnose_performance",
                        steps=(
                            PlanStep(
                                tool_name="top_processes",
                                rationale="Inspect the highest CPU consumers.",
                                arguments={"limit": _extract_int(message, default=5, min_value=1, max_value=10)},
                            ),
                        ),
                    ),
                )

            candidate_service = _guess_service_name_from_context(summary_map, last_context)
            if (
                "service_status" in available_tools
                and candidate_service
                and _needs_refresh(freshness_map, "service")
            ):
                message_text = f"Vou correlacionar isso com o estado do serviço `{candidate_service}`."
                if "service" in freshness_map and freshness_map["service"].stale:
                    message_text = (
                        f"Vou atualizar o estado do serviço `{candidate_service}` antes de concluir."
                    )
                return ProviderResponse(
                    message=message_text,
                    plan=ExecutionPlan(
                        intent="diagnose_performance",
                        steps=(
                            PlanStep(
                                tool_name="service_status",
                                rationale="Inspect the service related to the hottest process.",
                                arguments=_with_service_scope({"name": candidate_service}, service_scope),
                            ),
                        ),
                    ),
                )

            return ProviderResponse(
                message=_build_diagnostic_summary(summary_map),
                plan=None,
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
            return ProviderResponse(
                message="Vou montar um resumo rápido do host.",
                plan=ExecutionPlan(intent="host_overview", steps=tuple(steps)),
            )

        if _contains_any(normalized, ("log", "logs", "journal")) and "read_journal" in available_tools:
            unit = _extract_journal_unit(message) or last_context.get("unit")
            lines = _extract_int(message, default=20, min_value=1, max_value=200)
            return ProviderResponse(
                message="Vou ler as entradas recentes do journal.",
                plan=ExecutionPlan(
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
                ),
            )

        if _contains_any(normalized, ("recarregar", "recarregue", "reload")) and (
            "reload_service" in available_tools
        ):
            service_name = _extract_service_name(message) or last_context.get("unit")
            if service_name:
                return ProviderResponse(
                    message=f"Posso recarregar o serviço `{service_name}` com confirmação explícita.",
                    plan=ExecutionPlan(
                        intent="reload_service",
                        steps=(
                            PlanStep(
                                tool_name="reload_service",
                                rationale="Reload the requested service after explicit confirmation.",
                                arguments=_with_service_scope({"name": service_name}, service_scope),
                            ),
                        ),
                    ),
                )

        if _contains_any(normalized, ("reiniciar", "reinicie", "restart")) and (
            "restart_service" in available_tools
        ):
            service_name = _extract_service_name(message) or last_context.get("unit")
            if service_name:
                return ProviderResponse(
                    message=f"Posso reiniciar o serviço `{service_name}` com confirmação explícita.",
                    plan=ExecutionPlan(
                        intent="restart_service",
                        steps=(
                            PlanStep(
                                tool_name="restart_service",
                                rationale="Restart the requested service after explicit confirmation.",
                                arguments=_with_service_scope({"name": service_name}, service_scope),
                            ),
                        ),
                    ),
                )

        if _contains_any(normalized, ("servico", "serviço", "service", "status")) and (
            "service_status" in available_tools
        ):
            service_name = _extract_service_name(message) or last_context.get("unit")
            if service_name:
                return ProviderResponse(
                    message=f"Vou verificar o status do serviço `{service_name}`.",
                    plan=ExecutionPlan(
                        intent="inspect_service_status",
                        steps=(
                            PlanStep(
                                tool_name="service_status",
                                rationale="Check the unit state in systemd.",
                                arguments=_with_service_scope({"name": service_name}, service_scope),
                            ),
                        ),
                    ),
                )

        if _looks_like_log_follow_up(normalized) and "read_journal" in available_tools:
            unit = last_context.get("unit")
            if unit:
                lines = _extract_int(message, default=20, min_value=1, max_value=200)
                return ProviderResponse(
                    message=f"Vou continuar a inspeção dos logs de `{unit}`.",
                    plan=ExecutionPlan(
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
                    ),
                )

        if _looks_like_service_follow_up(normalized) and "service_status" in available_tools:
            unit = last_context.get("unit")
            if unit:
                return ProviderResponse(
                    message=f"Vou continuar a inspeção do serviço `{unit}`.",
                    plan=ExecutionPlan(
                        intent="inspect_service_status_follow_up",
                        steps=(
                            PlanStep(
                                tool_name="service_status",
                                rationale="Reuse the last referenced unit from session history.",
                                arguments=_with_service_scope({"name": unit}, service_scope),
                            ),
                        ),
                    ),
                )

        if _contains_any(normalized, ("disco", "disk", "espaco", "espaço", "storage")) and (
            "disk_usage" in available_tools
        ):
            path = _extract_path(message) or "/"
            return ProviderResponse(
                message=f"Vou verificar o uso de disco em `{path}`.",
                plan=ExecutionPlan(
                    intent="inspect_disk_usage",
                    steps=(
                        PlanStep(
                            tool_name="disk_usage",
                            rationale="Inspect filesystem utilization for the requested path.",
                            arguments={"path": path},
                        ),
                    ),
                ),
            )

        if _contains_any(normalized, ("arquivo", "config", "configuracao", "configuração")) and (
            "read_config_file" in available_tools
        ):
            path = _extract_path(message) or last_context.get("path")
            if path:
                return ProviderResponse(
                    message=f"Vou ler o arquivo gerenciado `{path}`.",
                    plan=ExecutionPlan(
                        intent="read_config_file",
                        steps=(
                            PlanStep(
                                tool_name="read_config_file",
                                rationale="Read the requested managed configuration file.",
                                arguments={"path": path},
                            ),
                        ),
                    ),
                )

        if _contains_any(normalized, ("memoria", "memória", "ram", "swap")) and (
            "memory_usage" in available_tools
        ):
            return ProviderResponse(
                message="Vou verificar a memória do sistema.",
                plan=ExecutionPlan(
                    intent="inspect_memory",
                    steps=(
                        PlanStep(
                            tool_name="memory_usage",
                            rationale="Inspect RAM and swap usage.",
                        ),
                    ),
                ),
            )

        if _contains_any(normalized, ("processo", "processos", "cpu")) and (
            "top_processes" in available_tools
        ):
            limit = _extract_int(message, default=5, min_value=1, max_value=20)
            return ProviderResponse(
                message="Vou listar os processos com maior uso de CPU.",
                plan=ExecutionPlan(
                    intent="inspect_processes",
                    steps=(
                        PlanStep(
                            tool_name="top_processes",
                            rationale="Show the most CPU-intensive processes.",
                            arguments={"limit": limit},
                        ),
                    ),
                ),
            )

        if _contains_any(normalized, ("sistema", "host", "hostname")) and (
            "system_info" in available_tools
        ):
            return ProviderResponse(
                message="Vou coletar as informações básicas do host.",
                plan=ExecutionPlan(
                    intent="inspect_system_info",
                    steps=(
                        PlanStep(
                            tool_name="system_info",
                            rationale="Collect basic host metadata.",
                        ),
                    ),
                ),
            )

        return ProviderResponse(
            message=(
                "Ainda não consegui mapear esse pedido para uma ação segura. "
                "Posso inspecionar memória, disco, processos, status de serviço, logs do journal e informações básicas do host."
            )
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


def _extract_service_scope(normalized_text: str) -> str:
    if any(
        token in normalized_text
        for token in ("servico de usuario", "servico do usuario", "user service", "service user")
    ):
        return "user"
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


def _extract_history_context(
    conversation_history: tuple[ConversationMessage, ...],
) -> dict[str, str]:
    for message in reversed(conversation_history):
        if message.role != "user":
            continue
        unit = _extract_journal_unit(message.content) or _extract_service_name(message.content)
        path = _extract_path(message.content)
        if unit:
            return {"unit": unit}
        if path:
            return {"path": path}
    return {}


def _extract_summary_context(session_summary: str | None) -> dict[str, str]:
    if not session_summary:
        return {}

    context: dict[str, str] = {}
    for line in session_summary.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", maxsplit=1)
        normalized_key = key.strip()
        normalized_value = value.strip()
        if not normalized_value:
            continue
        if normalized_key == "tracked_unit":
            context["unit"] = normalized_value
        if normalized_key == "tracked_path":
            context["path"] = normalized_value
    return context


def _extract_context(
    conversation_history: tuple[ConversationMessage, ...],
    session_summary: str | None,
) -> dict[str, str]:
    history_context = _extract_history_context(conversation_history)
    summary_context = _extract_summary_context(session_summary)
    return {
        **summary_context,
        **history_context,
    }


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


def _guess_service_name_from_context(
    summary_map: dict[str, str],
    context: dict[str, str],
) -> str | None:
    if "service" in summary_map:
        service_line = summary_map["service"]
        if ":" in service_line:
            return service_line.split(":", maxsplit=1)[0].strip()

    unit = context.get("unit")
    if unit:
        return unit

    process_line = summary_map.get("processes")
    if not process_line:
        return None
    first_item = process_line.split(",", maxsplit=1)[0].strip()
    if "(" in first_item:
        first_item = first_item.split("(", maxsplit=1)[0].strip()
    first_item = first_item.rstrip(":")
    if not first_item:
        return None
    return first_item


def _build_diagnostic_summary(summary_map: dict[str, str]) -> str:
    fragments: list[str] = []
    if "memory" in summary_map:
        fragments.append(f"memória: {summary_map['memory']}")
    if "processes" in summary_map:
        fragments.append(f"processos: {summary_map['processes']}")
    if "service" in summary_map:
        fragments.append(f"serviço: {summary_map['service']}")

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
