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
            self.assertTrue(payload["store_diagnostics"]["ok"])
            self.assertEqual(payload["store_diagnostics"]["journal_mode"], "wal")
            self.assertIn("summary", payload["bootstrap_python_diagnostics"])
            self.assertIn("available", payload["reconcile_timer_diagnostics"])

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
                {
                    "service": "nginx",
                    "scope": "system",
                    "activestate": "active",
                    "substate": "running",
                },
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
                    and event["payload"].get("decision", {}).get("state") == "needs_tools"
                    for event in plan_events
                )
            )

    def test_list_session_recommendations_includes_signal_freshness(self) -> None:
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
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {"service": "nginx.service", "scope": "system"},
                observed_at="2026-03-17T20:00:00Z",
                ttl_seconds=180,
            )
            app.store.sync_session_recommendations(
                session_id,
                [
                    {
                        "dedupe_key": "service_state_refresh:nginx.service",
                        "source_key": "service_state_refresh",
                        "severity": "warning",
                        "message": "Atualize o status do serviço antes de agir.",
                        "action": {
                            "kind": "run_tool",
                            "tool_name": "service_status",
                            "title": "Atualizar o status do serviço `nginx.service`.",
                            "arguments": {"name": "nginx.service", "scope": "system"},
                        },
                    }
                ],
            )

            payload = app.list_session_recommendations(session_id=session_id)

            recommendation = payload["recommendations"][0]
            self.assertEqual(recommendation["confidence"], "stale")
            self.assertEqual(recommendation["signal_freshness"]["observation_key"], "service")

    def test_list_session_recommendations_prioritizes_fresh_items(self) -> None:
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
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {"service": "nginx.service", "scope": "system"},
                observed_at="2026-03-18T01:00:00Z",
                ttl_seconds=180,
            )
            app.store.record_observation(
                session_id,
                "memory_usage",
                "memory",
                {"memory_used_percent": 20.0, "swap_used_percent": 0.0},
                observed_at="2100-03-18T01:00:00Z",
                ttl_seconds=300,
            )
            app.store.sync_session_recommendations(
                session_id,
                [
                    {
                        "dedupe_key": "service_state_refresh:nginx.service",
                        "source_key": "service_state_refresh",
                        "severity": "critical",
                        "message": "Atualize o status do serviço antes de agir.",
                        "action": {
                            "kind": "run_tool",
                            "tool_name": "service_status",
                            "title": "Atualizar o status do serviço `nginx.service`.",
                            "arguments": {"name": "nginx.service", "scope": "system"},
                        },
                    },
                    {
                        "dedupe_key": "memory_pressure:memory",
                        "source_key": "memory_pressure",
                        "severity": "warning",
                        "message": "Há pressão de memória no host.",
                    },
                ],
            )

            payload = app.list_session_recommendations(session_id=session_id)

            self.assertEqual(payload["recommendations"][0]["source_key"], "memory_pressure")
            self.assertEqual(payload["recommendations"][0]["confidence"], "fresh")
            self.assertEqual(payload["recommendations"][1]["source_key"], "service_state_refresh")
            self.assertEqual(payload["recommendations"][1]["confidence"], "stale")

    def test_reconcile_recommendations_updates_session_state(self) -> None:
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
            app.store.sync_session_recommendations(
                session_id,
                [
                    {
                        "dedupe_key": "service_state:nginx.service",
                        "source_key": "service_state",
                        "severity": "critical",
                        "message": "O serviço está falhando.",
                        "action": {
                            "kind": "run_tool",
                            "tool_name": "restart_service",
                            "title": "Reiniciar o serviço `nginx.service`.",
                            "arguments": {"name": "nginx.service"},
                        },
                    }
                ],
            )

            payload = app.reconcile_recommendations(session_id=session_id)
            recommendations = app.list_session_recommendations(session_id=session_id)
            events = app.list_audit_events(limit=10)

            self.assertEqual(payload["mode"], "single")
            self.assertEqual(payload["sessions"][0]["session_id"], session_id)
            self.assertEqual(payload["sessions"][0]["new_count"], 1)
            self.assertEqual(payload["sessions"][0]["auto_resolved_count"], 1)
            self.assertEqual(
                recommendations["recommendations"][0]["source_key"],
                "service_state_refresh",
            )
            self.assertTrue(
                any(event["event_type"] == "recommendations_reconciled" for event in events)
            )

    def test_reconcile_recommendations_can_scan_all_sessions(self) -> None:
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
            first_session = app.store.create_session()
            second_session = app.store.create_session()
            app.store.upsert_session_summary(
                first_session, "memory: memory 95.0% used, swap 20.0% used"
            )
            app.store.upsert_session_summary(
                second_session, "service: nginx.service: active=failed, sub=failed"
            )

            payload = app.reconcile_recommendations(all_sessions=True)

            self.assertEqual(payload["mode"], "all")
            self.assertEqual(payload["session_count"], 2)

    def test_render_reconcile_timer_is_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            target_dir = state_dir / "units"
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.render_reconcile_timer(
                target_dir=str(target_dir),
                python_executable="/usr/bin/python3",
            )

            self.assertFalse(target_dir.exists())
            self.assertFalse(settings.db_path.exists())
            self.assertEqual(payload["scope"], "user")
            self.assertEqual(
                payload["service"]["path"], str(target_dir / "master-control-reconcile.service")
            )
            self.assertIn(
                "ExecStart=/usr/bin/python3 -m master_control reconcile --all",
                payload["service"]["content"],
            )
            self.assertIn("Environment=MC_PROVIDER=noop", payload["service"]["content"])
            self.assertIn("OnCalendar=hourly", payload["timer"]["content"])

    def test_install_and_remove_reconcile_timer_record_audit_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            target_dir = state_dir / "units"
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            install_payload = app.install_reconcile_timer(
                target_dir=str(target_dir),
                run_systemctl=False,
                python_executable="/usr/bin/python3",
            )

            service_path = target_dir / "master-control-reconcile.service"
            timer_path = target_dir / "master-control-reconcile.timer"
            self.assertTrue(service_path.exists())
            self.assertTrue(timer_path.exists())
            self.assertEqual(install_payload["service"]["path"], str(service_path))
            self.assertFalse(install_payload["run_systemctl"])

            remove_payload = app.remove_reconcile_timer(
                target_dir=str(target_dir),
                run_systemctl=False,
            )

            self.assertFalse(service_path.exists())
            self.assertFalse(timer_path.exists())
            self.assertEqual(
                sorted(remove_payload["removed_paths"]),
                sorted([str(service_path), str(timer_path)]),
            )

            events = app.list_audit_events(limit=10)
            event_types = [event["event_type"] for event in events]
            self.assertIn("reconcile_timer_installed", event_types)
            self.assertIn("reconcile_timer_removed", event_types)

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
                    "failed_services",
                    "memory_usage",
                    "process_to_unit",
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
