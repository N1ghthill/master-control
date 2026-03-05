#!/usr/bin/env python3
"""MasterControl daemon prototype with humanized response pipeline."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from mastercontrol.context.mc_operator_profiler import OperatorEvent, OperatorProfiler
    from mastercontrol.modules.mod_dns import DNSModule
    from mastercontrol.modules.mod_network import NetworkModule
    from mastercontrol.modules.mod_packages import PackageModule
    from mastercontrol.modules.mod_services import ServiceModule
    from mastercontrol.modules.registry import ModuleRegistry
    from mastercontrol.tone.mc_tone_analyzer import ToneAnalyzer
    from mastercontrol.core.humanized_kernel import SoulKernel, load_profile
    from mastercontrol.core.path_selector import PathSelector, VALID_PATH, VALID_RISK
except ImportError:  # pragma: no cover
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from mastercontrol.context.mc_operator_profiler import OperatorEvent, OperatorProfiler  # type: ignore
    from mastercontrol.modules.mod_dns import DNSModule  # type: ignore
    from mastercontrol.modules.mod_network import NetworkModule  # type: ignore
    from mastercontrol.modules.mod_packages import PackageModule  # type: ignore
    from mastercontrol.modules.mod_services import ServiceModule  # type: ignore
    from mastercontrol.modules.registry import ModuleRegistry  # type: ignore
    from mastercontrol.tone.mc_tone_analyzer import ToneAnalyzer  # type: ignore
    from mastercontrol.core.humanized_kernel import SoulKernel, load_profile  # type: ignore
    from mastercontrol.core.path_selector import PathSelector, VALID_PATH, VALID_RISK  # type: ignore


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

    def __init__(self, profile_path: Path | None = None) -> None:
        profile = load_profile(profile_path)
        self.soul = SoulKernel(profile)
        self.profiler = OperatorProfiler()
        self.tone = ToneAnalyzer()

        self.repo_root = Path(__file__).resolve().parents[2]
        self.mc_root_action = self.repo_root / "scripts" / "mc-root-action"
        self.core_log_path = Path.home() / ".local" / "share" / "mastercontrol" / "mastercontrold.log"
        self.action_risk = self._load_action_risk()
        self.selector = PathSelector(db_path=self.profiler.db_path)
        self.dns_module = DNSModule()
        self.network_module = NetworkModule()
        self.service_module = ServiceModule()
        self.package_module = PackageModule()
        self.registry = ModuleRegistry(
            modules=[self.service_module, self.package_module, self.network_module, self.dns_module]
        )

    def handle(self, req: OperatorRequest) -> dict[str, Any]:
        t0 = time.monotonic()
        request_id = req.request_id.strip() or self._make_request_id()

        risk = self._normalize_risk(req.risk_level)
        tone_result = self.tone.analyze(req.intent, mode="heuristic")
        operator_profile = self.profiler.get_profile(req.operator_name.lower())

        risk, incident = self._adjust_risk_with_tone(
            risk=risk,
            incident=req.incident,
            tone=tone_result.tone,
            frustration=tone_result.frustration_score,
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
        )
        plan = plan_bundle["steps"]
        mapped_action = plan_bundle.get("action")

        execution = self._execute_plan(
            mapped_action=mapped_action,
            path=path_decision["path"],
            request=req,
            request_id=request_id,
            simulate_failure=req.simulate_failure,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        mapped_id = mapped_action["action_id"] if mapped_action else "none"
        rule_note = ""
        if path_decision.get("rule_applied"):
            rule_note = f", learned_rule={path_decision.get('rule_key', '')}"
        risk_assessment = (
            f"risk={risk}, path={path_decision['path']}, "
            f"confidence={path_decision['confidence']:.2f}, reason={path_decision['reason']}, "
            f"tone={tone_result.tone}, frustration={tone_result.frustration_score:.2f}, "
            f"mapped_action={mapped_id}{rule_note}"
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
            "risk_level": risk,
            "incident": incident,
            "intent_understood": req.intent,
            "planned_actions": plan,
            "risk_assessment": risk_assessment,
            "outcome": execution["outcome"],
            "rollback_or_next_step": next_step,
        }
        message = self.soul.compose_message(message_payload)

        reflection_input = {
            "risk_level": risk,
            "path_used": path_decision["path"],
            "success": execution["success"],
            "policy_compliant": execution["policy_compliant"],
            "confidence": path_decision["confidence"],
            "incident": incident,
        }
        reflection = self.soul.reflect(reflection_input)

        self.profiler.record_event(
            OperatorEvent(
                operator_id=req.operator_name.lower(),
                intent_text=req.intent,
                intent_cluster=tone_result.intent_cluster,
                risk_level=risk,
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
                "risk_level": risk,
                "path": path_decision["path"],
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
            "operator_profile": operator_profile,
            "plan": plan,
            "mapped_action": mapped_action,
            "execution": execution,
            "latency_ms": latency_ms,
            "reflection": reflection,
        }

    @staticmethod
    def _normalize_risk(risk_level: str) -> str:
        risk = (risk_level or "").strip().lower()
        return risk if risk in VALID_RISK else "medium"

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
        }

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
    ) -> dict[str, Any]:
        text = (intent or "").lower()
        steps = ["Collect current context snapshot (who/where/when/what-now)."]
        resolved = self.registry.resolve(intent_text=text, intent_cluster=intent_cluster)
        module_plan = resolved.plan
        action = self._map_action(intent_text=text, intent_cluster=intent_cluster, module_plan=module_plan)

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
        return {"steps": steps, "action": action}

    def _execute_plan(
        self,
        mapped_action: dict[str, Any] | None,
        path: str,
        request: OperatorRequest,
        request_id: str,
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

        if mapped_action is None:
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

        action_id = str(mapped_action["action_id"])
        action_args = dict(mapped_action.get("args", {}))
        action_risk = str(mapped_action.get("action_risk", "unknown"))

        if (
            path == "fast_with_confirm"
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
                "outcome": "Execution requires confirmation for fast_with_confirm path. Use --approve.",
                "command_error": "confirmation_required",
                "returncode": 0,
                "action_id": action_id,
                "request_id": request_id,
            }

        if (
            action_risk in {"high", "critical"}
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
                    f"Blocked high-risk action '{action_id}'. "
                    "Use --allow-high-risk (and --approve when required)."
                ),
                "command_error": "high_risk_blocked",
                "returncode": 0,
                "action_id": action_id,
                "request_id": request_id,
            }

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

        cmd = [str(self.mc_root_action)]
        if request.dry_run:
            cmd.append("--dry-run")
        cmd.extend(["--request-id", request_id, action_id])
        for key, value in action_args.items():
            cmd.append(f"{key}={value}")

        started = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
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
        return {
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
        }

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
        }

    def _load_action_risk(self) -> dict[str, str]:
        path = self.repo_root / "config" / "privilege" / "actions.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        actions = raw.get("actions", {})
        out: dict[str, str] = {}
        if isinstance(actions, dict):
            for aid, spec in actions.items():
                if isinstance(spec, dict):
                    out[str(aid)] = str(spec.get("risk", "unknown"))
        return out

    @staticmethod
    def _utc_now() -> str:
        return dt.datetime.now(tz=dt.timezone.utc).isoformat()

    @staticmethod
    def _make_request_id() -> str:
        return f"mc-{uuid.uuid4().hex[:12]}"

    def _append_core_log(self, entry: dict[str, Any]) -> None:
        self.core_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.core_log_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, ensure_ascii=True) + "\n")


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
