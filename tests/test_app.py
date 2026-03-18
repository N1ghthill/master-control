from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from master_control.app import MasterControlApp
from master_control.config import Settings


class MasterControlAppTest(unittest.TestCase):
    def test_doctor_bootstraps_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.doctor()

            self.assertTrue((state_dir / "mc.sqlite3").exists())
            self.assertIn("system_info", payload["tools"])
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["planner_mode"], "heuristic")

    def test_doctor_reports_unavailable_explicit_ollama_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="ollama",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
                ollama_model="qwen2.5:7b",
            )
            app = MasterControlApp(settings)

            with patch(
                "master_control.app.collect_provider_checks",
                return_value={
                    "ollama": {
                        "name": "ollama",
                        "available": False,
                        "summary": "endpoint unavailable: connection refused",
                    },
                    "openai": {
                        "name": "openai",
                        "available": False,
                        "summary": "OPENAI_API_KEY is not set",
                    },
                    "heuristic": {
                        "name": "heuristic",
                        "available": True,
                        "summary": "offline structured planner available",
                    },
                    "noop": {
                        "name": "noop",
                        "available": True,
                        "summary": "static disabled provider available",
                    },
                },
            ):
                payload = app.doctor()

            self.assertFalse(payload["ok"])
            self.assertEqual(payload["provider_backend"], "ollama")
            self.assertEqual(payload["planner_mode"], "llm")
            self.assertFalse(payload["llm_provider_available"])
            self.assertIn("connection refused", payload["active_provider_check"]["summary"])

    def test_run_tool_records_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.run_tool("system_info")
            events = app.list_audit_events()

            self.assertTrue(payload["ok"])
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_type"], "tool_execution")
            self.assertEqual(events[0]["payload"]["tool"], "system_info")

    def test_run_tool_records_session_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()

            payload = app.run_tool(
                "memory_usage",
                audit_context={"source": "tool_command", "session_id": session_id},
            )
            observations = app.list_session_observations(session_id=session_id)

            self.assertTrue(payload["ok"])
            self.assertEqual(observations["total_count"], 1)
            self.assertEqual(observations["observations"][0]["key"], "memory")

    def test_plan_generated_audit_includes_stale_refresh_keys(self) -> None:
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
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    [
                        "memory: memory 42.0% used, swap 0.0% used",
                        "processes: nginx(5.0%), sshd(1.0%)",
                        "service: nginx: active=active, sub=running",
                    ]
                ),
            )
            old_time = "2026-03-17T00:00:00Z"
            app.store.record_observation(
                session_id,
                "memory_usage",
                "memory",
                {"memory_used_percent": 42.0, "swap_used_percent": 0.0},
                observed_at=old_time,
                ttl_seconds=300,
            )
            app.store.record_observation(
                session_id,
                "top_processes",
                "processes",
                {"processes": [{"command": "nginx", "cpu_percent": 5.0}]},
                observed_at=old_time,
                ttl_seconds=120,
            )
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {"service": "nginx", "scope": "system", "activestate": "active", "substate": "running"},
                observed_at=old_time,
                ttl_seconds=180,
            )

            app.chat("o host esta lento", session_id=session_id)
            events = app.list_audit_events(limit=20)
            plan_events = [event for event in events if event["event_type"] == "plan_generated"]

            self.assertTrue(
                any(
                    "memory" in event["payload"].get("stale_observation_keys", [])
                    and "memory" in event["payload"].get("planned_refresh_keys", [])
                    for event in plan_events
                )
            )

    def test_registry_contains_core_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            tools = {spec.name for spec in app.list_tools()}

            self.assertEqual(
                tools,
                {
                    "disk_usage",
                    "memory_usage",
                    "read_journal",
                    "read_config_file",
                    "reload_service",
                    "restore_config_backup",
                    "restart_service",
                    "service_status",
                    "system_info",
                    "top_processes",
                    "write_config_file",
                },
            )

    def test_invalid_tool_arguments_are_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.run_tool("service_status")
            events = app.list_audit_events()

            self.assertFalse(payload["ok"])
            self.assertIn("Missing required argument: name", payload["error"])
            self.assertEqual(len(events), 1)
            self.assertFalse(events[0]["payload"]["ok"])


if __name__ == "__main__":
    unittest.main()
