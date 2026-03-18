from __future__ import annotations

import re
from dataclasses import dataclass

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
SOURCE_KEY_TO_OBSERVATION_KEY = {
    "disk_pressure": "disk",
    "disk_pressure_refresh": "disk",
    "memory_pressure": "memory",
    "memory_pressure_refresh": "memory",
    "service_state": "service",
    "service_state_refresh": "service",
    "service_logs_follow_up": "logs",
    "failed_service_detected": "failed_services",
    "failed_services_refresh": "failed_services",
    "hot_process": "processes",
    "hot_process_refresh": "processes",
    "config_verification_available": "config",
    "config_backup_available": "config",
}


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


def observation_key_for_recommendation(source_key: str) -> str | None:
    return SOURCE_KEY_TO_OBSERVATION_KEY.get(source_key)


def sort_recommendations(recommendations: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(recommendations, key=_recommendation_sort_key)


def _recommendation_sort_key(item: dict[str, object]) -> tuple[int, int, int, int]:
    status_rank = {
        RECOMMENDATION_STATUS_OPEN: 0,
        RECOMMENDATION_STATUS_ACCEPTED: 1,
        RECOMMENDATION_STATUS_DISMISSED: 2,
        RECOMMENDATION_STATUS_RESOLVED: 3,
    }.get(str(item.get("status", "")), 9)
    confidence_rank = {
        "fresh": 0,
        "unknown": 1,
        "stale": 2,
    }.get(str(item.get("confidence", "unknown")), 1)
    severity_rank = {
        "critical": 0,
        "warning": 1,
        "info": 2,
    }.get(str(item.get("severity", "")), 3)
    recommendation_id = item.get("id")
    recency_rank = -int(recommendation_id) if isinstance(recommendation_id, int) else 0
    return (status_rank, confidence_rank, severity_rank, recency_rank)
