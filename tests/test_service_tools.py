from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from master_control.executor.command_runner import CommandResult
from master_control.tools.base import ToolError
from master_control.tools.reload_service import ReloadServiceTool
from master_control.tools.restart_service import RestartServiceTool
from master_control.tools.service_status import ServiceStatusTool


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


class ServiceToolsTest(unittest.TestCase):
    def test_service_status_supports_user_scope(self) -> None:
        runner = StubRunner(
            [
                CommandResult(
                    returncode=0,
                    stdout=(
                        "Id=ollama-local.service\n"
                        "LoadState=loaded\n"
                        "ActiveState=active\n"
                        "SubState=running\n"
                        "UnitFileState=enabled\n"
                        "CanReload=no\n"
                    ),
                    stderr="",
                    truncated_stdout=False,
                    truncated_stderr=False,
                )
            ]
        )
        tool = ServiceStatusTool(runner)

        with patch.dict(
            os.environ,
            {
                "XDG_RUNTIME_DIR": "/run/user/1000",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                "HOME": "/home/tester",
            },
            clear=False,
        ):
            payload = tool.invoke({"name": "ollama-local.service", "scope": "user"})

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["scope"], "user")
        self.assertEqual(runner.calls[0]["args"][:2], ["systemctl", "--user"])
        self.assertEqual(runner.calls[0]["env"]["XDG_RUNTIME_DIR"], "/run/user/1000")
        self.assertEqual(
            runner.calls[0]["env"]["DBUS_SESSION_BUS_ADDRESS"],
            "unix:path=/run/user/1000/bus",
        )

    def test_restart_service_uses_user_scope_without_system_password_flag(self) -> None:
        runner = StubRunner(
            [
                CommandResult(
                    returncode=0,
                    stdout=(
                        "Id=demo.service\n"
                        "LoadState=loaded\n"
                        "ActiveState=active\n"
                        "SubState=running\n"
                        "UnitFileState=enabled\n"
                        "CanReload=yes\n"
                    ),
                    stderr="",
                    truncated_stdout=False,
                    truncated_stderr=False,
                ),
                CommandResult(
                    returncode=0,
                    stdout="",
                    stderr="",
                    truncated_stdout=False,
                    truncated_stderr=False,
                ),
                CommandResult(
                    returncode=0,
                    stdout=(
                        "Id=demo.service\n"
                        "LoadState=loaded\n"
                        "ActiveState=active\n"
                        "SubState=running\n"
                        "UnitFileState=enabled\n"
                        "CanReload=yes\n"
                    ),
                    stderr="",
                    truncated_stdout=False,
                    truncated_stderr=False,
                ),
            ]
        )
        tool = RestartServiceTool(runner)

        with patch.dict(
            os.environ,
            {
                "XDG_RUNTIME_DIR": "/run/user/1000",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            },
            clear=False,
        ):
            payload = tool.invoke({"name": "demo.service", "scope": "user"})

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["scope"], "user")
        restart_args = runner.calls[1]["args"]
        self.assertEqual(restart_args[:2], ["systemctl", "--user"])
        self.assertIn("restart", restart_args)
        self.assertNotIn("--no-ask-password", restart_args)

    def test_reload_service_rejects_non_reloadable_unit(self) -> None:
        runner = StubRunner(
            [
                CommandResult(
                    returncode=0,
                    stdout=(
                        "Id=demo.service\n"
                        "LoadState=loaded\n"
                        "ActiveState=active\n"
                        "SubState=running\n"
                        "UnitFileState=enabled\n"
                        "CanReload=no\n"
                    ),
                    stderr="",
                    truncated_stdout=False,
                    truncated_stderr=False,
                )
            ]
        )
        tool = ReloadServiceTool(runner)

        with patch.dict(
            os.environ,
            {
                "XDG_RUNTIME_DIR": "/run/user/1000",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(ToolError, "does not support reload"):
                tool.invoke({"name": "demo.service", "scope": "user"})


if __name__ == "__main__":
    unittest.main()
