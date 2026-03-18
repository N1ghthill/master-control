from __future__ import annotations

from dataclasses import dataclass

from master_control.tools.base import RiskLevel, ToolSpec


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    needs_confirmation: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "needs_confirmation": self.needs_confirmation,
            "reason": self.reason,
        }


class PolicyEngine:
    def evaluate(self, spec: ToolSpec) -> PolicyDecision:
        if spec.risk is RiskLevel.READ_ONLY:
            return PolicyDecision(
                allowed=True,
                needs_confirmation=False,
                reason="Read-only tool.",
            )

        if spec.risk is RiskLevel.MUTATING_SAFE:
            return PolicyDecision(
                allowed=True,
                needs_confirmation=True,
                reason="Mutating tool requires explicit confirmation.",
            )

        return PolicyDecision(
            allowed=True,
            needs_confirmation=True,
            reason="Privileged tool requires confirmation and preflight validation.",
        )

