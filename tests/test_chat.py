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
