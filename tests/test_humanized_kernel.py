#!/usr/bin/env python3
"""Tests for adaptive communication in the SoulKernel."""

from __future__ import annotations

import unittest

from mastercontrol.core.humanized_kernel import SoulKernel, load_profile


class SoulKernelAdaptiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kernel = SoulKernel(load_profile())

    def test_communication_plan_uses_tone_and_profile_signals(self) -> None:
        payload = {
            "operator_name": "Irving",
            "risk_level": "medium",
            "incident": False,
            "intent_understood": "restart unbound.service",
            "planned_actions": ["Inspect service health.", "Prepare restart through allowlisted path."],
            "risk_assessment": "risk=high, path=fast_with_confirm",
            "outcome": "Execution pending operator confirmation.",
            "rollback_or_next_step": "Confirm execution or keep analysis only.",
            "tone": "urgent",
            "tone_confidence": 0.92,
            "frustration_score": 0.71,
            "intent_cluster": "service.restart",
            "intent_confidence": 0.58,
            "intent_source": "history",
            "operator_profile": {
                "path_preference": "deep_when_uncertain",
                "tone_sensitivity": 0.82,
                "common_intents": ["service.restart"],
                "error_prone_commands": ["service.restart"],
            },
        }

        plan = self.kernel.communication_plan(payload)

        self.assertEqual(plan["style"], "explicit")
        self.assertTrue(any("Detected urgency/friction" in note for note in plan["adaptation_notes"]))
        self.assertTrue(any("Learned operator preference" in note for note in plan["adaptation_notes"]))
        self.assertTrue(any("Recent history shows friction" in note for note in plan["adaptation_notes"]))
        self.assertTrue(any("Intent confidence is limited" in note for note in plan["adaptation_notes"]))

    def test_compose_and_reflect_surface_adaptive_guidance(self) -> None:
        payload = {
            "operator_name": "Irving",
            "risk_level": "medium",
            "incident": False,
            "intent_understood": "remove nginx package",
            "planned_actions": ["Resolve package impact.", "Prepare package mutation through allowlisted apt action."],
            "risk_assessment": "risk=high, path=fast_with_confirm",
            "outcome": "Execution failed after validation.",
            "rollback_or_next_step": "Escalate to deeper diagnostic before retry.",
            "tone": "urgent",
            "tone_confidence": 0.88,
            "frustration_score": 0.81,
            "intent_cluster": "package.remove",
            "intent_confidence": 0.61,
            "intent_source": "heuristic",
            "operator_profile": {
                "path_preference": "confirm_heavy",
                "tone_sensitivity": 0.90,
                "common_intents": ["package.remove"],
                "error_prone_commands": ["package.remove"],
            },
        }

        communication = self.kernel.communication_plan(payload)
        message = self.kernel.compose_message(payload, communication_plan=communication)
        reflection = self.kernel.reflect(
            {
                "risk_level": "high",
                "path_used": "fast_with_confirm",
                "success": False,
                "policy_compliant": True,
                "confidence": 0.62,
                "incident": False,
                "tone": "urgent",
                "frustration_score": 0.81,
                "intent_cluster": "package.remove",
                "operator_profile": payload["operator_profile"],
            }
        )

        self.assertEqual(communication["style"], "calm_supportive")
        self.assertIn("How I'm adapting:", message)
        self.assertIn("keep confirmation visible before mutation", message)
        self.assertTrue(
            any("deeper verification" in suggestion for suggestion in reflection["suggestions"])
        )
        self.assertTrue(
            any("next safe step visible earlier" in suggestion for suggestion in reflection["suggestions"])
        )


if __name__ == "__main__":
    unittest.main()
