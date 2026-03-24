from __future__ import annotations

import fnmatch
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from master_control.config_manager import ConfigTarget
from master_control.policy.config import PolicyLoader, ToolPolicyRule
from master_control.tools.base import RiskLevel, ToolSpec


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    needs_confirmation: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "needs_confirmation": self.needs_confirmation,
            "reason": self.reason,
        }


class PolicyEngine:
    def __init__(self, *, state_dir: Path, policy_path: Path) -> None:
        self.loader = PolicyLoader(policy_path, state_dir)

    def diagnostics(self) -> dict[str, object]:
        return self.loader.diagnostics()

    def config_targets(self) -> tuple[ConfigTarget, ...]:
        return self.loader.config_targets()

    def evaluate(
        self,
        spec: ToolSpec,
        arguments: Mapping[str, object] | None = None,
    ) -> PolicyDecision:
        policy = self.loader.load()
        if policy.error is not None:
            return PolicyDecision(
                allowed=False,
                needs_confirmation=False,
                reason=f"Policy load error: {policy.error}",
            )

        rule = policy.tool_rules.get(spec.name)
        if rule is not None and rule.enabled is False:
            return PolicyDecision(
                allowed=False,
                needs_confirmation=False,
                reason=f"Tool `{spec.name}` is disabled by operator policy.",
            )

        denied_reason = self._evaluate_argument_constraints(spec.name, arguments or {}, rule)
        if denied_reason is not None:
            return PolicyDecision(
                allowed=False,
                needs_confirmation=False,
                reason=denied_reason,
            )

        needs_confirmation = spec.risk is not RiskLevel.READ_ONLY
        if rule is not None and rule.require_confirmation:
            needs_confirmation = True

        return PolicyDecision(
            allowed=True,
            needs_confirmation=needs_confirmation,
            reason=self._build_reason(spec.risk, rule, needs_confirmation),
        )

    def _evaluate_argument_constraints(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        rule: ToolPolicyRule | None,
    ) -> str | None:
        if rule is None:
            return None

        if rule.allowed_scopes:
            scope = self._normalize_scope(arguments.get("scope"))
            if scope not in rule.allowed_scopes:
                allowed_scopes = ", ".join(rule.allowed_scopes)
                return f"Tool `{tool_name}` is limited by policy to scopes: {allowed_scopes}."

        if rule.service_patterns and tool_name in {
            "service_status",
            "restart_service",
            "reload_service",
        }:
            service_name = arguments.get("name")
            if not isinstance(service_name, str) or not service_name.strip():
                return f"Tool `{tool_name}` requires a valid service name for policy evaluation."
            normalized_name = service_name.strip()
            if not any(
                fnmatch.fnmatch(normalized_name, pattern) for pattern in rule.service_patterns
            ):
                patterns = ", ".join(rule.service_patterns)
                return (
                    f"Tool `{tool_name}` is limited by policy to these service patterns: {patterns}."
                )
        return None

    def _normalize_scope(self, raw_scope: object) -> str:
        if isinstance(raw_scope, str) and raw_scope.strip():
            return raw_scope.strip().lower()
        return "system"

    def _build_reason(
        self,
        risk: RiskLevel,
        rule: ToolPolicyRule | None,
        needs_confirmation: bool,
    ) -> str:
        if rule is not None and rule.require_confirmation and risk is RiskLevel.READ_ONLY:
            return "Operator policy requires explicit confirmation for this tool."
        if risk is RiskLevel.READ_ONLY and not needs_confirmation:
            return "Read-only tool."
        if risk is RiskLevel.MUTATING_SAFE:
            return "Mutating tool requires explicit confirmation."
        return "Privileged tool requires confirmation and preflight validation."
