#!/usr/bin/env python3
"""Tests for privileged execution planning."""

from __future__ import annotations

import unittest
from pathlib import Path

from mastercontrol.contracts import PExecRequest
from mastercontrol.privilege import BootstrapPkexecTransport, PExecPlanner, PrivilegeBrokerTransport


class PExecTests(unittest.TestCase):
    def test_bootstrap_transport_uses_pkexec_for_real_execution(self) -> None:
        transport = BootstrapPkexecTransport(
            exec_path=Path("/usr/lib/mastercontrol/root-exec"),
            actions_file=Path("/etc/mastercontrol/actions.json"),
        )
        command = transport.build_command(
            PExecRequest(
                action_id="service.systemctl.restart",
                args={"unit": "unbound.service"},
                request_id="req-1",
            )
        )

        self.assertEqual(command[0:2], ("pkexec", "/usr/lib/mastercontrol/root-exec"))
        self.assertIn("--request-id", command)

    def test_dry_run_skips_pkexec(self) -> None:
        planner = PExecPlanner(
            BootstrapPkexecTransport(
                exec_path=Path("/usr/lib/mastercontrol/root-exec"),
                actions_file=Path("/etc/mastercontrol/actions.json"),
            )
        )
        result = planner.plan(
            PExecRequest(
                action_id="network.diagnose.route_default",
                privilege_mode="pkexec_bootstrap",
                dry_run=True,
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.command[0], "/usr/lib/mastercontrol/root-exec")
        self.assertNotIn("pkexec", result.command)

    def test_none_privilege_mode_is_rejected(self) -> None:
        result = PExecPlanner().plan(
            PExecRequest(
                action_id="network.diagnose.route_default",
                privilege_mode="none",
            )
        )

        self.assertFalse(result.ok)
        self.assertIn("cannot be routed through pexec", result.stderr)

    def test_broker_transport_builds_client_command(self) -> None:
        planner = PExecPlanner(
            broker_transport=PrivilegeBrokerTransport(
                socket_path=Path("/tmp/mc-broker.sock"),
                python_bin="/usr/bin/python3",
            )
        )
        result = planner.plan(
            PExecRequest(
                action_id="service.systemctl.restart",
                args={"unit": "unbound.service"},
                privilege_mode="broker",
                request_id="req-broker-1",
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.transport, "broker")
        self.assertEqual(result.command[0:3], ("/usr/bin/python3", "-m", "mastercontrol.privilege.broker"))
        self.assertIn("--socket", result.command)
        self.assertIn("/tmp/mc-broker.sock", result.command)


if __name__ == "__main__":
    unittest.main()
