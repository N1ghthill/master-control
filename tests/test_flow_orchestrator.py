#!/usr/bin/env python3
"""Tests for shared interactive flow orchestration."""

from __future__ import annotations

import unittest

from mastercontrol.interface.flow_orchestrator import FlowOrchestrator


class FlowOrchestratorTests(unittest.TestCase):
    def test_confirm_mode_returns_preview_and_pending_choice(self) -> None:
        calls: list[dict[str, object]] = []

        def run_intent(intent: str, execute: bool, dry_run: bool, **kwargs):  # type: ignore[no-untyped-def]
            calls.append({"intent": intent, "execute": execute, "dry_run": dry_run, **kwargs})
            return {
                "request_id": "req-preview",
                "mapped_action": {
                    "action_id": "service.systemctl.restart",
                    "action_risk": "medium",
                    "requires_mutation": True,
                },
                "execution": {"executed": False, "blocked": False, "outcome": "preview"},
                "message": "preview",
                "path": {"path": "fast_with_confirm", "source": "selector", "confidence": 0.8},
                "tone": {"intent_cluster": "service.restart", "intent_source": "heuristic"},
            }

        flow = FlowOrchestrator(run_intent, lambda mapped: str((mapped or {}).get("action_risk")) in {"high", "critical"})
        outcome = flow.begin("restart unbound.service", mode="confirm")

        self.assertEqual(len(outcome.results), 1)
        self.assertIsNotNone(outcome.pending_choice)
        assert outcome.pending_choice is not None
        self.assertEqual(outcome.pending_choice.request_id, "req-preview")
        self.assertFalse(calls[0]["execute"])

    def test_execute_mode_only_requests_step_up_after_block(self) -> None:
        calls: list[dict[str, object]] = []

        def run_intent(intent: str, execute: bool, dry_run: bool, **kwargs):  # type: ignore[no-untyped-def]
            calls.append({"intent": intent, "execute": execute, "dry_run": dry_run, **kwargs})
            return {
                "request_id": "req-step-up",
                "mapped_action": {
                    "action_id": "service.systemctl.restart",
                    "action_risk": "high",
                    "requires_mutation": True,
                },
                "execution": {
                    "executed": False,
                    "blocked": True,
                    "command_error": "step_up_required",
                    "outcome": "blocked",
                },
                "message": "blocked",
                "path": {"path": "deep", "source": "selector", "confidence": 0.9},
                "tone": {"intent_cluster": "service.restart", "intent_source": "heuristic"},
            }

        flow = FlowOrchestrator(run_intent, lambda mapped: str((mapped or {}).get("action_risk")) in {"high", "critical"})
        outcome = flow.begin("restart unbound.service", mode="execute")

        self.assertEqual(len(outcome.results), 1)
        self.assertIsNone(outcome.pending_choice)
        self.assertIsNotNone(outcome.pending_high_risk)
        assert outcome.pending_high_risk is not None
        self.assertEqual(outcome.pending_high_risk.request_id, "req-step-up")
        self.assertTrue(calls[0]["execute"])
        self.assertTrue(calls[0]["approve"])
        self.assertFalse(calls[0]["allow_high_risk"])

    def test_confirm_high_risk_reuses_request_id(self) -> None:
        calls: list[dict[str, object]] = []

        def run_intent(intent: str, execute: bool, dry_run: bool, **kwargs):  # type: ignore[no-untyped-def]
            calls.append({"intent": intent, "execute": execute, "dry_run": dry_run, **kwargs})
            return {
                "request_id": str(kwargs.get("request_id", "") or "req-high"),
                "mapped_action": {
                    "action_id": "service.systemctl.restart",
                    "action_risk": "high",
                    "requires_mutation": True,
                },
                "execution": {"executed": True, "blocked": False, "outcome": "ok"},
                "message": "ok",
                "path": {"path": "deep", "source": "selector", "confidence": 0.9},
                "tone": {"intent_cluster": "service.restart", "intent_source": "heuristic"},
            }

        flow = FlowOrchestrator(run_intent, lambda mapped: str((mapped or {}).get("action_risk")) in {"high", "critical"})
        preview = flow.begin("restart unbound.service", mode="confirm")
        assert preview.pending_choice is not None
        confirm = flow.choose(preview.pending_choice, choice="e")
        assert confirm.pending_high_risk is not None

        outcome = flow.confirm_high_risk(confirm.pending_high_risk, confirmed=True)

        self.assertEqual(len(outcome.results), 1)
        self.assertEqual(calls[-1]["request_id"], "req-high")
        self.assertTrue(calls[-1]["allow_high_risk"])


if __name__ == "__main__":
    unittest.main()
