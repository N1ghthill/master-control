from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from master_control.agent.observations import (
    build_observation_envelopes,
    build_observation_freshness,
    format_observation_freshness,
)
from master_control.app import MasterControlApp
from master_control.config import Settings


class ObservationFreshnessTest(unittest.TestCase):
    def test_build_observation_envelopes_maps_memory_tool(self) -> None:
        envelopes = build_observation_envelopes(
            "memory_usage",
            {},
            {
                "memory_used_percent": 42.0,
                "swap_used_percent": 0.0,
            },
        )

        self.assertEqual(len(envelopes), 1)
        self.assertEqual(envelopes[0].key, "memory")
        self.assertEqual(envelopes[0].source, "memory_usage")
        self.assertEqual(envelopes[0].ttl_seconds, 300)

    def test_build_observation_freshness_marks_expired_rows_stale(self) -> None:
        observed_at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        expires_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")

        entries = build_observation_freshness(
            (
                {
                    "source": "memory_usage",
                    "key": "memory",
                    "value": {"memory_used_percent": 91.0},
                    "observed_at": observed_at,
                    "expires_at": expires_at,
                },
            )
        )

        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].stale)
        self.assertEqual(entries[0].ttl_seconds, 300)
        self.assertGreaterEqual(entries[0].age_seconds or 0, 600)

    def test_format_observation_freshness_renders_status_lines(self) -> None:
        observed_at = (datetime.now(UTC) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
        expires_at = (datetime.now(UTC) + timedelta(minutes=4)).isoformat().replace("+00:00", "Z")
        entries = build_observation_freshness(
            (
                {
                    "source": "service_status",
                    "key": "service",
                    "value": {"service": "nginx", "scope": "system"},
                    "observed_at": observed_at,
                    "expires_at": expires_at,
                },
            )
        )

        rendered = format_observation_freshness(entries)

        self.assertIsInstance(rendered, str)
        assert rendered is not None
        self.assertIn("service", rendered)
        self.assertIn("fresh", rendered)
        self.assertIn("nginx", rendered)

    def test_chat_reuses_fresh_diagnostic_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    [
                        "memory: memory 42.0% used, swap 0.0% used",
                        "processes: nginx(5.0%), sshd(1.0%)",
                        "service: nginx: active=active, sub=running",
                    ]
                ),
            )
            now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            app.store.record_observation(
                session_id,
                "memory_usage",
                "memory",
                {"memory_used_percent": 42.0, "swap_used_percent": 0.0},
                observed_at=now,
                ttl_seconds=300,
            )
            app.store.record_observation(
                session_id,
                "top_processes",
                "processes",
                {"processes": [{"command": "nginx", "cpu_percent": 5.0}]},
                observed_at=now,
                ttl_seconds=120,
            )
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {
                    "service": "nginx",
                    "scope": "system",
                    "activestate": "active",
                    "substate": "running",
                },
                observed_at=now,
                ttl_seconds=180,
            )

            payload = app.chat("o host esta lento", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertIn("Resumo do diagnóstico", payload["message"])

    def test_chat_refreshes_stale_diagnostic_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.upsert_session_summary(
                session_id,
                "\n".join(
                    [
                        "memory: memory 42.0% used, swap 0.0% used",
                        "processes: nginx(5.0%), sshd(1.0%)",
                        "service: nginx: active=active, sub=running",
                    ]
                ),
            )
            old_time = (
                (datetime.now(UTC) - timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
            )
            app.store.record_observation(
                session_id,
                "memory_usage",
                "memory",
                {"memory_used_percent": 42.0, "swap_used_percent": 0.0},
                observed_at=old_time,
                ttl_seconds=300,
            )
            app.store.record_observation(
                session_id,
                "top_processes",
                "processes",
                {"processes": [{"command": "nginx", "cpu_percent": 5.0}]},
                observed_at=old_time,
                ttl_seconds=120,
            )
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {
                    "service": "nginx",
                    "scope": "system",
                    "activestate": "active",
                    "substate": "running",
                },
                observed_at=old_time,
                ttl_seconds=180,
            )

            payload = app.chat("o host esta lento", session_id=session_id)

            self.assertGreaterEqual(len(payload["executions"]), 1)
            self.assertEqual(payload["executions"][0]["tool"], "memory_usage")
            self.assertTrue(
                any(
                    item["key"] == "memory" and not item["stale"]
                    for item in payload["observation_freshness"]
                )
            )

    def test_chat_can_complete_diagnostic_from_fresh_observations_without_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            app.store.record_observation(
                session_id,
                "memory_usage",
                "memory",
                {"memory_used_percent": 42.0, "swap_used_percent": 0.0},
                observed_at=now,
                ttl_seconds=300,
            )
            app.store.record_observation(
                session_id,
                "top_processes",
                "processes",
                {"processes": [{"command": "nginx", "cpu_percent": 5.0}]},
                observed_at=now,
                ttl_seconds=120,
            )

            payload = app.chat("o host esta lento", session_id=session_id)

            self.assertIsNone(payload["plan"])
            self.assertIn("Resumo do diagnóstico", payload["message"])
            self.assertIn("memória:", payload["message"])
            self.assertIn("processos:", payload["message"])


if __name__ == "__main__":
    unittest.main()
