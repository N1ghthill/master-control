from __future__ import annotations

from collections.abc import Callable

from master_control.core.observations import ObservationFreshness, format_duration
from master_control.core.recommendation_sync import RecommendationSyncResult
from master_control.core.session_recommendations import (
    RECOMMENDATION_STATUS_ACCEPTED,
    RECOMMENDATION_STATUS_OPEN,
    observation_key_for_recommendation,
    sort_recommendations,
)


def build_recommendation_sync_result(
    sync_payload: dict[str, list[dict[str, object]]],
    observation_freshness: tuple[ObservationFreshness, ...],
    *,
    command_builder: Callable[[int], dict[str, str]] | None = None,
) -> RecommendationSyncResult:
    active = sort_recommendations(
        enrich_recommendations_with_operator_guidance(
            enrich_recommendations_with_freshness(
                list(sync_payload["active"]),
                observation_freshness,
            ),
            command_builder=command_builder,
        )
    )
    new = sort_recommendations(
        enrich_recommendations_with_operator_guidance(
            enrich_recommendations_with_freshness(
                list(sync_payload["new"]),
                observation_freshness,
            ),
            command_builder=command_builder,
        )
    )
    reopened = sort_recommendations(
        enrich_recommendations_with_operator_guidance(
            enrich_recommendations_with_freshness(
                list(sync_payload["reopened"]),
                observation_freshness,
            ),
            command_builder=command_builder,
        )
    )
    auto_resolved = sort_recommendations(
        enrich_recommendations_with_operator_guidance(
            enrich_recommendations_with_freshness(
                list(sync_payload["auto_resolved"]),
                observation_freshness,
            ),
            command_builder=command_builder,
        )
    )
    return RecommendationSyncResult(
        active=active,
        new=new,
        reopened=reopened,
        auto_resolved=auto_resolved,
    )


def enrich_recommendations_with_freshness(
    recommendations: list[dict[str, object]],
    observation_freshness: tuple[ObservationFreshness, ...],
) -> list[dict[str, object]]:
    freshness_by_key = {item.key: item for item in observation_freshness}
    enriched: list[dict[str, object]] = []
    for item in recommendations:
        source_key = item.get("source_key")
        observation_key = (
            observation_key_for_recommendation(source_key) if isinstance(source_key, str) else None
        )
        freshness = freshness_by_key.get(observation_key) if observation_key else None
        confidence = "unknown"
        signal_freshness: dict[str, object] | None = None
        if freshness is not None:
            confidence = "stale" if freshness.stale else "fresh"
            signal_freshness = {
                "observation_key": freshness.key,
                "status": confidence,
                "age_seconds": freshness.age_seconds,
                "ttl_seconds": freshness.ttl_seconds,
                "observed_at": freshness.observed_at,
                "expires_at": freshness.expires_at,
            }
        enriched.append(
            {
                **item,
                "confidence": confidence,
                "signal_freshness": signal_freshness,
            }
        )
    return enriched


def enrich_recommendations_with_operator_guidance(
    recommendations: list[dict[str, object]],
    *,
    command_builder: Callable[[int], dict[str, str]] | None = None,
) -> list[dict[str, object]]:
    return [
        _enrich_recommendation_with_operator_guidance(
            item,
            command_builder=command_builder,
        )
        for item in recommendations
    ]


def _enrich_recommendation_with_operator_guidance(
    item: dict[str, object],
    *,
    command_builder: Callable[[int], dict[str, str]] | None = None,
) -> dict[str, object]:
    target_summary = _extract_target_summary(item)
    evidence_summary = _build_evidence_summary(item, target_summary)
    action_summary = _build_action_summary(item)
    next_step = _build_next_step(item, command_builder)

    payload = dict(item)
    if target_summary:
        payload["target_summary"] = target_summary
    if evidence_summary:
        payload["evidence_summary"] = evidence_summary
    if action_summary:
        payload["action_summary"] = action_summary
    if next_step is not None:
        payload["next_step"] = next_step
    return payload


def _extract_target_summary(item: dict[str, object]) -> str | None:
    action = item.get("action")
    if isinstance(action, dict):
        arguments = action.get("arguments")
        if isinstance(arguments, dict):
            name = arguments.get("name")
            scope = arguments.get("scope")
            if isinstance(name, str) and name:
                if isinstance(scope, str) and scope:
                    return f"{name} ({scope})"
                return name
            path = arguments.get("path")
            if isinstance(path, str) and path:
                return path
            process_name = arguments.get("name")
            if isinstance(process_name, str) and process_name:
                return process_name
            pid = arguments.get("pid")
            if isinstance(pid, (int, str)):
                return f"pid={pid}"
    dedupe_key = item.get("dedupe_key")
    if isinstance(dedupe_key, str) and ":" in dedupe_key:
        return dedupe_key.split(":", maxsplit=1)[1]
    return None


def _build_evidence_summary(item: dict[str, object], target_summary: str | None) -> str | None:
    source_key = item.get("source_key")
    if not isinstance(source_key, str) or not source_key:
        return None

    signal = observation_key_for_recommendation(source_key) or source_key
    confidence = item.get("confidence")
    confidence_text = str(confidence) if isinstance(confidence, str) else "unknown"
    fragments = [f"sinal={signal}", f"status={confidence_text}"]
    if target_summary:
        fragments.append(f"alvo={target_summary}")

    freshness = item.get("signal_freshness")
    if isinstance(freshness, dict):
        age_seconds = freshness.get("age_seconds")
        if isinstance(age_seconds, int):
            fragments.append(f"idade={format_duration(age_seconds)}")
    return ", ".join(fragments)


def _build_action_summary(item: dict[str, object]) -> str | None:
    action = item.get("action")
    if not isinstance(action, dict):
        return None
    title = action.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    tool_name = action.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        return None
    arguments = action.get("arguments")
    if isinstance(arguments, dict) and arguments:
        rendered_arguments = " ".join(f"{key}={value}" for key, value in arguments.items())
        return f"{tool_name} {rendered_arguments}"
    return tool_name


def _build_next_step(
    item: dict[str, object],
    command_builder: Callable[[int], dict[str, str]] | None,
) -> dict[str, str] | None:
    if command_builder is None:
        return None
    recommendation_id = item.get("id")
    if not isinstance(recommendation_id, int):
        return None
    action = item.get("action")
    if not isinstance(action, dict):
        return None
    commands = command_builder(recommendation_id)
    status = item.get("status")
    if status == RECOMMENDATION_STATUS_OPEN:
        return {
            "phase": "accept",
            "summary": "Aceite a recomendação antes de executar qualquer ação.",
            "cli_command": commands["cli_accept_command"],
            "chat_command": commands["chat_accept_command"],
        }
    if status == RECOMMENDATION_STATUS_ACCEPTED:
        return {
            "phase": "confirm",
            "summary": "Execute a ação recomendada com confirmação explícita.",
            "cli_command": commands["cli_confirm_command"],
            "chat_command": commands["chat_confirm_command"],
        }
    return None
