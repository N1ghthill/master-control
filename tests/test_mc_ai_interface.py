#!/usr/bin/env python3
"""Tests for the interactive interface command parsing/state updates."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mastercontrol.interface.mc_ai import (
    InterfaceState,
    MasterControlInterface,
    OllamaAdapterError,
    _guardrailed_chat_reply,
    _looks_like_explicit_operational_command,
    _looks_like_operational_request,
    _should_keep_raw_intent,
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
        message, should_exit = apply_directive(state, "model", ["qwen3:4b-instruct-2507-q4_K_M"])
        self.assertIn("qwen3:4b-instruct-2507-q4_K_M", message)
        self.assertFalse(should_exit)
        self.assertEqual(state.llm_model, "qwen3:4b-instruct-2507-q4_K_M")

    def test_interface_state_defaults(self) -> None:
        state = InterfaceState()
        self.assertEqual(state.llm_model, "qwen3:4b-instruct-2507-q4_K_M")
        self.assertEqual(state.llm_timeout_s, 25)

    def test_parser_defaults(self) -> None:
        args = build_parser().parse_args([])
        self.assertEqual(args.llm_model, "qwen3:4b-instruct-2507-q4_K_M")
        self.assertEqual(args.llm_timeout, 25)
        self.assertFalse(args.no_llm_warmup)

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

    def test_looks_like_operational_request_positive(self) -> None:
        self.assertTrue(_looks_like_operational_request("mostre a rota default"))

    def test_looks_like_operational_request_explanatory_question(self) -> None:
        self.assertFalse(_looks_like_operational_request("o que e apt update?"))

    def test_looks_like_explicit_operational_command(self) -> None:
        self.assertTrue(_looks_like_explicit_operational_command("apt remove htop"))

    def test_should_keep_raw_intent_when_context_lost(self) -> None:
        self.assertTrue(
            _should_keep_raw_intent(
                "ping 1.1.1.1",
                "Executar comando ping no Linux",
            )
        )
        self.assertTrue(
            _should_keep_raw_intent(
                "limpar cache bogus do unbound",
                "Limpar cache de dados invalidos do unbound",
            )
        )

    def test_prepare_intent_bypasses_llm_for_explicit_command(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon_cls.return_value = MagicMock()
            interface = MasterControlInterface(InterfaceState())
            adapter = MagicMock()
            adapter.model = interface.state.llm_model
            adapter.interpret.side_effect = AssertionError("LLM should not be called")
            interface.adapter = adapter
            out = interface._prepare_intent("apt remove htop", use_llm=True)
            self.assertEqual(out, "apt remove htop")
            adapter.interpret.assert_not_called()

    def test_prepare_intent_forces_intent_when_llm_routes_operational_text_to_chat(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon_cls.return_value = MagicMock()
            interface = MasterControlInterface(InterfaceState())
            adapter = MagicMock()
            adapter.model = interface.state.llm_model
            adapter.interpret.return_value = SimpleNamespace(
                route="chat",
                intent="",
                chat_reply="Resposta qualquer",
                confidence=0.9,
                raw="{}",
            )
            interface.adapter = adapter
            out = interface._prepare_intent("mostre a rota default", use_llm=True)
            self.assertEqual(out, "mostre a rota default")

    def test_warmup_llm_runs_once_per_model(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon_cls.return_value = MagicMock()
            interface = MasterControlInterface(InterfaceState())
            adapter = MagicMock()
            adapter.model = interface.state.llm_model
            adapter.interpret.return_value = SimpleNamespace(
                route="chat",
                intent="",
                chat_reply="ok",
                confidence=1.0,
                raw="{}",
            )
            interface.adapter = adapter
            interface.warmup_llm()
            interface.warmup_llm()
            self.assertEqual(adapter.interpret.call_count, 1)

    def test_warmup_llm_handles_adapter_error_without_crashing(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon_cls.return_value = MagicMock()
            interface = MasterControlInterface(InterfaceState())
            adapter = MagicMock()
            adapter.model = interface.state.llm_model
            adapter.interpret.side_effect = OllamaAdapterError("timeout")
            interface.adapter = adapter
            interface.warmup_llm()
            interface.warmup_llm()
            self.assertEqual(adapter.interpret.call_count, 2)

    def test_warmup_llm_rewarms_after_model_change(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon_cls.return_value = MagicMock()
            interface = MasterControlInterface(InterfaceState())
            adapter_v1 = MagicMock()
            adapter_v1.model = interface.state.llm_model
            adapter_v1.interpret.return_value = SimpleNamespace(
                route="chat",
                intent="",
                chat_reply="ok",
                confidence=1.0,
                raw="{}",
            )
            interface.adapter = adapter_v1
            interface.warmup_llm()

            interface.state.llm_model = "qwen2.5:7b"
            adapter_v2 = MagicMock()
            adapter_v2.model = interface.state.llm_model
            adapter_v2.interpret.return_value = SimpleNamespace(
                route="chat",
                intent="",
                chat_reply="ok",
                confidence=1.0,
                raw="{}",
            )
            interface.adapter = adapter_v2
            interface.warmup_llm()

            self.assertEqual(adapter_v1.interpret.call_count, 1)
            self.assertEqual(adapter_v2.interpret.call_count, 1)


if __name__ == "__main__":
    unittest.main()
