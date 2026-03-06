#!/usr/bin/env python3
"""Tests for the interactive interface command parsing/state updates."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from mastercontrol.interface.mc_ai import (
    InterfaceState,
    build_parser,
    _resolve_ollama_bin,
    apply_directive,
    parse_directive,
)


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

    def test_apply_llm_toggle(self) -> None:
        state = InterfaceState()
        message, should_exit = apply_directive(state, "llm", ["off"])
        self.assertIn("desativado", message)
        self.assertFalse(should_exit)
        self.assertFalse(state.llm_enabled)

    def test_apply_model_updates_state(self) -> None:
        state = InterfaceState()
        message, should_exit = apply_directive(state, "model", ["qwen2.5:7b"])
        self.assertIn("qwen2.5:7b", message)
        self.assertFalse(should_exit)
        self.assertEqual(state.llm_model, "qwen2.5:7b")

    def test_interface_state_defaults(self) -> None:
        state = InterfaceState()
        self.assertEqual(state.llm_model, "qwen2.5:7b")
        self.assertEqual(state.llm_timeout_s, 25)

    def test_parser_defaults(self) -> None:
        args = build_parser().parse_args([])
        self.assertEqual(args.llm_model, "qwen2.5:7b")
        self.assertEqual(args.llm_timeout, 25)

    def test_resolve_ollama_bin_keeps_explicit_binary(self) -> None:
        resolved = _resolve_ollama_bin("/usr/bin/ollama")
        self.assertEqual(resolved, "/usr/bin/ollama")

    def test_resolve_ollama_bin_uses_local_when_available(self) -> None:
        local = Path("/bin/sh")
        with (
            patch("mastercontrol.interface.mc_ai.LOCAL_OLLAMA_BIN", local),
            patch.dict(os.environ, {}, clear=True),
        ):
            resolved = _resolve_ollama_bin("ollama")
            self.assertEqual(resolved, str(local))
            self.assertEqual(os.environ.get("OLLAMA_HOST"), "127.0.0.1:11435")


if __name__ == "__main__":
    unittest.main()
