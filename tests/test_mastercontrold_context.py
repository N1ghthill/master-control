#!/usr/bin/env python3
"""Tests for runtime context snapshot in MasterControlD planning."""

from __future__ import annotations

import unittest

from mastercontrol.core.mastercontrold import MasterControlD


class MasterControlDContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.daemon = MasterControlD()

    def test_runtime_context_snapshot_contains_concrete_fields(self) -> None:
        snapshot = self.daemon.runtime_context_snapshot("Irving")
        self.assertEqual(snapshot["operator"], "Irving")
        self.assertTrue(snapshot["hostname"])
        self.assertTrue(snapshot["os_pretty"])
        self.assertTrue(snapshot["user"])
        self.assertTrue(snapshot["cwd"])
        self.assertTrue(snapshot["timestamp_local"])

    def test_build_plan_includes_runtime_context_details(self) -> None:
        plan_bundle = self.daemon._build_plan(
            intent="onde voce esta",
            risk_level="low",
            path="fast",
            intent_cluster="general.assist",
            operator_name="Irving",
        )
        first_step = plan_bundle["steps"][0]
        self.assertIn("operator=Irving", first_step)
        self.assertIn("host=", first_step)
        self.assertIn("os=", first_step)
        self.assertIn("cwd=", first_step)
        self.assertIn("ts_local=", first_step)


if __name__ == "__main__":
    unittest.main()
