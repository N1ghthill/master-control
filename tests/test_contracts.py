#!/usr/bin/env python3
"""Tests for shared contracts."""

from __future__ import annotations

import datetime as dt
import unittest

from mastercontrol.contracts import ContextSnapshot, IncidentRecord, normalize_incident_status, normalize_risk, tier_allows


class ContractsTests(unittest.TestCase):
    def test_normalize_risk_falls_back_to_medium(self) -> None:
        self.assertEqual(normalize_risk("unexpected"), "medium")

    def test_context_snapshot_detects_stale(self) -> None:
        snapshot = ContextSnapshot(
            source="session",
            tier="hot",
            collected_at_utc="2026-03-14T10:00:00+00:00",
            ttl_s=60,
            payload={"operator": "Irving"},
        )
        now = dt.datetime(2026, 3, 14, 10, 2, tzinfo=dt.timezone.utc)
        self.assertTrue(snapshot.is_stale(now=now))

    def test_tier_allows_lower_or_equal_tier(self) -> None:
        self.assertTrue(tier_allows("hot", "warm"))
        self.assertFalse(tier_allows("deep", "warm"))

    def test_incident_record_reports_active_status(self) -> None:
        incident = IncidentRecord(
            incident_id="inc-1",
            fingerprint="service.failure.cluster",
            category="service",
            severity="high",
            status="contained",
            opened_at_utc="2026-03-14T10:00:00+00:00",
            updated_at_utc="2026-03-14T10:05:00+00:00",
        )
        self.assertTrue(incident.is_active())
        self.assertEqual(normalize_incident_status("dismissed"), "dismissed")


if __name__ == "__main__":
    unittest.main()
