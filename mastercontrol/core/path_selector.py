#!/usr/bin/env python3
"""Autonomous path selector for MasterControl."""

from __future__ import annotations

from dataclasses import dataclass

VALID_PATH = {"fast", "deep", "fast_with_confirm"}
VALID_RISK = {"low", "medium", "high", "critical"}

COMPLEXITY_KEYWORDS = {
    "diagnose",
    "diagnosticar",
    "analisar",
    "investigar",
    "incidente",
    "security",
    "seguranca",
    "latency",
    "degradacao",
    "auditoria",
    "rollback",
    "forense",
}


@dataclass
class PathDecision:
    path: str
    confidence: float
    reason: str
    complexity_score: int


class PathSelector:
    """Decides execution path without operator intervention."""

    def decide(self, intent: str, risk_level: str, incident: bool) -> PathDecision:
        intent_norm = (intent or "").strip().lower()
        risk = risk_level.lower().strip()
        if risk not in VALID_RISK:
            risk = "medium"

        tokens = [w for w in intent_norm.replace("/", " ").replace("-", " ").split() if w]
        complexity = self._complexity_score(tokens)
        confidence = self._confidence(tokens=tokens, complexity=complexity, risk=risk, incident=incident)

        if incident:
            return PathDecision(
                path="deep",
                confidence=confidence,
                reason="Incident context detected; forcing deep path.",
                complexity_score=complexity,
            )
        if risk in {"high", "critical"}:
            return PathDecision(
                path="fast_with_confirm",
                confidence=confidence,
                reason="High-risk action requires confirmation with explicit plan.",
                complexity_score=complexity,
            )
        if risk == "low" and complexity <= 1 and confidence >= 0.78:
            return PathDecision(
                path="fast",
                confidence=confidence,
                reason="Low-risk and low-complexity request with high confidence.",
                complexity_score=complexity,
            )
        if risk == "medium" and complexity <= 2 and confidence >= 0.65:
            return PathDecision(
                path="fast_with_confirm",
                confidence=confidence,
                reason="Medium-risk request suitable for quick plan with confirmation.",
                complexity_score=complexity,
            )
        return PathDecision(
            path="deep",
            confidence=confidence,
            reason="Context or complexity indicates deeper reasoning is safer.",
            complexity_score=complexity,
        )

    @staticmethod
    def _complexity_score(tokens: list[str]) -> int:
        score = 0
        if len(tokens) > 16:
            score += 2
        elif len(tokens) > 8:
            score += 1
        if any(token in COMPLEXITY_KEYWORDS for token in tokens):
            score += 2
        if not tokens:
            score += 2
        if len(tokens) <= 3:
            score -= 1
        return max(score, 0)

    @staticmethod
    def _confidence(tokens: list[str], complexity: int, risk: str, incident: bool) -> float:
        conf = 0.92
        if complexity >= 2:
            conf -= 0.18
        elif complexity == 1:
            conf -= 0.09
        if risk in {"high", "critical"}:
            conf -= 0.08
        if incident:
            conf -= 0.12
        if not tokens:
            conf -= 0.25
        return max(0.05, min(conf, 0.99))

