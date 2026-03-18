from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable


OBSERVATION_TTLS_S = {
    "system_info": 3600,
    "disk_usage": 600,
    "memory_usage": 300,
    "top_processes": 120,
    "service_status": 180,
    "restart_service": 180,
    "reload_service": 180,
    "read_journal": 90,
    "read_config_file": 300,
    "write_config_file": 300,
    "restore_config_backup": 300,
}

TOOL_OBSERVATION_KEYS = {
    "system_info": "host",
    "memory_usage": "memory",
    "disk_usage": "disk",
    "top_processes": "processes",
    "service_status": "service",
    "restart_service": "service",
    "reload_service": "service",
    "read_journal": "logs",
    "read_config_file": "config",
    "write_config_file": "config",
    "restore_config_backup": "config",
}


@dataclass(frozen=True, slots=True)
class ObservationEnvelope:
    source: str
    key: str
    value: dict[str, object]
    ttl_seconds: int | None


@dataclass(frozen=True, slots=True)
class ObservationFreshness:
    key: str
    source: str
    value: dict[str, object]
    observed_at: str
    expires_at: str | None
    age_seconds: int | None
    ttl_seconds: int | None
    stale: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "source": self.source,
            "value": dict(self.value),
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "age_seconds": self.age_seconds,
            "ttl_seconds": self.ttl_seconds,
            "stale": self.stale,
        }


def build_observation_envelopes(
    tool_name: str,
    arguments: dict[str, object],
    result: dict[str, object],
) -> tuple[ObservationEnvelope, ...]:
    status = result.get("status")
    if isinstance(status, str) and status != "ok":
        return ()

    ttl_seconds = OBSERVATION_TTLS_S.get(tool_name)
    observation_key = observation_key_for_tool(tool_name)
    if observation_key:
        return (_make_envelope(tool_name, observation_key, result, ttl_seconds),)
    return ()


def build_observation_freshness(
    rows: Iterable[dict[str, object]],
    *,
    now: datetime | None = None,
) -> tuple[ObservationFreshness, ...]:
    reference_time = now or datetime.now(UTC)
    items: list[ObservationFreshness] = []
    for row in rows:
        key = row.get("key")
        source = row.get("source")
        observed_at = row.get("observed_at")
        if not isinstance(key, str) or not isinstance(source, str) or not isinstance(observed_at, str):
            continue

        value = row.get("value")
        if not isinstance(value, dict):
            continue

        observed_at_dt = _parse_timestamp(observed_at)
        expires_at = row.get("expires_at")
        expires_at_dt = _parse_timestamp(expires_at) if isinstance(expires_at, str) else None
        age_seconds = None
        if observed_at_dt is not None:
            age_seconds = max(0, int((reference_time - observed_at_dt).total_seconds()))

        ttl_seconds = None
        if observed_at_dt is not None and expires_at_dt is not None:
            ttl_seconds = max(0, int((expires_at_dt - observed_at_dt).total_seconds()))

        stale = False
        if expires_at_dt is not None and reference_time >= expires_at_dt:
            stale = True

        items.append(
            ObservationFreshness(
                key=key,
                source=source,
                value=value,
                observed_at=observed_at,
                expires_at=expires_at if isinstance(expires_at, str) else None,
                age_seconds=age_seconds,
                ttl_seconds=ttl_seconds,
                stale=stale,
            )
        )
    return tuple(items)


def format_observation_freshness(items: Iterable[ObservationFreshness]) -> str | None:
    lines: list[str] = []
    for item in items:
        status = "stale" if item.stale else "fresh"
        details = [status]
        if item.age_seconds is not None:
            details.append(f"age={_format_duration(item.age_seconds)}")
        if item.ttl_seconds is not None:
            details.append(f"ttl={_format_duration(item.ttl_seconds)}")
        target = _render_target(item)
        target_text = f" ({target})" if target else ""
        lines.append(f"- {item.key}{target_text}: {', '.join(details)}")
    if not lines:
        return None
    return "\n".join(lines)


def observation_key_for_tool(tool_name: str) -> str | None:
    return TOOL_OBSERVATION_KEYS.get(tool_name)


def compute_expires_at(
    *,
    observed_at: datetime | None = None,
    ttl_seconds: int | None,
) -> str | None:
    if ttl_seconds is None:
        return None
    base_time = observed_at or datetime.now(UTC)
    return _format_timestamp(base_time + timedelta(seconds=ttl_seconds))


def serialize_observation_value(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True)


def deserialize_observation_value(raw_value: str) -> dict[str, object]:
    parsed = json.loads(raw_value)
    if not isinstance(parsed, dict):
        raise ValueError("Observation value must be a JSON object.")
    return parsed


def _make_envelope(
    source: str,
    key: str,
    value: dict[str, object],
    ttl_seconds: int | None,
) -> ObservationEnvelope:
    return ObservationEnvelope(
        source=source,
        key=key,
        value=dict(value),
        ttl_seconds=ttl_seconds,
    )


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        if normalized.endswith("Z"):
            return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _format_duration(total_seconds: int) -> str:
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes, seconds = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _render_target(item: ObservationFreshness) -> str | None:
    if item.key == "disk":
        path = item.value.get("path")
        if isinstance(path, str) and path:
            return path
    if item.key == "service":
        service = item.value.get("service")
        scope = item.value.get("scope")
        if isinstance(service, str) and service:
            if isinstance(scope, str) and scope:
                return f"{service}, scope={scope}"
            return service
    if item.key == "logs":
        unit = item.value.get("unit")
        if isinstance(unit, str) and unit:
            return unit
    if item.key == "config":
        path = item.value.get("path")
        if isinstance(path, str) and path:
            return path
    return None
