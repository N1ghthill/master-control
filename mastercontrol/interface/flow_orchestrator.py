#!/usr/bin/env python3
"""Shared orchestration policy for interactive execution flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


RunIntentFn = Callable[..., dict[str, Any]]
HighRiskFn = Callable[[dict[str, Any] | None], bool]


@dataclass(frozen=True)
class PendingChoice:
    prepared: str
    mapped_action: dict[str, Any]
    request_id: str = ""


@dataclass(frozen=True)
class PendingHighRisk:
    prepared: str
    mapped_action: dict[str, Any]
    request_id: str = ""


@dataclass
class FlowOutcome:
    results: list[dict[str, Any]] = field(default_factory=list)
    pending_choice: PendingChoice | None = None
    pending_high_risk: PendingHighRisk | None = None
    cancelled: bool = False


class FlowOrchestrator:
    """Centralizes preview/confirm/execute decisions for terminal interfaces."""

    def __init__(self, run_intent: RunIntentFn, is_high_risk_action: HighRiskFn) -> None:
        self._run_intent = run_intent
        self._is_high_risk_action = is_high_risk_action

    def begin(self, prepared: str, *, mode: str) -> FlowOutcome:
        current_mode = (mode or "confirm").strip().lower() or "confirm"
        if current_mode == "plan":
            preview = self._run_intent(prepared, execute=False, dry_run=False)
            return FlowOutcome(results=[preview])

        if current_mode == "dry-run":
            result = self._execute(prepared, dry_run=True)
            return FlowOutcome(results=[result])

        if current_mode == "execute":
            result = self._execute(prepared, dry_run=False, approve=True, allow_high_risk=False)
            outcome = FlowOutcome(results=[result])
            if self._blocks_on_step_up(result):
                mapped = result.get("mapped_action")
                if isinstance(mapped, dict):
                    outcome.pending_high_risk = PendingHighRisk(
                        prepared=prepared,
                        mapped_action=dict(mapped),
                        request_id=str(result.get("request_id", "")),
                    )
            return outcome

        preview = self._run_intent(prepared, execute=False, dry_run=False)
        outcome = FlowOutcome(results=[preview])
        if not self._can_offer_choice(preview):
            return outcome

        mapped = preview.get("mapped_action")
        if not isinstance(mapped, dict):
            return outcome
        outcome.pending_choice = PendingChoice(
            prepared=prepared,
            mapped_action=dict(mapped),
            request_id=str(preview.get("request_id", "")),
        )
        return outcome

    def choose(self, pending: PendingChoice, *, choice: str) -> FlowOutcome:
        selected = (choice or "").strip().lower()
        if selected == "n":
            return FlowOutcome(cancelled=True)
        if selected == "d":
            result = self._execute(
                pending.prepared,
                dry_run=True,
                request_id=pending.request_id,
            )
            return FlowOutcome(results=[result])
        if selected != "e":
            raise ValueError(f"invalid execution choice '{choice}'")

        if self._is_high_risk_action(pending.mapped_action):
            return FlowOutcome(
                pending_high_risk=PendingHighRisk(
                    prepared=pending.prepared,
                    mapped_action=dict(pending.mapped_action),
                    request_id=pending.request_id,
                )
            )

        result = self._execute(
            pending.prepared,
            dry_run=False,
            approve=True,
            allow_high_risk=False,
            request_id=pending.request_id,
        )
        return FlowOutcome(results=[result])

    def confirm_high_risk(self, pending: PendingHighRisk, *, confirmed: bool) -> FlowOutcome:
        if not confirmed:
            return FlowOutcome(cancelled=True)
        result = self._execute(
            pending.prepared,
            dry_run=False,
            approve=True,
            allow_high_risk=True,
            request_id=pending.request_id,
        )
        return FlowOutcome(results=[result])

    def _execute(
        self,
        prepared: str,
        *,
        dry_run: bool,
        approve: bool = False,
        allow_high_risk: bool = False,
        request_id: str = "",
    ) -> dict[str, Any]:
        return self._run_intent(
            prepared,
            execute=True,
            dry_run=dry_run,
            approve=approve,
            allow_high_risk=allow_high_risk,
            request_id=request_id,
        )

    def _can_offer_choice(self, result: dict[str, Any]) -> bool:
        mapped = result.get("mapped_action")
        if not isinstance(mapped, dict):
            return False
        execution = result.get("execution", {})
        if isinstance(execution, dict) and execution.get("blocked"):
            return False
        if isinstance(execution, dict) and execution.get("executed") and not mapped.get("requires_mutation", False):
            return False
        return True

    def _blocks_on_step_up(self, result: dict[str, Any]) -> bool:
        execution = result.get("execution", {})
        if not isinstance(execution, dict):
            return False
        if not execution.get("blocked"):
            return False
        if execution.get("command_error") != "step_up_required":
            return False
        return self._is_high_risk_action(result.get("mapped_action"))
