#!/usr/bin/env python3
"""Tests for the interactive interface command parsing/state updates."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from mastercontrol.interface.mc_ai import (
    InterfaceState,
    _guardrailed_chat_reply,
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

    def test_guardrailed_chat_reply_for_identity_question(self) -> None:
        out = _guardrailed_chat_reply(
            "quem e voce?",
            "sou um assistente virtual criado pela alibaba cloud",
            profile_name="MasterControl",
            profile_creator="Irving",
            profile_role="Linux Debian Orchestrator",
            context={},
        )
        self.assertIn("Sou o MasterControl", out)
        self.assertIn("criado por Irving", out)

    def test_guardrailed_chat_reply_for_location_question(self) -> None:
        out = _guardrailed_chat_reply(
            "onde voce esta agora?",
            "Estou no Alibaba Cloud",
            profile_name="MasterControl",
            profile_creator="Irving",
            profile_role="Linux Debian Orchestrator",
            context={
                "hostname": "rainbow",
                "os_pretty": "Debian GNU/Linux",
                "user": "irving",
                "cwd": "/home/irving/ruas/repos/master-control",
                "timestamp_local": "2026-03-06T03:00:00-03:00",
            },
        )
        self.assertIn("host local 'rainbow'", out)
        self.assertIn("Debian GNU/Linux", out)
        self.assertIn("cwd '/home/irving/ruas/repos/master-control'", out)

    def test_guardrailed_chat_reply_replaces_external_identity_claim(self) -> None:
        out = _guardrailed_chat_reply(
            "me ajuda com uma duvida",
            "Eu sou um assistente virtual da Alibaba Cloud.",
            profile_name="MasterControl",
            profile_creator="Irving",
            profile_role="Linux Debian Orchestrator",
            context={},
        )
        self.assertIn("Sou o MasterControl", out)
        self.assertNotIn("Alibaba", out)

    def test_guardrailed_chat_reply_for_runtime_context_question(self) -> None:
        out = _guardrailed_chat_reply(
            "o que esta acontecendo agora no sistema?",
            "Posso ajudar com isso.",
            profile_name="MasterControl",
            profile_creator="Irving",
            profile_role="Linux Debian Orchestrator",
            context={
                "hostname": "rainbow",
                "os_pretty": "Debian GNU/Linux",
                "user": "irving",
                "cwd": "/home/irving/ruas/repos/master-control",
                "timestamp_local": "2026-03-06T03:10:00-03:00",
            },
        )
        self.assertIn("host local 'rainbow'", out)
        self.assertIn("hora_local", out)


if __name__ == "__main__":
    unittest.main()
