from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from typing import Any

from master_control.agent.observations import (
    ObservationFreshness,
    build_observation_envelopes,
    build_observation_freshness,
    observation_key_for_tool,
)
from master_control.agent.recommendation_sync import RecommendationSyncResult
from master_control.agent.session_insights import SessionInsight, collect_session_insights
from master_control.agent.planner import ExecutionPlan
from master_control.agent.session_recommendations import (
    ACTIVE_RECOMMENDATION_STATUSES,
    RECOMMENDATION_STATUSES,
    build_recommendation_candidates,
)
from master_control.agent.session_summary import update_session_summary
from master_control.config import Settings
from master_control.policy.engine import PolicyEngine
from master_control.providers.availability import collect_provider_checks
from master_control.providers.base import (
    ConversationMessage,
    ProviderClient,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
)
from master_control.providers.factory import build_provider
from master_control.store.session_store import SessionStore
from master_control.tools.base import ToolError
from master_control.tools.registry import ToolRegistry, build_default_registry


PROVIDER_HISTORY_LIMIT = 8
MAX_PLANNING_ITERATIONS = 4


@dataclass(frozen=True, slots=True)
class PlanningLoopResult:
    provider_response: ProviderResponse
    executions: list[dict[str, object]]
    working_summary: str | None
    working_freshness: tuple[ObservationFreshness, ...]
    response_id: str | None


class MasterControlApp:
    def __init__(
        self,
        settings: Settings,
        *,
        provider_override: ProviderClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = SessionStore(settings.db_path)
        self.policy = PolicyEngine()
        self.provider = provider_override or build_provider(settings)
        self.registry: ToolRegistry = build_default_registry(settings.state_dir)
        self.chat_session_id: int | None = None
        self.previous_provider_response_id: str | None = None

    def bootstrap(self) -> None:
        self.settings.ensure_directories()
        self.store.initialize()

    def doctor(self) -> dict[str, object]:
        self.bootstrap()
        provider_checks = collect_provider_checks(self.settings)
        active_provider_check = dict(
            provider_checks.get(
                self.provider.name,
                {
                    "name": self.provider.name,
                    "available": True,
                    "summary": "active provider has no dedicated health probe",
                },
            )
        )
        doctor_ok = bool(active_provider_check.get("available", False))
        llm_provider_available = any(
            bool(provider_checks[name].get("available", False))
            for name in ("ollama", "openai")
        )
        return {
            "ok": doctor_ok,
            "state_dir": str(self.settings.state_dir),
            "db_path": str(self.settings.db_path),
            "provider": self.settings.provider,
            "provider_backend": self.provider.name,
            "planner_mode": "llm" if self.provider.name in {"openai", "ollama"} else "heuristic",
            "llm_provider_available": llm_provider_available,
            "active_provider_check": active_provider_check,
            "provider_checks": provider_checks,
            "provider_diagnostics": self.provider.diagnostics(),
            "audit_event_count": self.store.count_audit_events(),
            "session_count": len(self.store.list_sessions(limit=10_000)),
            "tools": [spec.name for spec in self.list_tools()],
        }

    def list_tools(self):
        return self.registry.list_specs()

    def list_audit_events(self, limit: int = 20) -> list[dict[str, object]]:
        self.bootstrap()
        return self.store.list_audit_events(limit=limit)

    def list_sessions(self, limit: int = 20) -> list[dict[str, object]]:
        self.bootstrap()
        sessions = self.store.list_sessions(limit=limit)
        enriched: list[dict[str, object]] = []
        for session in sessions:
            summary_text = session.get("summary_text")
            insights = collect_session_insights(
                str(summary_text) if isinstance(summary_text, str) else None
            )
            active_recommendations = self.store.list_session_recommendations(
                int(session["session_id"]),
                limit=200,
            )
            active_count = sum(
                1 for item in active_recommendations if item["status"] in ACTIVE_RECOMMENDATION_STATUSES
            )
            enriched.append(
                {
                    **session,
                    "insight_count": len(insights),
                    "active_recommendation_count": active_count,
                }
            )
        return enriched

    def get_session_insights(self, session_id: int | None = None) -> dict[str, object]:
        self.bootstrap()
        resolved_session_id = self._resolve_session_id(session_id)
        summary_text = self._load_session_summary(resolved_session_id)
        insights = collect_session_insights(summary_text)
        return {
            "session_id": resolved_session_id,
            "summary_text": summary_text,
            "insights": [insight.as_dict() for insight in insights],
        }

    def list_session_observations(
        self,
        session_id: int | None = None,
        *,
        stale_only: bool = False,
    ) -> dict[str, object]:
        self.bootstrap()
        resolved_session_id = self._resolve_session_id(session_id)
        observations = list(self._load_observation_freshness(resolved_session_id))
        if stale_only:
            observations = [item for item in observations if item.stale]
        stale_count = sum(1 for item in observations if item.stale)
        return {
            "session_id": resolved_session_id,
            "stale_only": stale_only,
            "total_count": len(observations),
            "stale_count": stale_count,
            "fresh_count": len(observations) - stale_count,
            "observations": [item.as_dict() for item in observations],
        }

    def list_session_recommendations(
        self,
        session_id: int | None = None,
        *,
        status: str | None = None,
    ) -> dict[str, object]:
        self.bootstrap()
        resolved_session_id = self._resolve_session_id(session_id)
        recommendations = self.store.list_session_recommendations(
            resolved_session_id,
            status=status,
            limit=200,
        )
        return {
            "session_id": resolved_session_id,
            "status_filter": status,
            "recommendations": recommendations,
        }

    def update_recommendation_status(
        self,
        recommendation_id: int,
        status: str,
    ) -> dict[str, object]:
        self.bootstrap()
        if status not in RECOMMENDATION_STATUSES:
            raise ValueError(f"Invalid recommendation status: {status}")
        payload = self.store.update_recommendation_status(recommendation_id, status)
        if payload is None:
            raise ValueError(f"Unknown recommendation_id: {recommendation_id}")
        self.store.record_audit_event(
            "recommendation_status_updated",
            {
                "recommendation_id": recommendation_id,
                "session_id": payload["session_id"],
                "status": status,
            },
        )
        if status == "accepted":
            action = payload.get("action")
            if isinstance(action, dict):
                payload = {
                    **payload,
                    "next_step": self._build_recommendation_commands(recommendation_id),
                }
        return payload

    def run_recommendation_action(
        self,
        recommendation_id: int,
        *,
        confirmed: bool = False,
    ) -> dict[str, object]:
        self.bootstrap()
        recommendation = self.store.get_recommendation(recommendation_id)
        if recommendation is None:
            raise ValueError(f"Unknown recommendation_id: {recommendation_id}")

        status = recommendation.get("status")
        if status != "accepted":
            commands = self._build_recommendation_commands(recommendation_id)
            raise ValueError(
                "Recommendation must be in 'accepted' status before its action can run. "
                f"Use `{commands['cli_accept_command']}` or `{commands['chat_accept_command']}` first."
            )

        action = recommendation.get("action")
        if not isinstance(action, dict):
            raise ValueError("Recommendation has no executable action.")

        tool_name = action.get("tool_name")
        arguments = action.get("arguments")
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("Recommendation action is missing tool_name.")
        if not isinstance(arguments, dict):
            arguments = {}

        execution = self.run_tool(
            tool_name,
            dict(arguments),
            confirmed=confirmed,
            audit_context={
                "source": "recommendation_action",
                "recommendation_id": recommendation_id,
                "session_id": recommendation["session_id"],
            },
        )
        self.store.record_audit_event(
            "recommendation_action_requested",
            {
                "recommendation_id": recommendation_id,
                "session_id": recommendation["session_id"],
                "tool": tool_name,
                "confirmed": confirmed,
                "ok": execution.get("ok", False),
                "pending_confirmation": execution.get("pending_confirmation", False),
            },
        )
        return {
            "recommendation": recommendation,
            "execution": execution,
        }

    def start_chat_session(
        self,
        *,
        session_id: int | None = None,
        new_session: bool = False,
    ) -> int:
        self.bootstrap()
        return self._prepare_chat_session(session_id=session_id, new_session=new_session)

    def run_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
        *,
        confirmed: bool = False,
        audit_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.bootstrap()
        argument_payload: dict[str, object] = dict(arguments or {})
        context_payload = dict(audit_context or {})

        try:
            tool = self.registry.get(name)
        except KeyError as exc:
            payload = {
                "ok": False,
                "tool": name,
                "arguments": argument_payload,
                **context_payload,
                "error": str(exc),
            }
            self.store.record_audit_event("tool_execution", payload)
            return payload

        decision = self.policy.evaluate(tool.spec)
        audit_base = {
            "tool": tool.spec.name,
            "risk": tool.spec.risk.value,
            "arguments": argument_payload,
            "policy": decision.as_dict(),
            **context_payload,
        }

        if not decision.allowed:
            payload = {
                "ok": False,
                **audit_base,
                "error": "Policy denied tool execution.",
            }
            self.store.record_audit_event("tool_execution", payload)
            return payload

        if decision.needs_confirmation and not confirmed:
            payload = {
                "ok": False,
                **audit_base,
                "pending_confirmation": True,
                "approval": self._build_approval_payload(
                    tool.spec.name,
                    argument_payload,
                    context_payload,
                ),
                "error": "Tool requires explicit confirmation before execution.",
            }
            self.store.record_audit_event("tool_execution", payload)
            return payload

        try:
            result = tool.invoke(argument_payload)
        except ToolError as exc:
            payload = {
                "ok": False,
                **audit_base,
                "error": str(exc),
            }
            self.store.record_audit_event("tool_execution", payload)
            return payload

        payload = {
            "ok": True,
            "tool": tool.spec.name,
            "arguments": argument_payload,
            "policy": decision.as_dict(),
            **context_payload,
            "result": result,
        }
        session_id = context_payload.get("session_id")
        if isinstance(session_id, int):
            self._record_execution_observations(
                session_id=session_id,
                tool_name=tool.spec.name,
                arguments=argument_payload,
                result=result,
            )
        self.store.record_audit_event(
            "tool_execution",
            {
                **audit_base,
                "ok": True,
                "result_summary": self._summarize_result(result),
            },
        )
        return payload

    def _summarize_result(self, result: dict[str, Any]) -> dict[str, object]:
        summary: dict[str, object] = {"keys": sorted(result)}
        if "status" in result:
            summary["status"] = result["status"]
        if "processes" in result and isinstance(result["processes"], list):
            summary["process_count"] = len(result["processes"])
        if "entries" in result and isinstance(result["entries"], list):
            summary["entry_count"] = len(result["entries"])
        if "service" in result:
            summary["service"] = result["service"]
        if "path" in result:
            summary["path"] = result["path"]
        return summary

    def _build_approval_payload(
        self,
        tool_name: str,
        arguments: dict[str, object],
        context_payload: dict[str, object],
    ) -> dict[str, object]:
        recommendation_id = context_payload.get("recommendation_id")
        if isinstance(recommendation_id, int):
            commands = self._build_recommendation_commands(recommendation_id)
            return {
                "required": True,
                "cli_command": commands["cli_confirm_command"],
                "chat_command": commands["chat_confirm_command"],
                "summary": "Execute a ação da recomendação com confirmação explícita.",
            }

        return {
            "required": True,
            "cli_command": self._format_cli_tool_command(tool_name, arguments, confirmed=True),
            "chat_command": self._format_chat_tool_command(tool_name, arguments, confirmed=True),
            "summary": "Reexecute a tool com confirmação explícita.",
        }

    def _build_recommendation_commands(self, recommendation_id: int) -> dict[str, str]:
        return {
            "cli_accept_command": f"mc recommendation {recommendation_id} accepted",
            "chat_accept_command": f"/recommendation {recommendation_id} accepted",
            "cli_confirm_command": f"mc recommendation-run {recommendation_id} --confirm",
            "chat_confirm_command": f"/recommendation-run {recommendation_id} confirm",
        }

    def _format_cli_tool_command(
        self,
        tool_name: str,
        arguments: dict[str, object],
        *,
        confirmed: bool,
    ) -> str:
        parts = ["mc", "tool", tool_name]
        for key, value in arguments.items():
            parts.extend(["--arg", f"{key}={self._stringify_argument(value)}"])
        if confirmed:
            parts.append("--confirm")
        return " ".join(shlex.quote(part) for part in parts)

    def _format_chat_tool_command(
        self,
        tool_name: str,
        arguments: dict[str, object],
        *,
        confirmed: bool,
    ) -> str:
        parts = ["/tool", tool_name]
        for key, value in arguments.items():
            parts.append(f"{key}={self._stringify_argument(value)}")
        if confirmed:
            parts.append("confirm")
        return " ".join(shlex.quote(part) for part in parts)

    def _stringify_argument(self, value: object) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, sort_keys=True)

    def chat(
        self,
        user_input: str,
        *,
        session_id: int | None = None,
        new_session: bool = False,
    ) -> dict[str, object]:
        self.bootstrap()
        active_session_id = self._prepare_chat_session(session_id=session_id, new_session=new_session)
        conversation_history = self._load_conversation_history(active_session_id)
        session_summary = self._load_session_summary(active_session_id)
        observation_freshness = self._load_observation_freshness(active_session_id)
        self.store.append_conversation_message(active_session_id, "user", user_input)

        try:
            planning_result = self._run_planning_loop(
                user_input=user_input,
                session_id=active_session_id,
                conversation_history=conversation_history,
                session_summary=session_summary,
                observation_freshness=observation_freshness,
            )
        except ProviderError as exc:
            error_message = f"Provider `{self.provider.name}` falhou: {exc}"
            self._record_provider_error(
                session_id=active_session_id,
                user_input=user_input,
                conversation_history=conversation_history,
                session_summary=session_summary,
                error=str(exc),
            )
            self.store.append_conversation_message(active_session_id, "assistant", error_message)
            return {
                "provider": self.provider.name,
                "session_id": active_session_id,
                "message": error_message,
                "plan": None,
                "executions": [],
                "error": str(exc),
            }

        self.previous_provider_response_id = planning_result.response_id
        self.store.update_session_provider_state(
            active_session_id,
            self.provider.name,
            planning_result.response_id,
        )
        plan_payload = (
            planning_result.provider_response.plan.as_dict()
            if planning_result.provider_response.plan
            else None
        )
        final_message = self._render_chat_response(
            planning_result.provider_response,
            planning_result.executions,
        )
        updated_summary = update_session_summary(
            planning_result.working_summary,
            user_input=user_input,
            plan=planning_result.provider_response.plan,
            executions=[],
            assistant_message=final_message,
        )
        self.store.upsert_session_summary(active_session_id, updated_summary)
        insights = collect_session_insights(updated_summary)
        recommendation_sync = self._sync_session_recommendations(active_session_id, insights)
        final_message_with_recommendations = self._append_recommendations_to_message(
            final_message,
            recommendation_sync,
        )
        self.store.append_conversation_message(
            active_session_id,
            "assistant",
            final_message_with_recommendations,
        )
        return {
            "provider": self.provider.name,
            "session_id": active_session_id,
            "message": final_message_with_recommendations,
            "plan": plan_payload,
            "provider_metadata": planning_result.provider_response.metadata,
            "session_summary": updated_summary,
            "observation_freshness": [
                item.as_dict() for item in planning_result.working_freshness
            ],
            "insights": [insight.as_dict() for insight in insights],
            "recommendations": recommendation_sync.as_dict(),
            "executions": planning_result.executions,
        }

    def _run_planning_loop(
        self,
        *,
        user_input: str,
        session_id: int,
        conversation_history: list[ConversationMessage],
        session_summary: str | None,
        observation_freshness: tuple[ObservationFreshness, ...],
    ) -> PlanningLoopResult:
        available_tools = tuple(self.list_tools())
        working_summary = session_summary
        working_freshness = observation_freshness
        accumulated_executions: list[dict[str, object]] = []
        executed_signatures: set[str] = set()
        previous_response_id = self.previous_provider_response_id
        last_provider_response = ProviderResponse(
            message="Ainda não consegui gerar uma resposta útil para este pedido."
        )

        for iteration in range(MAX_PLANNING_ITERATIONS):
            provider_request = ProviderRequest(
                user_message=user_input,
                available_tools=available_tools,
                conversation_history=tuple(conversation_history),
                session_summary=working_summary,
                observation_freshness=working_freshness,
                previous_response_id=previous_response_id,
                system_prompt=self._build_turn_planning_prompt(
                    user_input=user_input,
                    iteration=iteration,
                    executions=accumulated_executions,
                ),
            )
            provider_response = self.provider.plan(provider_request)
            last_provider_response = provider_response
            previous_response_id = provider_response.response_id or previous_response_id

            plan_payload = provider_response.plan.as_dict() if provider_response.plan else None
            self._record_plan_generated(
                session_id=session_id,
                user_input=user_input,
                conversation_history=conversation_history,
                session_summary=working_summary,
                observation_freshness=working_freshness,
                provider_response=provider_response,
                plan_payload=plan_payload,
                iteration=iteration,
                accumulated_executions=accumulated_executions,
            )

            new_executions = self._execute_plan(
                provider_response.plan,
                session_id=session_id,
                executed_signatures=executed_signatures,
            )
            if not new_executions:
                break

            accumulated_executions.extend(new_executions)
            working_summary = update_session_summary(
                working_summary,
                user_input=user_input,
                plan=provider_response.plan,
                executions=new_executions,
                assistant_message=provider_response.message,
            )
            working_freshness = self._load_observation_freshness(session_id)

            if any(not execution.get("ok") for execution in new_executions):
                break

        return PlanningLoopResult(
            provider_response=last_provider_response,
            executions=accumulated_executions,
            working_summary=working_summary,
            working_freshness=working_freshness,
            response_id=previous_response_id,
        )

    def _load_conversation_history(self, session_id: int) -> list[ConversationMessage]:
        rows = self.store.list_conversation_messages(session_id, limit=PROVIDER_HISTORY_LIMIT)
        return [
            ConversationMessage(
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]) if row["created_at"] is not None else None,
            )
            for row in rows
        ]

    def _load_session_summary(self, session_id: int) -> str | None:
        payload = self.store.get_session_summary(session_id)
        if payload is None:
            return None
        summary_text = payload.get("summary_text")
        if isinstance(summary_text, str) and summary_text.strip():
            return summary_text
        return None

    def _load_observation_freshness(self, session_id: int) -> tuple[ObservationFreshness, ...]:
        rows = self.store.list_latest_observations(session_id)
        return build_observation_freshness(rows)

    def _resolve_session_id(self, session_id: int | None) -> int:
        if session_id is not None:
            if not self.store.session_exists(session_id):
                raise ValueError(f"Unknown session_id: {session_id}")
            return session_id

        sessions = self.store.list_sessions(limit=1)
        if not sessions:
            raise ValueError("No sessions available.")
        resolved = sessions[0].get("session_id")
        if not isinstance(resolved, int):
            raise ValueError("No sessions available.")
        return resolved

    def _ensure_chat_session(self) -> int:
        if self.chat_session_id is None:
            self.chat_session_id = self.store.create_session()
        return self.chat_session_id

    def _prepare_chat_session(self, *, session_id: int | None, new_session: bool) -> int:
        if session_id is not None and new_session:
            raise ValueError("Cannot use session_id and new_session at the same time.")

        if new_session:
            self.chat_session_id = None
            self.previous_provider_response_id = None

        if session_id is not None:
            self._resume_session(session_id)

        return self._ensure_chat_session()

    def _resume_session(self, session_id: int) -> None:
        if not self.store.session_exists(session_id):
            raise ValueError(f"Unknown session_id: {session_id}")

        self.chat_session_id = session_id
        state = self.store.get_session_provider_state(session_id)
        if state is None:
            self.previous_provider_response_id = None
            return

        provider_backend = state.get("provider_backend")
        if provider_backend == self.provider.name:
            previous_response_id = state.get("previous_response_id")
            self.previous_provider_response_id = (
                str(previous_response_id) if previous_response_id else None
            )
            return

        self.previous_provider_response_id = None

    def _execute_plan(
        self,
        plan: ExecutionPlan | None,
        *,
        session_id: int,
        executed_signatures: set[str] | None = None,
    ) -> list[dict[str, object]]:
        if plan is None:
            return []

        seen_signatures = executed_signatures if executed_signatures is not None else set()
        executions: list[dict[str, object]] = []
        for step in plan.steps:
            signature = self._step_signature(step.tool_name, step.arguments)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            executions.append(
                self.run_tool(
                    step.tool_name,
                    step.arguments,
                    confirmed=False,
                    audit_context={
                        "source": "chat",
                        "session_id": session_id,
                    },
                )
            )
        return executions

    def _step_signature(self, tool_name: str, arguments: dict[str, object]) -> str:
        return f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"

    def _build_turn_planning_prompt(
        self,
        *,
        user_input: str,
        iteration: int,
        executions: list[dict[str, object]],
    ) -> str | None:
        if not executions:
            if iteration == 0:
                return None
            return (
                "This is a continuation of the same user request. "
                "If enough information is already available, return no steps and summarize it."
            )

        observation_lines = [
            self._summarize_execution_for_planner(execution)
            for execution in executions
        ]
        rendered_observations = "\n".join(f"- {line}" for line in observation_lines)
        return "\n".join(
            [
                "Current-turn planning context:",
                f"- original_user_request: {user_input}",
                f"- planning_iteration: {iteration + 1}",
                "- Do not repeat tool calls that already ran in this same turn unless the user explicitly asked to rerun them.",
                "- If the observations below are already enough, return no steps and summarize the findings.",
                "- If a prior step failed or requires confirmation, do not propose dependent steps.",
                "Execution observations:",
                rendered_observations,
            ]
        )

    def _summarize_execution_for_planner(self, execution: dict[str, object]) -> str:
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

        if tool_name == "memory_usage":
            return (
                f"{tool_name}({argument_text}) -> memory={result.get('memory_used_percent')}%, "
                f"swap={result.get('swap_used_percent')}%"
            )
        if tool_name == "top_processes":
            processes = result.get("processes")
            if isinstance(processes, list) and processes:
                items = []
                for item in processes[:3]:
                    if isinstance(item, dict):
                        command = item.get("command")
                        cpu = item.get("cpu_percent")
                        if isinstance(command, str):
                            items.append(f"{command}({cpu}%)")
                if items:
                    return f"{tool_name}({argument_text}) -> {', '.join(items)}"
        if tool_name == "service_status":
            service_scope = result.get("scope")
            scope_text = f", scope={service_scope}" if service_scope else ""
            return (
                f"{tool_name}({argument_text}) -> active={result.get('activestate')}, "
                f"sub={result.get('substate')}{scope_text}"
            )
        if tool_name in {"restart_service", "reload_service"}:
            post_state = result.get("post_restart") or result.get("post_reload")
            if isinstance(post_state, dict):
                service_scope = result.get("scope") or post_state.get("scope")
                scope_text = f", scope={service_scope}" if service_scope else ""
                return (
                    f"{tool_name}({argument_text}) -> post active={post_state.get('activestate')}, "
                    f"sub={post_state.get('substate')}{scope_text}"
                )
        if tool_name == "disk_usage":
            return f"{tool_name}({argument_text}) -> used={result.get('used_percent')}%"
        if tool_name == "read_journal":
            return (
                f"{tool_name}({argument_text}) -> lines={result.get('returned_lines')}, "
                f"unit={result.get('unit')}"
            )
        if tool_name in {"read_config_file", "write_config_file", "restore_config_backup"}:
            return f"{tool_name}({argument_text}) -> path={result.get('path')}"
        return f"{tool_name}({argument_text}) -> ok"

    def _record_execution_observations(
        self,
        *,
        session_id: int,
        tool_name: str,
        arguments: dict[str, object],
        result: dict[str, object],
    ) -> None:
        for envelope in build_observation_envelopes(tool_name, arguments, result):
            self.store.record_observation(
                session_id,
                envelope.source,
                envelope.key,
                envelope.value,
                ttl_seconds=envelope.ttl_seconds,
            )

    def _record_provider_error(
        self,
        *,
        session_id: int,
        user_input: str,
        conversation_history: list[ConversationMessage],
        session_summary: str | None,
        error: str,
    ) -> None:
        self.store.record_audit_event(
            "provider_error",
            {
                "source": "chat",
                "session_id": session_id,
                "configured_provider": self.settings.provider,
                "provider_backend": self.provider.name,
                "user_message": user_input,
                "history_size": len(conversation_history),
                "summary_present": bool(session_summary),
                "error": error,
            },
        )

    def _record_plan_generated(
        self,
        *,
        session_id: int,
        user_input: str,
        conversation_history: list[ConversationMessage],
        session_summary: str | None,
        observation_freshness: tuple[ObservationFreshness, ...],
        provider_response: ProviderResponse,
        plan_payload: dict[str, object] | None,
        iteration: int,
        accumulated_executions: list[dict[str, object]],
    ) -> None:
        stale_observation_keys = sorted({item.key for item in observation_freshness if item.stale})
        planned_refresh_keys = self._collect_planned_refresh_keys(provider_response.plan)
        self.store.record_audit_event(
            "plan_generated",
            {
                "source": "chat",
                "session_id": session_id,
                "configured_provider": self.settings.provider,
                "provider_backend": self.provider.name,
                "user_message": user_input,
                "history_size": len(conversation_history),
                "summary_present": bool(session_summary),
                "message": provider_response.message,
                "provider_metadata": provider_response.metadata,
                "response_id": provider_response.response_id,
                "plan": plan_payload,
                "stale_observation_keys": stale_observation_keys,
                "planned_refresh_keys": planned_refresh_keys,
                "iteration": iteration,
                "prior_execution_count": len(accumulated_executions),
            },
        )

    def _collect_planned_refresh_keys(self, plan: ExecutionPlan | None) -> list[str]:
        if plan is None:
            return []
        keys: list[str] = []
        for step in plan.steps:
            observation_key = observation_key_for_tool(step.tool_name)
            if observation_key is None or observation_key in keys:
                continue
            keys.append(observation_key)
        return keys

    def _render_chat_response(
        self,
        provider_response: ProviderResponse,
        executions: list[dict[str, object]],
    ) -> str:
        sections = [provider_response.message]
        rendered_results = [self._render_execution_summary(execution) for execution in executions]
        rendered_results = [item for item in rendered_results if item]
        if rendered_results:
            sections.extend(rendered_results)
        return "\n\n".join(sections)

    def _sync_session_recommendations(
        self,
        session_id: int,
        insights: list[SessionInsight],
    ) -> RecommendationSyncResult:
        candidates = [item.as_dict() for item in build_recommendation_candidates(insights)]
        payload = self.store.sync_session_recommendations(session_id, candidates)
        return RecommendationSyncResult(
            active=list(payload["active"]),
            new=list(payload["new"]),
            reopened=list(payload["reopened"]),
            auto_resolved=list(payload["auto_resolved"]),
        )

    def _append_recommendations_to_message(
        self,
        message: str,
        sync: RecommendationSyncResult,
    ) -> str:
        highlighted = [*sync.new, *sync.reopened]
        if not highlighted:
            return message

        lines: list[str] = []
        for item in highlighted[:2]:
            line = f"- [#{item['id']} {item['status']}] {item['message']}"
            action = item.get("action")
            if isinstance(action, dict):
                title = action.get("title")
                if isinstance(title, str) and title.strip():
                    line += f" Ação sugerida: {title.strip()}"
            lines.append(line)
        rendered = "\n".join(lines)
        return f"{message}\n\nRecomendações da sessão:\n{rendered}"

    def _render_execution_summary(self, execution: dict[str, object]) -> str:
        if not execution.get("ok"):
            if execution.get("pending_confirmation"):
                approval = execution.get("approval")
                if isinstance(approval, dict):
                    cli_command = approval.get("cli_command")
                    chat_command = approval.get("chat_command")
                    return (
                        f"A execução de `{execution['tool']}` exige confirmação explícita antes de prosseguir. "
                        f"CLI: `{cli_command}`. Chat: `{chat_command}`."
                    )
                return (
                    f"A execução de `{execution['tool']}` exige confirmação explícita antes de prosseguir."
                )
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
                "Disco em {path}: {used_percent}% usado "
                "({used} usados de {total}, {free} livres)."
            ).format(
                path=result["path"],
                used_percent=result["used_percent"],
                used=self._human_bytes(int(result["used_bytes"])),
                total=self._human_bytes(int(result["total_bytes"])),
                free=self._human_bytes(int(result["free_bytes"])),
            )

        if tool_name == "memory_usage":
            return (
                "Memória usada: {mem_percent}% ({mem_used} de {mem_total}). "
                "Swap usada: {swap_percent}% ({swap_used} de {swap_total})."
            ).format(
                mem_percent=result["memory_used_percent"],
                mem_used=self._human_bytes(int(result["memory_used_bytes"])),
                mem_total=self._human_bytes(int(result["memory_total_bytes"])),
                swap_percent=result["swap_used_percent"],
                swap_used=self._human_bytes(int(result["swap_used_bytes"])),
                swap_total=self._human_bytes(int(result["swap_total_bytes"])),
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

        if tool_name == "service_status":
            if result.get("status") != "ok":
                service = result.get("service", execution["arguments"].get("name", "serviço"))
                scope = result.get("scope")
                scope_text = f" ({scope})" if isinstance(scope, str) and scope else ""
                return (
                    f"Nao foi possivel consultar o serviço{scope_text} `{service}`: "
                    f"{result.get('reason', 'motivo desconhecido')}."
                )
            active = result.get("activestate", "desconhecido")
            sub = result.get("substate", "desconhecido")
            unit_file_state = result.get("unitfilestate", "desconhecido")
            service = result.get("service", execution["arguments"].get("name", "serviço"))
            scope = result.get("scope")
            scope_text = f" ({scope})" if isinstance(scope, str) and scope else ""
            return (
                f"Serviço{scope_text} `{service}`: active={active}, sub={sub}, unit_file_state={unit_file_state}."
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

        if tool_name == "read_config_file":
            path = result.get("path", execution["arguments"].get("path", "arquivo"))
            line_count = result.get("line_count", 0)
            return f"Arquivo `{path}` lido com sucesso ({line_count} linhas)."

        if tool_name == "write_config_file":
            path = result.get("path", execution["arguments"].get("path", "arquivo"))
            backup_path = result.get("backup_path")
            changed = result.get("changed", False)
            if not changed:
                return f"Arquivo `{path}` já estava no conteúdo desejado."
            if backup_path:
                return f"Arquivo `{path}` atualizado com backup em `{backup_path}`."
            return f"Arquivo `{path}` criado e validado."

        if tool_name == "restore_config_backup":
            path = result.get("path", execution["arguments"].get("path", "arquivo"))
            restored_from = result.get("restored_from")
            return f"Arquivo `{path}` restaurado a partir de `{restored_from}`."

        if tool_name == "restart_service":
            service = result.get("service", execution["arguments"].get("name", "serviço"))
            scope = result.get("scope")
            scope_text = f" ({scope})" if isinstance(scope, str) and scope else ""
            post_restart = result.get("post_restart")
            if not isinstance(post_restart, dict):
                return f"Serviço{scope_text} `{service}` reiniciado."
            active = post_restart.get("activestate", "desconhecido")
            sub = post_restart.get("substate", "desconhecido")
            return (
                f"Serviço{scope_text} `{service}` reiniciado. Estado atual: active={active}, sub={sub}."
            )

        if tool_name == "reload_service":
            service = result.get("service", execution["arguments"].get("name", "serviço"))
            scope = result.get("scope")
            scope_text = f" ({scope})" if isinstance(scope, str) and scope else ""
            post_reload = result.get("post_reload")
            if not isinstance(post_reload, dict):
                return f"Serviço{scope_text} `{service}` recarregado."
            active = post_reload.get("activestate", "desconhecido")
            sub = post_reload.get("substate", "desconhecido")
            return (
                f"Serviço{scope_text} `{service}` recarregado. Estado atual: active={active}, sub={sub}."
            )

        return json.dumps(result, indent=2, sort_keys=True)

    def _human_bytes(self, value: int) -> str:
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} TiB"

    def handle_message(self, user_input: str) -> str:
        normalized = user_input.strip()
        lowered = normalized.lower()

        if lowered in {"/help", "help"}:
            return (
                "Commands: /help, /doctor, /tools, /audit, /insights, /recommendations, "
                "/recommendation <id> <status>, /recommendation-run <id> [confirm], "
                "/tool <name> [key=value ...] [confirm]. "
                "Natural-language requests are routed through the configured provider."
            )

        if lowered == "/doctor":
            return json.dumps(self.doctor(), indent=2, sort_keys=True)

        if lowered == "/tools":
            payload = [spec.as_dict() for spec in self.list_tools()]
            return json.dumps(payload, indent=2, sort_keys=True)

        if lowered == "/audit":
            return json.dumps(self.list_audit_events(), indent=2, sort_keys=True)

        if lowered == "/insights":
            try:
                payload = self.get_session_insights()
            except ValueError as exc:
                return str(exc)
            return json.dumps(payload, indent=2, sort_keys=True)

        if lowered == "/recommendations":
            try:
                payload = self.list_session_recommendations()
            except ValueError as exc:
                return str(exc)
            return json.dumps(payload, indent=2, sort_keys=True)

        if lowered.startswith("/recommendation "):
            try:
                tokens = shlex.split(normalized)
            except ValueError as exc:
                return f"Invalid /recommendation invocation: {exc}"

            if len(tokens) != 3:
                return "Usage: /recommendation <id> <open|accepted|dismissed|resolved>"
            try:
                recommendation_id = int(tokens[1])
            except ValueError:
                return "Recommendation id must be an integer."
            try:
                payload = self.update_recommendation_status(recommendation_id, tokens[2])
            except ValueError as exc:
                return str(exc)
            return json.dumps(payload, indent=2, sort_keys=True)

        if lowered.startswith("/recommendation-run "):
            try:
                tokens = shlex.split(normalized)
            except ValueError as exc:
                return f"Invalid /recommendation-run invocation: {exc}"

            if len(tokens) not in {2, 3}:
                return "Usage: /recommendation-run <id> [confirm]"
            try:
                recommendation_id = int(tokens[1])
            except ValueError:
                return "Recommendation id must be an integer."
            confirmed = len(tokens) == 3 and tokens[2].lower() == "confirm"
            if len(tokens) == 3 and not confirmed:
                return "Usage: /recommendation-run <id> [confirm]"
            try:
                payload = self.run_recommendation_action(
                    recommendation_id,
                    confirmed=confirmed,
                )
            except ValueError as exc:
                return str(exc)
            return json.dumps(payload, indent=2, sort_keys=True)

        if lowered.startswith("/tool "):
            try:
                tokens = shlex.split(normalized)
            except ValueError as exc:
                return f"Invalid /tool invocation: {exc}"

            if len(tokens) < 2:
                return "Usage: /tool <name> [key=value ...] [confirm]"

            name = tokens[1]
            arguments: dict[str, object] = {}
            confirmed = False
            for token in tokens[2:]:
                if token.lower() == "confirm":
                    confirmed = True
                    continue
                if "=" not in token:
                    return "Tool arguments must use key=value syntax."
                key, value = token.split("=", maxsplit=1)
                arguments[key] = value
            return json.dumps(
                self.run_tool(name, arguments, confirmed=confirmed),
                indent=2,
                sort_keys=True,
            )

        return self.chat(normalized)["message"]
