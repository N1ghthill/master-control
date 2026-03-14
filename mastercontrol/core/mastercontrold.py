#!/usr/bin/env python3
"""MasterControl daemon prototype with humanized response pipeline."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import sqlite3
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from mastercontrol.context import (
        AlertJournalCollector,
        CollectorSpec,
        ContextEngine,
        EventSweepResult,
        HostContextCollector,
        NetworkContextCollector,
        ServiceContextCollector,
        SessionContextCollector,
        SQLiteContextStore,
        StaticContextCollector,
        SystemEventMonitor,
    )
    from mastercontrol.context.mc_operator_profiler import OperatorEvent, OperatorProfiler
    from mastercontrol.contracts import ActionPlan, ContextSnapshot, OperatorIdentity, PExecRequest, PlannedAction
    from mastercontrol.modules.mod_dns import DNSModule
    from mastercontrol.modules.mod_network import NetworkModule
    from mastercontrol.modules.mod_packages import PackageModule
    from mastercontrol.modules.mod_security import SecurityModule
    from mastercontrol.modules.mod_services import ServiceModule
    from mastercontrol.modules.registry import ModuleRegistry
    from mastercontrol.policy import PolicyEngine, PolicyInput
    from mastercontrol.privilege import PExecPlanner, PrivilegeBrokerClient, PrivilegeBrokerTransport
    from mastercontrol.security import SecurityWatchEngine
    from mastercontrol.tone.mc_tone_analyzer import ToneAnalyzer
    from mastercontrol.core.humanized_kernel import SoulKernel, load_profile
    from mastercontrol.core.path_selector import PathSelector, VALID_PATH, VALID_RISK
    from mastercontrol.runtime.root_exec import build_command as build_allowlisted_command
    from mastercontrol.runtime.root_exec import validate_action_args
except ImportError:  # pragma: no cover
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from mastercontrol.context import (  # type: ignore
        AlertJournalCollector,
        CollectorSpec,
        ContextEngine,
        EventSweepResult,
        HostContextCollector,
        NetworkContextCollector,
        ServiceContextCollector,
        SessionContextCollector,
        SQLiteContextStore,
        StaticContextCollector,
        SystemEventMonitor,
    )
    from mastercontrol.context.mc_operator_profiler import OperatorEvent, OperatorProfiler  # type: ignore
    from mastercontrol.contracts import ActionPlan, ContextSnapshot, OperatorIdentity, PExecRequest, PlannedAction  # type: ignore
    from mastercontrol.modules.mod_dns import DNSModule  # type: ignore
    from mastercontrol.modules.mod_network import NetworkModule  # type: ignore
    from mastercontrol.modules.mod_packages import PackageModule  # type: ignore
    from mastercontrol.modules.mod_security import SecurityModule  # type: ignore
    from mastercontrol.modules.mod_services import ServiceModule  # type: ignore
    from mastercontrol.modules.registry import ModuleRegistry  # type: ignore
    from mastercontrol.policy import PolicyEngine, PolicyInput  # type: ignore
    from mastercontrol.privilege import PExecPlanner, PrivilegeBrokerClient, PrivilegeBrokerTransport  # type: ignore
    from mastercontrol.security import SecurityWatchEngine  # type: ignore
    from mastercontrol.tone.mc_tone_analyzer import ToneAnalyzer  # type: ignore
    from mastercontrol.core.humanized_kernel import SoulKernel, load_profile  # type: ignore
    from mastercontrol.core.path_selector import PathSelector, VALID_PATH, VALID_RISK  # type: ignore
    from mastercontrol.runtime.root_exec import build_command as build_allowlisted_command  # type: ignore
    from mastercontrol.runtime.root_exec import validate_action_args  # type: ignore


@dataclass
class OperatorRequest:
    operator_name: str
    intent: str
    risk_level: str
    incident: bool
    requested_path: str
    execute: bool
    dry_run: bool
    approve: bool
    allow_high_risk: bool
    request_id: str
    simulate_failure: bool


class MasterControlD:
    """Orchestrator using SoulKernel in every response."""

    def __init__(
        self,
        profile_path: Path | None = None,
        db_path: Path | None = None,
        context_command_runner: Any | None = None,
        system_event_runner: Any | None = None,
        broker_socket_path: Path | None = None,
        broker_python_bin: str | None = None,
    ) -> None:
        profile = load_profile(profile_path)
        self.soul = SoulKernel(profile)
        self.profiler = OperatorProfiler(db_path=db_path)
        self.tone = ToneAnalyzer()
        self.context_command_runner = context_command_runner
        self.system_event_runner = system_event_runner or context_command_runner

        self.repo_root = Path(__file__).resolve().parents[2]
        self.mc_root_action = self.repo_root / "scripts" / "mc-root-action"
        self.core_log_path = self._default_core_log_path(self.profiler.db_path)
        self.action_catalog = self._load_action_catalog()
        self.action_risk = self._load_action_risk()
        self.context_store = SQLiteContextStore(self.profiler.db_path)
        self.system_event_monitor = SystemEventMonitor(
            db_path=self.profiler.db_path,
            store=self.context_store,
            runner=self.system_event_runner,
        )
        self.security_watch = SecurityWatchEngine(
            db_path=self.profiler.db_path,
            event_monitor=self.system_event_monitor,
        )
        self.selector = PathSelector(db_path=self.profiler.db_path)
        self.policy_engine = PolicyEngine(broker_socket=broker_socket_path)
        self.pexec_planner = PExecPlanner(
            broker_transport=PrivilegeBrokerTransport(
                socket_path=broker_socket_path,
                python_bin=broker_python_bin or sys.executable,
            )
        )
        self.broker_client = PrivilegeBrokerClient(socket_path=broker_socket_path)
        self.dns_module = DNSModule()
        self.network_module = NetworkModule()
        self.service_module = ServiceModule()
        self.package_module = PackageModule()
        self.security_module = SecurityModule()
        self.registry = ModuleRegistry(
            modules=[
                self.service_module,
                self.package_module,
                self.network_module,
                self.dns_module,
                self.security_module,
            ]
        )

    def handle(self, req: OperatorRequest) -> dict[str, Any]:
        t0 = time.monotonic()
        request_id = req.request_id.strip() or self._make_request_id()

        risk = self._normalize_risk(req.risk_level)
        tone_result = self.tone.analyze(req.intent, mode="heuristic")
        operator_profile = self.profiler.get_profile(req.operator_name.lower())
        operator_identity = self._build_operator_identity(req.operator_name, operator_profile)

        risk, incident = self._adjust_risk_with_tone(
            risk=risk,
            incident=req.incident,
            tone=tone_result.tone,
            frustration=tone_result.frustration_score,
        )

        event_sweep = self._ingest_system_events(
            intent=req.intent,
            risk_level=risk,
            incident=incident,
            intent_cluster=tone_result.intent_cluster,
        )
        self._prefetch_selector_context(
            intent=req.intent,
            risk_level=risk,
            incident=incident,
            intent_cluster=tone_result.intent_cluster,
            operator_name=req.operator_name,
            operator_profile=operator_profile,
            request_id=request_id,
        )
        path_decision = self._decide_path(
            intent=req.intent,
            risk_level=risk,
            incident=incident,
            requested=req.requested_path,
            operator_profile=operator_profile,
            intent_cluster=tone_result.intent_cluster,
            operator_id=req.operator_name.lower(),
        )

        plan_bundle = self._build_plan(
            intent=req.intent,
            risk_level=risk,
            path=path_decision["path"],
            intent_cluster=tone_result.intent_cluster,
            operator_name=req.operator_name,
            operator_profile=operator_profile,
            incident=incident,
            request_id=request_id,
        )
        plan = plan_bundle["steps"]
        mapped_action = plan_bundle.get("action")
        action_plan = plan_bundle["action_plan"]
        policy_decision = self.policy_engine.evaluate(
            PolicyInput(
                plan=action_plan,
                operator=operator_identity,
                context_snapshots=tuple(plan_bundle["context_snapshots"]),
            )
        )
        pexec_plan = self._plan_pexec(
            action_plan=action_plan,
            policy_decision=policy_decision,
            request_id=request_id,
            dry_run=req.dry_run,
        )

        execution = self._execute_plan(
            action_plan=action_plan,
            policy_decision=policy_decision,
            mapped_action=mapped_action,
            pexec_plan=pexec_plan,
            request=req,
            request_id=request_id,
            operator_identity=operator_identity,
            simulate_failure=req.simulate_failure,
        )
        incident_activity = self._record_security_incident_execution(
            mapped_action=mapped_action,
            execution=execution,
            operator_identity=operator_identity,
            request_id=request_id,
        )
        if incident_activity is not None:
            execution["incident_activity"] = incident_activity
        latency_ms = int((time.monotonic() - t0) * 1000)

        effective_risk = self._max_risk_level(action_plan.risk_level, policy_decision.risk_level)
        mapped_id = mapped_action["action_id"] if mapped_action else "none"
        rule_note = ""
        if path_decision.get("rule_applied"):
            rule_note = f", learned_rule={path_decision.get('rule_key', '')}"
        context_signal_note = ""
        if path_decision.get("context_signals"):
            context_signal_note = f", env_signals={len(path_decision['context_signals'])}"
        policy_signal_note = ""
        if policy_decision.context_signals:
            policy_signal_note = f", policy_signals={len(policy_decision.context_signals)}"
        event_signal_note = ""
        if event_sweep.get("invalidated_sources"):
            event_signal_note = f", event_invalidations={len(event_sweep['invalidated_sources'])}"
        risk_assessment = (
            f"risk={effective_risk}, path={path_decision['path']}, "
            f"confidence={path_decision['confidence']:.2f}, reason={path_decision['reason']}, "
            f"context={plan_bundle['context_tier']}, "
            f"policy={'allow' if policy_decision.allowed else 'deny'}, "
            f"privilege={policy_decision.privilege_mode}, approval={policy_decision.approval_scope}, "
            f"tone={tone_result.tone}, frustration={tone_result.frustration_score:.2f}, "
            f"mapped_action={mapped_id}{rule_note}{context_signal_note}{policy_signal_note}{event_signal_note}"
        )

        if execution.get("executed") is False and mapped_action:
            next_step = execution["outcome"]
        else:
            next_step = (
                "Rollback not required; keep monitoring."
                if execution["success"]
                else "Escalate to deep diagnostic and apply rollback-safe action."
            )
            if not execution["success"] and mapped_action and mapped_action.get("rollback_hint"):
                next_step = str(mapped_action["rollback_hint"])

        message_payload = {
            "operator_name": req.operator_name,
            "risk_level": effective_risk,
            "incident": incident,
            "intent_understood": req.intent,
            "planned_actions": plan,
            "risk_assessment": risk_assessment,
            "outcome": execution["outcome"],
            "rollback_or_next_step": next_step,
            "tone": tone_result.tone,
            "tone_confidence": tone_result.confidence,
            "frustration_score": tone_result.frustration_score,
            "intent_cluster": tone_result.intent_cluster,
            "intent_confidence": tone_result.intent_confidence,
            "intent_source": tone_result.intent_source,
            "operator_profile": operator_profile,
        }
        communication = self.soul.communication_plan(message_payload)
        message = self.soul.compose_message(message_payload, communication_plan=communication)

        reflection_input = {
            "risk_level": effective_risk,
            "path_used": path_decision["path"],
            "success": execution["success"],
            "policy_compliant": execution["policy_compliant"],
            "confidence": path_decision["confidence"],
            "incident": incident,
            "tone": tone_result.tone,
            "frustration_score": tone_result.frustration_score,
            "intent_cluster": tone_result.intent_cluster,
            "operator_profile": operator_profile,
        }
        reflection = self.soul.reflect(reflection_input)

        self.profiler.record_event(
            OperatorEvent(
                operator_id=req.operator_name.lower(),
                intent_text=req.intent,
                intent_cluster=tone_result.intent_cluster,
                risk_level=effective_risk,
                selected_path=path_decision["path"],
                success=execution["success"],
                latency_ms=latency_ms,
                command_error=str(execution.get("command_error", "")),
                forced_path=path_decision["source"] == "manual",
                incident=incident,
            )
        )

        self._append_core_log(
            {
                "ts_utc": self._utc_now(),
                "request_id": request_id,
                "operator_id": req.operator_name.lower(),
                "intent": req.intent,
                "risk_level": effective_risk,
                "path": path_decision["path"],
                "context": plan_bundle["context"],
                "operator_identity": asdict(operator_identity),
                "system_event_sweep": event_sweep,
                "action_plan": asdict(action_plan),
                "policy_decision": asdict(policy_decision),
                "pexec_plan": pexec_plan,
                "mapped_action": mapped_action,
                "execution": execution,
                "tone": {
                    "tone": tone_result.tone,
                    "confidence": tone_result.confidence,
                    "intent_cluster": tone_result.intent_cluster,
                    "intent_source": tone_result.intent_source,
                    "intent_confidence": tone_result.intent_confidence,
                    "frustration_score": tone_result.frustration_score,
                },
                "communication": communication,
                "reflection_status": reflection["status"],
                "latency_ms": latency_ms,
            }
        )

        return {
            "request_id": request_id,
            "message": message,
            "path": path_decision,
            "tone": {
                "tone": tone_result.tone,
                "confidence": tone_result.confidence,
                "intent_cluster": tone_result.intent_cluster,
                "intent_source": tone_result.intent_source,
                "intent_confidence": tone_result.intent_confidence,
                "frustration_score": tone_result.frustration_score,
            },
            "communication": communication,
            "operator_profile": operator_profile,
            "operator_identity": asdict(operator_identity),
            "system_event_sweep": event_sweep,
            "context": plan_bundle["context"],
            "plan": plan,
            "action_plan": asdict(action_plan),
            "policy_decision": asdict(policy_decision),
            "pexec_plan": pexec_plan,
            "mapped_action": mapped_action,
            "execution": execution,
            "latency_ms": latency_ms,
            "reflection": reflection,
            "effective_risk_level": effective_risk,
        }

    @staticmethod
    def _normalize_risk(risk_level: str) -> str:
        risk = (risk_level or "").strip().lower()
        return risk if risk in VALID_RISK else "medium"

    @staticmethod
    def _detect_os_pretty() -> str:
        os_release = Path("/etc/os-release")
        if os_release.exists():
            try:
                for line in os_release.read_text(encoding="utf-8").splitlines():
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
            except OSError:
                pass
        return platform.platform()

    def runtime_context_snapshot(self, operator_name: str) -> dict[str, str]:
        collector = SessionContextCollector(operator_name, ttl_s=15)
        engine = ContextEngine([collector], store=self.context_store)
        engine.ensure_context("hot")
        snapshot = engine.store.get(collector.spec.collector_id)
        if snapshot is not None:
            return dict(snapshot.payload)
        user = os.getenv("USER") or os.getenv("LOGNAME") or "unknown-user"
        return {
            "operator": (operator_name or "Operator").strip() or "Operator",
            "hostname": socket.gethostname() or "unknown-host",
            "os_pretty": self._detect_os_pretty(),
            "user": user,
            "cwd": "unknown-cwd",
            "timestamp_local": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    @staticmethod
    def _context_snapshot_step(snapshot: dict[str, str]) -> str:
        return (
            "Collect current context snapshot "
            f"(operator={snapshot.get('operator', 'Operator')}, "
            f"host={snapshot.get('hostname', 'unknown-host')}, "
            f"os={snapshot.get('os_pretty', 'unknown-os')}, "
            f"user={snapshot.get('user', 'unknown-user')}, "
            f"cwd={snapshot.get('cwd', 'unknown-cwd')}, "
            f"ts_local={snapshot.get('timestamp_local', 'unknown-time')})."
        )

    @staticmethod
    def _context_snapshot_summary_step(snapshot: ContextSnapshot) -> str:
        summary = snapshot.summary or "fresh snapshot available"
        return f"Use {snapshot.tier} context from {snapshot.source}: {summary}."

    @staticmethod
    def _max_risk_level(current_risk: str, mapped_risk: str) -> str:
        risk_order = ["low", "medium", "high", "critical"]
        current = current_risk if current_risk in risk_order else "medium"
        mapped = mapped_risk if mapped_risk in risk_order else current
        return risk_order[max(risk_order.index(current), risk_order.index(mapped))]

    @staticmethod
    def _trust_from_profile(operator_profile: dict[str, Any]) -> tuple[str, float]:
        common_intents = operator_profile.get("common_intents", [])
        updated_at = str(operator_profile.get("updated_at", "")).strip()
        if not common_intents:
            return "T0", 0.50
        if len(common_intents) >= 3 and updated_at:
            return "T2", 0.82
        return "T1", 0.68

    def _build_operator_identity(
        self,
        operator_name: str,
        operator_profile: dict[str, Any],
    ) -> OperatorIdentity:
        trust_level, trust_score = self._trust_from_profile(operator_profile)
        unix_user = os.getenv("USER") or os.getenv("LOGNAME") or operator_name.lower()
        session_id = os.getenv("XDG_SESSION_ID", "")
        return OperatorIdentity(
            operator_id=operator_name.lower(),
            display_name=(operator_name or "Operator").strip() or "Operator",
            unix_user=unix_user,
            session_id=session_id,
            trust_level=trust_level,
            trust_score=trust_score,
            tags=tuple(operator_profile.get("common_intents", [])[:3]),
        )

    @staticmethod
    def _action_requires_privilege(action_id: str) -> bool:
        return not (
            action_id.startswith("network.diagnose.")
            or action_id.startswith("security.audit.")
            or action_id.startswith("security.incident.")
            or action_id.startswith("security.vigilance.")
            or action_id.startswith("security.alerts.")
        )

    @staticmethod
    def _action_requires_mutation(action_id: str) -> bool:
        return not (
            action_id.startswith("network.diagnose.")
            or action_id.startswith("security.audit.")
            or action_id.startswith("security.incident.")
            or action_id.startswith("security.vigilance.")
            or action_id.startswith("security.alerts.")
        )

    def _determine_context_tier(
        self,
        *,
        intent: str,
        risk_level: str,
        path: str,
        mapped_action: dict[str, Any] | None,
        incident: bool,
    ) -> str:
        text = (intent or "").lower()
        diagnostics = path == "deep" or any(
            hint in text
            for hint in ("diagnose", "diagnosticar", "investigar", "analisar", "incident", "incidente", "log")
        )
        ambiguity = mapped_action is None and path != "fast"
        requires_mutation = bool(mapped_action and mapped_action.get("requires_mutation", False))
        return ContextEngine.required_tier(
            risk_level=risk_level,
            requires_mutation=requires_mutation,
            diagnostics=diagnostics,
            incident=incident,
            ambiguity=ambiguity,
        )

    def _build_context_collectors(
        self,
        *,
        operator_name: str,
        operator_profile: dict[str, Any],
        required_tier: str,
        intent_cluster: str,
        path: str,
        mapped_action: dict[str, Any] | None,
        incident: bool,
        request_id: str | None,
    ) -> list[Any]:
        operator_key = (operator_name or "operator").strip().lower() or "operator"
        collectors: list[Any] = [
            SessionContextCollector(operator_name, ttl_s=15),
            HostContextCollector(ttl_s=120),
            NetworkContextCollector(ttl_s=45, runner=self.context_command_runner),
            ServiceContextCollector(ttl_s=45, runner=self.context_command_runner),
            StaticContextCollector(
                CollectorSpec(
                    collector_id=f"operator.profile.{operator_key}",
                    tier="warm",
                    ttl_s=180,
                    description="Recent operator behavior snapshot",
                ),
                {
                    "active_hours": operator_profile.get("active_hours", "unknown"),
                    "path_preference": operator_profile.get("path_preference", "balanced"),
                    "common_intents": operator_profile.get("common_intents", []),
                    "error_prone_commands": operator_profile.get("error_prone_commands", []),
                },
                summary=(
                    f"path_pref={operator_profile.get('path_preference', 'balanced')}, "
                    f"active_hours={operator_profile.get('active_hours', 'unknown')}, "
                    f"common_intents={','.join(operator_profile.get('common_intents', [])[:3]) or 'none'}"
                ),
            ),
        ]
        if mapped_action is not None:
            collectors.append(
                StaticContextCollector(
                    CollectorSpec(
                        collector_id=f"planning.action.{request_id or 'preview'}",
                        tier="warm",
                        ttl_s=20,
                        description="Resolved action and operational scope",
                    ),
                    {
                        "action_id": mapped_action["action_id"],
                        "risk": mapped_action["action_risk"],
                        "requires_privilege": mapped_action["requires_privilege"],
                        "requires_mutation": mapped_action["requires_mutation"],
                    },
                    summary=(
                        f"action={mapped_action['action_id']}, "
                        f"risk={mapped_action['action_risk']}, "
                        f"mutation={mapped_action['requires_mutation']}"
                    ),
                )
            )
        if required_tier == "deep":
            collectors.append(AlertJournalCollector(ttl_s=20, runner=self.context_command_runner))
            collectors.append(
                StaticContextCollector(
                    CollectorSpec(
                        collector_id=f"planning.deep.{request_id or 'preview'}",
                        tier="deep",
                        ttl_s=15,
                        description="Deep context trigger summary",
                    ),
                    {
                        "path": path,
                        "incident": incident,
                        "intent_cluster": intent_cluster,
                    },
                    summary=(
                        f"path={path}, incident={incident}, "
                        f"cluster={intent_cluster or 'unknown'}"
                    ),
                )
            )
        return collectors

    def _collect_context(
        self,
        *,
        operator_name: str,
        operator_profile: dict[str, Any],
        required_tier: str,
        intent_cluster: str,
        path: str,
        mapped_action: dict[str, Any] | None,
        incident: bool,
        request_id: str | None,
    ) -> list[ContextSnapshot]:
        collectors = self._build_context_collectors(
            operator_name=operator_name,
            operator_profile=operator_profile,
            required_tier=required_tier,
            intent_cluster=intent_cluster,
            path=path,
            mapped_action=mapped_action,
            incident=incident,
            request_id=request_id,
        )
        engine = ContextEngine(collectors=collectors, store=self.context_store)
        return engine.ensure_context(required_tier)

    def _build_action_plan(
        self,
        *,
        intent: str,
        risk_level: str,
        path: str,
        context_tier: str,
        mapped_action: dict[str, Any] | None,
        request_id: str | None,
    ) -> ActionPlan:
        actions: tuple[PlannedAction, ...] = ()
        effective_risk = risk_level
        if mapped_action is not None:
            effective_risk = self._max_risk_level(
                risk_level,
                str(mapped_action.get("action_risk", risk_level)),
            )
            actions = (
                PlannedAction(
                    action_id=str(mapped_action["action_id"]),
                    module_id=str(mapped_action.get("module_id", "unknown")),
                    description=f"Run allowlisted action '{mapped_action['action_id']}'.",
                    args=dict(mapped_action.get("args", {})),
                    risk_level=str(mapped_action.get("action_risk", "medium")),
                    requires_privilege=bool(mapped_action.get("requires_privilege", False)),
                    rollback_hint=str(mapped_action.get("rollback_hint", "")),
                ),
            )
        return ActionPlan(
            plan_id=f"{request_id}:plan" if request_id else f"plan-{uuid.uuid4().hex[:10]}",
            intent=intent,
            path=path,
            risk_level=effective_risk,
            context_tier=context_tier,
            actions=actions,
            summary=f"path={path}, context={context_tier}, actions={len(actions)}",
            requires_mutation=bool(mapped_action and mapped_action.get("requires_mutation", False)),
        )

    def _plan_pexec(
        self,
        *,
        action_plan: ActionPlan,
        policy_decision: Any,
        request_id: str,
        dry_run: bool,
    ) -> dict[str, Any] | None:
        if not action_plan.actions or policy_decision.privilege_mode == "none":
            return None
        action = action_plan.actions[0]
        planned = self.pexec_planner.plan(
            PExecRequest(
                action_id=action.action_id,
                args=dict(action.args),
                request_id=request_id,
                privilege_mode=policy_decision.privilege_mode,
                approval_scope=policy_decision.approval_scope,
                dry_run=dry_run,
            )
        )
        payload = asdict(planned)
        payload["shell_preview"] = self.pexec_planner.shell_preview(planned) if planned.command else ""
        return payload

    def _decide_path(
        self,
        intent: str,
        risk_level: str,
        incident: bool,
        requested: str,
        operator_profile: dict[str, Any],
        intent_cluster: str,
        operator_id: str,
    ) -> dict[str, Any]:
        path_req = (requested or "auto").strip().lower()
        if path_req == "auto":
            decision = self.selector.decide(
                intent=intent,
                risk_level=risk_level,
                incident=incident,
                intent_cluster=intent_cluster,
                operator_id=operator_id,
            )
            path = decision.path
            reason = decision.reason
            profile_pref = str(operator_profile.get("path_preference", "balanced"))
            if (
                profile_pref == "deep_when_uncertain"
                and decision.confidence < 0.75
                and decision.path != "deep"
            ):
                path = "deep"
                reason = (
                    f"{reason} Operator preference deep_when_uncertain promoted path to deep."
                )
            return {
                "path": path,
                "confidence": decision.confidence,
                "reason": reason,
                "complexity_score": decision.complexity_score,
                "source": "selector",
                "profile_preference": profile_pref,
                "rule_applied": decision.rule_applied,
                "rule_key": decision.rule_key,
                "context_signals": list(decision.context_signals),
            }
        if path_req not in VALID_PATH:
            path_req = "deep"
        return {
            "path": path_req,
            "confidence": 0.60,
            "reason": "Path was manually forced by operator input.",
            "complexity_score": 0,
            "source": "manual",
            "profile_preference": str(operator_profile.get("path_preference", "balanced")),
            "rule_applied": False,
            "rule_key": "",
            "context_signals": [],
        }

    @staticmethod
    def _selector_prefetch_tier(
        *,
        intent: str,
        risk_level: str,
        incident: bool,
        intent_cluster: str,
    ) -> str | None:
        cluster = (intent_cluster or "").strip().lower()
        text = (intent or "").strip().lower()
        if incident or risk_level in {"medium", "high", "critical"}:
            return "warm"
        if cluster.startswith(("dns.", "network.", "service.", "package.", "security.")):
            return "warm"
        if any(
            token in text
            for token in (
                "apt",
                "dpkg",
                "package",
                "install",
                "remove",
                "upgrade",
                "service",
                "systemctl",
                "restart",
                "start",
                "stop",
                "network",
                "rede",
                "route",
                "rota",
                "dns",
                "ping",
                "resolver",
                "security",
                "seguranca",
            )
        ):
            return "warm"
        return None

    def _should_scan_system_events(
        self,
        *,
        intent: str,
        risk_level: str,
        incident: bool,
        intent_cluster: str,
    ) -> bool:
        return (
            self._selector_prefetch_tier(
                intent=intent,
                risk_level=risk_level,
                incident=incident,
                intent_cluster=intent_cluster,
            )
            is not None
        )

    def _ingest_system_events(
        self,
        *,
        intent: str,
        risk_level: str,
        incident: bool,
        intent_cluster: str,
    ) -> dict[str, Any]:
        if not self._should_scan_system_events(
            intent=intent,
            risk_level=risk_level,
            incident=incident,
            intent_cluster=intent_cluster,
        ):
            return {
                "scanned": False,
                "events_seen": 0,
                "relevant_events": 0,
                "invalidated_sources": [],
                "command_status": 0,
                "reason": "not_applicable",
            }
        result: EventSweepResult = self.system_event_monitor.sweep()
        return {
            "scanned": result.scanned,
            "events_seen": result.events_seen,
            "relevant_events": result.relevant_events,
            "invalidated_sources": list(result.invalidated_sources),
            "command_status": result.command_status,
            "reason": result.reason,
        }

    def _prefetch_selector_context(
        self,
        *,
        intent: str,
        risk_level: str,
        incident: bool,
        intent_cluster: str,
        operator_name: str,
        operator_profile: dict[str, Any],
        request_id: str,
    ) -> None:
        required_tier = self._selector_prefetch_tier(
            intent=intent,
            risk_level=risk_level,
            incident=incident,
            intent_cluster=intent_cluster,
        )
        if required_tier is None:
            return
        self._collect_context(
            operator_name=operator_name,
            operator_profile=operator_profile,
            required_tier=required_tier,
            intent_cluster=intent_cluster,
            path="fast",
            mapped_action=None,
            incident=incident,
            request_id=request_id,
        )

    @staticmethod
    def _adjust_risk_with_tone(
        risk: str,
        incident: bool,
        tone: str,
        frustration: float,
    ) -> tuple[str, bool]:
        risk_order = ["low", "medium", "high", "critical"]
        level = risk_order.index(risk)

        incident_flag = incident or tone == "incident"
        if tone == "urgent":
            level = min(level + 1, len(risk_order) - 1)
        if frustration >= 0.7:
            level = min(level + 1, len(risk_order) - 1)
        return risk_order[level], incident_flag

    def _build_plan(
        self,
        intent: str,
        risk_level: str,
        path: str,
        intent_cluster: str,
        operator_name: str,
        operator_profile: dict[str, Any] | None = None,
        incident: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        text = (intent or "").lower()
        operator_profile = operator_profile or {}
        resolved = self.registry.resolve(intent_text=text, intent_cluster=intent_cluster)
        module_plan = resolved.plan
        action = self._map_action(intent_text=text, intent_cluster=intent_cluster, module_plan=module_plan)
        effective_risk = self._max_risk_level(
            risk_level,
            str(action.get("action_risk", risk_level)) if action is not None else risk_level,
        )
        context_tier = self._determine_context_tier(
            intent=intent,
            risk_level=effective_risk,
            path=path,
            mapped_action=action,
            incident=incident,
        )
        context_snapshots = self._collect_context(
            operator_name=operator_name,
            operator_profile=operator_profile,
            required_tier=context_tier,
            intent_cluster=intent_cluster,
            path=path,
            mapped_action=action,
            incident=incident,
            request_id=request_id,
        )
        action_plan = self._build_action_plan(
            intent=intent,
            risk_level=effective_risk,
            path=path,
            context_tier=context_tier,
            mapped_action=action,
            request_id=request_id,
        )
        steps: list[str] = []
        session_snapshot = next(
            (
                snapshot
                for snapshot in context_snapshots
                if snapshot.source.startswith("runtime.session.")
            ),
            None,
        )
        if session_snapshot is not None:
            steps.append(self._context_snapshot_step(session_snapshot.payload))
        else:
            steps.append("Collect current context snapshot (runtime session unavailable).")
        for snapshot in context_snapshots:
            if session_snapshot is not None and snapshot.source == session_snapshot.source:
                continue
            steps.append(self._context_snapshot_summary_step(snapshot))

        if module_plan and module_plan.module_id == "mod_dns":
            steps.extend(module_plan.pre_checks)
            if "flush" in text or "cache" in text:
                steps.append("Prepare DNS cache maintenance action through allowlisted path.")
        elif module_plan and module_plan.module_id == "mod_services":
            steps.extend(module_plan.pre_checks)
            steps.append("Prepare service mutation through allowlisted systemctl action.")
        elif module_plan and module_plan.module_id == "mod_packages":
            steps.extend(module_plan.pre_checks)
            steps.append("Prepare package mutation through allowlisted apt action.")
        elif module_plan and module_plan.module_id == "mod_network":
            steps.extend(module_plan.pre_checks)
            steps.append("Prepare read-only network diagnostic through allowlisted action.")
        elif module_plan and module_plan.module_id == "mod_security":
            steps.extend(module_plan.pre_checks)
            if module_plan.capability == "security.incident.contain":
                steps.append("Prepare controlled service containment bound to active incident evidence.")
            elif action and action["action_id"].startswith("security.incident.plan"):
                steps.append("Prepare local incident playbook from active alerts, recent events and bounded recommendations.")
            elif action and action["action_id"].startswith("security.incident.list"):
                steps.append("Prepare local incident ledger listing with status, severity and operator decision.")
            elif action and action["action_id"].startswith("security.incident.show"):
                steps.append("Prepare local incident detail with evidence and recent activity trail.")
            elif action and action["action_id"].startswith("security.incident.resolve"):
                steps.append("Prepare local incident resolution and close matching open alerts in the ledger.")
            elif action and action["action_id"].startswith("security.incident.dismiss"):
                steps.append("Prepare local incident dismissal and close matching open alerts in the ledger.")
            elif action and action["action_id"].startswith("security.vigilance."):
                steps.append("Prepare local vigilance status from persisted system events and login-session signals.")
            elif action and action["action_id"].startswith("security.alerts.list"):
                steps.append("Prepare local listing of persisted security alerts.")
            elif action and action["action_id"].startswith("security.alerts.ack"):
                steps.append("Prepare local acknowledgement of matching security alerts.")
            elif action and action["action_id"].startswith("security.alerts.silence"):
                steps.append("Prepare local silence window for recurring security alerts.")
            else:
                steps.append("Prepare local security audit from persisted system events.")
        elif "service" in text or "systemctl" in text:
            steps.append("Inspect service status and dependencies before mutation.")
        elif "package" in text or "apt" in text:
            steps.append("Resolve package impact and lock state.")
        elif "network" in text or "rede" in text or "ping" in text or "route" in text:
            steps.append("Assess connectivity and routing diagnostics.")
        else:
            steps.append("Map intent to module capability and verify prerequisites.")

        if action:
            arg_hint = ", ".join(f"{k}={v}" for k, v in action.get("args", {}).items())
            if arg_hint:
                steps.append(
                    f"Mapped allowlisted action: {action['action_id']} ({arg_hint})."
                )
            else:
                steps.append(f"Mapped allowlisted action: {action['action_id']}.")
            for item in action.get("verify_checks", []):
                steps.append(f"Verify: {item}")
        else:
            steps.append("No allowlisted action mapped; remain in analysis-only mode.")

        if path in {"deep", "fast_with_confirm"}:
            steps.append("Generate verification checkpoints and rollback-safe next step.")
        if risk_level in {"high", "critical"}:
            steps.append("Require explicit confirmation before privileged mutation.")
        if not module_plan and resolved.attempted_modules:
            attempted = ", ".join(resolved.attempted_modules)
            steps.append(f"Module resolution attempted: {attempted}.")
        return {
            "steps": steps,
            "action": action,
            "action_plan": action_plan,
            "context_snapshots": context_snapshots,
            "context_tier": context_tier,
            "context": {
                "required_tier": context_tier,
                "snapshots": [asdict(item) for item in context_snapshots],
            },
        }

    def _execute_plan(
        self,
        action_plan: ActionPlan,
        policy_decision: Any,
        mapped_action: dict[str, Any] | None,
        pexec_plan: dict[str, Any] | None,
        request: OperatorRequest,
        request_id: str,
        operator_identity: OperatorIdentity,
        simulate_failure: bool,
    ) -> dict[str, Any]:
        if simulate_failure:
            return {
                "success": False,
                "policy_compliant": True,
                "executed": False,
                "blocked": False,
                "dry_run": False,
                "outcome": "Plan execution failed in simulation; no system mutation applied.",
                "command_error": "simulated_execution_failure",
                "returncode": 1,
                "request_id": request_id,
            }

        if not action_plan.actions or mapped_action is None:
            return {
                "success": True,
                "policy_compliant": True,
                "executed": False,
                "blocked": False,
                "dry_run": request.dry_run,
                "outcome": "No mapped allowlisted action; analysis-only response.",
                "command_error": "",
                "returncode": 0,
                "request_id": request_id,
            }

        action = action_plan.actions[0]
        action_id = action.action_id
        action_args = dict(action.args)

        if not policy_decision.allowed:
            return {
                "success": False,
                "policy_compliant": True,
                "executed": False,
                "blocked": True,
                "dry_run": request.dry_run,
                "outcome": policy_decision.reason,
                "command_error": "policy_blocked",
                "returncode": 0,
                "action_id": action_id,
                "request_id": request_id,
            }

        if (
            policy_decision.requires_confirmation
            and request.execute
            and not request.dry_run
            and not request.approve
        ):
            return {
                "success": False,
                "policy_compliant": True,
                "executed": False,
                "blocked": True,
                "dry_run": request.dry_run,
                "outcome": (
                    f"Execution requires confirmation for '{action_id}'. "
                    "Use --approve."
                ),
                "command_error": "confirmation_required",
                "returncode": 0,
                "action_id": action_id,
                "request_id": request_id,
            }

        if (
            policy_decision.requires_step_up
            and request.execute
            and not request.dry_run
            and not request.allow_high_risk
        ):
            return {
                "success": False,
                "policy_compliant": True,
                "executed": False,
                "blocked": True,
                "dry_run": request.dry_run,
                "outcome": (
                    f"Blocked stepped-up action '{action_id}'. "
                    "Use --allow-high-risk (and --approve when required)."
                ),
                "command_error": "step_up_required",
                "returncode": 0,
                "action_id": action_id,
                "request_id": request_id,
            }

        if (
            action_id.startswith("security.audit.")
            or action_id.startswith("security.incident.")
            or action_id.startswith("security.vigilance.")
            or action_id.startswith("security.alerts.")
        ):
            result = self._execute_local_security_action(
                action_id=action_id,
                action_args=action_args,
                request=request,
                request_id=request_id,
                operator_id=operator_identity.operator_id,
            )
            return self._finalize_execution_result(action_id=action_id, request=request, result=result)

        if not request.execute:
            return {
                "success": True,
                "policy_compliant": True,
                "executed": False,
                "blocked": False,
                "dry_run": request.dry_run,
                "outcome": (
                    f"Mapped action '{action_id}' ready. "
                    "Run with --execute to perform (or --execute --dry-run to validate)."
                ),
                "command_error": "",
                "returncode": 0,
                "action_id": action_id,
                "request_id": request_id,
            }

        if (
            mapped_action is not None
            and str(mapped_action.get("module_id", "")) == "mod_security"
            and str(mapped_action.get("capability", "")) == "security.incident.contain"
        ):
            incident_validation = self._validate_security_incident_containment(
                action_id=action_id,
                action_args=action_args,
            )
            if not incident_validation.get("allowed", False):
                return {
                    "success": False,
                    "policy_compliant": True,
                    "executed": False,
                    "blocked": True,
                    "dry_run": request.dry_run,
                    "outcome": str(incident_validation.get("reason", "Incident containment validation failed.")),
                    "command_error": "incident_validation_failed",
                    "returncode": 0,
                    "action_id": action_id,
                    "request_id": request_id,
                    "incident_validation": incident_validation,
                }

        if policy_decision.privilege_mode == "none":
            result = self._execute_direct_allowlisted_action(
                action_id=action_id,
                action_args=action_args,
                request=request,
                request_id=request_id,
            )
            return self._finalize_execution_result(action_id=action_id, request=request, result=result)

        if pexec_plan is None or not pexec_plan.get("ok", False):
            return {
                "success": False,
                "policy_compliant": True,
                "executed": False,
                "blocked": True,
                "dry_run": request.dry_run,
                "outcome": f"Unable to plan privileged execution for '{action_id}'.",
                "command_error": "pexec_planning_failed",
                "returncode": 2,
                "action_id": action_id,
                "request_id": request_id,
                "pexec_plan": pexec_plan,
            }

        if policy_decision.privilege_mode == "broker":
            result = self._execute_broker_action(
                action_id=action_id,
                action_args=action_args,
                request=request,
                request_id=request_id,
                operator_identity=operator_identity,
                policy_decision=policy_decision,
                pexec_plan=pexec_plan,
            )
            return self._finalize_execution_result(action_id=action_id, request=request, result=result)

        cmd = list(pexec_plan.get("command", []))
        started = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                check=False,
                timeout=max(self._action_timeout(action_id) + 5, 30),
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "policy_compliant": True,
                "executed": True,
                "blocked": False,
                "dry_run": request.dry_run,
                "outcome": f"Action '{action_id}' timed out.",
                "command_error": "execution_timeout",
                "returncode": 124,
                "action_id": action_id,
                "request_id": request_id,
                "transport": policy_decision.privilege_mode,
                "pexec_plan": pexec_plan,
                "duration_ms": int((time.monotonic() - started) * 1000),
            }

        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        payload: dict[str, Any] = {}
        if stdout:
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                payload = {}

        ok_flag = bool(payload.get("ok", proc.returncode == 0))
        success = proc.returncode == 0 and ok_flag
        command_error = ""
        if not success:
            if payload.get("error"):
                command_error = str(payload.get("error", "")).strip()
            elif stderr:
                command_error = stderr.splitlines()[-1]
            elif stdout:
                command_error = stdout.splitlines()[-1]

        outcome = self._execution_outcome(
            action_id=action_id,
            success=success,
            payload=payload,
            stderr=stderr,
            dry_run=request.dry_run,
        )
        result = {
            "success": success,
            "policy_compliant": True,
            "executed": True,
            "blocked": False,
            "dry_run": request.dry_run,
            "outcome": outcome,
            "command_error": command_error,
            "returncode": proc.returncode,
            "action_id": action_id,
            "request_id": request_id,
            "duration_ms": duration_ms,
            "stdout": payload.get("stdout", stdout),
            "stderr": payload.get("stderr", stderr),
            "command": cmd,
            "action_args": action_args,
            "transport": policy_decision.privilege_mode,
            "pexec_plan": pexec_plan,
        }
        return self._finalize_execution_result(action_id=action_id, request=request, result=result)

    @staticmethod
    def _broker_approval_ttl_s(policy_decision: Any) -> int:
        scope = str(policy_decision.approval_scope or "single_action")
        risk = str(policy_decision.risk_level or "medium")
        ttl_s = 300 if scope == "time_window" else 120
        if risk in {"high", "critical"}:
            ttl_s = min(ttl_s, 90)
        return ttl_s

    def _issue_broker_approval(
        self,
        *,
        action_id: str,
        action_args: dict[str, str],
        request_id: str,
        operator_identity: OperatorIdentity,
        policy_decision: Any,
    ) -> tuple[str, dict[str, Any]]:
        scope = str(policy_decision.approval_scope or "single_action")
        if scope == "none":
            scope = "single_action"
        payload, returncode = self.broker_client.issue_approval(
            action_id=action_id,
            args=action_args,
            request_id=request_id,
            operator_id=operator_identity.operator_id,
            session_id=operator_identity.session_id,
            approval_scope=scope,
            risk_level=str(policy_decision.risk_level or "medium"),
            ttl_s=self._broker_approval_ttl_s(policy_decision),
        )
        if returncode != 0 or not payload.get("ok", False):
            raise RuntimeError(str(payload.get("error", "unable to issue broker approval token")))
        token = str(payload.get("approval_token", "")).strip()
        if not token:
            raise RuntimeError("broker approval token missing from broker response")
        approval = {
            "approval_ref": str(payload.get("approval_ref", "")).strip(),
            "approval_scope": str(payload.get("approval_scope", scope)).strip(),
            "expires_at_utc": str(payload.get("expires_at_utc", "")).strip(),
            "risk_level": str(payload.get("risk_level", policy_decision.risk_level)).strip(),
        }
        return token, approval

    def _execute_broker_action(
        self,
        *,
        action_id: str,
        action_args: dict[str, str],
        request: OperatorRequest,
        request_id: str,
        operator_identity: OperatorIdentity,
        policy_decision: Any,
        pexec_plan: dict[str, Any],
    ) -> dict[str, Any]:
        started = time.monotonic()
        approval: dict[str, Any] = {}
        approval_token = ""
        try:
            if not request.dry_run:
                approval_token, approval = self._issue_broker_approval(
                    action_id=action_id,
                    action_args=action_args,
                    request_id=request_id,
                    operator_identity=operator_identity,
                    policy_decision=policy_decision,
                )
            payload, returncode = self.broker_client.exec_action(
                action_id=action_id,
                args=action_args,
                request_id=request_id,
                approval_token=approval_token,
                dry_run=request.dry_run,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "policy_compliant": True,
                "executed": True,
                "blocked": False,
                "dry_run": request.dry_run,
                "outcome": f"Broker execution failed for '{action_id}'.",
                "command_error": str(exc),
                "returncode": 2,
                "action_id": action_id,
                "request_id": request_id,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "stdout": "",
                "stderr": str(exc),
                "command": list(pexec_plan.get("command", [])),
                "action_args": action_args,
                "transport": "broker",
                "pexec_plan": pexec_plan,
                "broker_approval": approval,
            }

        duration_ms = int((time.monotonic() - started) * 1000)
        success = returncode == 0 and bool(payload.get("ok", returncode == 0))
        stderr = str(payload.get("stderr", "")).strip()
        command_error = ""
        if not success:
            command_error = str(payload.get("error", "")).strip() or stderr
        outcome = self._execution_outcome(
            action_id=action_id,
            success=success,
            payload=payload,
            stderr=stderr,
            dry_run=request.dry_run,
        )
        return {
            "success": success,
            "policy_compliant": True,
            "executed": True,
            "blocked": False,
            "dry_run": request.dry_run,
            "outcome": outcome,
            "command_error": command_error,
            "returncode": returncode,
            "action_id": action_id,
            "request_id": request_id,
            "duration_ms": duration_ms,
            "stdout": str(payload.get("stdout", "")).strip(),
            "stderr": stderr,
            "command": list(pexec_plan.get("command", [])),
            "action_args": action_args,
            "transport": "broker",
            "pexec_plan": pexec_plan,
            "broker_approval": approval,
        }

    def _finalize_execution_result(
        self,
        *,
        action_id: str,
        request: OperatorRequest,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        invalidated_sources: list[str] = []
        if result.get("success") and result.get("executed") and not request.dry_run:
            invalidated_sources = self._invalidate_context_for_action(action_id)
        result["invalidated_context_sources"] = invalidated_sources
        return result

    def _invalidate_context_for_action(self, action_id: str) -> list[str]:
        sources = self._context_sources_for_action(action_id)
        if not sources:
            return []
        self.context_store.invalidate_sources(sources)
        return sources

    @staticmethod
    def _context_sources_for_action(action_id: str) -> list[str]:
        if action_id.startswith("service.systemctl."):
            return ["services.summary", "journal.alerts"]
        if action_id.startswith("package.apt."):
            return ["host.system", "services.summary", "journal.alerts"]
        if action_id.startswith("dns.unbound."):
            return ["journal.alerts"]
        if action_id.startswith("network.") and not action_id.startswith("network.diagnose."):
            return ["network.summary", "journal.alerts"]
        return []

    def _execute_direct_allowlisted_action(
        self,
        *,
        action_id: str,
        action_args: dict[str, str],
        request: OperatorRequest,
        request_id: str,
    ) -> dict[str, Any]:
        try:
            spec = self.action_catalog[action_id]
            clean_args = validate_action_args(action_id, spec, action_args)
            command = build_allowlisted_command(action_id, spec, clean_args)
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "policy_compliant": True,
                "executed": False,
                "blocked": True,
                "dry_run": request.dry_run,
                "outcome": f"Action '{action_id}' failed local validation: {exc}",
                "command_error": "validation_failed",
                "returncode": 2,
                "action_id": action_id,
                "request_id": request_id,
            }

        if request.dry_run:
            return {
                "success": True,
                "policy_compliant": True,
                "executed": False,
                "blocked": False,
                "dry_run": True,
                "outcome": f"Dry-run validated for direct allowlisted action '{action_id}'.",
                "command_error": "",
                "returncode": 0,
                "action_id": action_id,
                "request_id": request_id,
                "command": command,
                "action_args": clean_args,
                "transport": "direct",
            }

        started = time.monotonic()
        try:
            proc = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=self._action_timeout(action_id),
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "policy_compliant": True,
                "executed": True,
                "blocked": False,
                "dry_run": False,
                "outcome": f"Action '{action_id}' timed out.",
                "command_error": "execution_timeout",
                "returncode": 124,
                "action_id": action_id,
                "request_id": request_id,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "transport": "direct",
                "command": command,
            }

        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        success = proc.returncode == 0
        command_error = ""
        if not success:
            command_error = stderr.splitlines()[-1] if stderr else stdout.splitlines()[-1] if stdout else ""
        outcome = self._execution_outcome(
            action_id=action_id,
            success=success,
            payload={},
            stderr=stderr,
            dry_run=False,
        )
        return {
            "success": success,
            "policy_compliant": True,
            "executed": True,
            "blocked": False,
            "dry_run": False,
            "outcome": outcome,
            "command_error": command_error,
            "returncode": proc.returncode,
            "action_id": action_id,
            "request_id": request_id,
            "duration_ms": duration_ms,
            "stdout": stdout,
            "stderr": stderr,
            "command": command,
            "action_args": clean_args,
            "transport": "direct",
        }

    def _execute_local_security_action(
        self,
        *,
        action_id: str,
        action_args: dict[str, str],
        request: OperatorRequest,
        request_id: str,
        operator_id: str,
    ) -> dict[str, Any]:
        if action_id.startswith("security.incident."):
            return self._execute_local_security_incident_action(
                action_id=action_id,
                action_args=action_args,
                request=request,
                request_id=request_id,
                operator_id=operator_id,
            )
        if action_id.startswith("security.alerts."):
            return self._execute_local_security_alert_action(
                action_id=action_id,
                action_args=action_args,
                request=request,
                request_id=request_id,
                operator_id=operator_id,
            )
        if action_id.startswith("security.vigilance."):
            return self._execute_local_security_vigilance_action(
                action_id=action_id,
                action_args=action_args,
                request=request,
                request_id=request_id,
            )
        category = str(action_args.get("category", "all")).strip().lower() or "all"
        try:
            limit = max(1, min(int(action_args.get("limit", "5")), 20))
        except Exception:  # noqa: BLE001
            limit = 5

        cutoff = (dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(hours=24)).isoformat()
        where = "WHERE ts_utc >= ?"
        params: list[Any] = [cutoff]
        if category != "all":
            where += " AND category = ?"
            params.append(category)

        conn = sqlite3.connect(self.profiler.db_path)
        conn.row_factory = sqlite3.Row
        try:
            counts = conn.execute(
                f"""
                SELECT category, COUNT(*) AS total
                FROM system_events
                {where}
                GROUP BY category
                ORDER BY total DESC, category ASC
                """,
                params,
            ).fetchall()
            recent = conn.execute(
                f"""
                SELECT ts_utc, category, source, summary
                FROM system_events
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params + [limit],
            ).fetchall()
        finally:
            conn.close()

        if not recent:
            summary = (
                f"Local security audit found no recent events for category '{category}' in the last 24h."
                if category != "all"
                else "Local security audit found no recent events in the last 24h."
            )
        else:
            counts_text = ", ".join(f"{row['category']}={row['total']}" for row in counts) or "none"
            recent_text = " | ".join(
                f"{row['category']}:{row['summary']}" for row in recent
            )
            summary = f"Local security audit summary: {counts_text}. Recent: {recent_text}"

        return {
            "success": True,
            "policy_compliant": True,
            "executed": True,
            "blocked": False,
            "dry_run": request.dry_run,
            "outcome": summary,
            "command_error": "",
            "returncode": 0,
            "action_id": action_id,
            "request_id": request_id,
            "stdout": summary,
            "stderr": "",
            "command": [],
            "action_args": {"category": category, "limit": str(limit)},
            "transport": "local",
        }

    def _execute_local_security_incident_action(
        self,
        *,
        action_id: str,
        action_args: dict[str, str],
        request: OperatorRequest,
        request_id: str,
        operator_id: str,
    ) -> dict[str, Any]:
        if action_id == "security.incident.list":
            status = str(action_args.get("status", "active")).strip().lower() or "active"
            category = str(action_args.get("category", "all")).strip().lower() or "all"
            severity = str(action_args.get("severity", "all")).strip().lower() or "all"
            fingerprint = str(action_args.get("fingerprint", "")).strip().lower()
            try:
                limit = max(1, min(int(action_args.get("limit", "5")), 50))
            except Exception:  # noqa: BLE001
                limit = 5

            self.security_watch.run_once(max_events=max(limit * 4, 16))
            incidents = self.security_watch.list_incidents(
                limit=limit,
                status=status,
                category=category,
                severity=severity,
                fingerprint=fingerprint,
            )
            if not incidents:
                scope_bits = [f"status '{status}'"]
                if category != "all":
                    scope_bits.append(f"category '{category}'")
                if severity != "all":
                    scope_bits.append(f"severity '{severity}'")
                if fingerprint:
                    scope_bits.append(f"fingerprint '{fingerprint}'")
                summary = "No incident ledger rows found for " + ", ".join(scope_bits) + "."
            else:
                items = " | ".join(
                    (
                        f"{row['incident_id']} [{row['status']}] {row['severity']} "
                        f"{row['category']} {row['fingerprint']} "
                        f"units={','.join(row['correlated_units']) or 'none'}"
                    )
                    for row in incidents
                )
                summary = f"Incident ledger: {items}"
            return {
                "success": True,
                "policy_compliant": True,
                "executed": True,
                "blocked": False,
                "dry_run": request.dry_run,
                "outcome": summary,
                "command_error": "",
                "returncode": 0,
                "action_id": action_id,
                "request_id": request_id,
                "stdout": summary,
                "stderr": "",
                "command": [],
                "action_args": {
                    "status": status,
                    "category": category,
                    "severity": severity,
                    "fingerprint": fingerprint,
                    "limit": str(limit),
                },
                "transport": "local",
                "incidents": incidents,
            }

        if action_id == "security.incident.show":
            incident_id = str(action_args.get("incident_id", "")).strip().lower()
            try:
                activity_limit = max(1, min(int(action_args.get("activity_limit", "10")), 20))
            except Exception:  # noqa: BLE001
                activity_limit = 10
            self.security_watch.run_once(max_events=16)
            incident = self.security_watch.get_incident(
                incident_id,
                activity_limit=activity_limit,
            )
            if incident is None:
                summary = f"Incident '{incident_id}' was not found in the local ledger."
            else:
                alerts_text = ", ".join(
                    f"#{row['id']}:{row['fingerprint']}/{row['status']}"
                    for row in incident.get("alerts", [])[:5]
                ) or "none"
                activity_text = " | ".join(
                    f"{row['ts_utc']} {row['action_id']} {row['status_from']}->{row['status_to']}"
                    for row in incident.get("activity", [])[:activity_limit]
                ) or "none"
                units = ",".join(incident.get("correlated_units", ())) or "none"
                summary = (
                    f"Incident {incident['incident_id']} [{incident['status']}] "
                    f"{incident['severity']} {incident['category']} {incident['fingerprint']}. "
                    f"Units={units}. Latest={incident['latest_summary'] or 'n/a'}. "
                    f"Alerts={alerts_text}. Activity={activity_text}"
                )
            return {
                "success": True,
                "policy_compliant": True,
                "executed": True,
                "blocked": False,
                "dry_run": request.dry_run,
                "outcome": summary,
                "command_error": "",
                "returncode": 0,
                "action_id": action_id,
                "request_id": request_id,
                "stdout": summary,
                "stderr": "",
                "command": [],
                "action_args": {
                    "incident_id": incident_id,
                    "activity_limit": str(activity_limit),
                },
                "transport": "local",
                "incident": incident,
            }

        if action_id in {"security.incident.resolve", "security.incident.dismiss"}:
            incident_id = str(action_args.get("incident_id", "")).strip().lower()
            target_status = "resolved" if action_id.endswith(".resolve") else "dismissed"
            result = self.security_watch.update_incident_status(
                incident_id,
                status=target_status,
                operator_id=operator_id,
                request_id=request_id,
            )
            summary = str(result["summary"])
            return {
                "success": True,
                "policy_compliant": True,
                "executed": True,
                "blocked": False,
                "dry_run": request.dry_run,
                "outcome": summary,
                "command_error": "",
                "returncode": 0,
                "action_id": action_id,
                "request_id": request_id,
                "stdout": summary,
                "stderr": "",
                "command": [],
                "action_args": {
                    "incident_id": incident_id,
                    "status": target_status,
                },
                "transport": "local",
                "incident": result.get("incident"),
            }

        category = str(action_args.get("category", "all")).strip().lower() or "all"
        severity = str(action_args.get("severity", "all")).strip().lower() or "all"
        fingerprint = str(action_args.get("fingerprint", "")).strip().lower()
        try:
            limit = max(1, min(int(action_args.get("limit", "3")), 10))
        except Exception:  # noqa: BLE001
            limit = 3
        try:
            window_hours = max(1, min(int(action_args.get("window_hours", "24")), 72))
        except Exception:  # noqa: BLE001
            window_hours = 24

        self.security_watch.run_once(max_events=max(limit * 4, 16))
        playbook = self.security_watch.build_incident_playbook(
            category=category,
            severity=severity,
            fingerprint=fingerprint,
            limit=limit,
            window_hours=window_hours,
        )
        summary = str(playbook["summary"])
        return {
            "success": True,
            "policy_compliant": True,
            "executed": True,
            "blocked": False,
            "dry_run": request.dry_run,
            "outcome": summary,
            "command_error": "",
            "returncode": 0,
            "action_id": action_id,
            "request_id": request_id,
            "stdout": summary,
            "stderr": "",
            "command": [],
            "action_args": {
                "category": category,
                "severity": severity,
                "fingerprint": fingerprint,
                "limit": str(limit),
                "window_hours": str(window_hours),
            },
            "transport": "local",
            "incident_playbook": playbook,
        }

    def _execute_local_security_vigilance_action(
        self,
        *,
        action_id: str,
        action_args: dict[str, str],
        request: OperatorRequest,
        request_id: str,
    ) -> dict[str, Any]:
        category = str(action_args.get("category", "all")).strip().lower() or "all"
        try:
            window_hours = max(1, min(int(action_args.get("window_hours", "6")), 24))
        except Exception:  # noqa: BLE001
            window_hours = 6
        vigilance = self.security_watch.summarize_vigilance(
            category=category,
            window_hours=window_hours,
        )
        summary = str(vigilance["summary"])

        return {
            "success": True,
            "policy_compliant": True,
            "executed": True,
            "blocked": False,
            "dry_run": request.dry_run,
            "outcome": summary,
            "command_error": "",
            "returncode": 0,
            "action_id": action_id,
            "request_id": request_id,
            "stdout": summary,
            "stderr": "",
            "command": [],
            "action_args": {"category": category, "window_hours": str(window_hours)},
            "transport": "local",
        }

    def _execute_local_security_alert_action(
        self,
        *,
        action_id: str,
        action_args: dict[str, str],
        request: OperatorRequest,
        request_id: str,
        operator_id: str,
    ) -> dict[str, Any]:
        category = str(action_args.get("category", "all")).strip().lower() or "all"
        severity = str(action_args.get("severity", "all")).strip().lower() or "all"
        fingerprint = str(action_args.get("fingerprint", "")).strip().lower()
        alert_ids = [
            int(item)
            for item in str(action_args.get("alert_ids", "")).split(",")
            if item.strip().isdigit() and int(item.strip()) > 0
        ]

        if action_id == "security.alerts.list":
            try:
                limit = max(1, min(int(action_args.get("limit", "5")), 20))
            except Exception:  # noqa: BLE001
                limit = 5
            self.security_watch.run_once(max_events=max(limit * 4, 16))
            alerts = self.security_watch.list_recent_alerts(
                limit=limit,
                category=category,
                severity=severity,
                fingerprint=fingerprint,
            )
            if not alerts:
                scope_bits = []
                if category != "all":
                    scope_bits.append(f"category '{category}'")
                if severity != "all":
                    scope_bits.append(f"severity '{severity}'")
                if fingerprint:
                    scope_bits.append(f"fingerprint '{fingerprint}'")
                if scope_bits:
                    summary = "No recent security alerts found for " + ", ".join(scope_bits) + "."
                else:
                    summary = "No recent security alerts found."
            else:
                items = " | ".join(
                    f"#{row['id']} {row['severity']} {row['fingerprint']} ({row['status']}): {row['summary']}"
                    for row in alerts
                )
                summary = f"Recent security alerts: {items}"
            action_payload = {
                "category": category,
                "severity": severity,
                "fingerprint": fingerprint,
                "limit": str(limit),
            }
        elif action_id == "security.alerts.ack":
            try:
                limit = max(1, min(int(action_args.get("limit", "1")), 10))
            except Exception:  # noqa: BLE001
                limit = 1
            result = self.security_watch.acknowledge_alerts(
                alert_ids=alert_ids,
                limit=limit,
                category=category,
                severity=severity,
                fingerprint=fingerprint,
                operator_id=operator_id,
                request_id=request_id,
            )
            summary = str(result["summary"])
            action_payload = {
                "category": category,
                "severity": severity,
                "fingerprint": fingerprint,
                "limit": str(limit),
                "alert_ids": ",".join(str(item) for item in alert_ids),
            }
        else:
            try:
                silence_hours = max(1, min(int(action_args.get("silence_hours", "6")), 168))
            except Exception:  # noqa: BLE001
                silence_hours = 6
            try:
                limit = max(1, min(int(action_args.get("limit", "1")), 10))
            except Exception:  # noqa: BLE001
                limit = 1
            result = self.security_watch.silence_alerts(
                alert_ids=alert_ids,
                silence_hours=silence_hours,
                limit=limit,
                category=category,
                severity=severity,
                fingerprint=fingerprint,
                operator_id=operator_id,
                request_id=request_id,
            )
            summary = str(result["summary"])
            action_payload = {
                "category": category,
                "severity": severity,
                "fingerprint": fingerprint,
                "silence_hours": str(silence_hours),
                "limit": str(limit),
                "alert_ids": ",".join(str(item) for item in alert_ids),
            }

        return {
            "success": True,
            "policy_compliant": True,
            "executed": True,
            "blocked": False,
            "dry_run": request.dry_run,
            "outcome": summary,
            "command_error": "",
            "returncode": 0,
            "action_id": action_id,
            "request_id": request_id,
            "stdout": summary,
            "stderr": "",
            "command": [],
            "action_args": action_payload,
            "transport": "local",
        }

    def _validate_security_incident_containment(
        self,
        *,
        action_id: str,
        action_args: dict[str, str],
    ) -> dict[str, Any]:
        unit = str(action_args.get("unit", "")).strip().lower()
        category = str(action_args.get("category", "service")).strip().lower() or "service"
        severity = str(action_args.get("severity", "all")).strip().lower() or "all"
        fingerprint = str(action_args.get("fingerprint", "")).strip().lower()
        self.security_watch.run_once(max_events=32)
        return self.security_watch.validate_incident_containment(
            action_id=action_id,
            unit=unit,
            category=category,
            severity=severity,
            fingerprint=fingerprint,
        )

    def _record_security_incident_execution(
        self,
        *,
        mapped_action: dict[str, Any] | None,
        execution: dict[str, Any],
        operator_identity: OperatorIdentity,
        request_id: str,
    ) -> dict[str, Any] | None:
        if mapped_action is None:
            return None
        if str(mapped_action.get("module_id", "")) != "mod_security":
            return None
        if str(mapped_action.get("capability", "")) != "security.incident.contain":
            return None
        args = dict(mapped_action.get("args", {}))
        return self.security_watch.record_incident_action(
            action_id=str(mapped_action.get("action_id", "")),
            category=str(args.get("category", "all")),
            severity=str(args.get("severity", "all")),
            fingerprint=str(args.get("fingerprint", "")),
            unit=str(args.get("unit", "")),
            request_id=request_id,
            operator_id=operator_identity.operator_id,
            dry_run=bool(execution.get("dry_run", False)),
            success=bool(execution.get("success", False)),
            blocked=bool(execution.get("blocked", False)),
            command_error=str(execution.get("command_error", "")),
            outcome=str(execution.get("outcome", "")),
            extra={
                "transport": execution.get("transport", ""),
                "returncode": execution.get("returncode", 0),
                "broker_approval": execution.get("broker_approval", {}),
            },
        )

    @staticmethod
    def _execution_outcome(
        action_id: str,
        success: bool,
        payload: dict[str, Any],
        stderr: str,
        dry_run: bool,
    ) -> str:
        if success and dry_run:
            return f"Dry-run validated for '{action_id}'."
        if success:
            detail = str(payload.get("stdout", "")).strip()
            if detail:
                return f"Action '{action_id}' executed successfully: {detail}"
            return f"Action '{action_id}' executed successfully."
        if payload.get("error"):
            return f"Action '{action_id}' failed: {payload['error']}"
        if stderr:
            return f"Action '{action_id}' failed: {stderr.splitlines()[-1]}"
        return f"Action '{action_id}' failed."

    def _map_action(
        self,
        intent_text: str,
        intent_cluster: str,
        module_plan: Any | None = None,
    ) -> dict[str, Any] | None:
        del intent_text, intent_cluster

        if module_plan is not None:
            action = self._action(module_plan.action_id, module_plan.args)
            action["module_id"] = module_plan.module_id
            action["capability"] = module_plan.capability
            action["verify_checks"] = list(module_plan.verify_checks)
            action["rollback_hint"] = module_plan.rollback_hint
            return action

        return None

    def _action(self, action_id: str, args: dict[str, str] | None = None) -> dict[str, Any]:
        return {
            "action_id": action_id,
            "args": args or {},
            "action_risk": self.action_risk.get(action_id, "unknown"),
            "requires_privilege": self._action_requires_privilege(action_id),
            "requires_mutation": self._action_requires_mutation(action_id),
        }

    def _load_action_catalog(self) -> dict[str, dict[str, Any]]:
        path = self.repo_root / "config" / "privilege" / "actions.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        actions = raw.get("actions", {})
        out: dict[str, dict[str, Any]] = {}
        if isinstance(actions, dict):
            for aid, spec in actions.items():
                if isinstance(spec, dict):
                    out[str(aid)] = spec
        return out

    def _load_action_risk(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for action_id, spec in self.action_catalog.items():
            out[action_id] = str(spec.get("risk", "unknown"))
        return out

    def _action_timeout(self, action_id: str) -> int:
        spec = self.action_catalog.get(action_id, {})
        try:
            return int(spec.get("timeout_sec", 30))
        except Exception:  # noqa: BLE001
            return 30

    @staticmethod
    def _utc_now() -> str:
        return dt.datetime.now(tz=dt.timezone.utc).isoformat()

    @staticmethod
    def _default_core_log_path(db_path: Path | str | None) -> Path:
        if db_path:
            base = Path(db_path)
            return base.with_name("mastercontrold.log")
        return Path.home() / ".local" / "share" / "mastercontrol" / "mastercontrold.log"

    @staticmethod
    def _make_request_id() -> str:
        return f"mc-{uuid.uuid4().hex[:12]}"

    def _append_core_log(self, entry: dict[str, Any]) -> None:
        try:
            self.core_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.core_log_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(entry, ensure_ascii=True) + "\n")
        except OSError:
            return


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mastercontrold",
        description="MasterControl daemon prototype (humanized + path selector)",
    )
    p.add_argument("--profile", default=None, help="Path to soul profile YAML")
    p.add_argument("--json", action="store_true", help="Output JSON payload")
    p.add_argument("--operator-name", default="Irving")
    p.add_argument("--intent", required=True, help="Operator intent in natural language")
    p.add_argument("--risk-level", default="medium", choices=sorted(VALID_RISK))
    p.add_argument("--incident", action="store_true")
    p.add_argument(
        "--path",
        default="auto",
        choices=["auto"] + sorted(VALID_PATH),
        help="auto lets MasterControl choose fast/deep path",
    )
    p.add_argument("--execute", action="store_true", help="Execute mapped allowlisted action")
    p.add_argument("--dry-run", action="store_true", help="Validate action execution without mutation")
    p.add_argument("--approve", action="store_true", help="Approve execution when confirmation is required")
    p.add_argument(
        "--allow-high-risk",
        action="store_true",
        help="Allow high-risk mapped actions (still requires approval when applicable)",
    )
    p.add_argument("--request-id", default="", help="Optional correlation ID")
    p.add_argument("--simulate-failure", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    daemon = MasterControlD(Path(args.profile) if args.profile else None)
    req = OperatorRequest(
        operator_name=args.operator_name,
        intent=args.intent,
        risk_level=args.risk_level,
        incident=bool(args.incident),
        requested_path=args.path,
        execute=bool(args.execute),
        dry_run=bool(args.dry_run),
        approve=bool(args.approve),
        allow_high_risk=bool(args.allow_high_risk),
        request_id=args.request_id,
        simulate_failure=bool(args.simulate_failure),
    )
    result = daemon.handle(req)

    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0

    print(result["message"])
    print("\nPath decision:")
    print(
        f"- {result['path']['path']} ({result['path']['source']}), "
        f"confidence={result['path']['confidence']:.2f}"
    )
    print(f"- reason: {result['path']['reason']}")
    print(
        f"- profile_preference: {result['path'].get('profile_preference', 'balanced')}"
    )
    if result["path"].get("rule_applied"):
        print(f"- learned_rule: {result['path'].get('rule_key', '')}")

    print("\nTone analysis:")
    print(
        f"- tone={result['tone']['tone']}, "
        f"cluster={result['tone']['intent_cluster']}, "
        f"intent_source={result['tone'].get('intent_source', 'heuristic')}, "
        f"intent_conf={result['tone'].get('intent_confidence', 0.0):.2f}, "
        f"frustration={result['tone']['frustration_score']:.2f}"
    )
    print(f"- latency_ms={result['latency_ms']}")

    print("\nExecution:")
    mapped = result.get("mapped_action")
    print(f"- request_id: {result.get('request_id', '')}")
    print(f"- mapped_action: {mapped['action_id'] if mapped else 'none'}")
    print(
        f"- executed={result['execution'].get('executed', False)}, "
        f"blocked={result['execution'].get('blocked', False)}, "
        f"dry_run={result['execution'].get('dry_run', False)}"
    )
    print(
        f"- success={result['execution']['success']}, "
        f"rc={result['execution'].get('returncode', 0)}"
    )
    print(f"- outcome: {result['execution']['outcome']}")
    if result["execution"].get("command_error"):
        print(f"- command_error: {result['execution']['command_error']}")

    print("\nReflection status:")
    print(f"- status: {result['reflection']['status']}")
    if result["reflection"]["suggestions"]:
        print("- suggestions:")
        for item in result["reflection"]["suggestions"]:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
