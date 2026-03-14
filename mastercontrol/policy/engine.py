#!/usr/bin/env python3
"""Minimal policy engine for risk, approval and privilege routing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mastercontrol.contracts import (
    ActionPlan,
    ApprovalScope,
    ContextSnapshot,
    OperatorIdentity,
    PolicyDecision,
    PrivilegeMode,
    RISK_ORDER,
    RiskLevel,
    normalize_risk,
)
from mastercontrol.privilege.broker import DEFAULT_BROKER_SOCKET, broker_socket_available


@dataclass(frozen=True)
class PolicyInput:
    plan: ActionPlan
    operator: OperatorIdentity
    context_snapshots: tuple[ContextSnapshot, ...] = ()


class PolicyEngine:
    """Evaluates whether a plan can proceed and how it must be approved."""

    def __init__(
        self,
        *,
        broker_socket: Path | None = None,
        prefer_broker: bool = True,
    ) -> None:
        self.broker_socket = broker_socket or DEFAULT_BROKER_SOCKET
        self.prefer_broker = prefer_broker

    def _privilege_mode(self, plan: ActionPlan) -> PrivilegeMode:
        if any(action.requires_privilege for action in plan.actions):
            if self.prefer_broker and broker_socket_available(self.broker_socket):
                return "broker"
            return "pkexec_bootstrap"
        return "none"

    @staticmethod
    def _max_risk(left: RiskLevel, right: RiskLevel) -> RiskLevel:
        return left if RISK_ORDER[left] >= RISK_ORDER[right] else right

    def _environment_signals(self, policy_input: PolicyInput, base_risk: RiskLevel) -> tuple[RiskLevel, tuple[str, ...]]:
        plan = policy_input.plan
        if not plan.requires_mutation:
            return base_risk, ()

        action_id = plan.actions[0].action_id if plan.actions else ""
        snapshots = {snapshot.source: snapshot for snapshot in policy_input.context_snapshots}
        signals: list[str] = []
        severity = 0

        service_snapshot = snapshots.get("services.summary")
        if service_snapshot is not None:
            payload = service_snapshot.payload
            state = str(payload.get("system_state", "")).strip().lower()
            failed_count = int(payload.get("failed_count", 0) or 0)
            parts: list[str] = []
            if state and state != "running":
                parts.append(f"systemd={state}")
                severity += 1
            if failed_count > 0:
                parts.append(f"failed_units={failed_count}")
                severity += 1 if failed_count < 3 else 2
            if parts:
                signals.append("service posture " + ", ".join(parts))

        host_snapshot = snapshots.get("host.system")
        if host_snapshot is not None:
            payload = host_snapshot.payload
            mem_total = float(payload.get("mem_total_mib", 0.0) or 0.0)
            mem_available = float(payload.get("mem_available_mib", 0.0) or 0.0)
            cpu_count = int(payload.get("cpu_count", 0) or 0)
            loadavg = float(payload.get("loadavg_1m", 0.0) or 0.0)
            parts = []
            if mem_total > 0:
                mem_ratio = mem_available / mem_total
                if mem_ratio <= 0.10:
                    parts.append(f"mem_available_mib={mem_available:.1f}/{mem_total:.1f}")
                    severity += 1 if mem_ratio > 0.05 else 2
            if cpu_count > 0 and loadavg >= max(cpu_count, 1) * 1.25:
                parts.append(f"loadavg_1m={loadavg:.2f}/{cpu_count}cpu")
                severity += 1
            if parts:
                signals.append("host posture " + ", ".join(parts))

        if action_id.startswith("package.apt."):
            network_snapshot = snapshots.get("network.summary")
            if network_snapshot is not None:
                payload = network_snapshot.payload
                default_route = str(payload.get("default_route", "")).strip()
                route_status = int(payload.get("route_status", 0) or 0)
                nameservers = payload.get("nameservers", [])
                parts = []
                if route_status != 0 or not default_route:
                    parts.append("default_route=missing")
                    severity += 1
                if not nameservers:
                    parts.append("nameservers=none")
                    severity += 1
                if parts:
                    signals.append("network posture " + ", ".join(parts))

        if action_id.startswith(("service.", "package.", "dns.")):
            journal_snapshot = snapshots.get("journal.alerts")
            if journal_snapshot is not None:
                warning_count = int(journal_snapshot.payload.get("warning_event_count", 0) or 0)
                if warning_count > 0:
                    signals.append(f"journal posture warnings={warning_count}")
                    severity += 1 if warning_count < 3 else 2

        if severity >= 2:
            return self._max_risk(base_risk, "high"), tuple(signals)
        if severity == 1:
            return self._max_risk(base_risk, "medium"), tuple(signals)
        return base_risk, tuple(signals)

    def evaluate(self, policy_input: PolicyInput) -> PolicyDecision:
        plan = policy_input.plan
        operator = policy_input.operator
        risk: RiskLevel = normalize_risk(plan.risk_level)
        risk, context_signals = self._environment_signals(policy_input, risk)
        privilege_mode = self._privilege_mode(plan)
        approval_scope: ApprovalScope = "none"
        requires_confirmation = False
        requires_step_up = False
        allowed = True
        reasons: list[str] = ["Low-risk plan can proceed."]

        if risk == "medium":
            approval_scope = "single_action"
            requires_confirmation = True
            reasons = ["Medium-risk plan requires contextual confirmation."]
        elif risk == "high":
            approval_scope = "single_action"
            requires_confirmation = True
            requires_step_up = True
            reasons = ["High-risk plan requires confirmation and explicit operator step-up."]
        elif risk == "critical":
            approval_scope = "single_action"
            requires_confirmation = True
            requires_step_up = True
            allowed = False
            reasons = ["Critical plan is blocked until dedicated policy is defined."]

        if context_signals:
            approval_scope = "single_action"
            requires_confirmation = True
            reasons.append(
                "Environment signals require stricter approval: " + "; ".join(context_signals) + "."
            )

        if privilege_mode != "none" and operator.trust_level == "T0":
            requires_confirmation = True
            approval_scope = "single_action"
            reasons.append("Privileged action from low-trust session requires explicit approval.")

        return PolicyDecision(
            allowed=allowed,
            reason=" ".join(reasons),
            risk_level=risk,
            privilege_mode=privilege_mode,
            approval_scope=approval_scope,
            requires_confirmation=requires_confirmation,
            requires_step_up=requires_step_up,
            max_actions=max(len(plan.actions), 1),
            context_signals=context_signals,
        )
