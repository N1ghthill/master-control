#!/usr/bin/env python3
"""MasterControl daemon prototype with humanized response pipeline."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from mastercontrol.context.mc_operator_profiler import OperatorEvent, OperatorProfiler
    from mastercontrol.tone.mc_tone_analyzer import ToneAnalyzer
    from mastercontrol.core.humanized_kernel import SoulKernel, load_profile
    from mastercontrol.core.path_selector import PathSelector, VALID_PATH, VALID_RISK
except ImportError:  # pragma: no cover
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from mastercontrol.context.mc_operator_profiler import OperatorEvent, OperatorProfiler  # type: ignore
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
    simulate_failure: bool


class MasterControlD:
    """Minimal orchestrator using SoulKernel in every response."""

    def __init__(self, profile_path: Path | None = None) -> None:
        profile = load_profile(profile_path)
        self.soul = SoulKernel(profile)
        self.selector = PathSelector()
        self.profiler = OperatorProfiler()
        self.tone = ToneAnalyzer()

    def handle(self, req: OperatorRequest) -> dict[str, Any]:
        t0 = time.monotonic()
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
        )
        plan = self._build_plan(intent=req.intent, risk_level=risk, path=path_decision["path"])
        execution = self._execute_simulated(plan=plan, simulate_failure=req.simulate_failure)
        latency_ms = int((time.monotonic() - t0) * 1000)

        risk_assessment = (
            f"risk={risk}, path={path_decision['path']}, "
            f"confidence={path_decision['confidence']:.2f}, reason={path_decision['reason']}, "
            f"tone={tone_result.tone}, frustration={tone_result.frustration_score:.2f}"
        )
        next_step = (
            "Rollback not required; keep monitoring."
            if execution["success"]
            else "Escalate to deep diagnostic and apply rollback-safe action."
        )

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
                command_error="" if execution["success"] else "simulated_execution_failure",
                forced_path=path_decision["source"] == "manual",
                incident=incident,
            )
        )

        return {
            "message": message,
            "path": path_decision,
            "tone": {
                "tone": tone_result.tone,
                "confidence": tone_result.confidence,
                "intent_cluster": tone_result.intent_cluster,
                "frustration_score": tone_result.frustration_score,
            },
            "operator_profile": operator_profile,
            "plan": plan,
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
    ) -> dict[str, Any]:
        path_req = (requested or "auto").strip().lower()
        if path_req == "auto":
            decision = self.selector.decide(intent=intent, risk_level=risk_level, incident=incident)
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

    @staticmethod
    def _build_plan(intent: str, risk_level: str, path: str) -> list[str]:
        text = (intent or "").lower()
        plan = ["Collect current context snapshot (who/where/when/what-now)."]

        if "dns" in text or "unbound" in text:
            plan.append("Check DNS service health and resolver responsiveness.")
            if "flush" in text or "cache" in text:
                plan.append("Prepare DNS cache maintenance action through allowlisted path.")
        elif "service" in text or "systemctl" in text:
            plan.append("Inspect service status and dependencies before mutation.")
        elif "package" in text or "apt" in text:
            plan.append("Resolve package impact and lock state.")
        else:
            plan.append("Map intent to module capability and verify prerequisites.")

        if path in {"deep", "fast_with_confirm"}:
            plan.append("Generate verification checkpoints and rollback-safe next step.")
        if risk_level in {"high", "critical"}:
            plan.append("Require explicit confirmation before privileged mutation.")
        return plan

    @staticmethod
    def _execute_simulated(plan: list[str], simulate_failure: bool) -> dict[str, Any]:
        if simulate_failure:
            return {
                "success": False,
                "policy_compliant": True,
                "outcome": "Plan execution failed in simulation; no system mutation applied.",
                "steps_executed": min(2, len(plan)),
            }
        return {
            "success": True,
            "policy_compliant": True,
            "outcome": "Plan validated and ready for module execution.",
            "steps_executed": len(plan),
        }


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
    print("\nTone analysis:")
    print(
        f"- tone={result['tone']['tone']}, "
        f"cluster={result['tone']['intent_cluster']}, "
        f"frustration={result['tone']['frustration_score']:.2f}"
    )
    print(f"- latency_ms={result['latency_ms']}")
    print("\nReflection status:")
    print(f"- status: {result['reflection']['status']}")
    if result["reflection"]["suggestions"]:
        print("- suggestions:")
        for item in result["reflection"]["suggestions"]:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
