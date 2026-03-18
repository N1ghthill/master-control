from __future__ import annotations

from dataclasses import dataclass, field

from master_control.agent.observations import ObservationFreshness, format_duration
from master_control.agent.session_context import (
    ConfigContext,
    ServiceContext,
    SessionContext,
    build_session_context,
)


@dataclass(frozen=True, slots=True)
class SessionInsight:
    key: str
    severity: str
    message: str
    target: str | None = None
    action_tool_name: str | None = None
    action_title: str | None = None
    action_arguments: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "key": self.key,
            "severity": self.severity,
            "message": self.message,
        }
        if self.target:
            payload["target"] = self.target
        if self.action_tool_name:
            payload["action"] = {
                "kind": "run_tool",
                "tool_name": self.action_tool_name,
                "title": self.action_title,
                "arguments": dict(self.action_arguments),
            }
        return payload


def collect_session_insights(summary_text: str | None) -> list[SessionInsight]:
    return collect_session_insights_with_freshness(summary_text, ())


def collect_session_insights_with_freshness(
    summary_text: str | None,
    observation_freshness: tuple[ObservationFreshness, ...] | list[ObservationFreshness],
    *,
    session_context: SessionContext | None = None,
) -> list[SessionInsight]:
    resolved_context = session_context or build_session_context(summary_text, observation_freshness)
    return collect_session_insights_from_context(
        resolved_context,
        observation_freshness,
    )


def collect_session_insights_from_context(
    session_context: SessionContext,
    observation_freshness: tuple[ObservationFreshness, ...] | list[ObservationFreshness],
) -> list[SessionInsight]:
    insights: list[SessionInsight] = []
    freshness_by_key = {item.key: item for item in observation_freshness}

    disk_context = session_context.disk
    if disk_context is not None:
        stale_refresh = _build_stale_refresh_insight("disk", freshness_by_key.get("disk"))
        if stale_refresh is not None:
            insights.append(stale_refresh)
        else:
            path = disk_context.path or "/"
            used_percent = disk_context.used_percent
            if used_percent is not None:
                if used_percent >= 90:
                    insights.append(
                        SessionInsight(
                            key="disk_pressure",
                            severity="critical",
                            target=path,
                            message=(
                                f"Uso de disco alto em `{path}` ({used_percent:.1f}%). "
                                "Vale revisar arquivos grandes e liberar espaço antes de mudanças."
                            ),
                        )
                    )
                elif used_percent >= 80:
                    insights.append(
                        SessionInsight(
                            key="disk_pressure",
                            severity="warning",
                            target=path,
                            message=(
                                f"Uso de disco elevado em `{path}` ({used_percent:.1f}%). "
                                "Vale inspecionar os diretórios mais pesados."
                            ),
                        )
                    )

    memory_context = session_context.memory
    if memory_context is not None:
        stale_refresh = _build_stale_refresh_insight("memory", freshness_by_key.get("memory"))
        if stale_refresh is not None:
            insights.append(stale_refresh)
        else:
            memory_used = memory_context.memory_used_percent
            swap_used = memory_context.swap_used_percent
            if memory_used is not None and swap_used is not None:
                if memory_used >= 90 or swap_used >= 20:
                    insights.append(
                        SessionInsight(
                            key="memory_pressure",
                            severity="warning",
                            target="memory",
                            message=(
                                f"Pressão de memória observada: RAM {memory_used:.1f}% e swap {swap_used:.1f}%. "
                                "Vale correlacionar com os processos de maior consumo."
                            ),
                        )
                    )

    service_context = session_context.service
    if service_context is not None:
        stale_refresh = _build_stale_refresh_insight("service", freshness_by_key.get("service"))
        if stale_refresh is not None:
            insights.append(stale_refresh)
        else:
            service = service_context.name
            active_state = service_context.active_state
            sub_state = service_context.sub_state
            if active_state and sub_state and active_state != "active":
                severity = "critical" if active_state in {"failed", "inactive"} else "warning"
                service_freshness = freshness_by_key.get("service")
                action_tool_name = None
                action_title = None
                action_arguments: dict[str, str] = {}
                if _has_matching_service_evidence(service_context, service_freshness):
                    action_arguments = _build_service_action_arguments(
                        session_context,
                        service_freshness,
                    )
                    scope_text = _render_scope_suffix(action_arguments.get("scope"))
                    action_tool_name = "restart_service"
                    action_title = (
                        f"Reiniciar o serviço `{service}`{scope_text} com confirmação explícita."
                    )
                insights.append(
                    SessionInsight(
                        key="service_state",
                        severity=severity,
                        target=service,
                        message=(
                            f"O serviço `{service}` não está saudável "
                            f"(active={active_state}, sub={sub_state}). "
                            "Vale revisar logs antes de qualquer reinício."
                        ),
                        action_tool_name=action_tool_name,
                        action_title=action_title,
                        action_arguments=action_arguments,
                    )
                )

    failed_services_context = session_context.failed_services
    if failed_services_context is not None:
        stale_refresh = _build_stale_refresh_insight(
            "failed_services",
            freshness_by_key.get("failed_services"),
        )
        if stale_refresh is not None:
            insights.append(stale_refresh)
        elif failed_services_context.items:
            first_failed = failed_services_context.items[0]
            service_freshness = freshness_by_key.get("service")
            if not _has_matching_failed_service_evidence(
                first_failed.unit,
                failed_services_context.scope,
                service_context,
                service_freshness,
            ):
                count = len(failed_services_context.items)
                scope_text = _render_scope_suffix(failed_services_context.scope)
                message = (
                    f"Foi encontrado um serviço em falha{scope_text}: `{first_failed.unit}`. "
                    "Vale detalhar o status antes de qualquer ação."
                )
                if count > 1:
                    message = (
                        f"Foram encontrados {count} serviços em falha{scope_text}. "
                        f"Vale começar detalhando `{first_failed.unit}`."
                    )
                insights.append(
                    SessionInsight(
                        key="failed_service_detected",
                        severity="warning",
                        target=first_failed.unit,
                        message=message,
                        action_tool_name="service_status",
                        action_title=(
                            f"Inspecionar o status de `{first_failed.unit}`"
                            f"{scope_text} antes de intervir."
                        ),
                        action_arguments=_with_scope_argument(
                            {"name": first_failed.unit},
                            failed_services_context.scope,
                        ),
                    )
                )

    processes_context = session_context.processes
    if processes_context is not None and processes_context.items:
        stale_refresh = _build_stale_refresh_insight("processes", freshness_by_key.get("processes"))
        if stale_refresh is not None:
            insights.append(stale_refresh)
        else:
            top = processes_context.items[0]
            if top.cpu_percent is not None and top.cpu_percent >= 80:
                correlated_unit = None
                correlation_attempted = False
                correlation_no_match = False
                if (
                    session_context.process_unit is not None
                    and session_context.process_unit.query_name == top.command
                ):
                    correlation_attempted = session_context.process_unit.attempted
                    correlated_unit = session_context.process_unit.unit
                    correlation_no_match = (
                        session_context.process_unit.no_match and correlated_unit is None
                    )
                action_tool_name = None
                action_title = None
                process_action_arguments: dict[str, str] = {}
                if correlated_unit is None and not correlation_no_match:
                    action_tool_name = "process_to_unit"
                    action_title = (
                        f"Correlacionar o processo `{top.command}` com um unit do systemd."
                    )
                    process_action_arguments = {"name": top.command, "limit": "3"}
                message = (
                    f"O processo `{top.command}` apareceu com CPU alta ({top.cpu_percent:.1f}%). "
                    "Vale correlacionar isso com logs ou status do serviço relacionado."
                )
                if correlated_unit:
                    message = (
                        f"O processo `{top.command}` apareceu com CPU alta ({top.cpu_percent:.1f}%). "
                        f"Ele já foi correlacionado com `{correlated_unit}`."
                    )
                    if _looks_like_service_unit(correlated_unit):
                        service_action_arguments = _build_service_follow_up_arguments(
                            correlated_unit,
                            session_context.process_unit.scope
                            if session_context.process_unit is not None
                            else None,
                            session_context.service,
                            freshness_by_key.get("service"),
                        )
                        if service_action_arguments:
                            action_tool_name = "service_status"
                            action_title = (
                                f"Inspecionar o status de `{correlated_unit}`"
                                f"{_render_scope_suffix(service_action_arguments.get('scope'))}."
                            )
                            process_action_arguments = service_action_arguments
                elif correlation_attempted and correlation_no_match:
                    message = (
                        f"O processo `{top.command}` apareceu com CPU alta ({top.cpu_percent:.1f}%). "
                        "Já tentei correlacioná-lo com systemd nesta sessão, mas não houve um unit claro."
                    )
                insights.append(
                    SessionInsight(
                        key="hot_process",
                        severity="warning",
                        target=top.command,
                        message=message,
                        action_tool_name=action_tool_name,
                        action_title=action_title,
                        action_arguments=process_action_arguments,
                    )
                )

    config_context = session_context.config
    if config_context is not None:
        backup_insight = _build_config_backup_insight(config_context)
        if backup_insight is not None:
            insights.append(backup_insight)

    return insights


def _build_stale_refresh_insight(
    key: str,
    freshness: ObservationFreshness | None,
) -> SessionInsight | None:
    if freshness is None or not freshness.stale:
        return None

    age_text = _render_age_hint(freshness)
    if key == "disk":
        path = freshness.value.get("path")
        target = path if isinstance(path, str) and path else "/"
        return SessionInsight(
            key="disk_pressure_refresh",
            severity="warning",
            target=str(target),
            message=(
                f"A observação de disco em `{target}` está desatualizada{age_text}. "
                "Atualize o uso de disco antes de confiar neste alerta."
            ),
            action_tool_name="disk_usage",
            action_title=f"Atualizar o uso de disco em `{target}`.",
            action_arguments={"path": str(target)},
        )

    if key == "memory":
        return SessionInsight(
            key="memory_pressure_refresh",
            severity="warning",
            target="memory",
            message=(
                f"A observação de memória está desatualizada{age_text}. "
                "Atualize RAM e swap antes de agir em cima desse sinal."
            ),
            action_tool_name="memory_usage",
            action_title="Atualizar os dados de memória e swap.",
            action_arguments={},
        )

    if key == "service":
        service = freshness.value.get("service")
        scope = freshness.value.get("scope")
        if not isinstance(service, str) or not service:
            return None
        arguments = {"name": service}
        scope_text = ""
        if isinstance(scope, str) and scope:
            arguments["scope"] = scope
            scope_text = f" ({scope})"
        return SessionInsight(
            key="service_state_refresh",
            severity="warning",
            target=service,
            message=(
                f"A observação do serviço `{service}` está desatualizada{age_text}. "
                "Atualize o status antes de sugerir reinício ou concluir o diagnóstico."
            ),
            action_tool_name="service_status",
            action_title=f"Atualizar o status do serviço `{service}`{scope_text}.",
            action_arguments=arguments,
        )

    if key == "processes":
        return SessionInsight(
            key="hot_process_refresh",
            severity="warning",
            target="processes",
            message=(
                f"A lista de processos mais quentes está desatualizada{age_text}. "
                "Atualize os processos antes de confiar neste alerta."
            ),
            action_tool_name="top_processes",
            action_title="Atualizar os processos com maior uso de CPU.",
            action_arguments={"limit": "5"},
        )

    if key == "failed_services":
        scope = freshness.value.get("scope")
        arguments = {}
        scope_text = ""
        if isinstance(scope, str) and scope in {"system", "user"}:
            arguments["scope"] = scope
            scope_text = f" ({scope})"
        return SessionInsight(
            key="failed_services_refresh",
            severity="warning",
            target="failed_services",
            message=(
                f"A lista de serviços com falha está desatualizada{age_text}. "
                "Atualize essa lista antes de assumir que o problema continua igual."
            ),
            action_tool_name="failed_services",
            action_title=f"Atualizar a lista de serviços com falha{scope_text}.",
            action_arguments=arguments,
        )

    return None


def _render_age_hint(freshness: ObservationFreshness) -> str:
    if freshness.age_seconds is None:
        return ""
    return f" (idade {format_duration(freshness.age_seconds)})"


def _build_service_action_arguments(
    session_context: SessionContext,
    freshness: ObservationFreshness | None,
) -> dict[str, str]:
    service = session_context.service
    if service is None:
        return {}
    arguments = {"name": service.name}
    scope = _resolve_service_scope(session_context, freshness)
    if scope is not None:
        arguments["scope"] = scope
    return arguments


def _resolve_service_scope(
    session_context: SessionContext,
    freshness: ObservationFreshness | None,
) -> str | None:
    service = session_context.service
    if service is None:
        return None
    if freshness is not None:
        scoped_service = freshness.value.get("service")
        scope = freshness.value.get("scope")
        if (
            isinstance(scoped_service, str)
            and scoped_service == service.name
            and isinstance(scope, str)
            and scope in {"system", "user"}
        ):
            return scope

    if service.scope in {"system", "user"}:
        return service.scope

    tracked = session_context.tracked
    if tracked.unit == service.name and tracked.scope in {"system", "user"}:
        return tracked.scope
    return None


def _has_matching_service_evidence(
    service: ServiceContext,
    freshness: ObservationFreshness | None,
) -> bool:
    if freshness is None:
        return False
    observed_service = freshness.value.get("service")
    return isinstance(observed_service, str) and observed_service == service.name


def _has_matching_failed_service_evidence(
    unit: str,
    scope: str | None,
    service_context: ServiceContext | None,
    freshness: ObservationFreshness | None,
) -> bool:
    if service_context is None or service_context.name != unit:
        return False
    if scope in {"system", "user"} and service_context.scope not in {None, scope}:
        return False
    return _has_matching_service_evidence(service_context, freshness)


def _build_service_follow_up_arguments(
    unit: str,
    scope: str | None,
    service_context: ServiceContext | None,
    freshness: ObservationFreshness | None,
) -> dict[str, str]:
    if service_context is not None and service_context.name == unit and _has_matching_service_evidence(
        service_context,
        freshness,
    ):
        if scope not in {"system", "user"} or service_context.scope in {None, scope}:
            return {}
    return _with_scope_argument({"name": unit}, scope)


def _build_config_backup_insight(config: ConfigContext) -> SessionInsight | None:
    if config.stale or not config.path or not config.backup_path:
        return None
    return SessionInsight(
        key="config_backup_available",
        severity="info",
        target=config.path,
        message=(
            f"Há um backup recente disponível para `{config.path}`. "
            "Se a mudança não se comportar como esperado, dá para fazer rollback com confirmação."
        ),
        action_tool_name="restore_config_backup",
        action_title=f"Restaurar o último backup de `{config.path}` com confirmação explícita.",
        action_arguments={
            "path": config.path,
            "backup_path": config.backup_path,
        },
    )


def _with_scope_argument(arguments: dict[str, str], scope: str | None) -> dict[str, str]:
    if scope in {"system", "user"}:
        return {**arguments, "scope": scope}
    return arguments


def _looks_like_service_unit(value: str | None) -> bool:
    if not value:
        return False
    return "." not in value or value.endswith(".service")


def _render_scope_suffix(scope: str | None) -> str:
    if scope in {"system", "user"}:
        return f" ({scope})"
    return ""
