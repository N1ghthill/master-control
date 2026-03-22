from __future__ import annotations

from dataclasses import dataclass

from master_control.core.observations import ObservationFreshness
from master_control.core.session_context import SessionContext, build_session_context
from master_control.core.session_insights import (
    SessionInsight,
    collect_session_insights_from_context,
)


@dataclass(frozen=True, slots=True)
class SessionAnalysisSnapshot:
    summary_text: str | None
    observation_freshness: tuple[ObservationFreshness, ...]
    session_context: SessionContext
    insights: tuple[SessionInsight, ...]


def build_session_analysis(
    summary_text: str | None,
    observation_freshness: tuple[ObservationFreshness, ...],
) -> SessionAnalysisSnapshot:
    session_context = build_session_context(summary_text, observation_freshness)
    insights = tuple(
        collect_session_insights_from_context(
            session_context,
            observation_freshness,
        )
    )
    return SessionAnalysisSnapshot(
        summary_text=summary_text,
        observation_freshness=observation_freshness,
        session_context=session_context,
        insights=insights,
    )
