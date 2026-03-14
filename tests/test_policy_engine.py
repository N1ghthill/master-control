#!/usr/bin/env python3
"""Tests for policy decisions."""

from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

from mastercontrol.contracts import ActionPlan, ContextSnapshot, OperatorIdentity, PlannedAction
from mastercontrol.policy import PolicyEngine, PolicyInput


class PolicyEngineTests(unittest.TestCase):
    @staticmethod
    def _missing_broker_socket() -> Path:
        return Path("/tmp/mastercontrol-tests-missing-broker.sock")

    def test_low_risk_non_privileged_plan_is_allowed(self) -> None:
        plan = ActionPlan(
            plan_id="plan-1",
            intent="check status",
            path="fast",
            risk_level="low",
            context_tier="hot",
            actions=(
                PlannedAction(
                    action_id="network.diagnose.route_default",
                    module_id="mod_network",
                    description="Show default route",
                    risk_level="low",
                ),
            ),
        )
        operator = OperatorIdentity("irving", "Irving", "irving", trust_level="T2")
        decision = PolicyEngine().evaluate(PolicyInput(plan=plan, operator=operator))

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.privilege_mode, "none")
        self.assertFalse(decision.requires_confirmation)

    def test_high_risk_privileged_plan_requires_step_up(self) -> None:
        plan = ActionPlan(
            plan_id="plan-2",
            intent="restart unbound",
            path="fast_with_confirm",
            risk_level="high",
            context_tier="warm",
            requires_mutation=True,
            actions=(
                PlannedAction(
                    action_id="service.systemctl.restart",
                    module_id="mod_services",
                    description="Restart unbound",
                    risk_level="high",
                    requires_privilege=True,
                ),
            ),
        )
        operator = OperatorIdentity("irving", "Irving", "irving", trust_level="T1")
        decision = PolicyEngine(broker_socket=self._missing_broker_socket()).evaluate(
            PolicyInput(plan=plan, operator=operator)
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.privilege_mode, "pkexec_bootstrap")
        self.assertTrue(decision.requires_confirmation)
        self.assertTrue(decision.requires_step_up)

    def test_environment_degradation_escalates_mutating_policy(self) -> None:
        plan = ActionPlan(
            plan_id="plan-3",
            intent="restart nginx",
            path="fast_with_confirm",
            risk_level="low",
            context_tier="warm",
            requires_mutation=True,
            actions=(
                PlannedAction(
                    action_id="service.systemctl.restart",
                    module_id="mod_services",
                    description="Restart nginx",
                    risk_level="low",
                    requires_privilege=True,
                ),
            ),
        )
        operator = OperatorIdentity("irving", "Irving", "irving", trust_level="T2")
        decision = PolicyEngine(broker_socket=self._missing_broker_socket()).evaluate(
            PolicyInput(
                plan=plan,
                operator=operator,
                context_snapshots=(
                    ContextSnapshot(
                        source="services.summary",
                        tier="warm",
                        collected_at_utc="2026-03-14T12:00:00+00:00",
                        ttl_s=300,
                        payload={
                            "system_state": "degraded",
                            "failed_units": ["nginx.service", "ssh.service"],
                            "failed_count": 2,
                        },
                    ),
                ),
            )
        )

        self.assertEqual(decision.risk_level, "high")
        self.assertTrue(decision.requires_confirmation)
        self.assertTrue(decision.requires_step_up)
        self.assertTrue(decision.context_signals)
        self.assertIn("Environment signals require stricter approval", decision.reason)

    def test_non_mutating_plan_does_not_escalate_from_context(self) -> None:
        plan = ActionPlan(
            plan_id="plan-4",
            intent="show route",
            path="fast",
            risk_level="low",
            context_tier="warm",
            requires_mutation=False,
            actions=(
                PlannedAction(
                    action_id="network.diagnose.route_default",
                    module_id="mod_network",
                    description="Show default route",
                    risk_level="low",
                    requires_privilege=False,
                ),
            ),
        )
        operator = OperatorIdentity("irving", "Irving", "irving", trust_level="T2")
        decision = PolicyEngine().evaluate(
            PolicyInput(
                plan=plan,
                operator=operator,
                context_snapshots=(
                    ContextSnapshot(
                        source="services.summary",
                        tier="warm",
                        collected_at_utc="2026-03-14T12:00:00+00:00",
                        ttl_s=300,
                        payload={"system_state": "degraded", "failed_count": 4},
                    ),
                ),
            )
        )

        self.assertEqual(decision.risk_level, "low")
        self.assertFalse(decision.context_signals)
        self.assertFalse(decision.requires_confirmation)

    def test_privileged_plan_prefers_broker_when_socket_is_available(self) -> None:
        plan = ActionPlan(
            plan_id="plan-5",
            intent="restart unbound",
            path="fast_with_confirm",
            risk_level="high",
            context_tier="warm",
            requires_mutation=True,
            actions=(
                PlannedAction(
                    action_id="service.systemctl.restart",
                    module_id="mod_services",
                    description="Restart unbound",
                    risk_level="high",
                    requires_privilege=True,
                ),
            ),
        )
        operator = OperatorIdentity("irving", "Irving", "irving", trust_level="T2")
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "mc-broker.sock"
            broker_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.addCleanup(broker_sock.close)
            broker_sock.bind(str(socket_path))
            try:
                decision = PolicyEngine(broker_socket=socket_path).evaluate(
                    PolicyInput(plan=plan, operator=operator)
                )
            finally:
                broker_sock.close()

        self.assertEqual(decision.privilege_mode, "broker")


if __name__ == "__main__":
    unittest.main()
