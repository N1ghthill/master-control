from __future__ import annotations

from dataclasses import dataclass, field

PLANNING_DECISION_STATES = ("needs_tools", "complete", "blocked")


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

    def __post_init__(self) -> None:
        if self.state not in PLANNING_DECISION_STATES:
            raise ValueError(f"Invalid planning decision state: {self.state}")
        if not self.reason.strip():
            raise ValueError("Planning decision reason cannot be empty.")

    def as_dict(self) -> dict[str, str]:
        return {
            "state": self.state,
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
