from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from master_control.agent.observations import (
    ObservationFreshness,
    build_observation_envelopes,
    build_observation_freshness,
)
from master_control.agent.planner import ExecutionPlan
from master_control.agent.recommendation_sync import RecommendationSyncResult
from master_control.agent.recommendation_view import (
    build_recommendation_sync_result,
    enrich_recommendations_with_freshness,
    enrich_recommendations_with_operator_guidance,
)
from master_control.agent.session_analysis import build_session_analysis
from master_control.agent.session_context import SessionContext, build_session_context
from master_control.agent.session_insights import SessionInsight
from master_control.agent.session_recommendations import (
    ACTIVE_RECOMMENDATION_STATUSES,
    RECOMMENDATION_STATUSES,
    build_recommendation_candidates,
    sort_recommendations,
)
from master_control.agent.session_summary import update_session_summary
from master_control.agent.turn_planning import (
    build_turn_planning_prompt,
    classify_turn_decision,
    collect_planned_refresh_keys,
    collect_stale_observation_keys,
    should_continue_planning,
    summarize_execution_for_planner,
    validate_provider_response_for_loop,
)
from master_control.agent.turn_rendering import (
    append_recommendations_to_message,
    apply_turn_decision_guidance,
    collect_rendered_execution_summaries,
    render_chat_response,
)
from master_control.config import Settings
from master_control.policy.engine import PolicyEngine
from master_control.providers.availability import collect_provider_checks
from master_control.providers.base import (
    ConversationMessage,
    ProviderClient,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    SynthesisRequest,
)
from master_control.providers.factory import build_provider
from master_control.store.session_store import SessionStore
from master_control.systemd_timer import (
    SystemdTimerError,
    collect_reconcile_timer_diagnostics,
    install_reconcile_timer,
    remove_reconcile_timer,
    render_reconcile_units,
)
from master_control.tools.base import ToolError
from master_control.tools.registry import ToolRegistry, build_default_registry

PROVIDER_HISTORY_LIMIT = 8
MAX_PLANNING_ITERATIONS = 6
MULTI_STEP_PLANNING_INTENTS = {"diagnose_performance"}


@dataclass(frozen=True, slots=True)
class PlanningLoopResult:
    provider_response: ProviderResponse
    executions: list[dict[str, object]]
    working_summary: str | None
    working_session_context: SessionContext
    working_freshness: tuple[ObservationFreshness, ...]
    response_id: str | None


@dataclass(frozen=True, slots=True)
class FinalChatResponse:
    message: str
    response_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


def _describe_tool_target(tool_name: str, arguments: dict[str, object]) -> str:
    if tool_name in {"service_status", "restart_service", "reload_service"}:
        name = arguments.get("name")
        scope = arguments.get("scope")
        if isinstance(name, str) and name:
            if isinstance(scope, str) and scope:
                return f"`{tool_name}` no serviço `{name}` ({scope})"
            return f"`{tool_name}` no serviço `{name}`"
    if tool_name == "failed_services":
        scope = arguments.get("scope")
        if isinstance(scope, str) and scope:
            return f"`{tool_name}` no escopo `{scope}`"
        return f"`{tool_name}`"
    if tool_name == "process_to_unit":
        process_name = arguments.get("name")
        pid = arguments.get("pid")
        if isinstance(process_name, str) and process_name:
            return f"`{tool_name}` para o processo `{process_name}`"
        if isinstance(pid, int):
            return f"`{tool_name}` para `pid={pid}`"
    if tool_name in {"disk_usage", "read_config_file", "write_config_file", "restore_config_backup"}:
        path = arguments.get("path")
        if isinstance(path, str) and path:
            return f"`{tool_name}` em `{path}`"
    return f"`{tool_name}`"


def _coerce_int(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"Expected integer-compatible value for {label}, got {type(value).__name__}.")


def _coerce_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return {}


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
        store_diagnostics = self.store.diagnostics()
        timer_diagnostics = collect_reconcile_timer_diagnostics()
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
        doctor_ok = bool(active_provider_check.get("available", False)) and bool(
            store_diagnostics.get("ok", False)
        )
        llm_provider_available = any(
            bool(provider_checks[name].get("available", False)) for name in ("ollama", "openai")
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
            "store_diagnostics": store_diagnostics,
            "reconcile_timer_diagnostics": timer_diagnostics,
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
            session_id = _coerce_int(session["session_id"], "session_id")
            observation_freshness = self._load_observation_freshness(session_id)
            analysis = build_session_analysis(
                str(summary_text) if isinstance(summary_text, str) else None,
                observation_freshness,
            )
            active_recommendations = self.store.list_session_recommendations(
                session_id,
                limit=200,
            )
            active_count = sum(
                1
                for item in active_recommendations
                if item["status"] in ACTIVE_RECOMMENDATION_STATUSES
            )
            enriched.append(
                {
                    **session,
                    "session_context": analysis.session_context.as_dict(),
                    "insight_count": len(analysis.insights),
                    "active_recommendation_count": active_count,
                }
            )
        return enriched

    def get_session_insights(self, session_id: int | None = None) -> dict[str, object]:
        self.bootstrap()
        resolved_session_id = self._resolve_session_id(session_id)
        summary_text = self._load_session_summary(resolved_session_id)
        observation_freshness = self._load_observation_freshness(resolved_session_id)
        analysis = build_session_analysis(
            summary_text,
            observation_freshness,
        )
        return {
            "session_id": resolved_session_id,
            "summary_text": summary_text,
            "session_context": analysis.session_context.as_dict(),
            "observation_freshness": [item.as_dict() for item in observation_freshness],
            "insights": [insight.as_dict() for insight in analysis.insights],
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
        observation_freshness = self._load_observation_freshness(resolved_session_id)
        recommendations = self.store.list_session_recommendations(
            resolved_session_id,
            status=status,
            limit=200,
        )
        recommendations = enrich_recommendations_with_freshness(
            recommendations,
            observation_freshness,
        )
        recommendations = enrich_recommendations_with_operator_guidance(
            recommendations,
            command_builder=self._build_recommendation_commands,
        )
        recommendations = sort_recommendations(recommendations)
        return {
            "session_id": resolved_session_id,
            "status_filter": status,
            "recommendations": recommendations,
        }

    def reconcile_recommendations(
        self,
        *,
        session_id: int | None = None,
        all_sessions: bool = False,
    ) -> dict[str, object]:
        self.bootstrap()
        if all_sessions and session_id is not None:
            raise ValueError("Cannot use session_id and all_sessions at the same time.")

        if all_sessions:
            session_ids = [
                _coerce_int(item["session_id"], "session_id")
                for item in self.store.list_sessions(limit=10_000)
            ]
        else:
            session_ids = [self._resolve_session_id(session_id)]

        reconciled_sessions: list[dict[str, object]] = []
        for resolved_session_id in session_ids:
            summary_text = self._load_session_summary(resolved_session_id)
            observation_freshness = self._load_observation_freshness(resolved_session_id)
            analysis = build_session_analysis(summary_text, observation_freshness)
            sync = self._sync_session_recommendations(
                resolved_session_id,
                list(analysis.insights),
                observation_freshness,
            )
            payload = {
                "session_id": resolved_session_id,
                "insight_count": len(analysis.insights),
                "observation_count": len(observation_freshness),
                "stale_observation_count": sum(1 for item in observation_freshness if item.stale),
                "active_count": len(sync.active),
                "new_count": len(sync.new),
                "reopened_count": len(sync.reopened),
                "auto_resolved_count": len(sync.auto_resolved),
                "recommendations": sync.as_dict(),
            }
            self.store.record_audit_event(
                "recommendations_reconciled",
                payload,
            )
            reconciled_sessions.append(payload)

        return {
            "mode": "all" if all_sessions else "single",
            "session_count": len(reconciled_sessions),
            "sessions": reconciled_sessions,
        }

    def render_reconcile_timer(
        self,
        *,
        scope: str = "user",
        on_calendar: str = "hourly",
        randomized_delay: str = "5m",
        target_dir: str | None = None,
        python_executable: str | None = None,
    ) -> dict[str, object]:
        units = render_reconcile_units(
            self.settings,
            scope=scope,
            on_calendar=on_calendar,
            randomized_delay=randomized_delay,
            target_dir=Path(target_dir) if target_dir else None,
            python_executable=python_executable,
        )
        return {
            "scope": scope,
            "service": units["service"].as_dict(),
            "timer": units["timer"].as_dict(),
            "on_calendar": on_calendar,
            "randomized_delay": randomized_delay,
        }

    def install_reconcile_timer(
        self,
        *,
        scope: str = "user",
        on_calendar: str = "hourly",
        randomized_delay: str = "5m",
        target_dir: str | None = None,
        python_executable: str | None = None,
        run_systemctl: bool = True,
    ) -> dict[str, object]:
        self.bootstrap()
        try:
            payload = install_reconcile_timer(
                self.settings,
                scope=scope,
                on_calendar=on_calendar,
                randomized_delay=randomized_delay,
                target_dir=Path(target_dir) if target_dir else None,
                python_executable=python_executable,
                run_systemctl=run_systemctl,
            )
        except SystemdTimerError as exc:
            raise ValueError(str(exc)) from exc
        self.store.record_audit_event("reconcile_timer_installed", payload)
        return payload

    def remove_reconcile_timer(
        self,
        *,
        scope: str = "user",
        target_dir: str | None = None,
        run_systemctl: bool = True,
    ) -> dict[str, object]:
        self.bootstrap()
        try:
            payload = remove_reconcile_timer(
                scope=scope,
                target_dir=Path(target_dir) if target_dir else None,
                run_systemctl=run_systemctl,
            )
        except SystemdTimerError as exc:
            raise ValueError(str(exc)) from exc
        self.store.record_audit_event("reconcile_timer_removed", payload)
        return payload

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
            recommendation = self.store.get_recommendation(recommendation_id)
            summary = "Execute a ação da recomendação com confirmação explícita."
            if isinstance(recommendation, dict):
                action = recommendation.get("action")
                if isinstance(action, dict):
                    title = action.get("title")
                    if isinstance(title, str) and title.strip():
                        summary = title.strip()
                message = recommendation.get("message")
                if isinstance(message, str) and message.strip():
                    summary = f"{summary} Evidência: {message.strip()}"
            return {
                "required": True,
                "cli_command": commands["cli_confirm_command"],
                "chat_command": commands["chat_confirm_command"],
                "summary": summary,
            }

        return {
            "required": True,
            "cli_command": self._format_cli_tool_command(tool_name, arguments, confirmed=True),
            "chat_command": self._format_chat_tool_command(tool_name, arguments, confirmed=True),
            "summary": f"Confirme a execução de {_describe_tool_target(tool_name, arguments)}.",
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
        active_session_id = self._prepare_chat_session(
            session_id=session_id, new_session=new_session
        )
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

        plan_payload = (
            planning_result.provider_response.plan.as_dict()
            if planning_result.provider_response.plan
            else None
        )
        plan_decision = planning_result.provider_response.resolved_decision().as_dict()
        resolved_turn_decision = classify_turn_decision(
            planning_result.provider_response,
            planning_result.executions,
            multi_step_intents=MULTI_STEP_PLANNING_INTENTS,
        )
        turn_decision = resolved_turn_decision.as_dict()
        final_response = self._build_final_chat_response(
            planning_result.provider_response,
            planning_result.executions,
            user_input=user_input,
            session_id=active_session_id,
            conversation_history=conversation_history,
            session_summary=planning_result.working_summary,
            previous_response_id=planning_result.response_id,
        )
        final_provider_response_id = final_response.response_id or planning_result.response_id
        self.previous_provider_response_id = final_provider_response_id
        self.store.update_session_provider_state(
            active_session_id,
            self.provider.name,
            final_provider_response_id,
        )
        provider_metadata = dict(planning_result.provider_response.metadata)
        if final_response.metadata:
            provider_metadata["synthesis"] = final_response.metadata
        updated_summary = update_session_summary(
            planning_result.working_summary,
            user_input=user_input,
            plan=planning_result.provider_response.plan,
            executions=[],
            assistant_message=final_response.message,
        )
        self.store.upsert_session_summary(active_session_id, updated_summary)
        observation_freshness = planning_result.working_freshness
        analysis = build_session_analysis(
            updated_summary,
            observation_freshness,
        )
        recommendation_sync = self._sync_session_recommendations(
            active_session_id,
            list(analysis.insights),
            observation_freshness,
        )
        message_with_turn_guidance = apply_turn_decision_guidance(
            final_response.message,
            planning_result.executions,
            resolved_turn_decision,
        )
        final_message_with_recommendations = append_recommendations_to_message(
            message_with_turn_guidance,
            recommendation_sync,
        )
        self.store.append_conversation_message(
            active_session_id,
            "assistant",
            final_message_with_recommendations,
        )
        self.store.record_audit_event(
            "chat_completed",
            {
                "source": "chat",
                "session_id": active_session_id,
                "configured_provider": self.settings.provider,
                "provider_backend": self.provider.name,
                "plan_decision": plan_decision,
                "turn_decision": turn_decision,
                "execution_count": len(planning_result.executions),
                "recommendation_highlight_count": len(recommendation_sync.new)
                + len(recommendation_sync.reopened),
            },
        )
        return {
            "provider": self.provider.name,
            "session_id": active_session_id,
            "message": final_message_with_recommendations,
            "plan": plan_payload,
            "plan_decision": plan_decision,
            "turn_decision": turn_decision,
            "provider_metadata": provider_metadata,
            "session_summary": updated_summary,
            "session_context": analysis.session_context.as_dict(),
            "observation_freshness": [item.as_dict() for item in observation_freshness],
            "insights": [insight.as_dict() for insight in analysis.insights],
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
        working_session_context = self._build_session_context(working_summary, working_freshness)
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
                session_context=working_session_context,
                observation_freshness=working_freshness,
                previous_response_id=previous_response_id,
                system_prompt=build_turn_planning_prompt(
                    user_input=user_input,
                    iteration=iteration,
                    executions=accumulated_executions,
                ),
            )
            provider_response = self.provider.plan(provider_request)
            last_provider_response = provider_response
            previous_response_id = provider_response.response_id or previous_response_id
            decision = validate_provider_response_for_loop(provider_response)

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

            if decision.state != "needs_tools":
                break

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
            working_session_context = self._build_session_context(
                working_summary,
                working_freshness,
            )

            if any(not execution.get("ok") for execution in new_executions):
                break
            if not should_continue_planning(
                provider_response.plan,
                multi_step_intents=MULTI_STEP_PLANNING_INTENTS,
            ):
                break

        return PlanningLoopResult(
            provider_response=last_provider_response,
            executions=accumulated_executions,
            working_summary=working_summary,
            working_session_context=working_session_context,
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

    def _build_session_context(
        self,
        session_summary: str | None,
        observation_freshness: tuple[ObservationFreshness, ...],
    ) -> SessionContext:
        return build_session_context(session_summary, observation_freshness)

    def latest_session_id(self) -> int:
        self.bootstrap()
        sessions = self.store.list_sessions(limit=1)
        if not sessions:
            raise ValueError("No sessions available.")
        resolved = sessions[0].get("session_id")
        if not isinstance(resolved, int):
            raise ValueError("No sessions available.")
        return resolved

    def _resolve_session_id(self, session_id: int | None) -> int:
        if session_id is not None:
            if not self.store.session_exists(session_id):
                raise ValueError(f"Unknown session_id: {session_id}")
            return session_id
        return self.latest_session_id()

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
        phase: str = "planning",
    ) -> None:
        self.store.record_audit_event(
            "provider_error",
            {
                "source": "chat",
                "phase": phase,
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
        stale_observation_keys = collect_stale_observation_keys(observation_freshness)
        planned_refresh_keys = collect_planned_refresh_keys(provider_response.plan)
        decision = provider_response.resolved_decision()
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
                "decision": decision.as_dict(),
                "plan": plan_payload,
                "stale_observation_keys": stale_observation_keys,
                "planned_refresh_keys": planned_refresh_keys,
                "iteration": iteration,
                "prior_execution_count": len(accumulated_executions),
            },
        )

    def _build_final_chat_response(
        self,
        provider_response: ProviderResponse,
        executions: list[dict[str, object]],
        *,
        user_input: str,
        session_id: int,
        conversation_history: list[ConversationMessage],
        session_summary: str | None,
        previous_response_id: str | None,
    ) -> FinalChatResponse:
        fallback_message = render_chat_response(provider_response, executions)
        if not executions:
            return FinalChatResponse(message=fallback_message, response_id=previous_response_id)

        synthesize = getattr(self.provider, "synthesize", None)
        if not callable(synthesize):
            return FinalChatResponse(message=fallback_message, response_id=previous_response_id)

        request = SynthesisRequest(
            user_message=user_input,
            planning_message=provider_response.message,
            execution_observations=tuple(
                summarize_execution_for_planner(execution) for execution in executions
            ),
            rendered_results=tuple(collect_rendered_execution_summaries(executions)),
            previous_response_id=previous_response_id,
        )
        try:
            synthesis_response = synthesize(request)
        except ProviderError as exc:
            self._record_provider_error(
                session_id=session_id,
                user_input=user_input,
                conversation_history=conversation_history,
                session_summary=session_summary,
                error=str(exc),
                phase="synthesis",
            )
            return FinalChatResponse(message=fallback_message, response_id=previous_response_id)

        synthesized_message = synthesis_response.message.strip()
        if not synthesized_message:
            return FinalChatResponse(message=fallback_message, response_id=previous_response_id)
        return FinalChatResponse(
            message=synthesized_message,
            response_id=synthesis_response.response_id or previous_response_id,
            metadata=synthesis_response.metadata,
        )

    def _sync_session_recommendations(
        self,
        session_id: int,
        insights: list[SessionInsight],
        observation_freshness: tuple[ObservationFreshness, ...],
    ) -> RecommendationSyncResult:
        candidates = [item.as_dict() for item in build_recommendation_candidates(insights)]
        payload = self.store.sync_session_recommendations(session_id, candidates)
        return build_recommendation_sync_result(
            payload,
            observation_freshness,
            command_builder=self._build_recommendation_commands,
        )

    def handle_message(self, user_input: str) -> str:
        normalized = user_input.strip()
        lowered = normalized.lower()

        if lowered in {"/help", "help"}:
            return (
                "Commands: /help, /doctor, /tools, /audit, /insights, /recommendations, /reconcile, "
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
                insights_payload = self.get_session_insights()
            except ValueError as exc:
                return str(exc)
            return json.dumps(insights_payload, indent=2, sort_keys=True)

        if lowered == "/recommendations":
            try:
                recommendations_payload = self.list_session_recommendations()
            except ValueError as exc:
                return str(exc)
            return json.dumps(recommendations_payload, indent=2, sort_keys=True)

        if lowered == "/reconcile":
            try:
                reconcile_payload = self.reconcile_recommendations()
            except ValueError as exc:
                return str(exc)
            return json.dumps(reconcile_payload, indent=2, sort_keys=True)

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
                recommendation_payload = self.update_recommendation_status(
                    recommendation_id,
                    tokens[2],
                )
            except ValueError as exc:
                return str(exc)
            return json.dumps(recommendation_payload, indent=2, sort_keys=True)

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
                recommendation_run_payload = self.run_recommendation_action(
                    recommendation_id,
                    confirmed=confirmed,
                )
            except ValueError as exc:
                return str(exc)
            return json.dumps(recommendation_run_payload, indent=2, sort_keys=True)

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

        chat_payload = self.chat(normalized)
        message = chat_payload.get("message")
        return message if isinstance(message, str) else json.dumps(chat_payload, indent=2)
