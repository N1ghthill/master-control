from __future__ import annotations

from dataclasses import dataclass
import re

from master_control.agent.session_insights import SessionInsight


RECOMMENDATION_STATUS_OPEN = "open"
RECOMMENDATION_STATUS_ACCEPTED = "accepted"
RECOMMENDATION_STATUS_DISMISSED = "dismissed"
RECOMMENDATION_STATUS_RESOLVED = "resolved"
RECOMMENDATION_STATUSES = (
    RECOMMENDATION_STATUS_OPEN,
    RECOMMENDATION_STATUS_ACCEPTED,
    RECOMMENDATION_STATUS_DISMISSED,
    RECOMMENDATION_STATUS_RESOLVED,
)
ACTIVE_RECOMMENDATION_STATUSES = (
    RECOMMENDATION_STATUS_OPEN,
    RECOMMENDATION_STATUS_ACCEPTED,
)


@dataclass(frozen=True, slots=True)
class RecommendationAction:
    kind: str
    tool_name: str
    title: str | None = None
    arguments: dict[str, str] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "tool_name": self.tool_name,
            "title": self.title,
            "arguments": dict(self.arguments or {}),
        }


@dataclass(frozen=True, slots=True)
class RecommendationCandidate:
    dedupe_key: str
    source_key: str
    severity: str
    message: str
    action: RecommendationAction | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "dedupe_key": self.dedupe_key,
            "source_key": self.source_key,
            "severity": self.severity,
            "message": self.message,
        }
        if self.action is not None:
            payload["action"] = self.action.as_dict()
        return payload


def build_recommendation_candidates(
    insights: list[SessionInsight],
) -> list[RecommendationCandidate]:
    return [
        RecommendationCandidate(
            dedupe_key=_build_dedupe_key(insight),
            source_key=insight.key,
            severity=insight.severity,
            message=insight.message,
            action=_build_action(insight),
        )
        for insight in insights
    ]


def _build_dedupe_key(insight: SessionInsight) -> str:
    if not insight.target:
        return insight.key

    normalized_target = re.sub(r"\s+", " ", insight.target.strip()).lower()
    return f"{insight.key}:{normalized_target}"


def _build_action(insight: SessionInsight) -> RecommendationAction | None:
    if not insight.action_tool_name:
        return None

    return RecommendationAction(
        kind="run_tool",
        tool_name=insight.action_tool_name,
        title=insight.action_title,
        arguments=dict(insight.action_arguments),
    )
