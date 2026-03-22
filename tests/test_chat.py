from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from master_control.agent.planner import PlanningDecision
from master_control.app import MasterControlApp
from master_control.config import Settings
from master_control.providers.base import ProviderResponse
from master_control.tools.base import RiskLevel, Tool, ToolSpec


class FailedServicesListTool(Tool):
    spec = ToolSpec(
        name="failed_services",
        description="Fake failed-service listing tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("scope", "limit"),
    )

    def invoke(self, arguments):
        return {
            "status": "ok",
            "scope": arguments.get("scope", "system"),
            "limit": arguments.get("limit", 10),
            "unit_count": 1,
            "units": [
                {
                    "unit": "nginx.service",
                    "load_state": "loaded",
                    "active_state": "failed",
                    "sub_state": "failed",
                    "description": "Nginx service",
                }
            ],
        }


class FakeServiceStatusTool(Tool):
    spec = ToolSpec(
        name="service_status",
        description="Fake service status tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("name", "scope"),
    )

    def invoke(self, arguments):
        return {
            "status": "ok",
            "service": arguments.get("name", "nginx"),
            "scope": arguments.get("scope", "system"),
            "activestate": "failed",
            "substate": "failed",
            "unitfilestate": "enabled",
        }


class FakeJournalTool(Tool):
    spec = ToolSpec(
        name="read_journal",
        description="Fake journal reader for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("unit", "lines"),
    )

    def invoke(self, arguments):
        return {
            "status": "ok",
            "unit": arguments.get("unit"),
            "returned_lines": arguments.get("lines", 20),
            "entries": [
                {
                    "timestamp": "2026-03-19T20:00:00Z",
                    "message": "fake journal entry",
                }
            ],
        }


class ImprovedServiceStatusTool(Tool):
    spec = ToolSpec(
        name="service_status",
        description="Fake improved service status tool for comparative tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("name", "scope"),
    )

    def invoke(self, arguments):
        return {
            "status": "ok",
            "service": arguments.get("name", "nginx.service"),
            "scope": arguments.get("scope", "system"),
            "activestate": "active",
            "substate": "running",
            "unitfilestate": "enabled",
        }


class ImprovedJournalTool(Tool):
    spec = ToolSpec(
        name="read_journal",
        description="Fake improved journal reader for comparative tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("unit", "lines"),
    )

    def invoke(self, arguments):
        return {
            "status": "ok",
            "unit": arguments.get("unit"),
            "returned_lines": arguments.get("lines", 20),
            "entries": [
                {
                    "timestamp": "2026-03-19T20:05:00Z",
                    "message": "configuration reloaded successfully",
                },
                {
                    "timestamp": "2026-03-19T20:05:01Z",
                    "message": "accepting connections",
                },
            ],
        }


class FakeDiskUsageTool(Tool):
    spec = ToolSpec(
        name="disk_usage",
        description="Fake disk usage tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("path",),
    )

    def invoke(self, arguments):
        return {
            "path": arguments.get("path", "/"),
            "used_percent": 71.0,
            "total_bytes": 100,
            "used_bytes": 71,
            "free_bytes": 29,
        }


class FakeTopProcessesTool(Tool):
    spec = ToolSpec(
        name="top_processes",
        description="Fake top processes tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("limit",),
    )

    def invoke(self, arguments):
        return {
            "status": "ok",
            "processes": [
                {"command": "nginx", "cpu_percent": 81.0},
                {"command": "python3", "cpu_percent": 44.0},
            ],
            "limit": arguments.get("limit", 5),
        }


class FakeReadConfigTool(Tool):
    spec = ToolSpec(
        name="read_config_file",
        description="Fake config reader for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("path",),
    )

    def invoke(self, arguments):
        return {
            "path": arguments.get("path", "/etc/app.ini"),
            "content": "[service]\nmode=demo\n",
        }


class ChangingReadConfigTool(Tool):
    spec = ToolSpec(
        name="read_config_file",
        description="Fake changing config reader for comparative tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("path",),
    )

    def invoke(self, arguments):
        return {
            "path": arguments.get("path", "/etc/app.ini"),
            "content": "[service]\nmode=new\nworkers=4\nenabled=true\n",
            "target": "managed_ini",
            "line_count": 4,
        }


class FakeProcessToUnitTool(Tool):
    spec = ToolSpec(
        name="process_to_unit",
        description="Fake process correlation tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("name", "pid", "limit"),
    )

    def invoke(self, arguments):
        name = arguments.get("name", "nginx")
        return {
            "status": "ok",
            "query": {"name": name, "limit": arguments.get("limit", 3)},
            "matched_process_count": 1,
            "resolved_count": 1,
            "primary_match": {
                "pid": 321,
                "command": name,
                "unit": "nginx.service",
                "scope": "system",
            },
            "units": [
                {
                    "unit": "nginx.service",
                    "scope": "system",
                    "pid_count": 1,
                    "pids": [321],
                    "commands": [name],
                }
            ],
        }


class StaticNoPlanProvider:
    name = "static"

    def diagnostics(self) -> dict[str, object]:
        return {"name": self.name, "ready": True}

    def plan(self, request) -> ProviderResponse:
        del request
        return ProviderResponse(
            message="Ainda não vou executar nada sem atualizar o contexto.",
            plan=None,
            decision=PlanningDecision(
                state="complete",
                kind="evidence_sufficient",
                reason="No additional tool step requested for this turn.",
            ),
        )


class ChatFlowTest(unittest.TestCase):
    def test_chat_routes_memory_request_through_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.chat("mostre o uso de memoria")

            self.assertEqual(payload["provider"], "heuristic")
            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "memory_usage")
            self.assertEqual(payload["plan_decision"]["state"], "needs_tools")
            self.assertEqual(payload["plan_decision"]["kind"], "inspection_request")
            self.assertEqual(payload["turn_decision"]["state"], "complete")
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("Memória usada:", payload["message"])

    def test_chat_records_plan_generation_in_audit_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            app.chat("o host esta lento")
            events = app.list_audit_events(limit=10)
            event_types = {event["event_type"] for event in events}

            self.assertIn("plan_generated", event_types)
            self.assertIn("chat_completed", event_types)
            self.assertIn("tool_execution", event_types)

    def test_chat_returns_guidance_when_provider_cannot_map_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.chat("escreva um poema sobre o kernel")

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["plan_decision"]["state"], "blocked")
            self.assertEqual(payload["turn_decision"]["kind"], "unsupported_request")
            self.assertIn("Ainda não consegui mapear", payload["message"])

    def test_chat_extracts_unit_name_for_journal_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.chat("me mostre os logs do ssh 5 linhas")

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "read_journal")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["unit"], "ssh")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["lines"], 5)

    def test_chat_reports_provider_error_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="openai",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.chat("mostre o uso de memoria")

            self.assertEqual(payload["provider"], "openai")
            self.assertIsNone(payload["plan"])
            self.assertIn("OPENAI_API_KEY", payload["message"])

    def test_chat_surfaces_confirmation_commands_for_restart_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.chat("reinicie o servico nginx", new_session=True)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "restart_service")
            self.assertFalse(payload["executions"][0]["ok"])
            self.assertTrue(payload["executions"][0]["pending_confirmation"])
            self.assertEqual(payload["turn_decision"]["state"], "blocked")
            self.assertEqual(payload["turn_decision"]["kind"], "awaiting_confirmation")
            self.assertIn("Ação pendente de confirmação explícita.", payload["message"])
            self.assertIn("Confirme a execução de `restart_service` no serviço `nginx`.", payload["message"])
            self.assertIn("mc tool restart_service", payload["message"])
            self.assertIn("/tool restart_service", payload["message"])

    def test_chat_maps_reload_requests_to_reload_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.chat("recarregue o servico nginx", new_session=True)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "reload_service")
            self.assertFalse(payload["executions"][0]["ok"])
            self.assertTrue(payload["executions"][0]["pending_confirmation"])

    def test_chat_maps_informal_service_health_query_to_service_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FakeServiceStatusTool())

            payload = app.chat("o nginx caiu?", new_session=True)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "service_status")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["name"], "nginx")
            self.assertEqual(payload["executions"][0]["tool"], "service_status")
            self.assertIn("nginx", payload["message"])

    def test_chat_can_plan_user_scoped_service_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.chat("restart user service ollama-local", new_session=True)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "restart_service")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["name"], "ollama-local")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["scope"], "user")

    def test_heuristic_provider_reuses_session_history_for_log_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            first_app = MasterControlApp(settings)
            first_payload = first_app.chat("me mostre os logs do ssh 5 linhas", new_session=True)

            second_app = MasterControlApp(settings)
            follow_up_payload = second_app.chat(
                "agora 2 linhas", session_id=first_payload["session_id"]
            )

            self.assertEqual(follow_up_payload["plan"]["steps"][0]["tool_name"], "read_journal")
            self.assertEqual(follow_up_payload["plan"]["steps"][0]["arguments"]["unit"], "ssh")
            self.assertEqual(follow_up_payload["plan"]["steps"][0]["arguments"]["lines"], 2)

    def test_chat_preserves_user_scope_for_service_restart_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            first_app = MasterControlApp(settings)
            first_payload = first_app.chat("restart user service ollama-local", new_session=True)

            second_app = MasterControlApp(settings)
            follow_up_payload = second_app.chat(
                "reinicie novamente", session_id=first_payload["session_id"]
            )

            self.assertEqual(follow_up_payload["plan"]["steps"][0]["tool_name"], "restart_service")
            self.assertEqual(follow_up_payload["plan"]["steps"][0]["arguments"]["name"], "ollama-local")
            self.assertEqual(follow_up_payload["plan"]["steps"][0]["arguments"]["scope"], "user")

    def test_chat_reuses_service_context_for_short_reload_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {
                    "service": "ollama-local.service",
                    "scope": "user",
                    "activestate": "active",
                    "substate": "running",
                },
                ttl_seconds=180,
            )

            payload = app.chat("recarrega ele", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "reload_service")
            self.assertEqual(
                payload["plan"]["steps"][0]["arguments"],
                {"name": "ollama-local.service", "scope": "user"},
            )
            self.assertTrue(payload["executions"][0]["pending_confirmation"])

    def test_chat_reuses_service_context_for_short_restart_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {
                    "service": "nginx.service",
                    "scope": "system",
                    "activestate": "failed",
                    "substate": "failed",
                },
                ttl_seconds=180,
            )

            payload = app.chat("reinicia esse cara", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "restart_service")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["name"], "nginx.service")
            self.assertTrue(payload["executions"][0]["pending_confirmation"])

    def test_chat_reports_missing_safe_tool_when_runtime_lacks_memory_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry._tools.pop("memory_usage")

            payload = app.chat("mostre o uso de memoria")

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["plan_decision"]["state"], "blocked")
            self.assertEqual(payload["plan_decision"]["kind"], "missing_safe_tool")
            self.assertEqual(payload["turn_decision"]["kind"], "missing_safe_tool")
            self.assertIn("memory_usage", payload["message"])
            self.assertIn("mc tools", payload["message"])

    def test_heuristic_provider_ignores_assistant_log_output_when_reusing_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.append_conversation_message(
                session_id,
                "user",
                "me mostre os logs do ssh 5 linhas",
            )
            app.store.append_conversation_message(
                session_id,
                "assistant",
                "Entradas recentes do journal:\n- -- No entries --",
            )
            app.store.upsert_session_summary(session_id, "tracked_unit: ssh")

            payload = app.chat("agora 2 linhas", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "read_journal")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["unit"], "ssh")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["lines"], 2)

    def test_chat_command_reconcile_returns_payload_for_current_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            payload = app.chat("mostre o uso de memoria", new_session=True)

            rendered = app.handle_message("/reconcile")
            parsed = json.loads(rendered)

            self.assertEqual(parsed["mode"], "single")
            self.assertEqual(parsed["sessions"][0]["session_id"], payload["session_id"])

    def test_heuristic_provider_reuses_log_observation_context_without_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_journal",
                "logs",
                {"unit": "ssh", "returned_lines": 5},
                ttl_seconds=90,
            )

            payload = app.chat("agora 2 linhas", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "read_journal")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["unit"], "ssh")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["lines"], 2)

    def test_chat_reads_logs_from_contextual_pronoun_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FakeJournalTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {
                    "service": "nginx.service",
                    "scope": "system",
                    "activestate": "failed",
                    "substate": "failed",
                },
                ttl_seconds=180,
            )

            payload = app.chat("me mostra o que aconteceu com ele", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "read_journal")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["unit"], "nginx.service")
            self.assertEqual(payload["executions"][0]["tool"], "read_journal")

    def test_chat_investigates_explicit_service_failure_cause_with_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FakeJournalTool())

            payload = app.chat("por que o nginx caiu?", new_session=True)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "read_journal")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["unit"], "nginx")
            self.assertEqual(payload["executions"][0]["tool"], "read_journal")

    def test_chat_investigates_contextual_service_failure_cause_with_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FakeJournalTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {
                    "service": "nginx.service",
                    "scope": "system",
                    "activestate": "failed",
                    "substate": "failed",
                },
                ttl_seconds=180,
            )

            payload = app.chat("por que esse serviço caiu?", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "read_journal")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["unit"], "nginx.service")
            self.assertEqual(payload["executions"][0]["tool"], "read_journal")

    def test_chat_compares_service_status_with_previous_read_after_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(ImprovedServiceStatusTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {
                    "service": "nginx.service",
                    "scope": "system",
                    "activestate": "failed",
                    "substate": "failed",
                },
                ttl_seconds=180,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: nginx.service",
                        "tracked_scope: system",
                        "last_intent: inspect_service_status",
                    )
                ),
            )

            payload = app.chat("esta melhor agora?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual([item["tool"] for item in payload["executions"]], ["service_status"])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("Melhorou no servico `nginx.service`", payload["message"])
            self.assertIn("antes active=failed, sub=failed", payload["message"])
            self.assertIn("agora active=active, sub=running", payload["message"])

    def test_chat_compares_service_status_with_melhorada_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(ImprovedServiceStatusTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {
                    "service": "nginx.service",
                    "scope": "system",
                    "activestate": "failed",
                    "substate": "failed",
                },
                ttl_seconds=180,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: nginx.service",
                        "tracked_scope: system",
                        "last_intent: inspect_service_status",
                    )
                ),
            )

            payload = app.chat("deu uma melhorada?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual([item["tool"] for item in payload["executions"]], ["service_status"])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("Melhorou no servico `nginx.service`", payload["message"])

    def test_chat_summarizes_recent_logs_focus_request_without_new_tool_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_journal",
                "logs",
                {
                    "unit": "nginx.service",
                    "returned_lines": 3,
                    "entries": [
                        "2026-03-19T20:00:00Z nginx[321]: worker process exited unexpectedly",
                        "2026-03-19T20:00:01Z nginx[321]: connect() failed (111: Connection refused)",
                    ],
                },
                ttl_seconds=90,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: nginx.service",
                        "last_intent: inspect_logs",
                    )
                ),
            )

            payload = app.chat("qual foi a causa principal?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["executions"], [])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("Sinal principal nos logs de `nginx.service`", payload["message"])
            self.assertIn("Connection refused", payload["message"])

    def test_chat_compresses_restart_loop_logs_without_new_tool_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_journal",
                "logs",
                {
                    "unit": "nginx.service",
                    "returned_lines": 3,
                    "entries": [
                        "2026-03-20T00:00:00Z systemd[1]: nginx.service: Scheduled restart job, restart counter is at 5.",
                        "2026-03-20T00:00:01Z systemd[1]: nginx.service: Start request repeated too quickly.",
                        "2026-03-20T00:00:02Z systemd[1]: nginx.service: Failed with result 'exit-code'.",
                    ],
                },
                ttl_seconds=90,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: nginx.service",
                        "last_intent: inspect_logs",
                    )
                ),
            )

            payload = app.chat("qual foi a causa principal?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["executions"], [])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("padrao de restart loop", payload["message"])
            self.assertIn("Start request repeated too quickly", payload["message"])

    def test_chat_compresses_timeout_and_permission_patterns_from_recent_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_journal",
                "logs",
                {
                    "unit": "api.service",
                    "returned_lines": 3,
                    "entries": [
                        "2026-03-20T00:10:00Z api[221]: upstream request timed out after 30s",
                        "2026-03-20T00:10:01Z api[221]: background sync timed out after 30s",
                        "2026-03-20T00:10:02Z api[221]: open /var/lib/api/token: Permission denied",
                    ],
                },
                ttl_seconds=90,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: api.service",
                        "last_intent: inspect_logs",
                    )
                ),
            )

            payload = app.chat("resume so o importante", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["executions"], [])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("padrao de timeout (2 entradas)", payload["message"])
            self.assertIn("padrao de falha de permissao", payload["message"])

    def test_chat_compresses_dependency_and_environment_patterns_from_recent_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_journal",
                "logs",
                {
                    "unit": "api.service",
                    "returned_lines": 4,
                    "entries": [
                        "2026-03-20T00:10:00Z systemd[1]: Dependency failed for api.service.",
                        "2026-03-20T00:10:01Z systemd[1]: api.service: Failed with result 'dependency'.",
                        "2026-03-20T00:10:02Z systemd[1]: api.service: Failed to load environment files: No such file or directory",
                    ],
                },
                ttl_seconds=90,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: api.service",
                        "last_intent: inspect_logs",
                    )
                ),
            )

            payload = app.chat("resume so o importante", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["executions"], [])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("padrao de falha de dependencia (2 entradas)", payload["message"])
            self.assertIn("padrao de falha de ambiente", payload["message"])

    def test_chat_compresses_crash_loop_signals_from_recent_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_journal",
                "logs",
                {
                    "unit": "worker.service",
                    "returned_lines": 4,
                    "entries": [
                        "2026-03-20T00:00:00Z systemd[1]: worker.service: Main process exited, code=exited, status=1/FAILURE",
                        "2026-03-20T00:00:01Z systemd[1]: worker.service: Failed with result 'exit-code'.",
                        "2026-03-20T00:00:02Z systemd[1]: worker.service: Scheduled restart job, restart counter is at 4.",
                    ],
                },
                ttl_seconds=90,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: worker.service",
                        "last_intent: inspect_logs",
                    )
                ),
            )

            payload = app.chat("qual foi a causa principal?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["executions"], [])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("padrao de restart loop (3 entradas)", payload["message"])

    def test_chat_refreshes_stale_logs_for_focus_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FakeJournalTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_journal",
                "logs",
                {
                    "unit": "nginx.service",
                    "returned_lines": 2,
                    "entries": [
                        "2020-01-01T00:00:00Z nginx[1]: old failure",
                    ],
                },
                observed_at="2020-01-01T00:00:00Z",
                ttl_seconds=1,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: nginx.service",
                        "last_intent: inspect_logs",
                    )
                ),
            )

            payload = app.chat("qual foi a causa principal?", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "read_journal")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["unit"], "nginx.service")
            self.assertEqual(payload["executions"][0]["tool"], "read_journal")

    def test_chat_compares_logs_with_previous_read_after_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(ImprovedJournalTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_journal",
                "logs",
                {
                    "unit": "nginx.service",
                    "returned_lines": 2,
                    "entries": [
                        "2026-03-19T20:00:00Z nginx[321]: connect() failed (111: Connection refused)",
                        "2026-03-19T20:00:01Z nginx[321]: worker process exited unexpectedly",
                    ],
                },
                ttl_seconds=90,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: nginx.service",
                        "last_intent: inspect_logs",
                    )
                ),
            )

            payload = app.chat("o que mudou desde a última leitura?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual([item["tool"] for item in payload["executions"]], ["read_journal"])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("nginx.service", payload["message"])
            self.assertIn("antes", payload["message"])
            self.assertIn("agora", payload["message"])

    def test_chat_compares_logs_with_continua_igual_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(ImprovedJournalTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_journal",
                "logs",
                {
                    "unit": "nginx.service",
                    "returned_lines": 2,
                    "entries": [
                        "2026-03-19T20:00:00Z nginx[321]: connect() failed (111: Connection refused)",
                        "2026-03-19T20:00:01Z nginx[321]: worker process exited unexpectedly",
                    ],
                },
                ttl_seconds=90,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: nginx.service",
                        "last_intent: inspect_logs",
                    )
                ),
            )

            payload = app.chat("continua a mesma coisa?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual([item["tool"] for item in payload["executions"]], ["read_journal"])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("Melhorou nos logs de `nginx.service`", payload["message"])

    def test_chat_compares_logs_with_recovery_signal_after_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(ImprovedJournalTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_journal",
                "logs",
                {
                    "unit": "nginx.service",
                    "returned_lines": 2,
                    "entries": [
                        "2026-03-19T20:00:00Z nginx[321]: upstream request timed out after 30s",
                        "2026-03-19T20:00:01Z nginx[321]: worker shutdown timed out",
                    ],
                },
                ttl_seconds=90,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: nginx.service",
                        "last_intent: inspect_logs",
                    )
                ),
            )

            payload = app.chat("isso melhorou?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual([item["tool"] for item in payload["executions"]], ["read_journal"])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("Melhorou nos logs de `nginx.service`", payload["message"])
            self.assertIn("padrao de timeout", payload["message"])
            self.assertIn("sinal de recuperacao", payload["message"])

    def test_chat_compares_environment_failure_logs_with_recovery_after_refresh(self) -> None:
        class RecoveredEnvironmentJournalTool(Tool):
            spec = ToolSpec(
                name="read_journal",
                description="Fake recovered journal reader for environment-failure comparison tests.",
                risk=RiskLevel.READ_ONLY,
                arguments=("unit", "lines"),
            )

            def invoke(self, arguments):
                return {
                    "status": "ok",
                    "unit": arguments.get("unit"),
                    "returned_lines": arguments.get("lines", 20),
                    "entries": [
                        {
                            "timestamp": "2026-03-19T20:05:00Z",
                            "message": "environment loaded successfully",
                        },
                        {
                            "timestamp": "2026-03-19T20:05:01Z",
                            "message": "accepting connections",
                        },
                    ],
                }

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(RecoveredEnvironmentJournalTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_journal",
                "logs",
                {
                    "unit": "api.service",
                    "returned_lines": 2,
                    "entries": [
                        "2026-03-19T20:00:00Z systemd[1]: api.service: Failed to load environment files: No such file or directory",
                        "2026-03-19T20:00:01Z systemd[1]: api.service: Failed at step EXEC spawning /opt/api/bin/server: No such file or directory",
                    ],
                },
                ttl_seconds=90,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_unit: api.service",
                        "last_intent: inspect_logs",
                    )
                ),
            )

            payload = app.chat("isso melhorou?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual([item["tool"] for item in payload["executions"]], ["read_journal"])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("Melhorou nos logs de `api.service`", payload["message"])
            self.assertIn("padrao de falha de ambiente", payload["message"])
            self.assertIn("sinal de recuperacao", payload["message"])

    def test_chat_summarizes_recent_config_comparison_with_equal_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "content": "[service]\nmode=old\nworkers=2\n",
                    "target": "managed_ini",
                },
                ttl_seconds=300,
            )
            app.store.record_observation(
                session_id,
                "read_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "content": "[service]\nmode=old\nworkers=2\n",
                    "target": "managed_ini",
                },
                ttl_seconds=300,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_path: /etc/app.ini",
                        "last_intent: read_config_file",
                    )
                ),
            )

            payload = app.chat("continua igual nesse arquivo?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["executions"], [])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("Nao houve mudanca relevante em `/etc/app.ini`", payload["message"])

    def test_chat_maps_informal_disk_query_to_disk_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FakeDiskUsageTool())

            payload = app.chat("quanto espaco livre ainda tem no hd?", new_session=True)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "disk_usage")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["path"], "/")
            self.assertEqual(payload["executions"][0]["tool"], "disk_usage")

    def test_chat_maps_informal_process_query_to_top_processes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FakeTopProcessesTool())

            payload = app.chat("ve o que ta comendo cpu ai", new_session=True)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "top_processes")
            self.assertEqual(payload["executions"][0]["tool"], "top_processes")
            self.assertIn("nginx", payload["message"])

    def test_chat_reads_config_from_contextual_file_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FakeReadConfigTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.upsert_session_summary(session_id, "tracked_path: /etc/app.ini")

            payload = app.chat("abre esse arquivo pra mim", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "read_config_file")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["path"], "/etc/app.ini")
            self.assertEqual(payload["executions"][0]["tool"], "read_config_file")

    def test_chat_reads_config_from_contextual_ini_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FakeReadConfigTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.upsert_session_summary(session_id, "tracked_path: /etc/app.ini")

            payload = app.chat("confere esse ini", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "read_config_file")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["path"], "/etc/app.ini")
            self.assertEqual(payload["executions"][0]["tool"], "read_config_file")

    def test_chat_summarizes_recent_config_focus_request_without_new_tool_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "content": "# comment\n[service]\nmode=demo\nworkers=2\n",
                    "target": "managed_ini",
                },
                ttl_seconds=300,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_path: /etc/app.ini",
                        "last_intent: read_config_file",
                    )
                ),
            )

            payload = app.chat("mostra só o importante", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["executions"], [])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("Trechos mais relevantes de `/etc/app.ini`", payload["message"])
            self.assertIn("mode=demo", payload["message"])

    def test_chat_refreshes_stale_config_for_focus_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FakeReadConfigTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "content": "[service]\nmode=old\n",
                    "target": "managed_ini",
                },
                observed_at="2020-01-01T00:00:00Z",
                ttl_seconds=1,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_path: /etc/app.ini",
                        "last_intent: read_config_file",
                    )
                ),
            )

            payload = app.chat("mostra só o importante", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "read_config_file")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["path"], "/etc/app.ini")
            self.assertEqual(payload["executions"][0]["tool"], "read_config_file")

    def test_chat_summarizes_recent_config_comparison_without_new_tool_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "content": "[service]\nmode=old\nworkers=2\n",
                    "target": "managed_ini",
                },
                ttl_seconds=300,
            )
            app.store.record_observation(
                session_id,
                "read_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "content": "[service]\nmode=new\nworkers=4\n",
                    "target": "managed_ini",
                },
                ttl_seconds=300,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_path: /etc/app.ini",
                        "last_intent: read_config_file",
                    )
                ),
            )

            payload = app.chat("o que mudou nesse arquivo?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["executions"], [])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("Mudanças mais relevantes em `/etc/app.ini`", payload["message"])
            self.assertIn("mode=old -> mode=new", payload["message"])
            self.assertIn("workers=2 -> workers=4", payload["message"])

    def test_chat_summarizes_config_comparison_with_added_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "content": "[service]\nmode=old\nworkers=2\n",
                    "target": "managed_ini",
                },
                ttl_seconds=300,
            )
            app.store.record_observation(
                session_id,
                "read_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "content": (
                        "[service]\nmode=old\nworkers=2\n\n"
                        "[logging]\nlevel=debug\nformat=json\n"
                    ),
                    "target": "managed_ini",
                },
                ttl_seconds=300,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_path: /etc/app.ini",
                        "last_intent: read_config_file",
                    )
                ),
            )

            payload = app.chat("o que mudou nesse arquivo?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["executions"], [])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("[logging] adicionada", payload["message"])
            self.assertIn("level=debug", payload["message"])
            self.assertIn("format=json", payload["message"])

    def test_chat_summarizes_large_config_comparison_by_section_with_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "content": (
                        "[service]\nmode=old\nworkers=2\nport=8080\n\n"
                        "[logging]\nlevel=info\nformat=text\n\n"
                        "[limits]\nmax_clients=100\nburst=20\ntimeout=30\n"
                    ),
                    "target": "managed_ini",
                },
                ttl_seconds=300,
            )
            app.store.record_observation(
                session_id,
                "read_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "content": (
                        "[service]\nmode=new\nworkers=4\nport=9090\n\n"
                        "[logging]\nlevel=debug\nformat=json\n\n"
                        "[limits]\nmax_clients=150\nburst=30\ntimeout=45\n"
                    ),
                    "target": "managed_ini",
                },
                ttl_seconds=300,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_path: /etc/app.ini",
                        "last_intent: read_config_file",
                    )
                ),
            )

            payload = app.chat("o que mudou nesse arquivo?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual(payload["executions"], [])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("[service]: mode=old -> mode=new, workers=2 -> workers=4", payload["message"])
            self.assertIn(
                "[logging]: level=info -> level=debug, format=text -> format=json",
                payload["message"],
            )
            self.assertIn(
                "[limits]: max_clients=100 -> max_clients=150, burst=20 -> burst=30",
                payload["message"],
            )
            self.assertIn("+2 mudanças adicionais", payload["message"])

    def test_chat_compares_config_after_refresh_even_with_write_between_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(ChangingReadConfigTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "read_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "content": "[service]\nmode=old\nworkers=2\n",
                    "target": "managed_ini",
                },
                ttl_seconds=300,
            )
            app.store.record_observation(
                session_id,
                "write_config_file",
                "config",
                {
                    "path": "/etc/app.ini",
                    "target": "managed_ini",
                    "backup_path": "/tmp/app.bak",
                },
                ttl_seconds=300,
            )
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    (
                        "tracked_path: /etc/app.ini",
                        "last_intent: read_config_file",
                    )
                ),
            )

            payload = app.chat("o que mudou nesse arquivo?", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertEqual([item["tool"] for item in payload["executions"]], ["read_config_file"])
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("Mudanças mais relevantes em `/etc/app.ini`", payload["message"])
            self.assertIn("mode=old -> mode=new", payload["message"])
            self.assertIn("workers=2 -> workers=4", payload["message"])

    def test_chat_correlates_process_from_contextual_process_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FakeProcessToUnitTool())
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "top_processes",
                "processes",
                {
                    "processes": [
                        {"command": "nginx", "cpu_percent": 88.0},
                    ]
                },
                ttl_seconds=180,
            )

            payload = app.chat("esse processo pertence a qual serviço?", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "process_to_unit")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["name"], "nginx")
            self.assertEqual(payload["executions"][0]["tool"], "process_to_unit")
            self.assertIn("nginx.service", payload["message"])

    def test_heuristic_provider_prefers_structured_service_context_over_old_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.append_conversation_message(
                session_id,
                "user",
                "reinicie o servico ssh",
            )
            app.store.append_conversation_message(
                session_id,
                "assistant",
                "Posso reiniciar o serviço `ssh` com confirmação explícita.",
            )
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {
                    "service": "ollama-local.service",
                    "scope": "user",
                    "activestate": "failed",
                    "substate": "failed",
                },
                ttl_seconds=180,
            )

            payload = app.chat("reinicie novamente", session_id=session_id)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "restart_service")
            self.assertEqual(
                payload["plan"]["steps"][0]["arguments"],
                {"name": "ollama-local.service", "scope": "user"},
            )

    def test_chat_maps_failed_service_queries_to_failed_services_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FailedServicesListTool())

            payload = app.chat("quais servicos com falha eu tenho?", new_session=True)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "failed_services")
            self.assertEqual(payload["executions"][0]["tool"], "failed_services")
            self.assertIn("nginx.service", payload["message"])
            self.assertEqual(
                payload["recommendations"]["active"][0]["action"]["tool_name"],
                "service_status",
            )

    def test_chat_maps_informal_failed_service_queries_to_failed_services_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(FailedServicesListTool())

            payload = app.chat("tem algum servico quebrado por ai?", new_session=True)

            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "failed_services")
            self.assertEqual(payload["executions"][0]["tool"], "failed_services")
            self.assertIn("nginx.service", payload["message"])

    def test_chat_plans_config_rollback_from_recent_managed_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            managed_root = state_dir / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "service.ini"
            config_path.write_text("[service]\nmode=old\n", encoding="utf-8")

            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()

            written = app.run_tool(
                "write_config_file",
                {"path": str(config_path), "content": "[service]\nmode=new\n"},
                confirmed=True,
                audit_context={"source": "test", "session_id": session_id},
            )

            payload = app.chat("desfaça a última mudança", session_id=session_id)

            self.assertTrue(written["ok"])
            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "restore_config_backup")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["path"], str(config_path))
            self.assertEqual(
                payload["plan"]["steps"][0]["arguments"]["backup_path"],
                written["result"]["backup_path"],
            )
            self.assertTrue(payload["executions"][0]["pending_confirmation"])

    def test_chat_plans_config_rollback_from_short_follow_up_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            managed_root = state_dir / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "service.ini"
            config_path.write_text("[service]\nmode=old\n", encoding="utf-8")

            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()

            written = app.run_tool(
                "write_config_file",
                {"path": str(config_path), "content": "[service]\nmode=new\n"},
                confirmed=True,
                audit_context={"source": "test", "session_id": session_id},
            )

            payload = app.chat("reverte isso", session_id=session_id)

            self.assertTrue(written["ok"])
            self.assertEqual(payload["plan"]["steps"][0]["tool_name"], "restore_config_backup")
            self.assertEqual(payload["plan"]["steps"][0]["arguments"]["path"], str(config_path))
            self.assertEqual(
                payload["plan"]["steps"][0]["arguments"]["backup_path"],
                written["result"]["backup_path"],
            )
            self.assertTrue(payload["executions"][0]["pending_confirmation"])

    def test_reconcile_recommendations_exposes_config_verification_after_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            managed_root = state_dir / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "service.ini"
            config_path.write_text("[service]\nmode=old\n", encoding="utf-8")

            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings, provider_override=StaticNoPlanProvider())
            app.bootstrap()
            session_id = app.store.create_session()

            written = app.run_tool(
                "write_config_file",
                {"path": str(config_path), "content": "[service]\nmode=new\n"},
                confirmed=True,
                audit_context={"source": "test", "session_id": session_id},
            )
            sync = app.reconcile_recommendations(session_id=session_id)

            self.assertTrue(written["ok"])
            active = sync["sessions"][0]["recommendations"]["active"]
            verification = next(
                item
                for item in active
                if item.get("source_key") == "config_verification_available"
            )
            self.assertEqual(verification["action"]["tool_name"], "read_config_file")
            self.assertEqual(
                verification["action"]["arguments"],
                {"path": str(config_path)},
            )


if __name__ == "__main__":
    unittest.main()
