#!/usr/bin/env python3
"""Humanized communication kernel for MasterControl."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

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


def _parse_scalar(text: str) -> Any:
    value = text.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered.isdigit():
        return int(lowered)
    return value


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for idx, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:idx]
    return line


def _simple_yaml_load(raw_text: str) -> dict[str, Any]:
    tokens: list[tuple[int, str]] = []
    for raw_line in raw_text.splitlines():
        cleaned = _strip_comment(raw_line).rstrip()
        if not cleaned.strip():
            continue
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        tokens.append((indent, cleaned.strip()))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        container: Any = None
        while index < len(tokens):
            current_indent, content = tokens[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"Unsupported YAML indentation near '{content}'")

            if content.startswith("- "):
                if container is None:
                    container = []
                if not isinstance(container, list):
                    raise ValueError("Mixed YAML list/dict structures are not supported")
                item_text = content[2:].strip()
                if not item_text:
                    item, index = parse_block(index + 1, indent + 2)
                    container.append(item)
                    continue
                container.append(_parse_scalar(item_text))
                index += 1
                continue

            key, sep, rest = content.partition(":")
            if not sep:
                raise ValueError(f"Invalid YAML line '{content}'")
            if container is None:
                container = {}
            if not isinstance(container, dict):
                raise ValueError("Mixed YAML dict/list structures are not supported")
            key = key.strip()
            rest = rest.strip()
            if rest:
                container[key] = _parse_scalar(rest)
                index += 1
                continue

            next_index = index + 1
            if next_index >= len(tokens) or tokens[next_index][0] <= indent:
                container[key] = {}
                index += 1
                continue
            value, index = parse_block(next_index, indent + 2)
            container[key] = value

        return container if container is not None else {}, index

    data, _ = parse_block(0, 0)
    if not isinstance(data, dict):
        raise ValueError("Top-level YAML document must be a mapping")
    return data


def _load_structured_text(path: Path) -> dict[str, Any]:
    raw_text = path.read_text(encoding="utf-8")
    if yaml is not None:
        loaded = yaml.safe_load(raw_text)
        return loaded if isinstance(loaded, dict) else {}
    return _simple_yaml_load(raw_text)


def load_profile(path: Path | None = None) -> SoulProfile:
    profile_path = path or default_profile_path()
    raw = _load_structured_text(profile_path)
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

    @staticmethod
    def _coerce_string_list(value: Any) -> list[str]:
        if isinstance(value, str):
            cleaned = value.strip()
            return [cleaned] if cleaned else []
        if isinstance(value, list):
            out = []
            for item in value:
                cleaned = str(item).strip()
                if cleaned:
                    out.append(cleaned)
            return out
        return []

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def communication_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.validate_contract(payload)

        operator_name = str(payload.get("operator_name", "Operator")).strip() or "Operator"
        risk_level = str(payload.get("risk_level", "low")).lower()
        if risk_level not in VALID_RISK:
            raise ValueError(f"invalid risk_level '{risk_level}'")
        incident = bool(payload.get("incident", False))
        tone = str(payload.get("tone", "routine")).strip().lower() or "routine"
        tone_confidence = self._safe_float(payload.get("tone_confidence", 0.0))
        frustration_score = self._safe_float(payload.get("frustration_score", 0.0))
        intent_cluster = str(payload.get("intent_cluster", "")).strip().lower()
        intent_confidence = self._safe_float(payload.get("intent_confidence", 0.0))
        intent_source = str(payload.get("intent_source", "local")).strip() or "local"

        operator_profile = payload.get("operator_profile", {})
        if not isinstance(operator_profile, dict):
            operator_profile = {}
        path_preference = str(operator_profile.get("path_preference", "balanced")).strip() or "balanced"
        tone_sensitivity = self._safe_float(operator_profile.get("tone_sensitivity", 0.5), default=0.5)
        common_intents = self._coerce_string_list(operator_profile.get("common_intents", []))
        error_prone_commands = self._coerce_string_list(operator_profile.get("error_prone_commands", []))

        effective_style_risk = risk_level
        if tone == "urgent" or (frustration_score >= 0.65 and tone_sensitivity >= 0.7):
            if risk_level in {"low", "medium"}:
                effective_style_risk = "high"
        effective_incident = incident or tone == "incident"
        if tone == "urgent" and frustration_score >= 0.75 and tone_sensitivity >= 0.6:
            effective_incident = True

        style = choose_style(
            self.profile,
            risk_level=effective_style_risk,
            incident=effective_incident,
        )

        adaptation_notes: list[str] = []
        if tone == "incident":
            adaptation_notes.append(
                f"Detected incident tone (confidence={tone_confidence:.2f}); keeping communication calm and explicit."
            )
        elif tone == "urgent":
            if frustration_score >= 0.65 or tone_sensitivity >= 0.6:
                adaptation_notes.append(
                    f"Detected urgency/friction (frustration={frustration_score:.2f}); keeping guidance short and steady."
                )
            else:
                adaptation_notes.append(
                    f"Detected urgent tone (confidence={tone_confidence:.2f}); prioritizing explicit next steps."
                )
        elif tone == "exploratory":
            adaptation_notes.append(
                f"Detected exploratory tone (confidence={tone_confidence:.2f}); leaving more explanation room."
            )

        preference_note = {
            "deep_when_uncertain": "Learned operator preference: prefer deeper validation when confidence is lower.",
            "fast_default": "Learned operator preference: stay fast unless risk or ambiguity grows.",
            "confirm_heavy": "Learned operator preference: keep confirmation visible before mutation.",
        }.get(path_preference)
        if preference_note:
            adaptation_notes.append(preference_note)

        if intent_cluster and intent_cluster in error_prone_commands:
            adaptation_notes.append(
                f"Recent history shows friction on '{intent_cluster}'; verification and rollback stay explicit."
            )
        elif intent_cluster and intent_cluster in common_intents:
            adaptation_notes.append(
                f"This request matches a common intent family for {operator_name}; I can stay more direct."
            )

        if intent_confidence and intent_confidence < 0.65:
            adaptation_notes.append(
                f"Intent confidence is limited ({intent_confidence:.2f} via {intent_source}); confirmation may be useful."
            )

        return {
            "style": style,
            "tone": tone,
            "tone_confidence": tone_confidence,
            "frustration_score": frustration_score,
            "intent_cluster": intent_cluster,
            "intent_confidence": intent_confidence,
            "intent_source": intent_source,
            "path_preference": path_preference,
            "tone_sensitivity": tone_sensitivity,
            "common_intents": common_intents,
            "error_prone_commands": error_prone_commands,
            "adaptation_notes": adaptation_notes,
        }

    def compose_message(
        self,
        payload: dict[str, Any],
        communication_plan: dict[str, Any] | None = None,
    ) -> str:
        self.validate_contract(payload)
        communication = communication_plan or self.communication_plan(payload)

        actions = payload.get("planned_actions", [])
        if isinstance(actions, str):
            actions = [actions]
        if not isinstance(actions, list):
            raise ValueError("planned_actions must be a list or string")

        action_lines = []
        for idx, action in enumerate(actions, start=1):
            action_lines.append(f"{idx}. {str(action)}")

        sections = [
            f"{self.profile.name} | communication mode: {communication['style']}",
            f"Creator recognized: {self.profile.creator}",
            f"Current operator: {str(payload.get('operator_name', 'Operator')).strip() or 'Operator'}",
            f"Role: {self.profile.role}",
        ]
        adaptation_notes = communication.get("adaptation_notes", [])
        if adaptation_notes:
            sections.extend(
                [
                    "",
                    "How I'm adapting:",
                    "\n".join(f"- {str(note)}" for note in adaptation_notes),
                ]
            )
        sections.extend(
            [
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
        )
        return "\n".join(sections)

    def reflect(self, payload: dict[str, Any]) -> dict[str, Any]:
        risk_level = str(payload.get("risk_level", "low")).lower()
        path = str(payload.get("path_used", "fast")).lower()
        success = bool(payload.get("success", False))
        policy_ok = bool(payload.get("policy_compliant", True))
        confidence = float(payload.get("confidence", 0.0))
        incident = bool(payload.get("incident", False))
        tone = str(payload.get("tone", "routine")).strip().lower() or "routine"
        frustration_score = self._safe_float(payload.get("frustration_score", 0.0))
        intent_cluster = str(payload.get("intent_cluster", "")).strip().lower()
        operator_profile = payload.get("operator_profile", {})
        if not isinstance(operator_profile, dict):
            operator_profile = {}
        error_prone_commands = self._coerce_string_list(operator_profile.get("error_prone_commands", []))

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
        if tone in {"urgent", "incident"} and frustration_score >= 0.65 and not success:
            suggestions.append("Keep rollback and next safe step visible earlier in stressed exchanges.")
        if intent_cluster and intent_cluster in error_prone_commands and not success:
            suggestions.append("Bias this intent cluster to deeper verification because local history shows friction.")

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
