from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from master_control.config import Settings
from master_control.executor.command_runner import CommandResult
from master_control.systemd_timer import (
    RECONCILE_TIMER_NAME,
    collect_reconcile_timer_diagnostics,
    install_reconcile_timer,
    remove_reconcile_timer,
)


class StubRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    def run(self, args, *, cwd=None, timeout_s=5.0, env=None):
        self.calls.append(
            {
                "args": list(args),
                "cwd": cwd,
                "timeout_s": timeout_s,
                "env": dict(env) if isinstance(env, dict) else env,
            }
        )
        return self.results.pop(0)


class SystemdTimerTest(unittest.TestCase):
    def test_collect_timer_diagnostics_reports_missing_user_scope_env(self) -> None:
        with patch("master_control.systemd_timer._find_systemctl_path", return_value="/usr/bin/systemctl"):
            with patch.dict(os.environ, {}, clear=True):
                payload = collect_reconcile_timer_diagnostics()

        self.assertTrue(payload["available"])
        self.assertFalse(payload["user_scope_ready"])
        self.assertEqual(
            payload["user_scope_missing_env"],
            ["XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"],
        )

    def test_install_timer_runs_systemctl_through_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            runner = StubRunner(
                [
                    CommandResult(0, "", "", False, False),
                    CommandResult(0, "", "", False, False),
                ]
            )
            with patch("master_control.systemd_timer.ensure_systemctl_available", return_value=None):
                with patch.dict(
                    os.environ,
                    {
                        "XDG_RUNTIME_DIR": "/run/user/1000",
                        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                        "HOME": "/home/tester",
                    },
                    clear=False,
                ):
                    payload = install_reconcile_timer(
                        settings,
                        target_dir=state_dir / "units",
                        run_systemctl=True,
                        runner=runner,
                    )

        self.assertEqual(len(payload["systemctl_actions"]), 2)
        self.assertEqual(runner.calls[0]["args"], ["systemctl", "--user", "daemon-reload"])
        self.assertEqual(
            runner.calls[1]["args"],
            ["systemctl", "--user", "enable", "--now", RECONCILE_TIMER_NAME],
        )
        self.assertEqual(
            runner.calls[0]["env"]["DBUS_SESSION_BUS_ADDRESS"],
            "unix:path=/run/user/1000/bus",
        )

    def test_remove_timer_tolerates_disable_failure_when_check_is_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            units_dir = state_dir / "units"
            units_dir.mkdir(parents=True)
            (units_dir / "master-control-reconcile.service").write_text("service", encoding="utf-8")
            (units_dir / "master-control-reconcile.timer").write_text("timer", encoding="utf-8")
            runner = StubRunner(
                [
                    CommandResult(1, "", "not loaded", False, False),
                    CommandResult(0, "", "", False, False),
                ]
            )
            with patch("master_control.systemd_timer.ensure_systemctl_available", return_value=None):
                with patch.dict(
                    os.environ,
                    {
                        "XDG_RUNTIME_DIR": "/run/user/1000",
                        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                    },
                    clear=False,
                ):
                    payload = remove_reconcile_timer(
                        target_dir=units_dir,
                        run_systemctl=True,
                        runner=runner,
                    )

        self.assertEqual(len(payload["systemctl_actions"]), 2)
        self.assertFalse(payload["systemctl_actions"][0]["ok"])
        self.assertEqual(
            runner.calls[0]["args"],
            ["systemctl", "--user", "disable", "--now", RECONCILE_TIMER_NAME],
        )


if __name__ == "__main__":
    unittest.main()
