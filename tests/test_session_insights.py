from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from master_control.agent.observations import build_observation_freshness
from master_control.agent.planner import ExecutionPlan, PlanStep
from master_control.agent.session_context import (
    ConfigContext,
    LogContext,
    ProcessEntryContext,
    ProcessesContext,
    ProcessUnitContext,
    ServiceContext,
    SessionContext,
    TrackedEntities,
)
from master_control.agent.session_insights import (
    collect_session_insights,
    collect_session_insights_from_context,
    collect_session_insights_with_freshness,
)
from master_control.app import MasterControlApp
from master_control.config import Settings
from master_control.providers.base import ProviderResponse
from master_control.tools.base import RiskLevel, Tool, ToolSpec


class StaticPlanProvider:
    name = "static"

    def diagnostics(self) -> dict[str, object]:
        return {"name": self.name, "ready": True}

    def plan(self, request) -> ProviderResponse:
        del request
        return ProviderResponse(
            message="Vou verificar o disco.",
            plan=ExecutionPlan(
                intent="inspect_disk_usage",
                steps=(
                    PlanStep(
                        tool_name="disk_usage",
                        rationale="Inspect filesystem utilization for the requested path.",
                        arguments={"path": "/"},
                    ),
                ),
            ),
        )


class StaticServicePlanProvider:
    name = "static"

    def diagnostics(self) -> dict[str, object]:
        return {"name": self.name, "ready": True}

    def plan(self, request) -> ProviderResponse:
        del request
        return ProviderResponse(
            message="Vou verificar o status do serviço.",
            plan=ExecutionPlan(
                intent="inspect_service_status",
                steps=(
                    PlanStep(
                        tool_name="service_status",
                        rationale="Inspect the requested service status before any action.",
                        arguments={"name": "nginx.service"},
                    ),
                ),
            ),
        )


class StaticNoPlanProvider:
    name = "static"

    def diagnostics(self) -> dict[str, object]:
        return {"name": self.name, "ready": True}

    def plan(self, request) -> ProviderResponse:
        del request
        return ProviderResponse(
            message="Ainda não vou executar nada sem atualizar o contexto.",
            plan=None,
        )


class HighDiskUsageTool(Tool):
    spec = ToolSpec(
        name="disk_usage",
        description="Fake high disk usage tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("path",),
    )

    def invoke(self, arguments):
        path = arguments.get("path", "/")
        return {
            "path": path,
            "total_bytes": 100,
            "used_bytes": 95,
            "free_bytes": 5,
            "used_percent": 95.0,
        }


class SafeDiskUsageTool(Tool):
    spec = ToolSpec(
        name="disk_usage",
        description="Fake safe disk usage tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("path",),
    )

    def invoke(self, arguments):
        path = arguments.get("path", "/")
        return {
            "path": path,
            "total_bytes": 100,
            "used_bytes": 40,
            "free_bytes": 60,
            "used_percent": 40.0,
        }


class FailedServiceStatusTool(Tool):
    spec = ToolSpec(
        name="service_status",
        description="Fake unhealthy service status tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("name",),
    )

    def invoke(self, arguments):
        name = arguments.get("name", "nginx.service")
        return {
            "status": "ok",
            "service": name,
            "activestate": "failed",
            "substate": "failed",
            "unitfilestate": "enabled",
        }


class SuccessfulRestartServiceTool(Tool):
    spec = ToolSpec(
        name="restart_service",
        description="Fake restart service tool for tests.",
        risk=RiskLevel.PRIVILEGED,
        arguments=("name",),
    )

    def invoke(self, arguments):
        name = arguments.get("name", "nginx.service")
        return {
            "status": "ok",
            "service": name,
            "preflight": {
                "service": name,
                "activestate": "failed",
                "substate": "failed",
            },
            "post_restart": {
                "service": name,
                "activestate": "active",
                "substate": "running",
            },
        }


class SessionInsightsTest(unittest.TestCase):
    def test_collect_session_insights_detects_disk_pressure(self) -> None:
        insights = collect_session_insights("disk: / is 95.0% used")

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "disk_pressure")
        self.assertEqual(insights[0].severity, "critical")

    def test_collect_session_insights_hot_process_proposes_process_correlation(self) -> None:
        insights = collect_session_insights_from_context(
            SessionContext(
                tracked=TrackedEntities(),
                processes=ProcessesContext(
                    items=(ProcessEntryContext(command="python3", cpu_percent=91.2),),
                    stale=False,
                ),
            ),
            (),
        )

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "hot_process")
        self.assertEqual(insights[0].action_tool_name, "process_to_unit")
        self.assertEqual(insights[0].action_arguments, {"name": "python3", "limit": "3"})

    def test_collect_session_insights_hot_process_prefers_service_relevant_lead(self) -> None:
        insights = collect_session_insights_from_context(
            SessionContext(
                tracked=TrackedEntities(),
                processes=ProcessesContext(
                    items=(
                        ProcessEntryContext(command="python3", cpu_percent=91.2, occurrences=2),
                        ProcessEntryContext(command="nginx", cpu_percent=88.0),
                    ),
                    stale=False,
                ),
            ),
            (),
        )

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].target, "nginx")
        self.assertEqual(insights[0].action_tool_name, "process_to_unit")
        self.assertEqual(insights[0].action_arguments, {"name": "nginx", "limit": "3"})
        self.assertIn("melhor próximo alvo", insights[0].message)

    def test_collect_session_insights_hot_process_known_correlation_proposes_service_follow_up(
        self,
    ) -> None:
        insights = collect_session_insights_from_context(
            SessionContext(
                tracked=TrackedEntities(unit="ollama-local.service", scope="user"),
                processes=ProcessesContext(
                    items=(ProcessEntryContext(command="python3", cpu_percent=91.2),),
                    stale=False,
                ),
                process_unit=ProcessUnitContext(
                    query_name="python3",
                    unit="ollama-local.service",
                    scope="user",
                    stale=False,
                ),
            ),
            (),
        )

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "hot_process")
        self.assertEqual(insights[0].action_tool_name, "service_status")
        self.assertEqual(
            insights[0].action_arguments,
            {"name": "ollama-local.service", "scope": "user"},
        )
        self.assertIn("ollama-local.service", insights[0].message)

    def test_collect_session_insights_hot_process_with_service_correlation_proposes_status(
        self,
    ) -> None:
        insights = collect_session_insights_from_context(
            SessionContext(
                tracked=TrackedEntities(unit="nginx.service", scope="system"),
                processes=ProcessesContext(
                    items=(ProcessEntryContext(command="nginx", cpu_percent=91.2),),
                    stale=False,
                ),
                process_unit=ProcessUnitContext(
                    query_name="nginx",
                    unit="nginx.service",
                    scope="system",
                    attempted=True,
                    stale=False,
                ),
            ),
            (),
        )

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "hot_process")
        self.assertEqual(insights[0].action_tool_name, "service_status")
        self.assertEqual(
            insights[0].action_arguments,
            {"name": "nginx.service", "scope": "system"},
        )

    def test_collect_session_insights_hot_process_does_not_repeat_known_no_match(self) -> None:
        insights = collect_session_insights_from_context(
            SessionContext(
                tracked=TrackedEntities(),
                processes=ProcessesContext(
                    items=(ProcessEntryContext(command="python3", cpu_percent=91.2),),
                    stale=False,
                ),
                process_unit=ProcessUnitContext(
                    query_name="python3",
                    attempted=True,
                    no_match=True,
                    stale=False,
                ),
            ),
            (),
        )

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "hot_process")
        self.assertIsNone(insights[0].action_tool_name)
        self.assertIn("não houve um unit claro", insights[0].message)

    def test_collect_session_insights_failed_services_proposes_service_detail(self) -> None:
        freshness = build_observation_freshness(
            (
                {
                    "source": "failed_services",
                    "key": "failed_services",
                    "value": {
                        "scope": "system",
                        "units": [
                            {
                                "unit": "nginx.service",
                                "active_state": "failed",
                                "sub_state": "failed",
                            },
                            {
                                "unit": "postgresql.service",
                                "active_state": "failed",
                                "sub_state": "failed",
                            },
                        ],
                    },
                    "observed_at": "2100-03-18T01:00:00Z",
                    "expires_at": "2100-03-18T01:03:00Z",
                },
            )
        )

        insights = collect_session_insights_with_freshness(None, freshness)

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "failed_service_detected")
        self.assertEqual(insights[0].action_tool_name, "service_status")
        self.assertEqual(
            insights[0].action_arguments,
            {"name": "nginx.service", "scope": "system"},
        )

    def test_collect_session_insights_config_backup_proposes_restore(self) -> None:
        insights = collect_session_insights_from_context(
            SessionContext(
                tracked=TrackedEntities(path="/etc/app.ini"),
                config=ConfigContext(
                    path="/etc/app.ini",
                    target="managed_ini",
                    validation_kind="ini_parse",
                    backup_path="/tmp/app.bak",
                    stale=False,
                ),
            ),
            (),
        )

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "config_backup_available")
        self.assertEqual(insights[0].action_tool_name, "restore_config_backup")
        self.assertEqual(
            insights[0].action_arguments,
            {"path": "/etc/app.ini", "backup_path": "/tmp/app.bak"},
        )

    def test_collect_session_insights_config_write_proposes_verification(self) -> None:
        insights = collect_session_insights_from_context(
            SessionContext(
                tracked=TrackedEntities(path="/etc/app.ini"),
                config=ConfigContext(
                    source="write_config_file",
                    path="/etc/app.ini",
                    target="managed_ini",
                    validation_kind="ini_parse",
                    stale=False,
                ),
            ),
            (),
        )

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "config_verification_available")
        self.assertEqual(insights[0].action_tool_name, "read_config_file")
        self.assertEqual(insights[0].action_arguments, {"path": "/etc/app.ini"})

    def test_collect_session_insights_without_service_evidence_does_not_propose_restart(
        self,
    ) -> None:
        insights = collect_session_insights("service: nginx.service: active=failed, sub=failed")

        self.assertEqual(len(insights), 2)
        service_state = next(item for item in insights if item.key == "service_state")
        logs_follow_up = next(item for item in insights if item.key == "service_logs_follow_up")
        self.assertEqual(service_state.target, "nginx.service")
        self.assertIsNone(service_state.action_tool_name)
        self.assertEqual(service_state.action_arguments, {})
        self.assertEqual(logs_follow_up.action_tool_name, "read_journal")
        self.assertEqual(logs_follow_up.action_arguments, {"unit": "nginx.service", "lines": "40"})

    def test_collect_session_insights_preserves_scope_for_unhealthy_service(self) -> None:
        insights = collect_session_insights(
            "\n".join(
                [
                    "tracked_unit: ollama-local.service",
                    "tracked_scope: user",
                    "service: ollama-local.service: active=failed, sub=failed",
                ]
            )
        )

        self.assertEqual(len(insights), 2)
        service_state = next(item for item in insights if item.key == "service_state")
        logs_follow_up = next(item for item in insights if item.key == "service_logs_follow_up")
        self.assertIsNone(service_state.action_tool_name)
        self.assertEqual(service_state.action_arguments, {})
        self.assertEqual(logs_follow_up.action_tool_name, "read_journal")
        self.assertEqual(
            logs_follow_up.action_arguments,
            {"unit": "ollama-local.service", "lines": "40"},
        )

    def test_collect_session_insights_with_fresh_service_evidence_proposes_restart(self) -> None:
        freshness = build_observation_freshness(
            (
                {
                    "source": "service_status",
                    "key": "service",
                    "value": {"service": "ollama-local.service", "scope": "user"},
                    "observed_at": "2100-03-18T01:00:00Z",
                    "expires_at": "2100-03-18T01:03:00Z",
                },
                {
                    "source": "read_journal",
                    "key": "logs",
                    "value": {"unit": "ollama-local.service", "returned_lines": 20},
                    "observed_at": "2100-03-18T01:01:00Z",
                    "expires_at": "2100-03-18T01:02:30Z",
                },
            )
        )

        insights = collect_session_insights_with_freshness(
            "\n".join(
                [
                    "tracked_unit: ollama-local.service",
                    "tracked_scope: user",
                    "service: ollama-local.service: active=failed, sub=failed",
                ]
            ),
            freshness,
        )

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "service_state")
        self.assertEqual(insights[0].action_tool_name, "restart_service")
        self.assertEqual(
            insights[0].action_arguments,
            {"name": "ollama-local.service", "scope": "user"},
        )

    def test_collect_session_insights_from_context_proposes_restart_without_summary(self) -> None:
        freshness = build_observation_freshness(
            (
                {
                    "source": "service_status",
                    "key": "service",
                    "value": {"service": "ollama-local.service", "scope": "user"},
                    "observed_at": "2100-03-18T01:00:00Z",
                    "expires_at": "2100-03-18T01:03:00Z",
                },
                {
                    "source": "read_journal",
                    "key": "logs",
                    "value": {"unit": "ollama-local.service", "returned_lines": 20},
                    "observed_at": "2100-03-18T01:01:00Z",
                    "expires_at": "2100-03-18T01:02:30Z",
                },
            )
        )

        insights = collect_session_insights_from_context(
            SessionContext(
                tracked=TrackedEntities(unit="ollama-local.service", scope="user"),
                service=ServiceContext(
                    name="ollama-local.service",
                    scope="user",
                    active_state="failed",
                    sub_state="failed",
                ),
                logs=LogContext(unit="ollama-local.service", returned_lines=20, stale=False),
            ),
            freshness,
        )

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "service_state")
        self.assertEqual(insights[0].action_tool_name, "restart_service")
        self.assertEqual(
            insights[0].action_arguments,
            {"name": "ollama-local.service", "scope": "user"},
        )

    def test_collect_session_insights_unhealthy_service_suggests_logs_when_not_reviewed(
        self,
    ) -> None:
        freshness = build_observation_freshness(
            (
                {
                    "source": "service_status",
                    "key": "service",
                    "value": {"service": "nginx.service", "scope": "system"},
                    "observed_at": "2100-03-18T01:00:00Z",
                    "expires_at": "2100-03-18T01:03:00Z",
                },
            )
        )

        insights = collect_session_insights_from_context(
            SessionContext(
                tracked=TrackedEntities(unit="nginx.service", scope="system"),
                service=ServiceContext(
                    name="nginx.service",
                    scope="system",
                    active_state="failed",
                    sub_state="failed",
                ),
            ),
            freshness,
        )

        self.assertEqual(len(insights), 2)
        logs_follow_up = next(item for item in insights if item.key == "service_logs_follow_up")
        self.assertEqual(logs_follow_up.action_tool_name, "read_journal")
        self.assertEqual(
            logs_follow_up.action_arguments,
            {"unit": "nginx.service", "lines": "40"},
        )

    def test_collect_session_insights_stale_logs_suggest_log_refresh(self) -> None:
        freshness = build_observation_freshness(
            (
                {
                    "source": "service_status",
                    "key": "service",
                    "value": {"service": "nginx.service", "scope": "system"},
                    "observed_at": "2100-03-18T01:00:00Z",
                    "expires_at": "2100-03-18T01:03:00Z",
                },
                {
                    "source": "read_journal",
                    "key": "logs",
                    "value": {"unit": "nginx.service", "returned_lines": 10},
                    "observed_at": "2026-03-17T20:00:00Z",
                    "expires_at": "2026-03-17T20:01:30Z",
                },
            )
        )

        insights = collect_session_insights_from_context(
            SessionContext(
                tracked=TrackedEntities(unit="nginx.service", scope="system"),
                service=ServiceContext(
                    name="nginx.service",
                    scope="system",
                    active_state="failed",
                    sub_state="failed",
                ),
                logs=LogContext(unit="nginx.service", returned_lines=10, stale=True),
            ),
            freshness,
        )

        logs_follow_up = next(item for item in insights if item.key == "service_logs_follow_up")
        self.assertIn("desatualizados", logs_follow_up.message)
        self.assertEqual(logs_follow_up.action_tool_name, "read_journal")

    def test_collect_session_insights_requests_refresh_when_service_signal_is_stale(self) -> None:
        freshness = build_observation_freshness(
            (
                {
                    "source": "service_status",
                    "key": "service",
                    "value": {"service": "nginx.service", "scope": "system"},
                    "observed_at": "2026-03-17T20:00:00Z",
                    "expires_at": "2026-03-17T20:03:00Z",
                },
            )
        )

        insights = collect_session_insights_with_freshness(
            "service: nginx.service: active=failed, sub=failed",
            freshness,
        )

        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "service_state_refresh")
        self.assertEqual(insights[0].action_tool_name, "service_status")
        self.assertEqual(
            insights[0].action_arguments,
            {"name": "nginx.service", "scope": "system"},
        )

    def test_chat_appends_proactive_suggestions_when_summary_is_risky(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            app = MasterControlApp(settings, provider_override=StaticPlanProvider())
            app.registry.register(HighDiskUsageTool())

            payload = app.chat("verifique o disco", new_session=True)
            insights = app.get_session_insights(payload["session_id"])
            recommendations = app.list_session_recommendations(payload["session_id"])

            self.assertIn("Recomendações da sessão:", payload["message"])
            self.assertEqual(len(insights["insights"]), 1)
            self.assertEqual(insights["insights"][0]["key"], "disk_pressure")
            self.assertEqual(len(recommendations["recommendations"]), 1)
            self.assertEqual(recommendations["recommendations"][0]["status"], "open")
            messages = app.store.list_conversation_messages(payload["session_id"], limit=10)
            self.assertEqual(len(messages), 2)

    def test_recommendation_status_can_be_accepted_and_auto_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            app = MasterControlApp(settings, provider_override=StaticPlanProvider())
            app.registry.register(HighDiskUsageTool())

            first_payload = app.chat("verifique o disco", new_session=True)
            session_id = first_payload["session_id"]
            recommendation_id = first_payload["recommendations"]["active"][0]["id"]

            updated = app.update_recommendation_status(recommendation_id, "accepted")
            self.assertEqual(updated["status"], "accepted")

            app.registry.register(SafeDiskUsageTool())
            second_payload = app.chat("verifique o disco novamente", session_id=session_id)

            self.assertEqual(len(second_payload["recommendations"]["active"]), 0)
            all_recommendations = app.list_session_recommendations(session_id)
            self.assertEqual(all_recommendations["recommendations"][0]["status"], "resolved")

    def test_recommendation_action_requires_accepted_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            app = MasterControlApp(settings, provider_override=StaticServicePlanProvider())
            app.registry.register(FailedServiceStatusTool())
            app.registry.register(SuccessfulRestartServiceTool())

            payload = app.chat("verifique o nginx", new_session=True)
            recommendation_id = payload["recommendations"]["active"][0]["id"]

            with self.assertRaisesRegex(ValueError, "accepted"):
                app.run_recommendation_action(recommendation_id, confirmed=True)

    def test_accepted_recommendation_action_requires_confirmation_and_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            app = MasterControlApp(settings, provider_override=StaticServicePlanProvider())
            app.registry.register(FailedServiceStatusTool())
            app.registry.register(SuccessfulRestartServiceTool())

            payload = app.chat("verifique o nginx", new_session=True)
            recommendation = payload["recommendations"]["active"][0]
            self.assertEqual(recommendation["action"]["tool_name"], "restart_service")

            app.update_recommendation_status(recommendation["id"], "accepted")

            pending = app.run_recommendation_action(recommendation["id"])
            self.assertFalse(pending["execution"]["ok"])
            self.assertTrue(pending["execution"]["pending_confirmation"])

            confirmed = app.run_recommendation_action(
                recommendation["id"],
                confirmed=True,
            )
            self.assertTrue(confirmed["execution"]["ok"])
            self.assertEqual(
                confirmed["execution"]["result"]["post_restart"]["activestate"],
                "active",
            )

    def test_chat_recommendation_prefers_refresh_action_when_service_signal_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            app = MasterControlApp(settings, provider_override=StaticNoPlanProvider())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.upsert_session_summary(
                session_id,
                "service: nginx.service: active=failed, sub=failed",
            )
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {"service": "nginx.service", "scope": "system"},
                observed_at="2026-03-17T20:00:00Z",
                ttl_seconds=180,
            )

            payload = app.chat("o que devo fazer agora?", session_id=session_id)

            self.assertIn("Recomendações da sessão:", payload["message"])
            recommendation = payload["recommendations"]["active"][0]
            self.assertEqual(recommendation["source_key"], "service_state_refresh")
            self.assertEqual(recommendation["action"]["tool_name"], "service_status")

    def test_chat_recommendation_without_service_evidence_has_no_restart_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            app = MasterControlApp(settings, provider_override=StaticNoPlanProvider())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.upsert_session_summary(
                session_id,
                "service: nginx.service: active=failed, sub=failed",
            )

            payload = app.chat("o que devo fazer agora?", session_id=session_id)

            self.assertIn("Recomendações da sessão:", payload["message"])
            recommendation = payload["recommendations"]["active"][0]
            self.assertEqual(recommendation["source_key"], "service_state")
            self.assertIsNone(recommendation["action"])

    def test_chat_recommendation_with_fresh_system_service_evidence_proposes_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            app = MasterControlApp(settings, provider_override=StaticNoPlanProvider())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.upsert_session_summary(
                session_id,
                "service: nginx.service: active=failed, sub=failed",
            )
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {"service": "nginx.service", "scope": "system"},
                observed_at="2100-03-18T01:00:00Z",
                ttl_seconds=180,
            )

            payload = app.chat("o que devo fazer agora?", session_id=session_id)

            self.assertIn("Recomendações da sessão:", payload["message"])
            recommendation = payload["recommendations"]["active"][0]
            self.assertEqual(recommendation["source_key"], "service_state")
            self.assertEqual(recommendation["action"]["tool_name"], "restart_service")
            self.assertEqual(
                recommendation["action"]["arguments"],
                {"name": "nginx.service", "scope": "system"},
            )

    def test_chat_recommendation_with_fresh_user_service_evidence_proposes_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            app = MasterControlApp(settings, provider_override=StaticNoPlanProvider())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    [
                        "tracked_unit: ollama-local.service",
                        "tracked_scope: user",
                        "service: ollama-local.service: active=failed, sub=failed",
                    ]
                ),
            )
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {"service": "ollama-local.service", "scope": "user"},
                observed_at="2100-03-18T01:00:00Z",
                ttl_seconds=180,
            )

            payload = app.chat("o que devo fazer agora?", session_id=session_id)

            self.assertIn("Recomendações da sessão:", payload["message"])
            recommendation = payload["recommendations"]["active"][0]
            self.assertEqual(recommendation["source_key"], "service_state")
            self.assertEqual(recommendation["action"]["tool_name"], "restart_service")
            self.assertEqual(
                recommendation["action"]["arguments"],
                {"name": "ollama-local.service", "scope": "user"},
            )


if __name__ == "__main__":
    unittest.main()
