#!/usr/bin/env python3
"""Tests for the interactive interface command parsing/state updates."""

from __future__ import annotations

import unittest

from mastercontrol.interface.mc_ai import InterfaceState, apply_directive, parse_directive


class MCAIInterfaceTests(unittest.TestCase):
    def test_parse_directive(self) -> None:
        parsed = parse_directive("/risk high")
        self.assertEqual(parsed, ("risk", ["high"]))

    def test_parse_non_directive(self) -> None:
        parsed = parse_directive("restart nginx service")
        self.assertIsNone(parsed)

    def test_apply_mode_updates_state(self) -> None:
        state = InterfaceState()
        message, should_exit = apply_directive(state, "mode", ["dry-run"])
        self.assertIn("dry-run", message)
        self.assertFalse(should_exit)
        self.assertEqual(state.mode, "dry-run")

    def test_apply_risk_rejects_invalid_value(self) -> None:
        state = InterfaceState()
        message, should_exit = apply_directive(state, "risk", ["invalid"])
        self.assertIn("Uso", message)
        self.assertFalse(should_exit)
        self.assertEqual(state.risk_level, "medium")

    def test_apply_quit(self) -> None:
        state = InterfaceState()
        _message, should_exit = apply_directive(state, "quit", [])
        self.assertTrue(should_exit)


if __name__ == "__main__":
    unittest.main()

