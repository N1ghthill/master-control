#!/usr/bin/env python3
"""Tests for path selection using persisted environment signals."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from mastercontrol.context import SQLiteContextStore
from mastercontrol.contracts import ContextSnapshot
from mastercontrol.core.path_selector import PathSelector


class PathSelectorContextTests(unittest.TestCase):
    def test_network_signal_promotes_fast_request_to_fast_with_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            store = SQLiteContextStore(db_path)
            store.put(
                ContextSnapshot(
                    source="network.summary",
                    tier="warm",
                    collected_at_utc="2026-03-14T12:00:00+00:00",
                    ttl_s=300,
                    payload={
                        "default_route": "",
                        "nameservers": [],
                        "interfaces": ["eth0"],
                        "route_status": 1,
                    },
                    summary="route missing",
                )
            )
            selector = PathSelector(db_path=db_path)

            decision = selector.decide(
                intent="mostre a rota default",
                risk_level="low",
                incident=False,
                intent_cluster="network.route.default",
                operator_id="irving",
                now=dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc),
            )

        self.assertEqual(decision.path, "fast_with_confirm")
        self.assertIn("network state", decision.reason)
        self.assertTrue(decision.context_signals)

    def test_combined_service_and_host_signals_promote_to_deep(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            store = SQLiteContextStore(db_path)
            now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)
            store.put(
                ContextSnapshot(
                    source="services.summary",
                    tier="warm",
                    collected_at_utc="2026-03-14T12:00:00+00:00",
                    ttl_s=300,
                    payload={
                        "system_state": "degraded",
                        "failed_units": ["nginx.service", "ssh.service"],
                        "failed_count": 2,
                    },
                    summary="services degraded",
                )
            )
            store.put(
                ContextSnapshot(
                    source="host.system",
                    tier="warm",
                    collected_at_utc="2026-03-14T12:00:00+00:00",
                    ttl_s=300,
                    payload={
                        "cpu_count": 8,
                        "loadavg_1m": 2.5,
                        "mem_total_mib": 16000.0,
                        "mem_available_mib": 600.0,
                    },
                    summary="low memory",
                )
            )
            selector = PathSelector(db_path=db_path)

            decision = selector.decide(
                intent="restart nginx.service",
                risk_level="low",
                incident=False,
                intent_cluster="service.restart",
                operator_id="irving",
                now=now,
            )

        self.assertEqual(decision.path, "deep")
        self.assertIn("service state", decision.reason)
        self.assertIn("host pressure", decision.reason)

    def test_general_assist_ignores_operational_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "mastercontrol.db"
            store = SQLiteContextStore(db_path)
            store.put(
                ContextSnapshot(
                    source="services.summary",
                    tier="warm",
                    collected_at_utc="2026-03-14T12:00:00+00:00",
                    ttl_s=300,
                    payload={"system_state": "degraded", "failed_count": 3},
                    summary="services degraded",
                )
            )
            selector = PathSelector(db_path=db_path)

            decision = selector.decide(
                intent="quem e voce",
                risk_level="low",
                incident=False,
                intent_cluster="general.assist",
                operator_id="irving",
                now=dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc),
            )

        self.assertEqual(decision.path, "fast")
        self.assertFalse(decision.context_signals)


if __name__ == "__main__":
    unittest.main()
