#!/usr/bin/env python3
"""Tests for Ollama adapter parsing/fallback behavior."""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from mastercontrol.llm.ollama_adapter import OllamaAdapter, OllamaAdapterError


class OllamaAdapterTests(unittest.TestCase):
    @patch("mastercontrol.llm.ollama_adapter.subprocess.run")
    def test_interpret_intent_json(self, mock_run: object) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ollama"],
            returncode=0,
            stdout='{"route":"intent","intent":"reiniciar servico nginx","chat_reply":"","confidence":0.88}',
            stderr="",
        )
        adapter = OllamaAdapter(model="qwen2.5:7b")
        out = adapter.interpret("restart nginx", operator_name="irving")
        self.assertEqual(out.route, "intent")
        self.assertEqual(out.intent, "reiniciar servico nginx")
        self.assertAlmostEqual(out.confidence, 0.88, places=2)

    @patch("mastercontrol.llm.ollama_adapter.subprocess.run")
    def test_interpret_chat_json(self, mock_run: object) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ollama"],
            returncode=0,
            stdout='{"route":"chat","intent":"","chat_reply":"Estou monitorando o estado atual.","confidence":0.77}',
            stderr="",
        )
        adapter = OllamaAdapter(model="qwen2.5:7b")
        out = adapter.interpret("o que voce esta fazendo?", operator_name="irving")
        self.assertEqual(out.route, "chat")
        self.assertIn("monitorando", out.chat_reply)

    @patch("mastercontrol.llm.ollama_adapter.subprocess.run")
    def test_interpret_fallback_when_not_json(self, mock_run: object) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ollama"],
            returncode=0,
            stdout="texto livre sem json",
            stderr="",
        )
        adapter = OllamaAdapter(model="qwen2.5:7b")
        out = adapter.interpret("restart nginx", operator_name="irving")
        self.assertEqual(out.route, "intent")
        self.assertEqual(out.intent, "restart nginx")
        self.assertEqual(out.confidence, 0.0)

    @patch("mastercontrol.llm.ollama_adapter.subprocess.run")
    def test_raises_on_nonzero_exit(self, mock_run: object) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ollama"],
            returncode=1,
            stdout="",
            stderr="model not found",
        )
        adapter = OllamaAdapter(model="qwen2.5:7b")
        with self.assertRaises(OllamaAdapterError):
            adapter.interpret("restart nginx", operator_name="irving")

    @patch("mastercontrol.llm.ollama_adapter.subprocess.run")
    def test_retries_without_thinking_flags_when_unsupported(self, mock_run: object) -> None:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["ollama"],
                returncode=1,
                stdout="",
                stderr="unknown flag: --think",
            ),
            subprocess.CompletedProcess(
                args=["ollama"],
                returncode=0,
                stdout='{"route":"intent","intent":"reiniciar nginx","chat_reply":"","confidence":0.81}',
                stderr="",
            ),
        ]

        adapter = OllamaAdapter(model="qwen2.5:7b")
        out = adapter.interpret("restart nginx", operator_name="irving")
        self.assertEqual(out.route, "intent")
        self.assertEqual(out.intent, "reiniciar nginx")
        self.assertEqual(mock_run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
