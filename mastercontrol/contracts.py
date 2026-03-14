#!/usr/bin/env python3
"""Shared contracts for context, policy and privileged execution."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal


RiskLevel = Literal["low", "medium", "high", "critical"]
PathMode = Literal["fast", "fast_with_confirm", "deep"]
ContextTier = Literal["hot", "warm", "deep"]
PrivilegeMode = Literal["none", "pkexec_bootstrap", "broker"]
ApprovalScope = Literal["none", "single_action", "time_window"]
TrustLevel = Literal["T0", "T1", "T2", "T3"]
IncidentStatus = Literal["open", "contained", "resolved", "dismissed"]

VALID_RISK: set[str] = {"low", "medium", "high", "critical"}
VALID_PATH: set[str] = {"fast", "fast_with_confirm", "deep"}
VALID_CONTEXT_TIER: set[str] = {"hot", "warm", "deep"}
VALID_PRIVILEGE_MODE: set[str] = {"none", "pkexec_bootstrap", "broker"}
VALID_APPROVAL_SCOPE: set[str] = {"none", "single_action", "time_window"}
VALID_TRUST_LEVEL: set[str] = {"T0", "T1", "T2", "T3"}
VALID_INCIDENT_STATUS: set[str] = {"open", "contained", "resolved", "dismissed"}

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
CONTEXT_TIER_ORDER = {"hot": 0, "warm": 1, "deep": 2}


def utc_now() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat()


def parse_utc(ts: str) -> dt.datetime:
    value = dt.datetime.fromisoformat(ts)
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def normalize_risk(value: str) -> RiskLevel:
    risk = (value or "").strip().lower()
    return risk if risk in VALID_RISK else "medium"


def normalize_context_tier(value: str) -> ContextTier:
    tier = (value or "").strip().lower()
    return tier if tier in VALID_CONTEXT_TIER else "warm"


def normalize_incident_status(value: str) -> IncidentStatus:
    status = (value or "").strip().lower()
    return status if status in VALID_INCIDENT_STATUS else "open"


def tier_allows(candidate: str, required: str) -> bool:
    return CONTEXT_TIER_ORDER[normalize_context_tier(candidate)] <= CONTEXT_TIER_ORDER[normalize_context_tier(required)]


@dataclass(frozen=True)
class OperatorIdentity:
    operator_id: str
    display_name: str
    unix_user: str
    session_id: str = ""
    trust_level: TrustLevel = "T0"
    trust_score: float = 0.5
    groups: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextSnapshot:
    source: str
    tier: ContextTier
    collected_at_utc: str
    ttl_s: int
    payload: dict[str, Any]
    summary: str = ""
    version: int = 1

    def expires_at_utc(self) -> str:
        base = parse_utc(self.collected_at_utc)
        return (base + dt.timedelta(seconds=max(self.ttl_s, 0))).isoformat()

    def is_stale(self, now: dt.datetime | None = None) -> bool:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        expires = parse_utc(self.expires_at_utc())
        return current >= expires


@dataclass(frozen=True)
class PlannedAction:
    action_id: str
    module_id: str
    description: str
    args: dict[str, str] = field(default_factory=dict)
    risk_level: RiskLevel = "medium"
    requires_privilege: bool = False
    rollback_hint: str = ""


@dataclass(frozen=True)
class ActionPlan:
    plan_id: str
    intent: str
    path: PathMode
    risk_level: RiskLevel
    context_tier: ContextTier
    actions: tuple[PlannedAction, ...]
    summary: str = ""
    requires_mutation: bool = False


@dataclass(frozen=True)
class IncidentRecord:
    incident_id: str
    fingerprint: str
    category: str
    severity: RiskLevel
    status: IncidentStatus
    opened_at_utc: str
    updated_at_utc: str
    last_seen_at_utc: str = ""
    last_action_id: str = ""
    operator_decision: str = ""
    resolution_summary: str = ""
    latest_summary: str = ""
    alert_ids: tuple[int, ...] = ()
    event_ids: tuple[int, ...] = ()
    correlated_units: tuple[str, ...] = ()
    version: int = 1

    def is_active(self) -> bool:
        return self.status in {"open", "contained"}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    risk_level: RiskLevel
    privilege_mode: PrivilegeMode
    approval_scope: ApprovalScope
    requires_confirmation: bool = False
    requires_step_up: bool = False
    max_actions: int = 1
    context_signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    action_id: str
    returncode: int
    summary: str
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0


@dataclass(frozen=True)
class PExecRequest:
    action_id: str
    args: dict[str, str] = field(default_factory=dict)
    request_id: str = ""
    privilege_mode: PrivilegeMode = "pkexec_bootstrap"
    approval_scope: ApprovalScope = "single_action"
    audit_required: bool = True
    dry_run: bool = False


@dataclass(frozen=True)
class PExecResult:
    ok: bool
    command: tuple[str, ...]
    request_id: str = ""
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    transport: str = ""
