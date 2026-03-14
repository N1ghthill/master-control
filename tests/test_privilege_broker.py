#!/usr/bin/env python3
"""Tests for the local Unix-socket privilege broker."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from mastercontrol.privilege import PrivilegeBrokerClient, PrivilegeBrokerServer, broker_socket_available


class PrivilegeBrokerTests(unittest.TestCase):
    def test_client_and_server_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            socket_path = root / "mc-broker.sock"
            actions_file = root / "actions.json"
            actions_file.write_text(json.dumps({"version": 1, "actions": {}}), encoding="utf-8")
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
                self.assertEqual(audit_log, root / "audit.log")
                return {
                    "ok": True,
                    "action_id": action_id,
                    "request_id": request_id or "",
                    "stdout": "broker-ok",
                    "dry_run": dry_run,
                }, 0

            server = PrivilegeBrokerServer(
                socket_path=socket_path,
                actions_file=actions_file,
                audit_log=root / "audit.log",
                approval_db=root / "approvals.db",
                executor=fake_executor,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self._wait_for_socket(socket_path)

            client = PrivilegeBrokerClient(socket_path=socket_path)
            approval, approval_rc = client.issue_approval(
                action_id="service.systemctl.restart",
                args={"unit": "unbound.service"},
                request_id="req-broker-roundtrip",
                operator_id="irving",
                session_id="session-1",
                approval_scope="single_action",
                risk_level="high",
                ttl_s=120,
            )
            payload, returncode = client.exec_action(
                action_id="service.systemctl.restart",
                args={"unit": "unbound.service"},
                request_id="req-broker-roundtrip",
                approval_token=str(approval["approval_token"]),
                dry_run=False,
            )

            self.assertEqual(approval_rc, 0)
            self.assertTrue(approval["ok"])
            self.assertEqual(returncode, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["transport"], "broker")
            self.assertEqual(payload["approval_scope"], "single_action")
            self.assertEqual(
                calls,
                [("service.systemctl.restart", {"unit": "unbound.service"}, "req-broker-roundtrip", False)],
            )

    def test_exec_without_token_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            socket_path = root / "mc-broker.sock"
            actions_file = root / "actions.json"
            actions_file.write_text(json.dumps({"version": 1, "actions": {}}), encoding="utf-8")

            server = PrivilegeBrokerServer(
                socket_path=socket_path,
                actions_file=actions_file,
                audit_log=root / "audit.log",
                approval_db=root / "approvals.db",
                executor=lambda *args, **kwargs: ({"ok": True}, 0),  # pragma: no cover
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self._wait_for_socket(socket_path)

            client = PrivilegeBrokerClient(socket_path=socket_path)
            payload, returncode = client.exec_action(
                action_id="service.systemctl.restart",
                args={"unit": "unbound.service"},
                request_id="req-broker-missing-token",
                dry_run=False,
            )

            self.assertNotEqual(returncode, 0)
            self.assertFalse(payload["ok"])
            self.assertIn("approval", str(payload["error"]).lower())

    def test_time_window_approval_survives_broker_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            socket_path = root / "mc-broker.sock"
            actions_file = root / "actions.json"
            actions_file.write_text(json.dumps({"version": 1, "actions": {}}), encoding="utf-8")
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
                self.assertEqual(audit_log, root / "audit.log")
                return {
                    "ok": True,
                    "action_id": action_id,
                    "request_id": request_id or "",
                    "stdout": "broker-ok",
                    "dry_run": dry_run,
                }, 0

            first = PrivilegeBrokerServer(
                socket_path=socket_path,
                actions_file=actions_file,
                audit_log=root / "audit.log",
                approval_db=root / "approvals.db",
                executor=fake_executor,
            )
            first_thread = threading.Thread(target=first.serve_once, kwargs={"timeout_s": 2.0}, daemon=True)
            first_thread.start()
            self._wait_for_socket(socket_path)

            client = PrivilegeBrokerClient(socket_path=socket_path)
            approval, approval_rc = client.issue_approval(
                action_id="service.systemctl.restart",
                args={"unit": "unbound.service"},
                request_id="req-broker-before-restart",
                operator_id="irving",
                session_id="session-1",
                approval_scope="time_window",
                risk_level="high",
                ttl_s=120,
            )
            first_thread.join(timeout=2.0)

            second = PrivilegeBrokerServer(
                socket_path=socket_path,
                actions_file=actions_file,
                audit_log=root / "audit.log",
                approval_db=root / "approvals.db",
                executor=fake_executor,
            )
            second_thread = threading.Thread(target=second.serve_once, kwargs={"timeout_s": 2.0}, daemon=True)
            second_thread.start()
            self._wait_for_socket(socket_path)

            payload, returncode = client.exec_action(
                action_id="service.systemctl.restart",
                args={"unit": "unbound.service"},
                request_id="req-broker-after-restart",
                approval_token=str(approval["approval_token"]),
                dry_run=False,
            )
            second_thread.join(timeout=2.0)

            self.assertEqual(approval_rc, 0)
            self.assertTrue(approval["ok"])
            self.assertEqual(approval["approval_scope"], "time_window")
            self.assertEqual(returncode, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["transport"], "broker")
            self.assertEqual(payload["approval_scope"], "time_window")
            self.assertEqual(
                calls,
                [("service.systemctl.restart", {"unit": "unbound.service"}, "req-broker-after-restart", False)],
            )

    def test_broker_socket_available_ignores_permission_errors(self) -> None:
        path = Path("/run/mastercontrol/privilege-broker.sock")

        with mock.patch.object(Path, "stat", side_effect=PermissionError("denied")):
            self.assertFalse(broker_socket_available(path))

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
