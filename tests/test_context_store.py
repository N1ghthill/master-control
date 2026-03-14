#!/usr/bin/env python3
"""Tests for persistent context storage."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from mastercontrol.context import SQLiteContextStore
from mastercontrol.contracts import ContextSnapshot


class SQLiteContextStoreTests(unittest.TestCase):
    def test_snapshot_persists_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            store = SQLiteContextStore(db_path)
            snapshot = ContextSnapshot(
                source="host.system",
                tier="warm",
                collected_at_utc="2026-03-14T12:00:00+00:00",
                ttl_s=120,
                payload={"cpu_count": 8, "mem_total_mib": 32000.0},
                summary="cpu=8",
            )

            store.put(snapshot)
            reloaded = SQLiteContextStore(db_path).get("host.system")

        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.payload["cpu_count"], 8)
        self.assertEqual(reloaded.summary, "cpu=8")

    def test_snapshots_by_source_filters_stale_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            store = SQLiteContextStore(db_path)
            store.put(
                ContextSnapshot(
                    source="network.summary",
                    tier="warm",
                    collected_at_utc="2026-03-14T11:59:45+00:00",
                    ttl_s=30,
                    payload={"default_route": "default via 1.1.1.1 dev eth0"},
                    summary="fresh route",
                )
            )
            store.put(
                ContextSnapshot(
                    source="services.summary",
                    tier="warm",
                    collected_at_utc="2026-03-14T11:40:00+00:00",
                    ttl_s=30,
                    payload={"system_state": "degraded", "failed_count": 2},
                    summary="stale services",
                )
            )

            selected = store.snapshots_by_source(
                ["network.summary", "services.summary"],
                now=dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc),
            )

        self.assertIn("network.summary", selected)
        self.assertNotIn("services.summary", selected)

    def test_invalidate_sources_removes_matching_snapshots(self) -> None:
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
                    payload={"warning_event_count": 1},
                    summary="journal",
                )
            )

            removed = store.invalidate_sources(["services.summary"])
            reloaded = SQLiteContextStore(db_path)

            self.assertEqual(removed, 1)
            self.assertIsNone(reloaded.get("services.summary"))
            self.assertIsNotNone(reloaded.get("journal.alerts"))


if __name__ == "__main__":
    unittest.main()
