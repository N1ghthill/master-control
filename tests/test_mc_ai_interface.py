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
    _looks_like_date_question,
    _looks_like_explicit_operational_command,
    _looks_like_operational_request,
    _looks_like_system_config_question,
    _looks_like_year_remaining_question,
    _should_keep_raw_intent,
    build_directive_intent,
    build_parser,
    directive_usage,
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

    def test_build_directive_intent_for_incident_commands(self) -> None:
        self.assertEqual(build_directive_intent("incidents", []), "liste os incidentes status active")
        self.assertEqual(build_directive_intent("incidents", ["resolved"]), "liste os incidentes status resolved")
        self.assertEqual(build_directive_intent("incident-show", ["inc-123"]), "mostre o incidente inc-123")
        self.assertEqual(build_directive_intent("incident-resolve", ["inc-123"]), "resolva o incidente inc-123")
        self.assertEqual(build_directive_intent("incident-dismiss", ["inc-123"]), "descarte o incidente inc-123")

    def test_incident_directive_usage_is_reported_for_invalid_args(self) -> None:
        self.assertIsNone(build_directive_intent("incidents", ["invalid"]))
        self.assertEqual(directive_usage("incidents"), "Uso: /incidents [active|open|contained|resolved|dismissed|all]")
        self.assertEqual(directive_usage("incident-show"), "Uso: /incident-show <incident_id>")

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

    def test_guardrailed_chat_reply_for_date_question(self) -> None:
        out = _guardrailed_chat_reply(
            "Sabe que dia e hoje?",
            "Nao sei.",
            profile_name="MasterControl",
            profile_creator="Irving",
            profile_role="Linux Debian Orchestrator",
            context={},
        )
        self.assertIn("Hoje e", out)

    def test_guardrailed_chat_reply_for_year_remaining_question(self) -> None:
        out = _guardrailed_chat_reply(
            "quantos dias faltam para acabar o ano?",
            "Nao sei.",
            profile_name="MasterControl",
            profile_creator="Irving",
            profile_role="Linux Debian Orchestrator",
            context={},
        )
        self.assertIn("Restam", out)
        self.assertIn("dia(s)", out)

    def test_guardrailed_chat_reply_for_system_config_question(self) -> None:
        out = _guardrailed_chat_reply(
            "Me diz as configuracoes do meu computador",
            "Nao sei.",
            profile_name="MasterControl",
            profile_creator="Irving",
            profile_role="Linux Debian Orchestrator",
            context={
                "hostname": "rainbow",
                "os_pretty": "Debian GNU/Linux",
                "user": "irving",
                "cwd": "/home/irving/ruas/repos/master-control",
            },
        )
        self.assertIn("Host='rainbow'", out)
        self.assertIn("SO='Debian GNU/Linux'", out)

    def test_question_detectors_for_date_year_and_config(self) -> None:
        self.assertTrue(_looks_like_date_question("que dia e hoje?"))
        self.assertTrue(_looks_like_year_remaining_question("quantos dias faltam para acabar o ano?"))
        self.assertTrue(_looks_like_system_config_question("configuracoes do meu computador"))

    def test_looks_like_operational_request_positive(self) -> None:
        self.assertTrue(_looks_like_operational_request("mostre a rota default"))
        self.assertTrue(_looks_like_operational_request("mostre os alertas de seguranca"))

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

    def test_prepare_intent_handles_local_factual_questions_without_llm(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon = MagicMock()
            daemon.soul.profile = SimpleNamespace(
                name="MasterControl",
                creator="Irving",
                role="Linux Debian Orchestrator",
            )
            daemon.runtime_context_snapshot.return_value = {
                "hostname": "rainbow",
                "os_pretty": "Debian GNU/Linux",
                "user": "irving",
                "cwd": "/home/irving/ruas/repos/master-control",
                "timestamp_local": "2026-03-06T04:00:00-03:00",
            }
            daemon_cls.return_value = daemon
            interface = MasterControlInterface(InterfaceState())
            adapter = MagicMock()
            adapter.model = interface.state.llm_model
            adapter.interpret.side_effect = AssertionError("LLM should not be called")
            interface.adapter = adapter
            for question in (
                "Sabe que dia e hoje?",
                "Quantos dias faltam para acabar o ano?",
                "Me diz as configuracoes do meu computador",
            ):
                out = interface._prepare_intent(question, use_llm=True)
                self.assertIsNone(out)
            adapter.interpret.assert_not_called()

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

    def test_handle_intent_skips_confirmation_for_safe_autoexecuted_audit(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon = MagicMock()
            daemon.handle.return_value = {
                "request_id": "req-1",
                "message": "ok",
                "path": {"path": "fast", "source": "selector", "confidence": 0.9},
                "tone": {"intent_cluster": "security.audit", "intent_source": "heuristic"},
                "mapped_action": {
                    "action_id": "security.audit.recent_events",
                    "action_risk": "low",
                    "requires_mutation": False,
                },
                "execution": {
                    "outcome": "Local security audit summary: security=1.",
                    "executed": True,
                },
            }
            daemon_cls.return_value = daemon
            interface = MasterControlInterface(InterfaceState())
            interface._prepare_intent = MagicMock(return_value="faca uma auditoria de seguranca")
            interface._confirm_execution = MagicMock(side_effect=AssertionError("should not ask"))

            interface.handle_intent("faca uma auditoria de seguranca", use_llm=False)

            interface._confirm_execution.assert_not_called()

    def test_handle_intent_dry_run_mode_executes_in_single_pass(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon = MagicMock()
            daemon.handle.return_value = {
                "request_id": "req-dry",
                "message": "ok",
                "path": {"path": "fast_with_confirm", "source": "selector", "confidence": 0.82},
                "tone": {"intent_cluster": "service.restart", "intent_source": "heuristic"},
                "mapped_action": {
                    "action_id": "service.systemctl.restart",
                    "action_risk": "high",
                    "requires_mutation": True,
                },
                "execution": {
                    "outcome": "Dry-run validated for 'service.systemctl.restart'.",
                    "executed": True,
                    "blocked": False,
                },
            }
            daemon_cls.return_value = daemon
            interface = MasterControlInterface(InterfaceState(mode="dry-run"))
            interface._prepare_intent = MagicMock(return_value="restart unbound.service")

            interface.handle_intent("restart unbound.service", use_llm=False)

            self.assertEqual(daemon.handle.call_count, 1)
            req = daemon.handle.call_args.args[0]
            self.assertTrue(req.execute)
            self.assertTrue(req.dry_run)
            self.assertFalse(req.approve)
            self.assertFalse(req.allow_high_risk)

    def test_handle_intent_execute_mode_uses_single_pass_for_non_step_up(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon = MagicMock()
            daemon.handle.return_value = {
                "request_id": "req-exec",
                "message": "ok",
                "path": {"path": "fast_with_confirm", "source": "selector", "confidence": 0.86},
                "tone": {"intent_cluster": "package.install", "intent_source": "heuristic"},
                "mapped_action": {
                    "action_id": "package.apt.install",
                    "action_risk": "medium",
                    "requires_mutation": True,
                },
                "execution": {
                    "outcome": "Action executed successfully.",
                    "executed": True,
                    "blocked": False,
                },
            }
            daemon_cls.return_value = daemon
            interface = MasterControlInterface(InterfaceState(mode="execute"))
            interface._prepare_intent = MagicMock(return_value="apt install htop")
            interface._require_high_risk_confirmation = MagicMock(side_effect=AssertionError("should not ask"))

            interface.handle_intent("apt install htop", use_llm=False)

            self.assertEqual(daemon.handle.call_count, 1)
            req = daemon.handle.call_args.args[0]
            self.assertTrue(req.execute)
            self.assertFalse(req.dry_run)
            self.assertTrue(req.approve)
            self.assertFalse(req.allow_high_risk)
            interface._require_high_risk_confirmation.assert_not_called()

    def test_handle_intent_execute_mode_retries_only_after_step_up(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon = MagicMock()
            daemon.handle.side_effect = [
                {
                    "request_id": "req-step-up",
                    "message": "blocked",
                    "path": {"path": "deep", "source": "selector", "confidence": 0.91},
                    "tone": {"intent_cluster": "service.restart", "intent_source": "heuristic"},
                    "mapped_action": {
                        "action_id": "service.systemctl.restart",
                        "action_risk": "high",
                        "requires_mutation": True,
                    },
                    "execution": {
                        "outcome": "Blocked stepped-up action 'service.systemctl.restart'.",
                        "executed": False,
                        "blocked": True,
                        "command_error": "step_up_required",
                    },
                },
                {
                    "request_id": "req-step-up",
                    "message": "ok",
                    "path": {"path": "deep", "source": "selector", "confidence": 0.91},
                    "tone": {"intent_cluster": "service.restart", "intent_source": "heuristic"},
                    "mapped_action": {
                        "action_id": "service.systemctl.restart",
                        "action_risk": "high",
                        "requires_mutation": True,
                    },
                    "execution": {
                        "outcome": "Action executed successfully.",
                        "executed": True,
                        "blocked": False,
                    },
                },
            ]
            daemon_cls.return_value = daemon
            interface = MasterControlInterface(InterfaceState(mode="execute"))
            interface._prepare_intent = MagicMock(return_value="restart unbound.service")
            interface._require_high_risk_confirmation = MagicMock(return_value=True)

            interface.handle_intent("restart unbound.service", use_llm=False)

            self.assertEqual(daemon.handle.call_count, 2)
            first_req = daemon.handle.call_args_list[0].args[0]
            second_req = daemon.handle.call_args_list[1].args[0]
            self.assertTrue(first_req.execute)
            self.assertFalse(first_req.allow_high_risk)
            self.assertTrue(second_req.allow_high_risk)
            self.assertEqual(second_req.request_id, "req-step-up")
            interface._require_high_risk_confirmation.assert_called_once()

    def test_active_alert_status_line_caches_and_invalidates_after_run(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon = MagicMock()
            daemon.security_watch.active_alert_summary.side_effect = [
                {"summary": "alerts=2 status=elevated severity=high"},
                {"summary": "alerts=1 status=watch severity=medium"},
            ]
            daemon.security_watch.active_incident_summary.side_effect = [
                {"summary": "incidents=1 status=elevated severity=high [open=1]"},
                {"summary": "incidents=0 status=stable"},
            ]
            daemon.handle.return_value = {"message": "ok", "execution": {}, "mapped_action": None}
            daemon_cls.return_value = daemon
            interface = MasterControlInterface(InterfaceState())

            first = interface.active_alert_status_line()
            second = interface.active_alert_status_line()
            self.assertEqual(
                first,
                "alerts=2 status=elevated severity=high incidents=1 status=elevated severity=high [open=1]",
            )
            self.assertEqual(second, first)
            self.assertEqual(daemon.security_watch.active_alert_summary.call_count, 1)
            self.assertEqual(daemon.security_watch.active_incident_summary.call_count, 1)

            interface.run_intent("mostre os alertas", execute=False, dry_run=False)
            refreshed = interface.active_alert_status_line()

            self.assertEqual(refreshed, "alerts=1 status=watch severity=medium incidents=0 status=stable")
            self.assertEqual(daemon.security_watch.active_alert_summary.call_count, 2)
            self.assertEqual(daemon.security_watch.active_incident_summary.call_count, 2)

    def test_active_incident_snapshot_caches_and_invalidates_after_run(self) -> None:
        with patch("mastercontrol.interface.mc_ai.MasterControlD") as daemon_cls:
            daemon = MagicMock()
            daemon.security_watch.list_incidents.side_effect = [
                [
                    {
                        "incident_id": "inc-001",
                        "fingerprint": "service.failure.cluster",
                        "status": "open",
                    }
                ],
                [
                    {
                        "incident_id": "inc-002",
                        "fingerprint": "security.auth.anomaly",
                        "status": "contained",
                    }
                ],
            ]
            daemon.security_watch.get_incident.side_effect = [
                {"incident_id": "inc-001", "activity": []},
                {"incident_id": "inc-002", "activity": []},
            ]
            daemon.handle.return_value = {"message": "ok", "execution": {}, "mapped_action": None}
            daemon_cls.return_value = daemon
            interface = MasterControlInterface(InterfaceState())

            first = interface.active_incident_snapshot()
            second = interface.active_incident_snapshot()

            self.assertEqual(first["selected_incident_id"], "inc-001")
            self.assertEqual(second["selected_incident_id"], "inc-001")
            self.assertEqual(daemon.security_watch.list_incidents.call_count, 1)
            self.assertEqual(daemon.security_watch.get_incident.call_count, 1)

            interface.run_intent("mostre os incidentes", execute=False, dry_run=False)
            refreshed = interface.active_incident_snapshot()

            self.assertEqual(refreshed["selected_incident_id"], "inc-002")
            self.assertEqual(daemon.security_watch.list_incidents.call_count, 2)
            self.assertEqual(daemon.security_watch.get_incident.call_count, 2)


if __name__ == "__main__":
    unittest.main()
