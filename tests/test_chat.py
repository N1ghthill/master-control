from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from master_control.app import MasterControlApp
from master_control.config import Settings


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
            follow_up_payload = second_app.chat("agora 2 linhas", session_id=first_payload["session_id"])

            self.assertEqual(follow_up_payload["plan"]["steps"][0]["tool_name"], "read_journal")
            self.assertEqual(follow_up_payload["plan"]["steps"][0]["arguments"]["unit"], "ssh")
            self.assertEqual(follow_up_payload["plan"]["steps"][0]["arguments"]["lines"], 2)

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


if __name__ == "__main__":
    unittest.main()
