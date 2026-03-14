#!/usr/bin/env python3
"""Tests for structured planning and execution flow in MasterControlD."""

from __future__ import annotations

import datetime as dt
import sqlite3
import subprocess
import sys
import threading
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mastercontrol.context.contextd import CommandResult
from mastercontrol.core.mastercontrold import MasterControlD, OperatorRequest
from mastercontrol.privilege import PrivilegeBrokerServer, broker_socket_available
from mastercontrol.security import SecurityWatchEngine


class MasterControlDFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.daemon = MasterControlD(
            db_path=Path(self.tmpdir.name) / "mastercontrol.db",
            context_command_runner=self._context_runner,
            broker_socket_path=Path(self.tmpdir.name) / "missing-broker.sock",
        )

    @staticmethod
    def _context_runner(command: list[str], timeout_s: int) -> CommandResult:
        del timeout_s
        if command[:4] == ["journalctl", "--no-pager", "-o", "json"]:
            return CommandResult(returncode=0, stdout="")
        if command == ["udevadm", "info", "--export-db"]:
            return CommandResult(
                returncode=0,
                stdout="P: /devices/pci/net/eth0\nE: SUBSYSTEM=net\nE: INTERFACE=eth0\n\n",
            )
        if command[:3] == ["busctl", "--json=short", "call"]:
            return CommandResult(
                returncode=0,
                stdout=(
                    '{"type":"a(sussussbto)","data":[[['
                    '"2",1000,"irving","seat0",3801,"user","tty2",false,0,'
                    '"/org/freedesktop/login1/session/_32"]]]}'
                ),
            )
        if command == ["ip", "route", "show", "default"]:
            return CommandResult(returncode=0, stdout="default via 192.168.1.1 dev eth0\n")
        if command == ["systemctl", "is-system-running"]:
            return CommandResult(returncode=0, stdout="running\n")
        if command == ["systemctl", "--failed", "--no-legend", "--plain"]:
            return CommandResult(returncode=0, stdout="")
        if command[:2] == ["journalctl", "-p"]:
            return CommandResult(returncode=0, stdout="")
        raise AssertionError(f"Unexpected context command: {command}")

    def test_build_plan_returns_structured_plan_and_context_for_network_request(self) -> None:
        plan_bundle = self.daemon._build_plan(
            intent="mostre a rota default",
            risk_level="low",
            path="fast",
            intent_cluster="network.route.default",
            operator_name="Irving",
        )

        self.assertEqual(plan_bundle["context_tier"], "hot")
        self.assertEqual(plan_bundle["action"]["action_id"], "network.diagnose.route_default")
        self.assertEqual(plan_bundle["action_plan"].risk_level, "low")
        self.assertEqual(plan_bundle["action_plan"].context_tier, "hot")
        self.assertEqual(plan_bundle["context"]["required_tier"], "hot")

    def test_handle_returns_direct_policy_for_network_diagnostic(self) -> None:
        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="mostre a rota default",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-network",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "network.diagnose.route_default")
        self.assertEqual(result["policy_decision"]["privilege_mode"], "none")
        self.assertIsNone(result["pexec_plan"])
        self.assertTrue((Path(self.tmpdir.name) / "mastercontrold.log").exists())

    def test_handle_returns_pexec_plan_for_service_restart(self) -> None:
        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="restart unbound.service",
                risk_level="medium",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-service",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "service.systemctl.restart")
        self.assertEqual(result["action_plan"]["risk_level"], "high")
        self.assertEqual(result["policy_decision"]["privilege_mode"], "pkexec_bootstrap")
        self.assertTrue(result["policy_decision"]["requires_step_up"])
        self.assertIsNotNone(result["pexec_plan"])
        self.assertEqual(result["pexec_plan"]["command"][0], "pkexec")

    def test_handle_returns_structured_adaptive_communication(self) -> None:
        operator_profile = {
            "operator_id": "irving",
            "active_hours": "09:00-18:59",
            "common_intents": ["service.restart"],
            "error_prone_commands": ["service.restart"],
            "path_preference": "deep_when_uncertain",
            "tone_sensitivity": 0.84,
            "updated_at": "2026-03-14T12:00:00+00:00",
        }
        tone_result = SimpleNamespace(
            tone="urgent",
            confidence=0.91,
            intent_cluster="service.restart",
            intent_confidence=0.58,
            intent_source="history",
            frustration_score=0.72,
        )

        with (
            patch.object(self.daemon.profiler, "get_profile", return_value=operator_profile),
            patch.object(self.daemon.tone, "analyze", return_value=tone_result),
        ):
            result = self.daemon.handle(
                OperatorRequest(
                    operator_name="Irving",
                    intent="restart unbound.service",
                    risk_level="medium",
                    incident=False,
                    requested_path="auto",
                    execute=False,
                    dry_run=False,
                    approve=False,
                    allow_high_risk=False,
                    request_id="req-adaptive-comm",
                    simulate_failure=False,
                )
            )

        self.assertEqual(result["communication"]["style"], "explicit")
        self.assertTrue(
            any(
                "Learned operator preference" in note
                for note in result["communication"]["adaptation_notes"]
            )
        )
        self.assertIn("How I'm adapting:", result["message"])
        self.assertIn("Recent history shows friction", result["message"])
        self.assertIn("Intent confidence is limited", result["message"])

    def test_execute_network_diagnostic_uses_direct_transport(self) -> None:
        with patch("mastercontrol.core.mastercontrold.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["/usr/bin/ip", "route", "show", "default"],
                returncode=0,
                stdout="default via 1.1.1.1 dev eth0\n",
                stderr="",
            )
            result = self.daemon.handle(
                OperatorRequest(
                    operator_name="Irving",
                    intent="mostre a rota default",
                    risk_level="low",
                    incident=False,
                    requested_path="auto",
                    execute=True,
                    dry_run=False,
                    approve=True,
                    allow_high_risk=True,
                    request_id="req-direct-exec",
                    simulate_failure=False,
                )
            )

        called_command = run_mock.call_args.args[0]
        self.assertEqual(called_command[0], "/usr/bin/ip")
        self.assertEqual(result["execution"]["transport"], "direct")
        self.assertTrue(result["execution"]["success"])

    def test_execute_service_dry_run_uses_pexec_transport(self) -> None:
        with patch("mastercontrol.core.mastercontrold.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["/usr/lib/mastercontrol/root-exec"],
                returncode=0,
                stdout='{"ok": true, "dry_run": true, "action_id": "service.systemctl.restart"}',
                stderr="",
            )
            result = self.daemon.handle(
                OperatorRequest(
                    operator_name="Irving",
                    intent="restart unbound.service",
                    risk_level="medium",
                    incident=False,
                    requested_path="auto",
                    execute=True,
                    dry_run=True,
                    approve=False,
                    allow_high_risk=False,
                    request_id="req-pexec-dry-run",
                    simulate_failure=False,
                )
            )

        called_command = run_mock.call_args.args[0]
        self.assertEqual(called_command[0], "/usr/lib/mastercontrol/root-exec")
        self.assertEqual(result["execution"]["transport"], "pkexec_bootstrap")
        self.assertTrue(result["execution"]["success"])

    def test_execute_service_uses_broker_when_socket_is_available(self) -> None:
        socket_path = Path(self.tmpdir.name) / "mc-broker.sock"
        actions_file = Path(self.tmpdir.name) / "actions.json"
        actions_file.write_text('{"version": 1, "actions": {}}', encoding="utf-8")
        calls: list[tuple[str, dict[str, str], str | None, bool]] = []

        def fake_executor(
            actions_path: Path,
            action_id: str,
            args: dict[str, str],
            request_id: str | None,
            dry_run: bool,
            audit_log: Path,
        ) -> tuple[dict[str, object], int]:
            calls.append((action_id, dict(args), request_id, dry_run))
            self.assertEqual(actions_path, actions_file)
            self.assertEqual(audit_log, Path(self.tmpdir.name) / "broker.log")
            return {
                "ok": True,
                "action_id": action_id,
                "request_id": request_id or "",
                "stdout": "broker-ok",
                "stderr": "",
            }, 0

        server = PrivilegeBrokerServer(
            socket_path=socket_path,
            actions_file=actions_file,
            audit_log=Path(self.tmpdir.name) / "broker.log",
            approval_db=Path(self.tmpdir.name) / "approvals.db",
            executor=fake_executor,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._wait_for_socket(socket_path)

        daemon = MasterControlD(
            db_path=Path(self.tmpdir.name) / "mastercontrol-broker.db",
            context_command_runner=self._context_runner,
            broker_socket_path=socket_path,
            broker_python_bin=sys.executable,
        )
        result = daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="restart unbound.service",
                risk_level="medium",
                incident=False,
                requested_path="auto",
                execute=True,
                dry_run=False,
                approve=True,
                allow_high_risk=True,
                request_id="req-broker-exec",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["policy_decision"]["privilege_mode"], "broker")
        self.assertEqual(result["pexec_plan"]["transport"], "broker")
        self.assertEqual(result["execution"]["transport"], "broker")
        self.assertTrue(result["execution"]["success"])
        self.assertEqual(result["execution"]["broker_approval"]["approval_scope"], "single_action")
        self.assertEqual(
            calls,
            [("service.systemctl.restart", {"unit": "unbound.service"}, "req-broker-exec", False)],
        )

    def test_successful_mutation_invalidates_related_context_snapshots(self) -> None:
        self.daemon._collect_context(
            operator_name="Irving",
            operator_profile={},
            required_tier="warm",
            intent_cluster="service.restart",
            path="fast",
            mapped_action=None,
            incident=False,
            request_id="seed-context",
        )
        self.assertIsNotNone(self.daemon.context_store.get("services.summary"))

        with patch("mastercontrol.core.mastercontrold.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["/usr/lib/mastercontrol/root-exec"],
                returncode=0,
                stdout='{"ok": true, "action_id": "service.systemctl.restart"}',
                stderr="",
            )
            result = self.daemon.handle(
                OperatorRequest(
                    operator_name="Irving",
                    intent="restart unbound.service",
                    risk_level="medium",
                    incident=False,
                    requested_path="auto",
                    execute=True,
                    dry_run=False,
                    approve=True,
                    allow_high_risk=True,
                    request_id="req-pexec-real",
                    simulate_failure=False,
                )
            )

        self.assertEqual(result["execution"]["invalidated_context_sources"], ["services.summary", "journal.alerts"])
        self.assertIsNone(self.daemon.context_store.get("services.summary"))

    def test_security_audit_runs_locally_without_execute_flag(self) -> None:
        conn = sqlite3.connect(self.daemon.profiler.db_path)
        try:
            conn.execute(
                """
                INSERT INTO system_events (
                    monitor_id, cursor, ts_utc, category, source, summary,
                    invalidated_sources_json, raw_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "journal.core",
                    None,
                    "2026-03-14T12:00:00+00:00",
                    "security",
                    "sshd",
                    "Failed password for root from 10.0.0.2",
                    "[]",
                    "{}",
                    "2026-03-14T12:00:00+00:00",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="faca uma auditoria de seguranca",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-audit",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "security.audit.recent_events")
        self.assertEqual(result["execution"]["transport"], "local")
        self.assertTrue(result["execution"]["executed"])
        self.assertIn("security=1", result["execution"]["outcome"])

    def test_security_vigilance_runs_locally_without_execute_flag(self) -> None:
        base = dt.datetime.now(tz=dt.timezone.utc)
        ts1 = (base - dt.timedelta(minutes=15)).isoformat()
        ts2 = (base - dt.timedelta(minutes=5)).isoformat()
        conn = sqlite3.connect(self.daemon.profiler.db_path)
        try:
            conn.executemany(
                """
                INSERT INTO system_events (
                    monitor_id, cursor, ts_utc, category, source, summary,
                    invalidated_sources_json, raw_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "journal.core",
                        None,
                        ts1,
                        "security",
                        "sshd",
                        "Failed password for root from 10.0.0.2",
                        "[]",
                        "{}",
                        ts1,
                    ),
                    (
                        "journal.core",
                        None,
                        ts2,
                        "security",
                        "dbus.login1",
                        "login1 sessions changed: added=5:root@pts/0/user",
                        "[]",
                        "{}",
                        ts2,
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="vigie o sistema contra intrusos",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-vigilance",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "security.vigilance.status")
        self.assertEqual(result["execution"]["transport"], "local")
        self.assertTrue(result["execution"]["executed"])
        self.assertIn("Security vigilance status: elevated.", result["execution"]["outcome"])

    def test_security_alert_list_runs_locally_without_execute_flag(self) -> None:
        self._seed_security_alert_rows()

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="mostre os alertas de seguranca",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-alert-list",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "security.alerts.list")
        self.assertEqual(result["execution"]["transport"], "local")
        self.assertTrue(result["execution"]["executed"])
        self.assertIn("Recent security alerts:", result["execution"]["outcome"])

    def test_security_alert_list_filters_by_fingerprint(self) -> None:
        self._seed_security_alert_rows()

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="mostre os alertas fingerprint service.failure.cluster",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-alert-list-filtered",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "security.alerts.list")
        self.assertIn("service.failure.cluster", result["execution"]["outcome"])
        self.assertNotIn("security.auth.anomaly", result["execution"]["outcome"])

    def test_security_alert_acknowledge_runs_locally_without_execute_flag(self) -> None:
        self._seed_security_alert_rows()

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="reconheca o alerta 1",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-alert-ack",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "security.alerts.ack")
        self.assertIn("Acknowledged 1 security alert", result["execution"]["outcome"])

    def test_security_alert_silence_runs_locally_without_execute_flag(self) -> None:
        self._seed_security_alert_rows()

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="silencie o alerta 1 por 24 horas",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-alert-silence",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "security.alerts.silence")
        self.assertIn("Silenced 1 security alert fingerprint", result["execution"]["outcome"])

    def test_security_alert_acknowledge_runs_with_fingerprint_scope(self) -> None:
        self._seed_security_alert_rows()

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="reconheca os alertas fingerprint service.failure.cluster",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-alert-ack-scope",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "security.alerts.ack")
        self.assertIn("service.failure.cluster", result["execution"]["outcome"])

    def test_security_incident_plan_runs_locally_without_execute_flag(self) -> None:
        self._seed_service_incident_rows()

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="responda ao incidente de servico",
                risk_level="medium",
                incident=True,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-incident-plan",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "security.incident.plan")
        self.assertEqual(result["execution"]["transport"], "local")
        self.assertTrue(result["execution"]["executed"])
        self.assertIn("Incident response posture:", result["execution"]["outcome"])

    def test_security_incident_list_runs_locally_without_execute_flag(self) -> None:
        self._seed_service_incident_rows()

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="liste os incidentes ativos",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-incident-list",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "security.incident.list")
        self.assertEqual(result["execution"]["transport"], "local")
        self.assertTrue(result["execution"]["executed"])
        self.assertIn("Incident ledger:", result["execution"]["outcome"])

    def test_security_incident_show_runs_locally_without_execute_flag(self) -> None:
        self._seed_service_incident_rows()
        incident_id = str(self.daemon.security_watch.list_incidents(status="active")[0]["incident_id"])

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent=f"mostre o incidente {incident_id}",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-incident-show",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "security.incident.show")
        self.assertEqual(result["execution"]["transport"], "local")
        self.assertTrue(result["execution"]["executed"])
        self.assertIn(f"Incident {incident_id}", result["execution"]["outcome"])
        self.assertIn("Activity=", result["execution"]["outcome"])

    def test_security_incident_resolve_runs_locally_without_execute_flag(self) -> None:
        self._seed_service_incident_rows()
        incident_id = str(self.daemon.security_watch.list_incidents(status="active")[0]["incident_id"])

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent=f"resolva o incidente {incident_id}",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-incident-resolve",
                simulate_failure=False,
            )
        )

        resolved = self.daemon.security_watch.get_incident(incident_id, sync=False)
        self.assertEqual(result["mapped_action"]["action_id"], "security.incident.resolve")
        self.assertEqual(result["execution"]["transport"], "local")
        self.assertTrue(result["execution"]["executed"])
        self.assertIn("marked as resolved", result["execution"]["outcome"])
        assert resolved is not None
        self.assertEqual(resolved["status"], "resolved")

    def test_security_incident_dismiss_runs_locally_without_execute_flag(self) -> None:
        self._seed_auth_incident_rows()
        incident_id = str(self.daemon.security_watch.list_incidents(status="active")[0]["incident_id"])

        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent=f"descarte o incidente {incident_id}",
                risk_level="low",
                incident=False,
                requested_path="auto",
                execute=False,
                dry_run=False,
                approve=False,
                allow_high_risk=False,
                request_id="req-security-incident-dismiss",
                simulate_failure=False,
            )
        )

        dismissed = self.daemon.security_watch.get_incident(incident_id, sync=False)
        self.assertEqual(result["mapped_action"]["action_id"], "security.incident.dismiss")
        self.assertEqual(result["execution"]["transport"], "local")
        self.assertTrue(result["execution"]["executed"])
        self.assertIn("marked as dismissed", result["execution"]["outcome"])
        assert dismissed is not None
        self.assertEqual(dismissed["status"], "dismissed")

    def test_security_incident_containment_blocks_without_matching_active_incident(self) -> None:
        result = self.daemon.handle(
            OperatorRequest(
                operator_name="Irving",
                intent="responda ao incidente reiniciando nginx.service",
                risk_level="medium",
                incident=True,
                requested_path="auto",
                execute=True,
                dry_run=True,
                approve=True,
                allow_high_risk=True,
                request_id="req-security-incident-blocked",
                simulate_failure=False,
            )
        )

        self.assertEqual(result["mapped_action"]["action_id"], "service.systemctl.restart")
        self.assertEqual(result["mapped_action"]["module_id"], "mod_security")
        self.assertTrue(result["execution"]["blocked"])
        self.assertEqual(result["execution"]["command_error"], "incident_validation_failed")

    def test_security_incident_containment_executes_when_active_incident_matches_unit(self) -> None:
        self._seed_service_incident_rows()

        with patch("mastercontrol.core.mastercontrold.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["/usr/lib/mastercontrol/root-exec"],
                returncode=0,
                stdout='{"ok": true, "dry_run": true, "action_id": "service.systemctl.restart"}',
                stderr="",
            )
            result = self.daemon.handle(
                OperatorRequest(
                    operator_name="Irving",
                    intent="responda ao incidente reiniciando nginx.service",
                    risk_level="medium",
                    incident=True,
                    requested_path="auto",
                    execute=True,
                    dry_run=True,
                    approve=True,
                    allow_high_risk=True,
                    request_id="req-security-incident-contain",
                    simulate_failure=False,
                )
            )

        self.assertEqual(result["mapped_action"]["action_id"], "service.systemctl.restart")
        self.assertEqual(result["mapped_action"]["module_id"], "mod_security")
        self.assertEqual(result["mapped_action"]["capability"], "security.incident.contain")
        self.assertEqual(result["execution"]["transport"], "pkexec_bootstrap")
        self.assertTrue(result["execution"]["success"])
        self.assertEqual(result["execution"]["incident_activity"]["status"], "containment_dry_run")

    def test_auth_incident_remediation_executes_when_active_auth_alert_exists(self) -> None:
        self._seed_auth_incident_rows()

        with patch("mastercontrol.core.mastercontrold.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["/usr/lib/mastercontrol/root-exec"],
                returncode=0,
                stdout='{"ok": true, "dry_run": true, "action_id": "service.systemctl.restart"}',
                stderr="",
            )
            result = self.daemon.handle(
                OperatorRequest(
                    operator_name="Irving",
                    intent="responda ao incidente reiniciando ssh.service",
                    risk_level="medium",
                    incident=True,
                    requested_path="auto",
                    execute=True,
                    dry_run=True,
                    approve=True,
                    allow_high_risk=True,
                    request_id="req-auth-incident-contain",
                    simulate_failure=False,
                )
            )

        self.assertEqual(result["mapped_action"]["module_id"], "mod_security")
        self.assertEqual(result["mapped_action"]["capability"], "security.incident.contain")
        self.assertEqual(result["mapped_action"]["args"]["category"], "security")
        self.assertTrue(result["execution"]["success"])

    def test_network_incident_remediation_executes_when_active_network_alert_exists(self) -> None:
        self._seed_network_incident_rows()

        with patch("mastercontrol.core.mastercontrold.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                args=["/usr/lib/mastercontrol/root-exec"],
                returncode=0,
                stdout='{"ok": true, "dry_run": true, "action_id": "service.systemctl.restart"}',
                stderr="",
            )
            result = self.daemon.handle(
                OperatorRequest(
                    operator_name="Irving",
                    intent="responda ao incidente reiniciando networkmanager",
                    risk_level="medium",
                    incident=True,
                    requested_path="auto",
                    execute=True,
                    dry_run=True,
                    approve=True,
                    allow_high_risk=True,
                    request_id="req-network-incident-contain",
                    simulate_failure=False,
                )
            )

        self.assertEqual(result["mapped_action"]["module_id"], "mod_security")
        self.assertEqual(result["mapped_action"]["capability"], "security.incident.contain")
        self.assertEqual(result["mapped_action"]["args"]["category"], "network")
        self.assertTrue(result["execution"]["success"])

    def _seed_security_alert_rows(self) -> None:
        engine = SecurityWatchEngine(db_path=self.daemon.profiler.db_path)
        base = dt.datetime.now(tz=dt.timezone.utc)
        conn = sqlite3.connect(self.daemon.profiler.db_path)
        try:
            conn.executemany(
                """
                INSERT INTO security_alerts (
                    ts_utc, severity, category, fingerprint, summary,
                    recommendation, source, status, event_ids_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        (base - dt.timedelta(minutes=10)).isoformat(),
                        "high",
                        "security",
                        "security.auth.anomaly",
                        "Authentication anomalies detected.",
                        "Investigate auth failures.",
                        "security-watch",
                        "new",
                        "[1,2]",
                        "{}",
                    ),
                    (
                        (base - dt.timedelta(minutes=5)).isoformat(),
                        "medium",
                        "service",
                        "service.failure.cluster",
                        "Service degradation detected.",
                        "Inspect failed units.",
                        "security-watch",
                        "new",
                        "[3]",
                        "{}",
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()
        del engine

    def _seed_service_incident_rows(self) -> None:
        base = dt.datetime.now(tz=dt.timezone.utc)
        event_ts = (base - dt.timedelta(minutes=12)).isoformat()
        alert_ts = (base - dt.timedelta(minutes=6)).isoformat()
        conn = sqlite3.connect(self.daemon.profiler.db_path)
        try:
            event_cursor = conn.execute(
                """
                INSERT INTO system_events (
                    monitor_id, cursor, ts_utc, category, source, summary,
                    invalidated_sources_json, raw_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "journal.core",
                    None,
                    event_ts,
                    "service",
                    "systemd",
                    "nginx.service entered failed state",
                    "[]",
                    "{}",
                    event_ts,
                ),
            )
            event_id = int(event_cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO security_alerts (
                    ts_utc, severity, category, fingerprint, summary,
                    recommendation, source, status, event_ids_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_ts,
                    "high",
                    "service",
                    "service.failure.cluster",
                    "Service degradation detected.",
                    "Inspect failed units.",
                    "security-watch",
                    "new",
                    f"[{event_id}]",
                    "{}",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _seed_auth_incident_rows(self) -> None:
        base = dt.datetime.now(tz=dt.timezone.utc)
        alert_ts = (base - dt.timedelta(minutes=6)).isoformat()
        conn = sqlite3.connect(self.daemon.profiler.db_path)
        try:
            conn.execute(
                """
                INSERT INTO security_alerts (
                    ts_utc, severity, category, fingerprint, summary,
                    recommendation, source, status, event_ids_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_ts,
                    "critical",
                    "security",
                    "security.auth.anomaly",
                    "Authentication anomalies detected.",
                    "Investigate auth failures.",
                    "security-watch",
                    "new",
                    "[]",
                    "{}",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _seed_network_incident_rows(self) -> None:
        base = dt.datetime.now(tz=dt.timezone.utc)
        event_ts = (base - dt.timedelta(minutes=12)).isoformat()
        alert_ts = (base - dt.timedelta(minutes=6)).isoformat()
        conn = sqlite3.connect(self.daemon.profiler.db_path)
        try:
            event_cursor = conn.execute(
                """
                INSERT INTO system_events (
                    monitor_id, cursor, ts_utc, category, source, summary,
                    invalidated_sources_json, raw_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "journal.core",
                    None,
                    event_ts,
                    "network",
                    "networkmanager",
                    "NetworkManager lost carrier on wlan0",
                    "[]",
                    "{}",
                    event_ts,
                ),
            )
            event_id = int(event_cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO security_alerts (
                    ts_utc, severity, category, fingerprint, summary,
                    recommendation, source, status, event_ids_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_ts,
                    "high",
                    "network",
                    "network.instability",
                    "Network instability pattern detected.",
                    "Check routes and DNS.",
                    "security-watch",
                    "new",
                    f"[{event_id}]",
                    "{}",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _wait_for_socket(path: Path, timeout_s: float = 2.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if broker_socket_available(path):
                return
            time.sleep(0.01)
        raise AssertionError(f"broker socket did not appear: {path}")


if __name__ == "__main__":
    unittest.main()
