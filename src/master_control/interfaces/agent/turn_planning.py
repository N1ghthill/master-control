"""Planning helpers used by the chat-facing interface loop."""

from __future__ import annotations

import json

from master_control.core.observations import ObservationFreshness, observation_key_for_tool
from master_control.interfaces.agent.tool_result_views import build_tool_result_view
from master_control.providers.base import ProviderError, ProviderResponse
from master_control.shared.planning import ExecutionPlan, PlanningDecision


def build_turn_planning_prompt(
    *,
    user_input: str,
    iteration: int,
    executions: list[dict[str, object]],
) -> str | None:
    if not executions:
        if iteration == 0:
            return "\n".join(
                [
                    "Current-turn planning guardrails:",
                    f"- original_user_request: {user_input}",
                    "- For live host inspection requests, do not answer from memory alone.",
                    "- If the user asks about current memory, disk, processes, service state, logs, or host metadata, return decision.state=needs_tools and call the matching read-only tool first.",
                    "- Only return decision.state=complete on the first planning pass when the request is non-operational, already fully answered by the provided context, or safely unsupported.",
                ]
            )
        return (
            "This is a continuation of the same user request. "
            "If enough information is already available, return decision.state=complete with no steps."
        )

    observation_lines = [summarize_execution_for_planner(execution) for execution in executions]
    rendered_observations = "\n".join(f"- {line}" for line in observation_lines)
    return "\n".join(
        [
            "Current-turn planning context:",
            f"- original_user_request: {user_input}",
            f"- planning_iteration: {iteration + 1}",
            "- Return an explicit planner decision: needs_tools, complete, or blocked.",
            "- Do not repeat tool calls that already ran in this same turn unless the user explicitly asked to rerun them.",
            "- If the observations below are already enough, return decision.state=complete, no steps, and summarize the findings.",
            "- If the request cannot continue safely with the available tools, return decision.state=blocked.",
            "- If a prior step failed or requires confirmation, do not propose dependent steps.",
            "Execution observations:",
            rendered_observations,
        ]
    )


def summarize_execution_for_planner(execution: dict[str, object]) -> str:
    tool_name = str(execution.get("tool", "unknown"))
    arguments = execution.get("arguments", {})
    argument_text = json.dumps(arguments, sort_keys=True)
    if execution.get("pending_confirmation"):
        return f"{tool_name}({argument_text}) -> pending_confirmation"
    if not execution.get("ok"):
        return f"{tool_name}({argument_text}) -> error: {execution.get('error', 'unknown')}"

    result = execution.get("result")
    if not isinstance(result, dict):
        return f"{tool_name}({argument_text}) -> ok"
    return build_tool_result_view(tool_name, _coerce_mapping(arguments), result).planner_summary


def _coerce_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def validate_provider_response_for_loop(provider_response: ProviderResponse) -> PlanningDecision:
    decision = provider_response.resolved_decision()
    has_steps = bool(provider_response.plan and provider_response.plan.steps)
    if decision.state == "needs_tools" and not has_steps:
        raise ProviderError("Provider declared needs_tools without returning executable steps.")
    if decision.state != "needs_tools" and has_steps:
        raise ProviderError("Provider returned executable steps for a non-needs_tools decision.")
    return decision


def should_continue_planning(
    plan: ExecutionPlan | None,
    *,
    multi_step_intents: set[str],
) -> bool:
    if plan is None:
        return False
    return plan.intent in multi_step_intents


def classify_turn_decision(
    provider_response: ProviderResponse,
    executions: list[dict[str, object]],
    *,
    multi_step_intents: set[str],
) -> PlanningDecision:
    for execution in executions:
        if execution.get("pending_confirmation"):
            return PlanningDecision(
                state="blocked",
                kind="awaiting_confirmation",
                reason="The next action is waiting for explicit confirmation before it can run.",
            )
    for execution in executions:
        if not execution.get("ok"):
            return PlanningDecision(
                state="blocked",
                kind="execution_failed",
                reason="A tool execution failed before the request could complete safely.",
            )

    plan_decision = provider_response.resolved_decision()
    if executions and not should_continue_planning(
        provider_response.plan,
        multi_step_intents=multi_step_intents,
    ):
        return PlanningDecision(
            state="complete",
            kind="evidence_sufficient",
            reason="Current-turn evidence is sufficient for the final response.",
        )
    if plan_decision.state == "needs_tools" and collect_planned_refresh_keys(
        provider_response.plan
    ):
        return PlanningDecision(
            state="needs_tools",
            kind="refresh_required",
            reason="Fresh host observations are required before the diagnosis can continue.",
        )
    return plan_decision


def collect_planned_refresh_keys(plan: ExecutionPlan | None) -> list[str]:
    if plan is None:
        return []
    keys: list[str] = []
    for step in plan.steps:
        observation_key = observation_key_for_tool(step.tool_name)
        if observation_key is None or observation_key in keys:
            continue
        keys.append(observation_key)
    return keys


def collect_stale_observation_keys(
    observation_freshness: tuple[ObservationFreshness, ...],
) -> list[str]:
    return sorted({item.key for item in observation_freshness if item.stale})
