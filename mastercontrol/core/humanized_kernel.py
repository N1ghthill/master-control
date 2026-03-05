#!/usr/bin/env python3
"""Humanized communication kernel for MasterControl."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

VALID_RISK = {"low", "medium", "high", "critical"}


@dataclass
class SoulProfile:
    name: str
    creator: str
    role: str
    required_fields: list[str]
    style_default: str
    style_risk_high: str
    style_incident: str
    reflection_checks: list[str]


def default_profile_path() -> Path:
    env = os.getenv("MASTERCONTROL_SOUL_PROFILE")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "config" / "soul" / "core_profile.yaml"


def load_profile(path: Path | None = None) -> SoulProfile:
    profile_path = path or default_profile_path()
    raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    identity = raw.get("identity", {})
    comm = raw.get("communication", {})
    style = comm.get("style", {})
    reflection = raw.get("reflection", {})

    return SoulProfile(
        name=str(identity.get("name", "MasterControl")),
        creator=str(identity.get("creator", "")),
        role=str(identity.get("role", "Linux Orchestrator")),
        required_fields=list(comm.get("required_fields", [])),
        style_default=str(style.get("default", "concise")),
        style_risk_high=str(style.get("when_risk_high", "explicit")),
        style_incident=str(style.get("when_incident", "calm_supportive")),
        reflection_checks=list(reflection.get("checks", [])),
    )


def choose_style(profile: SoulProfile, risk_level: str, incident: bool) -> str:
    if incident:
        return profile.style_incident
    if risk_level in {"high", "critical"}:
        return profile.style_risk_high
    return profile.style_default


class SoulKernel:
    """Enforces the communication contract and reflection loop."""

    def __init__(self, profile: SoulProfile) -> None:
        self.profile = profile

    def validate_contract(self, payload: dict[str, Any]) -> None:
        missing = []
        for field in self.profile.required_fields:
            value = payload.get(field)
            if value is None:
                missing.append(field)
                continue
            if isinstance(value, str) and not value.strip():
                missing.append(field)
            if isinstance(value, list) and not value:
                missing.append(field)
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"communication contract missing fields: {joined}")

    def compose_message(self, payload: dict[str, Any]) -> str:
        self.validate_contract(payload)

        operator_name = str(payload.get("operator_name", "Operator"))
        risk_level = str(payload.get("risk_level", "low")).lower()
        if risk_level not in VALID_RISK:
            raise ValueError(f"invalid risk_level '{risk_level}'")
        incident = bool(payload.get("incident", False))
        style = choose_style(self.profile, risk_level=risk_level, incident=incident)

        actions = payload.get("planned_actions", [])
        if isinstance(actions, str):
            actions = [actions]
        if not isinstance(actions, list):
            raise ValueError("planned_actions must be a list or string")

        action_lines = []
        for idx, action in enumerate(actions, start=1):
            action_lines.append(f"{idx}. {str(action)}")

        sections = [
            f"{self.profile.name} | communication mode: {style}",
            f"Creator recognized: {self.profile.creator}",
            f"Current operator: {operator_name}",
            f"Role: {self.profile.role}",
            "",
            "What I understood:",
            str(payload["intent_understood"]),
            "",
            "Planned actions:",
            "\n".join(action_lines) if action_lines else "1. No planned actions reported.",
            "",
            "Risk assessment:",
            str(payload["risk_assessment"]),
            "",
            "Outcome:",
            str(payload["outcome"]),
            "",
            "Next step / rollback:",
            str(payload["rollback_or_next_step"]),
        ]
        return "\n".join(sections)

    def reflect(self, payload: dict[str, Any]) -> dict[str, Any]:
        risk_level = str(payload.get("risk_level", "low")).lower()
        path = str(payload.get("path_used", "fast")).lower()
        success = bool(payload.get("success", False))
        policy_ok = bool(payload.get("policy_compliant", True))
        confidence = float(payload.get("confidence", 0.0))
        incident = bool(payload.get("incident", False))

        checks = {
            "intent_accuracy": confidence >= 0.7,
            "path_selection_quality": not (path == "fast" and not success and confidence < 0.7),
            "safety_compliance": policy_ok,
            "operator_usefulness": success,
            "corrective_learning": True,
        }

        suggestions = []
        if not checks["intent_accuracy"]:
            suggestions.append("Increase context collection before planning.")
        if not checks["path_selection_quality"]:
            suggestions.append("Escalate similar future requests to deep path.")
        if not checks["safety_compliance"]:
            suggestions.append("Block action and request explicit step-up approval.")
        if not checks["operator_usefulness"]:
            suggestions.append("Provide a smaller safe action and verify again.")
        if incident and risk_level in {"high", "critical"} and path != "deep":
            suggestions.append("Force deep path for incident + high-risk combinations.")

        return {
            "identity": self.profile.name,
            "creator": self.profile.creator,
            "path_used": path,
            "risk_level": risk_level,
            "success": success,
            "policy_compliant": policy_ok,
            "checks": checks,
            "suggestions": suggestions,
            "status": "ok" if all(checks.values()) else "review",
        }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="humanized-kernel",
        description="MasterControl humanized communication kernel",
    )
    p.add_argument(
        "--profile",
        default=None,
        help="Path to soul profile YAML",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("speak", help="Compose humanized operator response")
    s.add_argument("--operator-name", default="Operator")
    s.add_argument("--risk-level", default="low", choices=sorted(VALID_RISK))
    s.add_argument("--incident", action="store_true")
    s.add_argument("--intent-understood", required=True)
    s.add_argument("--action", action="append", default=[])
    s.add_argument("--risk-assessment", required=True)
    s.add_argument("--outcome", required=True)
    s.add_argument("--next-step", required=True)

    r = sub.add_parser("reflect", help="Run post-action reflection checks")
    r.add_argument("--risk-level", default="low", choices=sorted(VALID_RISK))
    r.add_argument("--path-used", default="fast", choices=["fast", "deep", "fast_with_confirm"])
    r.add_argument("--success", action="store_true")
    r.add_argument("--policy-compliant", action="store_true")
    r.add_argument("--confidence", type=float, default=0.5)
    r.add_argument("--incident", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    profile = load_profile(Path(args.profile) if args.profile else None)
    kernel = SoulKernel(profile)

    if args.cmd == "speak":
        payload = {
            "operator_name": args.operator_name,
            "risk_level": args.risk_level,
            "incident": bool(args.incident),
            "intent_understood": args.intent_understood,
            "planned_actions": list(args.action),
            "risk_assessment": args.risk_assessment,
            "outcome": args.outcome,
            "rollback_or_next_step": args.next_step,
        }
        print(kernel.compose_message(payload))
        return 0

    if args.cmd == "reflect":
        payload = {
            "risk_level": args.risk_level,
            "path_used": args.path_used,
            "success": bool(args.success),
            "policy_compliant": bool(args.policy_compliant),
            "confidence": float(args.confidence),
            "incident": bool(args.incident),
        }
        print(json.dumps(kernel.reflect(payload), ensure_ascii=True, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

