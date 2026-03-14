#!/usr/bin/env python3
"""Tests for smoke-runner helpers."""

from __future__ import annotations

import unittest

from mastercontrol.interface.flow_smoke import _extract_request_ids, _normalize_output, _scenario_catalog


class FlowSmokeTests(unittest.TestCase):
    def test_extract_request_ids_preserves_order(self) -> None:
        output = (
            "[request_id] req-1\n"
            "...\n"
            "[request_id] req-1\n"
            "[request_id] req-2\n"
        )

        self.assertEqual(_extract_request_ids(output), ["req-1", "req-1", "req-2"])

    def test_normalize_output_converts_crlf(self) -> None:
        self.assertEqual(_normalize_output("a\r\nb\rc"), "a\nb\nc")

    def test_scenario_catalog_exposes_expected_real_flow_checks(self) -> None:
        catalog = _scenario_catalog()

        self.assertIn("plan-route-once", catalog)
        self.assertIn("confirm-route-execute", catalog)
        self.assertIn("execute-step-up-cancel", catalog)
        self.assertTrue(catalog["confirm-route-execute"].require_reused_request_id)
        self.assertTrue(catalog["execute-step-up-cancel"].interactive_steps)


if __name__ == "__main__":
    unittest.main()
