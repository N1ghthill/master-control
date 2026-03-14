#!/usr/bin/env python3
"""Tests for Debian-first real context collectors."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mastercontrol.context.contextd import (
    AlertJournalCollector,
    CommandResult,
    HostContextCollector,
    NetworkContextCollector,
    ServiceContextCollector,
    SessionContextCollector,
)


class ContextCollectorsTests(unittest.TestCase):
    def test_session_context_collector_exposes_runtime_fields(self) -> None:
        collector = SessionContextCollector(
            "Irving",
            env={"USER": "irving", "XDG_SESSION_ID": "42", "TTY": "pts/0"},
            cwd_provider=lambda: "/home/irving/ruas/repos/master-control",
            hostname_provider=lambda: "rainbow",
            now_provider=lambda: dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc),
        )

        snapshot = collector.collect()

        self.assertEqual(snapshot.payload["operator"], "Irving")
        self.assertEqual(snapshot.payload["hostname"], "rainbow")
        self.assertEqual(snapshot.payload["user"], "irving")
        self.assertEqual(snapshot.payload["session_id"], "42")

    def test_host_context_collector_reads_proc_style_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            os_release = root / "os-release"
            meminfo = root / "meminfo"
            loadavg = root / "loadavg"
            uptime = root / "uptime"
            os_release.write_text('PRETTY_NAME="Debian Testing"\n', encoding="utf-8")
            meminfo.write_text(
                "MemTotal:       32768000 kB\nMemAvailable:   16384000 kB\n",
                encoding="utf-8",
            )
            loadavg.write_text("0.20 0.15 0.10 1/100 12345\n", encoding="utf-8")
            uptime.write_text("7200.00 100.00\n", encoding="utf-8")
            collector = HostContextCollector(
                os_release_path=os_release,
                meminfo_path=meminfo,
                loadavg_path=loadavg,
                uptime_path=uptime,
                cpu_count_provider=lambda: 8,
                uname_provider=lambda: SimpleNamespace(release="6.10.0", machine="x86_64"),
            )

            snapshot = collector.collect()

        self.assertEqual(snapshot.payload["os_pretty"], "Debian Testing")
        self.assertEqual(snapshot.payload["cpu_count"], 8)
        self.assertEqual(snapshot.payload["uptime_s"], 7200)
        self.assertEqual(snapshot.payload["mem_total_mib"], 32000.0)

    def test_network_context_collector_parses_route_nameservers_and_interfaces(self) -> None:
        def runner(command: list[str], timeout_s: int) -> CommandResult:
            self.assertEqual(command, ["ip", "route", "show", "default"])
            self.assertEqual(timeout_s, 2)
            return CommandResult(returncode=0, stdout="default via 192.168.1.1 dev eth0\n")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            resolv = root / "resolv.conf"
            netdir = root / "net"
            netdir.mkdir()
            (netdir / "eth0").mkdir()
            (netdir / "wlan0").mkdir()
            resolv.write_text("nameserver 1.1.1.1\nnameserver 8.8.8.8\n", encoding="utf-8")
            collector = NetworkContextCollector(
                runner=runner,
                resolv_conf_path=resolv,
                sys_class_net_path=netdir,
            )

            snapshot = collector.collect()

        self.assertEqual(snapshot.payload["default_route"], "default via 192.168.1.1 dev eth0")
        self.assertEqual(snapshot.payload["nameservers"], ["1.1.1.1", "8.8.8.8"])
        self.assertEqual(snapshot.payload["interfaces"], ["eth0", "wlan0"])

    def test_service_context_collector_parses_system_state_and_failed_units(self) -> None:
        def runner(command: list[str], timeout_s: int) -> CommandResult:
            if command[:2] == ["systemctl", "is-system-running"]:
                return CommandResult(returncode=1, stdout="degraded\n")
            if command[:2] == ["systemctl", "--failed"]:
                return CommandResult(
                    returncode=0,
                    stdout=(
                        "nginx.service loaded failed failed nginx\n"
                        "ssh.service loaded failed failed ssh\n"
                    ),
                )
            raise AssertionError(f"Unexpected command: {command}")

        collector = ServiceContextCollector(runner=runner)
        snapshot = collector.collect()

        self.assertEqual(snapshot.payload["system_state"], "degraded")
        self.assertEqual(snapshot.payload["failed_count"], 2)
        self.assertEqual(snapshot.payload["failed_units"], ["nginx.service", "ssh.service"])

    def test_alert_journal_collector_keeps_recent_warning_lines(self) -> None:
        def runner(command: list[str], timeout_s: int) -> CommandResult:
            self.assertEqual(command[:2], ["journalctl", "-p"])
            return CommandResult(
                returncode=0,
                stdout=(
                    "2026-03-14 warning one\n"
                    "2026-03-14 warning two\n"
                ),
            )

        collector = AlertJournalCollector(runner=runner)
        snapshot = collector.collect()

        self.assertEqual(snapshot.payload["warning_event_count"], 2)
        self.assertEqual(len(snapshot.payload["recent_warning_events"]), 2)


if __name__ == "__main__":
    unittest.main()
