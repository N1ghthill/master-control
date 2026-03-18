from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from master_control.executor.command_runner import CommandResult
from master_control.tools.base import ToolArgumentError, ToolError
from master_control.tools.failed_services import FailedServicesTool
from master_control.tools.process_to_unit import ProcessToUnitTool
from master_control.tools.read_journal import ReadJournalTool
from master_control.tools.reload_service import ReloadServiceTool
from master_control.tools.restart_service import RestartServiceTool
from master_control.tools.service_status import ServiceStatusTool
from master_control.tools.top_processes import TopProcessesTool


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
    def test_top_processes_filters_collector_noise(self) -> None:
        runner = StubRunner(
            [
                CommandResult(
                    returncode=0,
                    stdout=(
                        " 100 1 99.0 0.1 python3\n"
                        " 101 100 88.0 0.0 ps\n"
                        " 200 1 77.0 1.2 nginx\n"
                        " 300 1 55.0 0.7 postgres\n"
                    ),
                    stderr="",
                    truncated_stdout=False,
                    truncated_stderr=False,
                )
            ]
        )
        tool = TopProcessesTool(runner)

        with patch("master_control.tools.top_processes.os.getpid", return_value=100):
            payload = tool.invoke({"limit": "2"})

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["excluded_process_count"], 2)
        self.assertEqual([item["command"] for item in payload["processes"]], ["nginx", "postgres"])

    def test_process_to_unit_correlates_name_matches_with_systemd_unit(self) -> None:
        runner = StubRunner(
            [
                CommandResult(
                    returncode=0,
                    stdout=" 123 88.0 nginx\n 999 10.0 sshd\n",
                    stderr="",
                    truncated_stdout=False,
                    truncated_stderr=False,
                )
            ]
        )
        tool = ProcessToUnitTool(runner)

        with patch(
            "master_control.tools.process_to_unit._read_primary_cgroup_path",
            return_value="/system.slice/nginx.service",
        ):
            payload = tool.invoke({"name": "nginx"})

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["primary_match"]["unit"], "nginx.service")
        self.assertEqual(payload["primary_match"]["scope"], "system")
        self.assertEqual(payload["units"][0]["pid_count"], 1)

    def test_process_to_unit_accepts_pid_queries(self) -> None:
        runner = StubRunner(
            [
                CommandResult(
                    returncode=0,
                    stdout=" 321 55.0 ollama\n",
                    stderr="",
                    truncated_stdout=False,
                    truncated_stderr=False,
                )
            ]
        )
        tool = ProcessToUnitTool(runner)

        with patch(
            "master_control.tools.process_to_unit._read_primary_cgroup_path",
            return_value="/user.slice/user-1000.slice/user@1000.service/app.slice/ollama-local.service",
        ):
            payload = tool.invoke({"pid": "321"})

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["primary_match"]["unit"], "ollama-local.service")
        self.assertEqual(payload["primary_match"]["scope"], "user")
        self.assertEqual(runner.calls[0]["args"][:3], ["ps", "-p", "321"])

    def test_failed_services_supports_user_scope(self) -> None:
        runner = StubRunner(
            [
                CommandResult(
                    returncode=0,
                    stdout=(
                        "ollama-local.service loaded failed failed Ollama validation unit\n"
                        "demo.service loaded failed failed Demo unit\n"
                    ),
                    stderr="",
                    truncated_stdout=False,
                    truncated_stderr=False,
                )
            ]
        )
        tool = FailedServicesTool(runner)

        with patch.dict(
            os.environ,
            {
                "XDG_RUNTIME_DIR": "/run/user/1000",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                "HOME": "/home/tester",
            },
            clear=False,
        ):
            payload = tool.invoke({"scope": "user", "limit": "1"})

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["scope"], "user")
        self.assertEqual(payload["unit_count"], 1)
        self.assertEqual(payload["units"][0]["unit"], "ollama-local.service")
        self.assertEqual(runner.calls[0]["args"][:2], ["systemctl", "--user"])
        self.assertEqual(runner.calls[0]["env"]["HOME"], "/home/tester")

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

    def test_service_status_rejects_option_like_unit_name(self) -> None:
        tool = ServiceStatusTool(StubRunner([]))

        with self.assertRaises(ToolArgumentError):
            tool.invoke({"name": "--help"})

    def test_service_status_reports_incomplete_systemctl_metadata(self) -> None:
        runner = StubRunner(
            [
                CommandResult(
                    returncode=0,
                    stdout="  -h --host=[USER@]HOST\n",
                    stderr="",
                    truncated_stdout=False,
                    truncated_stderr=False,
                )
            ]
        )
        tool = ServiceStatusTool(runner)

        payload = tool.invoke({"name": "demo.service"})

        self.assertEqual(payload["status"], "unavailable")
        self.assertIn("incomplete metadata", payload["reason"])

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

    def test_read_journal_rejects_option_like_unit_name(self) -> None:
        tool = ReadJournalTool(StubRunner([]))

        with self.assertRaises(ToolArgumentError):
            tool.invoke({"unit": "--since=yesterday"})

    def test_read_journal_filters_no_entries_sentinel(self) -> None:
        runner = StubRunner(
            [
                CommandResult(
                    returncode=0,
                    stdout="-- No entries --\n",
                    stderr="",
                    truncated_stdout=False,
                    truncated_stderr=False,
                )
            ]
        )
        tool = ReadJournalTool(runner)

        payload = tool.invoke({"unit": "ssh", "lines": "3"})

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["returned_lines"], 0)
        self.assertEqual(payload["entries"], [])
        self.assertIn("-q", runner.calls[0]["args"])


if __name__ == "__main__":
    unittest.main()
