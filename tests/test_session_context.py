from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from master_control.agent.observations import build_observation_freshness
from master_control.agent.planner import ExecutionPlan, PlanStep
from master_control.agent.session_context import (
    ConfigContext,
    ServiceContext,
    SessionContext,
    TrackedEntities,
    build_session_context,
)
from master_control.app import MasterControlApp
from master_control.config import Settings
from master_control.providers.base import ProviderRequest, ProviderResponse, SynthesisRequest
from master_control.providers.heuristic import HeuristicProvider
from master_control.tools.base import RiskLevel, ToolSpec


class FakeOpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        self.calls: list[ProviderRequest] = []

    def diagnostics(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ready": True,
        }

    def plan(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append(request)
        response_id = f"resp_{len(self.calls)}"
        return ProviderResponse(
            message="Vou verificar a memória do sistema.",
            plan=ExecutionPlan(
                intent="inspect_memory",
                steps=(
                    PlanStep(
                        tool_name="memory_usage",
                        rationale="Check RAM usage.",
                    ),
                ),
            ),
            response_id=response_id,
        )


class FakeSynthesisOpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        self.plan_calls: list[ProviderRequest] = []
        self.synthesis_calls: list[SynthesisRequest] = []

    def diagnostics(self) -> dict[str, object]:
        return {"name": self.name, "ready": True}

    def plan(self, request: ProviderRequest) -> ProviderResponse:
        self.plan_calls.append(request)
        if len(self.plan_calls) == 1:
            return ProviderResponse(
                message="Vou verificar a memória do sistema.",
                plan=ExecutionPlan(
                    intent="inspect_memory",
                    steps=(
                        PlanStep(
                            tool_name="memory_usage",
                            rationale="Check RAM usage.",
                        ),
                    ),
                ),
                response_id="resp_plan_1",
            )
        return ProviderResponse(
            message="Já tenho dados suficientes para responder.",
            plan=None,
            response_id="resp_plan_2",
        )

    def synthesize(self, request: SynthesisRequest) -> ProviderResponse:
        self.synthesis_calls.append(request)
        return ProviderResponse(
            message="A memória está dentro do resumo final sintetizado pelo provider.",
            response_id="resp_syn_1",
            metadata={"model": "fake-openai", "purpose": "response_synthesis"},
        )


class SessionContextTest(unittest.TestCase):
    def test_build_session_context_prefers_structured_observations(self) -> None:
        freshness = build_observation_freshness(
            (
                {
                    "source": "service_status",
                    "key": "service",
                    "value": {
                        "service": "ollama-local.service",
                        "scope": "user",
                        "activestate": "failed",
                        "substate": "failed",
                    },
                    "observed_at": "2100-03-18T01:00:00Z",
                    "expires_at": "2100-03-18T01:03:00Z",
                },
                {
                    "source": "top_processes",
                    "key": "processes",
                    "value": {
                        "processes": [
                            {"command": "python3", "cpu_percent": 91.2},
                            {"command": "python3", "cpu_percent": 88.0},
                            {"command": "ollama", "cpu_percent": 14.0},
                        ]
                    },
                    "observed_at": "2100-03-18T01:00:30Z",
                    "expires_at": "2100-03-18T01:02:30Z",
                },
                {
                    "source": "disk_usage",
                    "key": "disk",
                    "value": {"path": "/", "used_percent": 87.0},
                    "observed_at": "2100-03-18T01:00:45Z",
                    "expires_at": "2100-03-18T01:10:45Z",
                },
                {
                    "source": "process_to_unit",
                    "key": "process_unit",
                    "value": {
                        "query": {"name": "python3", "limit": 3},
                        "primary_match": {
                            "pid": 123,
                            "command": "python3",
                            "unit": "ollama-local.service",
                            "scope": "user",
                        },
                    },
                    "observed_at": "2100-03-18T01:01:00Z",
                    "expires_at": "2100-03-18T01:03:00Z",
                },
            )
        )

        context = build_session_context(
            "\n".join(
                [
                    "tracked_path: /etc/mc.ini",
                    "last_intent: diagnose_performance",
                    "service: ollama-local.service: active=failed, sub=failed",
                ]
            ),
            freshness,
        )

        self.assertEqual(context.tracked.unit, "ollama-local.service")
        self.assertEqual(context.tracked.scope, "user")
        self.assertEqual(context.tracked.path, "/etc/mc.ini")
        self.assertEqual(context.last_intent, "diagnose_performance")
        self.assertIsNotNone(context.service)
        self.assertEqual(context.service.name, "ollama-local.service")
        self.assertEqual(context.service.scope, "user")
        self.assertEqual(context.service.active_state, "failed")
        self.assertIsNotNone(context.processes)
        self.assertEqual(context.processes.items[0].command, "python3")
        self.assertEqual(context.processes.items[0].occurrences, 2)
        self.assertEqual(context.disk.path, "/")
        self.assertEqual(context.disk.used_percent, 87.0)
        self.assertIsNotNone(context.process_unit)
        self.assertEqual(context.process_unit.unit, "ollama-local.service")
        self.assertEqual(context.process_unit.scope, "user")
        self.assertTrue(context.process_unit.attempted)
        self.assertFalse(context.process_unit.no_match)

    def test_build_session_context_preserves_process_correlation_no_match_state(self) -> None:
        freshness = build_observation_freshness(
            (
                {
                    "source": "process_to_unit",
                    "key": "process_unit",
                    "value": {
                        "query": {"name": "python3", "limit": 3},
                        "matched_process_count": 1,
                        "resolved_count": 0,
                        "primary_match": None,
                        "units": [],
                    },
                    "observed_at": "2100-03-18T01:01:00Z",
                    "expires_at": "2100-03-18T01:03:00Z",
                },
            )
        )

        context = build_session_context(None, freshness)

        self.assertIsNotNone(context.process_unit)
        self.assertEqual(context.process_unit.query_name, "python3")
        self.assertTrue(context.process_unit.attempted)
        self.assertTrue(context.process_unit.no_match)
        self.assertIsNone(context.process_unit.unit)

    def test_build_session_context_extracts_failed_services_and_config_backup(self) -> None:
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
                                "description": "Nginx service",
                            },
                            {
                                "unit": "postgresql.service",
                                "active_state": "failed",
                                "sub_state": "failed",
                            },
                        ],
                    },
                    "observed_at": "2100-03-18T01:01:00Z",
                    "expires_at": "2100-03-18T01:04:00Z",
                },
                {
                    "source": "restore_config_backup",
                    "key": "config",
                    "value": {
                        "path": "/etc/app.ini",
                        "target": "managed_ini",
                        "restored_from": "/tmp/old.bak",
                        "rollback_backup_path": "/tmp/rollback.bak",
                        "validation": {"kind": "ini_parse", "status": "ok"},
                    },
                    "observed_at": "2100-03-18T01:02:00Z",
                    "expires_at": "2100-03-18T01:07:00Z",
                },
            )
        )

        context = build_session_context(None, freshness)

        self.assertIsNotNone(context.failed_services)
        self.assertEqual(context.failed_services.scope, "system")
        self.assertEqual(context.failed_services.items[0].unit, "nginx.service")
        self.assertEqual(context.failed_services.items[1].unit, "postgresql.service")
        self.assertIsNotNone(context.config)
        self.assertEqual(context.config.source, "restore_config_backup")
        self.assertEqual(context.config.path, "/etc/app.ini")
        self.assertEqual(context.config.target, "managed_ini")
        self.assertEqual(context.config.validation_kind, "ini_parse")
        self.assertEqual(context.config.backup_path, "/tmp/rollback.bak")

    def test_build_session_context_extracts_config_source_from_summary(self) -> None:
        context = build_session_context(
            "\n".join(
                [
                    "tracked_path: /etc/app.ini",
                    "config: write_config_file: /etc/app.ini",
                    "config_target: managed_ini",
                    "config_validation: ini_parse",
                    "last_backup_path: /tmp/app.bak",
                ]
            )
        )

        self.assertIsNotNone(context.config)
        self.assertEqual(context.config.source, "write_config_file")
        self.assertEqual(context.config.path, "/etc/app.ini")
        self.assertEqual(context.config.target, "managed_ini")
        self.assertEqual(context.config.validation_kind, "ini_parse")
        self.assertEqual(context.config.backup_path, "/tmp/app.bak")

    def test_build_session_context_keeps_recent_observation_history(self) -> None:
        history = build_observation_freshness(
            (
                {
                    "source": "service_status",
                    "key": "service",
                    "value": {
                        "service": "nginx.service",
                        "scope": "system",
                        "activestate": "active",
                        "substate": "running",
                    },
                    "observed_at": "2100-03-18T01:03:00Z",
                    "expires_at": "2100-03-18T01:06:00Z",
                },
                {
                    "source": "service_status",
                    "key": "service",
                    "value": {
                        "service": "nginx.service",
                        "scope": "system",
                        "activestate": "failed",
                        "substate": "failed",
                    },
                    "observed_at": "2100-03-18T01:00:00Z",
                    "expires_at": "2100-03-18T01:03:00Z",
                },
            )
        )

        context = build_session_context(None, history[:1], history)

        self.assertIn("service", context.recent_observations)
        self.assertEqual(len(context.recent_observations["service"]), 2)
        self.assertEqual(
            context.recent_observations["service"][0].value["activestate"],
            "active",
        )
        self.assertEqual(
            context.recent_observations["service"][1].value["activestate"],
            "failed",
        )

    def test_previous_response_id_is_reused_when_session_is_resumed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="openai",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            first_provider = FakeOpenAIProvider()
            first_app = MasterControlApp(settings, provider_override=first_provider)

            first_payload = first_app.chat("mostre o uso de memoria", new_session=True)
            session_id = first_payload["session_id"]

            second_provider = FakeOpenAIProvider()
            second_app = MasterControlApp(settings, provider_override=second_provider)
            second_app.chat("e agora me mostre de novo", session_id=session_id)

            self.assertEqual(first_provider.calls[0].previous_response_id, None)
            self.assertEqual(second_provider.calls[0].previous_response_id, "resp_1")
            self.assertGreater(len(second_provider.calls[0].conversation_history), 0)
            self.assertIsNotNone(second_provider.calls[0].session_summary)
            self.assertIsNotNone(second_provider.calls[0].session_context)
            self.assertIsNotNone(second_provider.calls[0].session_context.memory)
            self.assertIsInstance(
                second_provider.calls[0].session_context.memory.memory_used_percent,
                float,
            )

    def test_list_sessions_returns_provider_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="openai",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            provider = FakeOpenAIProvider()
            app = MasterControlApp(settings, provider_override=provider)

            payload = app.chat("mostre o uso de memoria", new_session=True)
            sessions = app.list_sessions(limit=10)

            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["session_id"], payload["session_id"])
            self.assertEqual(sessions[0]["provider_backend"], "openai")
            self.assertEqual(sessions[0]["previous_response_id"], "resp_1")
            self.assertIsInstance(sessions[0]["summary_text"], str)

    def test_session_summary_survives_beyond_short_history_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            first_payload = app.chat("me mostre os logs do ssh 5 linhas", new_session=True)
            session_id = first_payload["session_id"]

            app.bootstrap()
            for index in range(10):
                app.store.append_conversation_message(session_id, "user", f"mensagem {index}")
                app.store.append_conversation_message(session_id, "assistant", f"resposta {index}")

            resumed_app = MasterControlApp(settings)
            follow_up = resumed_app.chat("agora 2 linhas", session_id=session_id)

            self.assertEqual(follow_up["plan"]["steps"][0]["arguments"]["unit"], "ssh")

    def test_synthesis_response_id_is_persisted_for_resumed_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="openai",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            provider = FakeSynthesisOpenAIProvider()
            app = MasterControlApp(settings, provider_override=provider)

            payload = app.chat("mostre o uso de memoria", new_session=True)
            sessions = app.list_sessions(limit=10)

            self.assertIn("resumo final sintetizado", payload["message"])
            self.assertEqual(len(provider.synthesis_calls), 1)
            self.assertEqual(provider.synthesis_calls[0].previous_response_id, "resp_plan_1")
            self.assertTrue(provider.synthesis_calls[0].rendered_results)
            self.assertEqual(sessions[0]["previous_response_id"], "resp_syn_1")

    def test_heuristic_provider_reuses_structured_service_context_without_summary(self) -> None:
        provider = HeuristicProvider()
        response = provider.plan(
            ProviderRequest(
                user_message="reinicie novamente",
                available_tools=(
                    ToolSpec(
                        name="restart_service",
                        description="Restart a systemd unit.",
                        risk=RiskLevel.PRIVILEGED,
                        arguments=("name", "scope"),
                    ),
                ),
                session_context=SessionContext(
                    tracked=TrackedEntities(unit="ollama-local.service", scope="user"),
                    service=ServiceContext(
                        name="ollama-local.service",
                        scope="user",
                        active_state="failed",
                        sub_state="failed",
                    ),
                ),
            )
        )

        self.assertIsNotNone(response.plan)
        self.assertEqual(response.plan.steps[0].tool_name, "restart_service")
        self.assertEqual(
            response.plan.steps[0].arguments,
            {"name": "ollama-local.service", "scope": "user"},
        )

    def test_heuristic_provider_plans_config_rollback_from_structured_context(self) -> None:
        provider = HeuristicProvider()
        response = provider.plan(
            ProviderRequest(
                user_message="desfaça a última mudança",
                available_tools=(
                    ToolSpec(
                        name="restore_config_backup",
                        description="Restore a managed configuration backup.",
                        risk=RiskLevel.PRIVILEGED,
                        arguments=("path", "backup_path"),
                    ),
                ),
                session_context=SessionContext(
                    tracked=TrackedEntities(path="/etc/app.ini"),
                    config=ConfigContext(
                        source="write_config_file",
                        path="/etc/app.ini",
                        target="managed_ini",
                        validation_kind="ini_parse",
                        backup_path="/tmp/backup.bak",
                    ),
                ),
            )
        )

        self.assertIsNotNone(response.plan)
        self.assertEqual(response.plan.steps[0].tool_name, "restore_config_backup")
        self.assertEqual(
            response.plan.steps[0].arguments,
            {"path": "/etc/app.ini", "backup_path": "/tmp/backup.bak"},
        )

    def test_heuristic_provider_blocks_contextual_config_read_without_path(self) -> None:
        provider = HeuristicProvider()
        response = provider.plan(
            ProviderRequest(
                user_message="abre esse arquivo pra mim",
                available_tools=(
                    ToolSpec(
                        name="read_config_file",
                        description="Read a managed configuration file.",
                        risk=RiskLevel.READ_ONLY,
                        arguments=("path",),
                    ),
                ),
            )
        )

        self.assertIsNone(response.plan)
        self.assertEqual(response.decision.state, "blocked")
        self.assertEqual(response.decision.kind, "unsupported_request")

    def test_heuristic_provider_blocks_contextual_process_lookup_without_target(self) -> None:
        provider = HeuristicProvider()
        response = provider.plan(
            ProviderRequest(
                user_message="esse processo pertence a qual serviço?",
                available_tools=(
                    ToolSpec(
                        name="process_to_unit",
                        description="Correlate a process with systemd.",
                        risk=RiskLevel.READ_ONLY,
                        arguments=("name", "pid", "limit"),
                    ),
                ),
            )
        )

        self.assertIsNone(response.plan)
        self.assertEqual(response.decision.state, "blocked")
        self.assertEqual(response.decision.kind, "unsupported_request")

    def test_heuristic_provider_blocks_service_failure_investigation_without_target(self) -> None:
        provider = HeuristicProvider()
        response = provider.plan(
            ProviderRequest(
                user_message="por que esse serviço caiu?",
                available_tools=(
                    ToolSpec(
                        name="read_journal",
                        description="Read recent journal entries.",
                        risk=RiskLevel.READ_ONLY,
                        arguments=("unit", "lines"),
                    ),
                ),
            )
        )

        self.assertIsNone(response.plan)
        self.assertEqual(response.decision.state, "blocked")
        self.assertEqual(response.decision.kind, "unsupported_request")

    def test_heuristic_provider_blocks_focus_request_without_recent_artifact_context(self) -> None:
        provider = HeuristicProvider()
        response = provider.plan(
            ProviderRequest(
                user_message="mostra só o importante",
                available_tools=(
                    ToolSpec(
                        name="read_journal",
                        description="Read recent journal entries.",
                        risk=RiskLevel.READ_ONLY,
                        arguments=("unit", "lines"),
                    ),
                    ToolSpec(
                        name="read_config_file",
                        description="Read a managed configuration file.",
                        risk=RiskLevel.READ_ONLY,
                        arguments=("path",),
                    ),
                ),
            )
        )

        self.assertIsNone(response.plan)
        self.assertEqual(response.decision.state, "blocked")
        self.assertEqual(response.decision.kind, "unsupported_request")


if __name__ == "__main__":
    unittest.main()
