from __future__ import annotations

from dataclasses import dataclass, field


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
class ExecutionPlan:
    intent: str
    steps: tuple[PlanStep, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "steps": [step.as_dict() for step in self.steps],
        }
