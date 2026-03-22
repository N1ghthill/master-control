from __future__ import annotations

from dataclasses import dataclass, field

PLANNING_DECISION_STATES = ("needs_tools", "complete", "blocked")
PLANNING_DECISION_KINDS_BY_STATE = {
    "needs_tools": ("inspection_request", "diagnostic_step", "refresh_required"),
    "complete": ("evidence_sufficient",),
    "blocked": (
        "unsupported_request",
        "missing_safe_tool",
        "awaiting_confirmation",
        "execution_failed",
    ),
}


@dataclass(frozen=True, slots=True)
class PlanStep:
    tool_name: str
    rationale: str
    arguments: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "tool_name": self.tool_name,
            "rationale": self.rationale,
            "arguments": dict(self.arguments),
        }


@dataclass(frozen=True, slots=True)
class PlanningDecision:
    state: str
    reason: str
    kind: str | None = None

    def __post_init__(self) -> None:
        if self.state not in PLANNING_DECISION_STATES:
            raise ValueError(f"Invalid planning decision state: {self.state}")
        if not self.reason.strip():
            raise ValueError("Planning decision reason cannot be empty.")
        allowed_kinds = PLANNING_DECISION_KINDS_BY_STATE[self.state]
        resolved_kind = self.kind or allowed_kinds[0]
        if resolved_kind not in allowed_kinds:
            raise ValueError(
                f"Invalid planning decision kind for state {self.state}: {resolved_kind}"
            )
        object.__setattr__(self, "kind", resolved_kind)

    def as_dict(self) -> dict[str, str]:
        return {
            "state": self.state,
            "kind": str(self.kind),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    intent: str
    steps: tuple[PlanStep, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "steps": [step.as_dict() for step in self.steps],
        }
