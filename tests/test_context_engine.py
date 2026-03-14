#!/usr/bin/env python3
"""Tests for incremental context collection."""

from __future__ import annotations

import datetime as dt
import unittest

from mastercontrol.context import CollectorSpec, ContextEngine, StaticContextCollector


class ContextEngineTests(unittest.TestCase):
    def test_required_tier_prefers_hot_for_simple_low_risk_request(self) -> None:
        tier = ContextEngine.required_tier(
            risk_level="low",
            requires_mutation=False,
            diagnostics=False,
            incident=False,
            ambiguity=False,
        )
        self.assertEqual(tier, "hot")

    def test_required_tier_escalates_to_deep_for_incident(self) -> None:
        tier = ContextEngine.required_tier(
            risk_level="medium",
            requires_mutation=False,
            diagnostics=False,
            incident=True,
            ambiguity=False,
        )
        self.assertEqual(tier, "deep")

    def test_ensure_context_collects_only_needed_tier(self) -> None:
        hot = StaticContextCollector(
            CollectorSpec("session", "hot", 120, "session state"),
            {"operator": "Irving"},
        )
        warm = StaticContextCollector(
            CollectorSpec("services", "warm", 120, "service state"),
            {"systemd": "ok"},
        )
        deep = StaticContextCollector(
            CollectorSpec("logs", "deep", 120, "log drilldown"),
            {"journal": "expanded"},
        )
        engine = ContextEngine([hot, warm, deep])

        snapshots = engine.ensure_context("warm")

        self.assertEqual([snapshot.source for snapshot in snapshots], ["session", "services"])
        self.assertIsNotNone(engine.store.get("session"))
        self.assertIsNotNone(engine.store.get("services"))
        self.assertIsNone(engine.store.get("logs"))

    def test_fresh_snapshot_is_reused(self) -> None:
        hot = StaticContextCollector(
            CollectorSpec("session", "hot", 300, "session state"),
            {"operator": "Irving"},
        )
        engine = ContextEngine([hot])
        now = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.timezone.utc)

        first = engine.ensure_context("hot", now=now)
        second = engine.ensure_context("hot", now=now + dt.timedelta(seconds=30))

        self.assertEqual(first[0].collected_at_utc, second[0].collected_at_utc)


if __name__ == "__main__":
    unittest.main()
