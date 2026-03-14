#!/usr/bin/env python3
"""Tests for incremental system event monitoring."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from mastercontrol.context import SQLiteContextStore, SystemEventMonitor
from mastercontrol.context.contextd import CommandResult
from mastercontrol.contracts import ContextSnapshot


class SystemEventMonitorTests(unittest.TestCase):
    @staticmethod
    def _busctl_sessions(*rows: list[object]) -> str:
        return json.dumps(
            {
                "type": "a(sussussbto)",
                "data": [list(rows)],
            }
        )

    def test_service_event_invalidates_related_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            store = SQLiteContextStore(db_path)
            store.put(
                ContextSnapshot(
                    source="services.summary",
                    tier="warm",
                    collected_at_utc="2026-03-14T12:00:00+00:00",
                    ttl_s=300,
                    payload={"system_state": "running"},
                    summary="services",
                )
            )
            store.put(
                ContextSnapshot(
                    source="journal.alerts",
                    tier="deep",
                    collected_at_utc="2026-03-14T12:00:00+00:00",
                    ttl_s=300,
                    payload={"warning_event_count": 0},
                    summary="journal",
                )
            )

            def runner(command: list[str], timeout_s: int) -> CommandResult:
                self.assertEqual(timeout_s, 5)
                if command[:4] == ["journalctl", "--no-pager", "-o", "json"]:
                    event = {
                        "__CURSOR": "cursor-1",
                        "__REALTIME_TIMESTAMP": "1710417600000000",
                        "_SYSTEMD_UNIT": "nginx.service",
                        "SYSLOG_IDENTIFIER": "systemd",
                        "MESSAGE": "Started nginx.service - high performance web server.",
                    }
                    return CommandResult(returncode=0, stdout=json.dumps(event) + "\n")
                if command == ["udevadm", "info", "--export-db"]:
                    return CommandResult(returncode=0, stdout="")
                if command[:3] == ["busctl", "--json=short", "call"]:
                    return CommandResult(returncode=0, stdout=self._busctl_sessions())
                raise AssertionError(f"Unexpected command: {command}")

            monitor = SystemEventMonitor(db_path=db_path, store=store, runner=runner, min_interval_s=0)
            result = monitor.sweep(
                now=dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc),
                min_interval_s=0,
            )

            self.assertTrue(result.scanned)
            self.assertEqual(result.relevant_events, 1)
            self.assertEqual(result.invalidated_sources, ("journal.alerts", "services.summary"))
            self.assertIsNone(store.get("services.summary"))
            self.assertIsNone(store.get("journal.alerts"))

    def test_second_sweep_uses_persisted_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            store = SQLiteContextStore(db_path)
            commands: list[list[str]] = []

            def runner(command: list[str], timeout_s: int) -> CommandResult:
                del timeout_s
                commands.append(command)
                if command[:4] == ["journalctl", "--no-pager", "-o", "json"]:
                    if "--after-cursor" in command:
                        return CommandResult(returncode=0, stdout="")
                    return CommandResult(
                        returncode=0,
                        stdout=json.dumps(
                            {
                                "__CURSOR": "cursor-9",
                                "__REALTIME_TIMESTAMP": "1710417600000000",
                                "SYSLOG_IDENTIFIER": "apt",
                                "MESSAGE": "apt upgrade completed",
                            }
                        )
                        + "\n",
                    )
                if command == ["udevadm", "info", "--export-db"]:
                    return CommandResult(
                        returncode=0,
                        stdout="P: /devices/pci/net/eth0\nE: SUBSYSTEM=net\nE: INTERFACE=eth0\n\n",
                    )
                if command[:3] == ["busctl", "--json=short", "call"]:
                    return CommandResult(returncode=0, stdout=self._busctl_sessions(["2", 1000, "irving", "seat0", 3801, "user", "tty2", False, 0, "/org/freedesktop/login1/session/_32"]))
                raise AssertionError(f"Unexpected command: {command}")

            monitor = SystemEventMonitor(db_path=db_path, store=store, runner=runner, min_interval_s=0)
            monitor.sweep(
                now=dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc),
                min_interval_s=0,
            )
            monitor.sweep(
                now=dt.datetime(2026, 3, 14, 12, 1, tzinfo=dt.timezone.utc),
                min_interval_s=0,
            )

            journal_commands = [
                command for command in commands if command[:4] == ["journalctl", "--no-pager", "-o", "json"]
            ]
            self.assertEqual(len(journal_commands), 2)
            self.assertIn("--since", journal_commands[0])
            self.assertIn("--after-cursor", journal_commands[1])
            self.assertIn("cursor-9", journal_commands[1])

    def test_udev_state_change_invalidates_host_and_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            store = SQLiteContextStore(db_path)
            store.put(
                ContextSnapshot(
                    source="host.system",
                    tier="warm",
                    collected_at_utc="2026-03-14T12:00:00+00:00",
                    ttl_s=300,
                    payload={"cpu_count": 8},
                )
            )
            store.put(
                ContextSnapshot(
                    source="network.summary",
                    tier="warm",
                    collected_at_utc="2026-03-14T12:00:00+00:00",
                    ttl_s=300,
                    payload={"interfaces": ["eth0"]},
                )
            )
            responses = [
                CommandResult(returncode=0, stdout=""),
                CommandResult(
                    returncode=0,
                    stdout="P: /devices/pci/net/eth0\nE: SUBSYSTEM=net\nE: INTERFACE=eth0\n\n",
                ),
                CommandResult(returncode=0, stdout=""),
                CommandResult(
                    returncode=0,
                    stdout=(
                        "P: /devices/pci/net/eth0\nE: SUBSYSTEM=net\nE: INTERFACE=eth0\n\n"
                        "P: /devices/pci/net/wlan0\nE: SUBSYSTEM=net\nE: INTERFACE=wlan0\n\n"
                    ),
                ),
            ]

            def runner(command: list[str], timeout_s: int) -> CommandResult:
                del timeout_s
                if command[:4] == ["journalctl", "--no-pager", "-o", "json"]:
                    return responses.pop(0)
                if command == ["udevadm", "info", "--export-db"]:
                    return responses.pop(0)
                if command[:3] == ["busctl", "--json=short", "call"]:
                    return CommandResult(
                        returncode=0,
                        stdout=self._busctl_sessions(["2", 1000, "irving", "seat0", 3801, "user", "tty2", False, 0, "/org/freedesktop/login1/session/_32"]),
                    )
                raise AssertionError(f"Unexpected command: {command}")

            monitor = SystemEventMonitor(
                db_path=db_path,
                store=store,
                runner=runner,
                min_interval_s=0,
                udev_interval_s=0,
                dbus_interval_s=0,
            )
            first = monitor.sweep(
                now=dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc),
                min_interval_s=0,
            )
            second = monitor.sweep(
                now=dt.datetime(2026, 3, 14, 12, 1, tzinfo=dt.timezone.utc),
                min_interval_s=0,
            )

            self.assertEqual(first.invalidated_sources, ())
            self.assertEqual(second.invalidated_sources, ("host.system", "network.summary"))
            self.assertIsNone(store.get("host.system"))
            self.assertIsNone(store.get("network.summary"))

    def test_dbus_session_change_invalidates_journal_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            store = SQLiteContextStore(db_path)
            store.put(
                ContextSnapshot(
                    source="journal.alerts",
                    tier="deep",
                    collected_at_utc="2026-03-14T12:00:00+00:00",
                    ttl_s=300,
                    payload={"warning_event_count": 0},
                    summary="journal",
                )
            )
            busctl_responses = [
                CommandResult(
                    returncode=0,
                    stdout=self._busctl_sessions(
                        ["2", 1000, "irving", "seat0", 3801, "user", "tty2", False, 0, "/org/freedesktop/login1/session/_32"]
                    ),
                ),
                CommandResult(
                    returncode=0,
                    stdout=self._busctl_sessions(
                        ["2", 1000, "irving", "seat0", 3801, "user", "tty2", False, 0, "/org/freedesktop/login1/session/_32"],
                        ["5", 0, "root", "seat0", 4912, "user", "pts/0", False, 0, "/org/freedesktop/login1/session/_35"],
                    ),
                ),
            ]

            def runner(command: list[str], timeout_s: int) -> CommandResult:
                del timeout_s
                if command[:4] == ["journalctl", "--no-pager", "-o", "json"]:
                    return CommandResult(returncode=0, stdout="")
                if command == ["udevadm", "info", "--export-db"]:
                    return CommandResult(returncode=0, stdout="")
                if command[:3] == ["busctl", "--json=short", "call"]:
                    return busctl_responses.pop(0)
                raise AssertionError(f"Unexpected command: {command}")

            monitor = SystemEventMonitor(
                db_path=db_path,
                store=store,
                runner=runner,
                min_interval_s=0,
                udev_interval_s=0,
                dbus_interval_s=0,
            )
            first = monitor.sweep(
                now=dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc),
                min_interval_s=0,
            )
            second = monitor.sweep(
                now=dt.datetime(2026, 3, 14, 12, 1, tzinfo=dt.timezone.utc),
                min_interval_s=0,
            )

            self.assertEqual(first.invalidated_sources, ())
            self.assertEqual(second.invalidated_sources, ("journal.alerts",))
            self.assertEqual(second.relevant_events, 1)
            self.assertIsNone(store.get("journal.alerts"))

    def test_mastercontrol_self_log_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            store = SQLiteContextStore(db_path)

            def runner(command: list[str], timeout_s: int) -> CommandResult:
                del timeout_s
                if command[:4] == ["journalctl", "--no-pager", "-o", "json"]:
                    event = {
                        "__CURSOR": "cursor-self-1",
                        "__REALTIME_TIMESTAMP": "1710417600000000",
                        "_SYSTEMD_UNIT": "mastercontrol-security-watch.service",
                        "SYSLOG_IDENTIFIER": "mc-security-watch",
                        "MESSAGE": '{"active_alerts": 1, "schema_version": 3}',
                    }
                    return CommandResult(returncode=0, stdout=json.dumps(event) + "\n")
                if command == ["udevadm", "info", "--export-db"]:
                    return CommandResult(returncode=0, stdout="")
                if command[:3] == ["busctl", "--json=short", "call"]:
                    return CommandResult(returncode=0, stdout=self._busctl_sessions())
                raise AssertionError(f"Unexpected command: {command}")

            monitor = SystemEventMonitor(db_path=db_path, store=store, runner=runner, min_interval_s=0)
            result = monitor.sweep(
                now=dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc),
                min_interval_s=0,
            )

            self.assertTrue(result.scanned)
            self.assertEqual(result.relevant_events, 0)
            self.assertEqual(result.invalidated_sources, ())


if __name__ == "__main__":
    unittest.main()
