from __future__ import annotations

import re
from dataclasses import dataclass, field

from master_control.agent.session_summary import parse_session_summary


DISK_USAGE_RE = re.compile(r"^(?P<path>.+?) is (?P<percent>\d+(?:\.\d+)?)% used$")
MEMORY_RE = re.compile(
    r"^memory (?P<memory>\d+(?:\.\d+)?)% used, swap (?P<swap>\d+(?:\.\d+)?)% used$"
)
SERVICE_RE = re.compile(r"^(?P<service>.+?): active=(?P<active>[^,]+), sub=(?P<sub>.+)$")
PROCESS_RE = re.compile(r"(?P<command>[^,(]+)\((?P<cpu>\d+(?:\.\d+)?)%\)")


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
    summary = parse_session_summary(summary_text)
    insights: list[SessionInsight] = []

    disk_summary = summary.get("disk")
    if disk_summary:
        disk_match = DISK_USAGE_RE.match(disk_summary)
        if disk_match:
            path = disk_match.group("path")
            used_percent = float(disk_match.group("percent"))
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

    memory_summary = summary.get("memory")
    if memory_summary:
        memory_match = MEMORY_RE.match(memory_summary)
        if memory_match:
            memory_used = float(memory_match.group("memory"))
            swap_used = float(memory_match.group("swap"))
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

    service_summary = summary.get("service")
    if service_summary:
        service_match = SERVICE_RE.match(service_summary)
        if service_match:
            service = service_match.group("service")
            active_state = service_match.group("active")
            sub_state = service_match.group("sub")
            if active_state != "active":
                severity = "critical" if active_state in {"failed", "inactive"} else "warning"
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
                        action_tool_name="restart_service",
                        action_title=f"Reiniciar o serviço `{service}` com confirmação explícita.",
                        action_arguments={"name": service},
                    )
                )

    process_summary = summary.get("processes")
    if process_summary:
        process_matches = list(PROCESS_RE.finditer(process_summary))
        if process_matches:
            top = process_matches[0]
            command = top.group("command").strip()
            cpu_percent = float(top.group("cpu"))
            if cpu_percent >= 80:
                insights.append(
                    SessionInsight(
                        key="hot_process",
                        severity="warning",
                        target=command,
                        message=(
                            f"O processo `{command}` apareceu com CPU alta ({cpu_percent:.1f}%). "
                            "Vale correlacionar isso com logs ou status do serviço relacionado."
                        ),
                    )
                )

    return insights
