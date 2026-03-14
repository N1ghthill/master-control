#!/usr/bin/env python3
"""Tests for installer script rendering in output-dir mode."""

from __future__ import annotations

import os
import pwd
import subprocess
import tempfile
import unittest
from pathlib import Path


class InstallScriptsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.operator = pwd.getpwuid(os.getuid()).pw_name

    def test_security_watch_installer_renders_prune_config_in_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            subprocess.run(
                [
                    "bash",
                    "scripts/install-security-watch-timer.sh",
                    "--output-dir",
                    str(output_dir),
                    "--operator-id",
                    self.operator,
                    "--window-hours",
                    "12",
                    "--dedupe-minutes",
                    "45",
                    "--prune",
                    "--system-event-retention-days",
                    "21",
                    "--alert-retention-days",
                    "45",
                    "--incident-retention-days",
                    "120",
                    "--activity-retention-days",
                    "180",
                    "--silence-retention-days",
                    "60",
                ],
                check=True,
                cwd=self.repo_root,
            )

            service = (output_dir / "mastercontrol-security-watch.service").read_text(encoding="utf-8")
            timer = (output_dir / "mastercontrol-security-watch.timer").read_text(encoding="utf-8")

            self.assertIn("ExecStart=", service)
            self.assertIn("--window-hours 12", service)
            self.assertIn("--dedupe-minutes 45", service)
            self.assertIn("--prune", service)
            self.assertIn("--system-event-retention-days 21", service)
            self.assertIn("--alert-retention-days 45", service)
            self.assertIn("--incident-retention-days 120", service)
            self.assertIn("--activity-retention-days 180", service)
            self.assertIn("--silence-retention-days 60", service)
            self.assertIn("OnUnitActiveSec=120", timer)

    def test_privilege_broker_installer_renders_units_in_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            subprocess.run(
                [
                    "bash",
                    "scripts/install-privilege-broker.sh",
                    "--output-dir",
                    str(output_dir),
                    "--operator-id",
                    self.operator,
                    "--socket-group",
                    self.operator,
                    "--socket-path",
                    "/run/mastercontrol/test-broker.sock",
                ],
                check=True,
                cwd=self.repo_root,
            )

            service = (output_dir / "mastercontrol-privilege-broker.service").read_text(encoding="utf-8")
            socket_unit = (output_dir / "mastercontrol-privilege-broker.socket").read_text(encoding="utf-8")

            self.assertIn("ExecStart=", service)
            self.assertIn("--socket /run/mastercontrol/test-broker.sock", service)
            self.assertIn("--approval-db /var/lib/mastercontrol/privilege-broker.db", service)
            self.assertIn("ListenStream=/run/mastercontrol/test-broker.sock", socket_unit)
            self.assertIn(f"SocketGroup={self.operator}", socket_unit)


if __name__ == "__main__":
    unittest.main()
