#!/usr/bin/env python3
"""Tests for the continuous local security watch engine."""

from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mastercontrol.security import SecurityWatchEngine


class _FakeEventMonitor:
    def __init__(self) -> None:
        self.calls = 0

    def sweep(self, *, now: dt.datetime | None = None, max_events: int = 64):  # type: ignore[no-untyped-def]
        del now, max_events
        self.calls += 1

        class _Result:
            scanned = True
            events_seen = 2
            relevant_events = 2
            invalidated_sources = ("journal.alerts",)
            command_status = 0
            reason = "ok"

        return _Result()


class SecurityWatchEngineTests(unittest.TestCase):
    def test_init_migrates_legacy_watch_schema_to_current_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    CREATE TABLE security_alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts_utc TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        category TEXT NOT NULL,
                        fingerprint TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        recommendation TEXT NOT NULL,
                        source TEXT NOT NULL DEFAULT 'security-watch',
                        status TEXT NOT NULL DEFAULT 'new',
                        event_ids_json TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );

                    CREATE TABLE security_silences (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fingerprint TEXT NOT NULL,
                        reason TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        silence_until_utc TEXT NOT NULL,
                        source TEXT NOT NULL DEFAULT 'operator'
                    );
                    """
                )
                conn.execute(
                    """
                    INSERT INTO security_alerts (
                        ts_utc, severity, category, fingerprint, summary,
                        recommendation, source, status, event_ids_json, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "2026-03-14T12:00:00+00:00",
                        "high",
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

            engine = SecurityWatchEngine(db_path=db_path)
            alerts = engine.list_recent_alerts(limit=10)

            self.assertEqual(engine.schema_version(), 3)
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0]["fingerprint"], "security.auth.anomaly")

            conn = sqlite3.connect(db_path)
            try:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                meta_version = conn.execute(
                    """
                    SELECT meta_value
                    FROM security_watch_meta
                    WHERE meta_key = 'schema_version'
                    """
                ).fetchone()[0]
            finally:
                conn.close()

            self.assertIn("incidents", tables)
            self.assertIn("incident_activity", tables)
            self.assertEqual(meta_version, "3")

    def test_run_once_persists_and_dedupes_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            monitor = _FakeEventMonitor()
            engine = SecurityWatchEngine(db_path=db_path, event_monitor=monitor, dedupe_window_minutes=30)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_events(
                db_path,
                [
                    (now - dt.timedelta(minutes=20), "security", "sshd", "Failed password for root from 10.0.0.2"),
                    (now - dt.timedelta(minutes=10), "security", "dbus.login1", "login1 sessions changed: added=5:root@pts/0/user"),
                ],
            )

            first = engine.run_once(now=now)
            second = engine.run_once(now=now + dt.timedelta(minutes=5))

            self.assertEqual(monitor.calls, 2)
            self.assertEqual(first.highest_severity, "critical")
            self.assertEqual(first.vigilance_status, "elevated")
            self.assertGreaterEqual(first.alerts_emitted, 1)
            self.assertEqual(second.alerts_emitted, 0)

            conn = sqlite3.connect(db_path)
            try:
                total = conn.execute("SELECT COUNT(*) FROM security_alerts").fetchone()[0]
            finally:
                conn.close()
            self.assertGreaterEqual(total, 1)

    def test_summarize_vigilance_reports_top_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_events(
                db_path,
                [
                    (now - dt.timedelta(minutes=30), "security", "sshd", "Failed password for root from 10.0.0.2"),
                    (now - dt.timedelta(minutes=20), "service", "systemd", "nginx.service entered failed state"),
                    (now - dt.timedelta(minutes=10), "udev", "udevadm", "udev topology changed: usb:keyboard"),
                ],
            )

            summary = engine.summarize_vigilance(category="all", window_hours=6, now=now)

            self.assertEqual(summary["status"], "elevated")
            self.assertEqual(summary["highest_severity"], "critical")
            self.assertIn("Authentication anomalies detected", summary["summary"])
            self.assertEqual(summary["event_counts"]["security"], 1)

    def test_acknowledge_and_silence_alerts_update_state_and_suppress_recurrence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path, dedupe_window_minutes=1)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_events(
                db_path,
                [
                    (now - dt.timedelta(minutes=20), "security", "sshd", "Failed password for root from 10.0.0.2"),
                    (now - dt.timedelta(minutes=10), "security", "dbus.login1", "login1 sessions changed: added=5:root@pts/0/user"),
                ],
            )

            first = engine.run_once(now=now)
            alerts = engine.list_recent_alerts(limit=10, category="all", now=now)
            self.assertGreaterEqual(len(alerts), 1)

            acked = engine.acknowledge_alerts(alert_ids=[int(alerts[0]["id"])], now=now)
            self.assertEqual(acked["acknowledged"], 1)

            silenced = engine.silence_alerts(
                alert_ids=[int(row["id"]) for row in alerts],
                silence_hours=12,
                now=now,
            )
            self.assertGreaterEqual(silenced["silenced"], 1)

            second = engine.run_once(now=now + dt.timedelta(hours=2))

            self.assertGreaterEqual(first.alerts_emitted, 1)
            self.assertEqual(second.alerts_emitted, 0)

    def test_alert_filters_and_active_summary_track_open_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=20),
                        "critical",
                        "security",
                        "security.auth.anomaly",
                        "Authentication anomalies detected.",
                        "Investigate auth failures.",
                        "new",
                        "[]",
                    ),
                    (
                        now - dt.timedelta(minutes=15),
                        "high",
                        "service",
                        "service.failure.cluster",
                        "Service degradation detected.",
                        "Inspect failed units.",
                        "new",
                        "[]",
                    ),
                    (
                        now - dt.timedelta(minutes=10),
                        "low",
                        "udev",
                        "device.topology.change",
                        "Device topology changed.",
                        "Confirm device changes.",
                        "new",
                        "[]",
                    ),
                ],
            )

            high_rows = engine.list_recent_alerts(limit=10, severity="high", now=now)
            self.assertEqual(len(high_rows), 1)
            self.assertEqual(high_rows[0]["fingerprint"], "service.failure.cluster")

            acked = engine.acknowledge_alerts(
                fingerprint="service.failure.cluster",
                limit=10,
                now=now,
            )
            self.assertEqual(acked["acknowledged"], 1)

            silenced = engine.silence_alerts(
                severity="critical",
                limit=10,
                silence_hours=12,
                now=now,
            )
            self.assertEqual(silenced["silenced"], 1)
            self.assertEqual(silenced["fingerprints"], ["security.auth.anomaly"])

            summary = engine.active_alert_summary(now=now)
            self.assertEqual(summary["active_alerts"], 1)
            self.assertEqual(summary["highest_severity"], "low")
            self.assertIn("device.topology.change", summary["summary"])

    def test_build_incident_playbook_recommends_bounded_service_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_events(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=15),
                        "service",
                        "systemd",
                        "nginx.service entered failed state",
                    ),
                ],
            )
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "high",
                        "service",
                        "service.failure.cluster",
                        "Service degradation detected.",
                        "Inspect failed units.",
                        "new",
                        "[1]",
                    ),
                ],
            )

            playbook = engine.build_incident_playbook(category="service", now=now)

            self.assertEqual(playbook["status"], "elevated")
            self.assertTrue(playbook["recommendations"])
            contain = next(
                item for item in playbook["recommendations"] if item["action_id"] == "service.systemctl.restart"
            )
            self.assertEqual(contain["args"]["unit"], "nginx.service")

    def test_validate_service_containment_requires_correlated_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_events(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=15),
                        "service",
                        "systemd",
                        "nginx.service entered failed state",
                    ),
                ],
            )
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "high",
                        "service",
                        "service.failure.cluster",
                        "Service degradation detected.",
                        "Inspect failed units.",
                        "new",
                        "[1]",
                    ),
                ],
            )

            allowed = engine.validate_service_containment(unit="nginx.service", now=now)
            blocked = engine.validate_service_containment(unit="ssh.service", now=now)

            self.assertTrue(allowed["allowed"])
            self.assertEqual(allowed["derived_units"], ["nginx.service"])
            self.assertFalse(blocked["allowed"])
            self.assertIn("ssh.service", blocked["reason"])

    def test_build_incident_playbook_recommends_ssh_restart_for_auth_anomaly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "critical",
                        "security",
                        "security.auth.anomaly",
                        "Authentication anomalies detected.",
                        "Investigate auth failures.",
                        "new",
                        "[]",
                    ),
                ],
            )

            playbook = engine.build_incident_playbook(category="security", now=now)

            remediate = next(
                item for item in playbook["recommendations"] if item["action_id"] == "service.systemctl.restart"
            )
            self.assertEqual(remediate["args"]["unit"], "ssh.service")
            self.assertEqual(remediate["args"]["category"], "security")

    def test_validate_auth_containment_requires_active_auth_anomaly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "critical",
                        "security",
                        "security.auth.anomaly",
                        "Authentication anomalies detected.",
                        "Investigate auth failures.",
                        "new",
                        "[]",
                    ),
                ],
            )

            allowed = engine.validate_incident_containment(
                action_id="service.systemctl.restart",
                unit="ssh.service",
                category="security",
                now=now,
            )
            blocked = engine.validate_incident_containment(
                action_id="service.systemctl.restart",
                unit="NetworkManager.service",
                category="security",
                now=now,
            )

            self.assertTrue(allowed["allowed"])
            self.assertFalse(blocked["allowed"])
            self.assertIn("ssh.service", blocked["reason"])

    def test_build_incident_playbook_recommends_network_service_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_events(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=15),
                        "network",
                        "networkmanager",
                        "NetworkManager lost carrier on wlan0",
                    ),
                ],
            )
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "high",
                        "network",
                        "network.instability",
                        "Network instability pattern detected.",
                        "Check routes and DNS.",
                        "new",
                        "[1]",
                    ),
                ],
            )

            playbook = engine.build_incident_playbook(category="network", now=now)

            remediate = next(
                item for item in playbook["recommendations"] if item["action_id"] == "service.systemctl.restart"
            )
            self.assertEqual(remediate["args"]["unit"], "NetworkManager.service")
            self.assertEqual(remediate["args"]["category"], "network")

    def test_validate_network_containment_requires_correlated_network_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_events(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=15),
                        "network",
                        "networkmanager",
                        "NetworkManager lost carrier on wlan0",
                    ),
                ],
            )
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "high",
                        "network",
                        "network.instability",
                        "Network instability pattern detected.",
                        "Check routes and DNS.",
                        "new",
                        "[1]",
                    ),
                ],
            )

            allowed = engine.validate_incident_containment(
                action_id="service.systemctl.restart",
                unit="NetworkManager.service",
                category="network",
                now=now,
            )
            blocked = engine.validate_incident_containment(
                action_id="service.systemctl.restart",
                unit="ssh.service",
                category="network",
                now=now,
            )

            self.assertTrue(allowed["allowed"])
            self.assertFalse(blocked["allowed"])
            self.assertIn("network", blocked["reason"].lower())

    def test_successful_pkexec_session_open_does_not_raise_auth_anomaly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_events(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "security",
                        "pkexec",
                        "pam_unix(polkit-1:session): session opened for user root(uid=0) by irving(uid=1000)",
                    ),
                ],
            )

            summary = engine.summarize_vigilance(category="security", window_hours=6, now=now)
            alerts = engine.evaluate_alerts(now=now, window_hours=6)

            self.assertEqual(summary["highest_severity"], "none")
            self.assertFalse(any(alert.fingerprint == "security.auth.anomaly" for alert in alerts))

    def test_list_incidents_opens_ledger_rows_from_active_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_events(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=15),
                        "service",
                        "systemd",
                        "nginx.service entered failed state",
                    ),
                ],
            )
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "high",
                        "service",
                        "service.failure.cluster",
                        "Service degradation detected.",
                        "Inspect failed units.",
                        "new",
                        "[1]",
                    ),
                ],
            )

            incidents = engine.list_incidents(status="active", now=now)
            summary = engine.active_incident_summary(now=now)

            self.assertEqual(len(incidents), 1)
            self.assertEqual(incidents[0]["status"], "open")
            self.assertEqual(incidents[0]["correlated_units"], ("nginx.service",))
            self.assertIn("incidents=1", summary["summary"])

    def test_get_incident_returns_alerts_and_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_events(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=15),
                        "service",
                        "systemd",
                        "nginx.service entered failed state",
                    ),
                ],
            )
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "high",
                        "service",
                        "service.failure.cluster",
                        "Service degradation detected.",
                        "Inspect failed units.",
                        "new",
                        "[1]",
                    ),
                ],
            )

            incident_id = str(engine.list_incidents(status="active", now=now)[0]["incident_id"])
            detail = engine.get_incident(incident_id, now=now)

            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["incident_id"], incident_id)
            self.assertEqual(len(detail["alerts"]), 1)
            self.assertGreaterEqual(len(detail["activity"]), 1)

    def test_update_incident_status_closes_linked_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "critical",
                        "security",
                        "security.auth.anomaly",
                        "Authentication anomalies detected.",
                        "Investigate auth failures.",
                        "new",
                        "[]",
                    ),
                ],
            )

            incident_id = str(engine.list_incidents(status="active", now=now)[0]["incident_id"])
            updated = engine.update_incident_status(
                incident_id,
                status="dismissed",
                operator_id="irving",
                request_id="req-dismiss-incident",
                now=now,
            )
            detail = engine.get_incident(incident_id, now=now, sync=False)
            alerts = engine.list_recent_alerts(limit=10, category="security", now=now)

            self.assertEqual(updated["updated"], 1)
            assert detail is not None
            self.assertEqual(detail["status"], "dismissed")
            self.assertEqual(alerts[0]["status"], "acknowledged")

    def test_acknowledge_alert_resolves_incident_when_scope_has_no_open_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "critical",
                        "security",
                        "security.auth.anomaly",
                        "Authentication anomalies detected.",
                        "Investigate auth failures.",
                        "new",
                        "[]",
                    ),
                ],
            )

            incidents_before = engine.list_incidents(status="active", now=now)
            acked = engine.acknowledge_alerts(
                fingerprint="security.auth.anomaly",
                limit=10,
                operator_id="irving",
                request_id="req-ack-incident",
                now=now,
            )
            incidents_after = engine.list_incidents(status="resolved", now=now)

            self.assertEqual(len(incidents_before), 1)
            self.assertEqual(acked["incident_update"]["status"], "resolved")
            self.assertEqual(len(incidents_after), 1)
            self.assertEqual(incidents_after[0]["status"], "resolved")
            self.assertEqual(incidents_after[0]["last_action_id"], "security.alerts.ack")

    def test_record_incident_action_marks_real_containment_as_contained(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            self._seed_events(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=15),
                        "service",
                        "systemd",
                        "nginx.service entered failed state",
                    ),
                ],
            )
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "high",
                        "service",
                        "service.failure.cluster",
                        "Service degradation detected.",
                        "Inspect failed units.",
                        "new",
                        "[1]",
                    ),
                ],
            )

            update = engine.record_incident_action(
                action_id="service.systemctl.restart",
                category="service",
                unit="nginx.service",
                request_id="req-contain-incident",
                operator_id="irving",
                dry_run=False,
                success=True,
                outcome="Action 'service.systemctl.restart' executed successfully.",
                now=now,
            )
            incidents = engine.list_incidents(status="active", now=now)

            self.assertEqual(update["status"], "contained")
            self.assertEqual(len(incidents), 1)
            self.assertEqual(incidents[0]["status"], "contained")
            self.assertEqual(incidents[0]["last_action_id"], "service.systemctl.restart")

    def test_prune_data_removes_expired_history_but_preserves_active_incident_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            engine = SecurityWatchEngine(db_path=db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            old = now - dt.timedelta(days=120)
            active_old = now - dt.timedelta(days=95)
            self._seed_events(
                db_path,
                [
                    (old, "security", "sshd", "Failed password for root from 10.0.0.2"),
                    (now - dt.timedelta(days=1), "service", "systemd", "nginx.service entered failed state"),
                ],
            )
            self._seed_alerts(
                db_path,
                [
                    (
                        old,
                        "high",
                        "security",
                        "security.auth.anomaly",
                        "Authentication anomalies detected.",
                        "Investigate auth failures.",
                        "acknowledged",
                        "[]",
                    ),
                    (
                        active_old,
                        "high",
                        "service",
                        "service.failure.cluster",
                        "Service degradation detected.",
                        "Inspect failed units.",
                        "new",
                        "[]",
                    ),
                ],
            )
            self._seed_incidents(
                db_path,
                incidents=[
                    (
                        "inc-active",
                        "service.failure.cluster",
                        "service",
                        "high",
                        "open",
                        active_old,
                        active_old,
                        active_old,
                        "",
                        "",
                        "",
                        "Service degradation detected.",
                        "[2]",
                        "[]",
                        '["nginx.service"]',
                    ),
                    (
                        "inc-resolved",
                        "security.auth.anomaly",
                        "security",
                        "high",
                        "resolved",
                        old,
                        old,
                        old,
                        "security.alerts.ack",
                        "acknowledged",
                        "Resolved previously.",
                        "Authentication anomalies detected.",
                        "[1]",
                        "[]",
                        '["ssh.service"]',
                    ),
                ],
                activity=[
                    (
                        "inc-active",
                        active_old,
                        "",
                        "open",
                        "security.watch.open",
                        "security-watch",
                        "",
                        "opened",
                        "Service degradation detected.",
                    ),
                    (
                        "inc-resolved",
                        old,
                        "open",
                        "resolved",
                        "security.alerts.ack",
                        "irving",
                        "req-old",
                        "acknowledged",
                        "Resolved previously.",
                    ),
                ],
                silences=[
                    (
                        "security.auth.anomaly",
                        "obsolete",
                        old,
                        old,
                        "operator",
                    )
                ],
            )

            result = engine.prune_data(
                now=now,
                system_event_days=30,
                alert_days=30,
                incident_days=60,
                activity_days=60,
                silence_days=30,
            )

            self.assertEqual(result["schema_version"], 3)
            self.assertEqual(result["deleted"]["system_events"], 1)
            self.assertEqual(result["deleted"]["security_alerts"], 1)
            self.assertEqual(result["deleted"]["security_silences"], 1)
            self.assertEqual(result["deleted"]["incidents"], 1)
            self.assertGreaterEqual(result["deleted"]["incident_activity"], 1)
            self.assertEqual(result["preserved_active_incidents"], ["inc-active"])

            conn = sqlite3.connect(db_path)
            try:
                remaining_alerts = conn.execute(
                    "SELECT id, fingerprint, status FROM security_alerts ORDER BY id"
                ).fetchall()
                remaining_incidents = conn.execute(
                    "SELECT incident_id, status FROM incidents ORDER BY incident_id"
                ).fetchall()
                remaining_activity = conn.execute(
                    "SELECT incident_id FROM incident_activity ORDER BY incident_id"
                ).fetchall()
                remaining_silences = conn.execute(
                    "SELECT COUNT(*) FROM security_silences"
                ).fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(remaining_alerts, [(2, "service.failure.cluster", "new")])
            self.assertEqual(remaining_incidents, [("inc-active", "open")])
            self.assertEqual(remaining_activity, [("inc-active",)])
            self.assertEqual(remaining_silences, 0)

    def test_incident_ledger_persists_across_engine_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            SecurityWatchEngine(db_path=db_path)
            self._seed_events(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=15),
                        "service",
                        "systemd",
                        "nginx.service entered failed state",
                    ),
                ],
            )
            self._seed_alerts(
                db_path,
                [
                    (
                        now - dt.timedelta(minutes=10),
                        "high",
                        "service",
                        "service.failure.cluster",
                        "Service degradation detected.",
                        "Inspect failed units.",
                        "new",
                        "[1]",
                    ),
                ],
            )
            first = SecurityWatchEngine(db_path=db_path)
            incident_id = str(first.list_incidents(status="active", now=now)[0]["incident_id"])

            second = SecurityWatchEngine(db_path=db_path)
            detail = second.get_incident(incident_id, now=now)
            updated = second.update_incident_status(
                incident_id,
                status="resolved",
                operator_id="irving",
                request_id="req-restart-recover",
                now=now + dt.timedelta(minutes=5),
            )

            third = SecurityWatchEngine(db_path=db_path)
            resolved = third.list_incidents(status="resolved", now=now + dt.timedelta(minutes=5), sync=False)

            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["incident_id"], incident_id)
            self.assertEqual(updated["updated"], 1)
            self.assertEqual(len(resolved), 1)
            self.assertEqual(resolved[0]["incident_id"], incident_id)
            self.assertEqual(resolved[0]["status"], "resolved")

    @staticmethod
    def _seed_events(
        db_path: Path,
        rows: list[tuple[dt.datetime, str, str, str]],
    ) -> None:
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS system_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    monitor_id TEXT NOT NULL,
                    cursor TEXT,
                    ts_utc TEXT NOT NULL,
                    category TEXT NOT NULL,
                    source TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    invalidated_sources_json TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
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
                        ts.isoformat(),
                        category,
                        source,
                        summary,
                        "[]",
                        "{}",
                        ts.isoformat(),
                    )
                    for ts, category, source, summary in rows
                ],
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _seed_alerts(
        db_path: Path,
        rows: list[tuple[dt.datetime, str, str, str, str, str, str, str]],
    ) -> None:
        conn = sqlite3.connect(db_path)
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
                        ts.isoformat(),
                        severity,
                        category,
                        fingerprint,
                        summary,
                        recommendation,
                        "security-watch",
                        status,
                        event_ids_json,
                        "{}",
                    )
                    for ts, severity, category, fingerprint, summary, recommendation, status, event_ids_json in rows
                ],
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _seed_incidents(
        db_path: Path,
        *,
        incidents: list[tuple[str, str, str, str, str, dt.datetime, dt.datetime, dt.datetime, str, str, str, str, str, str, str]],
        activity: list[tuple[str, dt.datetime, str, str, str, str, str, str, str]],
        silences: list[tuple[str, str, dt.datetime, dt.datetime, str]],
    ) -> None:
        conn = sqlite3.connect(db_path)
        try:
            conn.executemany(
                """
                INSERT INTO incidents (
                    incident_id, fingerprint, category, severity, status,
                    opened_at_utc, updated_at_utc, last_seen_at_utc, last_action_id,
                    operator_decision, resolution_summary, latest_summary,
                    alert_ids_json, event_ids_json, correlated_units_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
                """,
                [
                    (
                        incident_id,
                        fingerprint,
                        category,
                        severity,
                        status,
                        opened_at.isoformat(),
                        updated_at.isoformat(),
                        last_seen_at.isoformat(),
                        last_action_id,
                        operator_decision,
                        resolution_summary,
                        latest_summary,
                        alert_ids_json,
                        event_ids_json,
                        correlated_units_json,
                    )
                    for (
                        incident_id,
                        fingerprint,
                        category,
                        severity,
                        status,
                        opened_at,
                        updated_at,
                        last_seen_at,
                        last_action_id,
                        operator_decision,
                        resolution_summary,
                        latest_summary,
                        alert_ids_json,
                        event_ids_json,
                        correlated_units_json,
                    ) in incidents
                ],
            )
            conn.executemany(
                """
                INSERT INTO incident_activity (
                    incident_id, ts_utc, status_from, status_to, action_id,
                    operator_id, request_id, operator_decision, resolution_summary, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
                """,
                [
                    (
                        incident_id,
                        ts.isoformat(),
                        status_from,
                        status_to,
                        action_id,
                        operator_id,
                        request_id,
                        operator_decision,
                        resolution_summary,
                    )
                    for (
                        incident_id,
                        ts,
                        status_from,
                        status_to,
                        action_id,
                        operator_id,
                        request_id,
                        operator_decision,
                        resolution_summary,
                    ) in activity
                ],
            )
            conn.executemany(
                """
                INSERT INTO security_silences (
                    fingerprint, reason, created_at, silence_until_utc, source
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        fingerprint,
                        reason,
                        created_at.isoformat(),
                        silence_until_utc.isoformat(),
                        source,
                    )
                    for fingerprint, reason, created_at, silence_until_utc, source in silences
                ],
            )
            conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
