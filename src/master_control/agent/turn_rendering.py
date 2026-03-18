from __future__ import annotations

from typing import cast

from master_control.agent.planner import PlanningDecision
from master_control.agent.recommendation_sync import RecommendationSyncResult
from master_control.agent.tool_result_views import build_tool_result_view
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
    return build_tool_result_view(tool_name, arguments, result).rendered_summary


def _coerce_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return {}
