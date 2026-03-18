from __future__ import annotations

import unittest

from master_control.policy.engine import PolicyEngine
from master_control.tools.base import RiskLevel, ToolSpec


class PolicyEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PolicyEngine()

    def test_read_only_does_not_require_confirmation(self) -> None:
        spec = ToolSpec(
            name="system_info",
            description="Inspect host metadata.",
            risk=RiskLevel.READ_ONLY,
        )

        decision = self.engine.evaluate(spec)

        self.assertTrue(decision.allowed)
        self.assertFalse(decision.needs_confirmation)

    def test_privileged_requires_confirmation(self) -> None:
        spec = ToolSpec(
            name="install_package",
            description="Install a package.",
            risk=RiskLevel.PRIVILEGED,
        )

        decision = self.engine.evaluate(spec)

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.needs_confirmation)


if __name__ == "__main__":
    unittest.main()
