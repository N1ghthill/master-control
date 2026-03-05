#!/usr/bin/env python3
"""Lightweight tone and intent analyzer for operator commands."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ToneResult:
    tone: str
    confidence: float
    intent_cluster: str
    frustration_score: float
    mode: str


class ToneAnalyzer:
    """Fast heuristic analyzer with optional future transformer mode."""

    URGENT_MARKERS = {
        "agora",
        "urgente",
        "imediato",
        "asap",
        "now",
        "rapido",
        "rápido",
        "emergencia",
        "emergência",
    }
    INCIDENT_MARKERS = {
        "incidente",
        "fora",
        "outage",
        "degradado",
        "quebrou",
        "falhando",
        "instavel",
        "instável",
    }
    FRUSTRATION_MARKERS = {
        "pelo amor",
        "caramba",
        "droga",
        "que inferno",
        "não funciona",
        "nao funciona",
        "resolve isso",
        "nada funciona",
    }
    EXPLORATORY_MARKERS = {
        "poderia",
        "talvez",
        "acho",
        "vamos pensar",
        "analisa",
        "entender",
        "investigar",
    }

    def analyze(self, text: str, mode: str = "heuristic") -> ToneResult:
        # v0: heuristic mode is the default and recommended.
        return self._heuristic(text=text, mode=mode)

    def _heuristic(self, text: str, mode: str) -> ToneResult:
        t = (text or "").strip().lower()
        tokens = re.findall(r"\w+", t, flags=re.UNICODE)
        token_set = set(tokens)
        joined = " ".join(tokens)

        frustration_score = self._frustration_score(t, token_set, joined)
        intent_cluster = self._intent_cluster(token_set, joined)

        urgent_hit = bool(token_set.intersection(self._normalize(self.URGENT_MARKERS)))
        incident_hit = bool(token_set.intersection(self._normalize(self.INCIDENT_MARKERS)))
        exploratory_hit = bool(token_set.intersection(self._normalize(self.EXPLORATORY_MARKERS)))

        if incident_hit:
            tone = "incident"
            confidence = 0.86
        elif urgent_hit or frustration_score >= 0.65:
            tone = "urgent"
            confidence = 0.82
        elif exploratory_hit:
            tone = "exploratory"
            confidence = 0.74
        else:
            tone = "routine"
            confidence = 0.78

        # Small confidence correction by text quality.
        if len(tokens) < 3:
            confidence -= 0.08
        if not t:
            tone = "exploratory"
            confidence = 0.35
        confidence = round(max(0.05, min(confidence, 0.99)), 3)

        return ToneResult(
            tone=tone,
            confidence=confidence,
            intent_cluster=intent_cluster,
            frustration_score=frustration_score,
            mode=mode,
        )

    @staticmethod
    def _normalize(words: set[str]) -> set[str]:
        return {re.sub(r"[^\w]+", "", w.lower()) for w in words}

    def _frustration_score(self, raw: str, token_set: set[str], joined: str) -> float:
        score = 0.0
        if "!" in raw:
            score += 0.15
        if raw.isupper() and raw:
            score += 0.20
        if len(re.findall(r"[A-Z]{3,}", raw)) > 0:
            score += 0.10
        if any(marker in joined for marker in self.FRUSTRATION_MARKERS):
            score += 0.45
        if {"erro", "error", "falha", "fail"}.intersection(token_set):
            score += 0.15
        return round(max(0.0, min(score, 1.0)), 3)

    @staticmethod
    def _intent_cluster(token_set: set[str], joined: str) -> str:
        if "dns" in token_set or "unbound" in token_set:
            if "flush" in token_set or "cache" in token_set:
                return "dns.flush"
            return "dns.inspect"
        if "systemctl" in token_set or "service" in token_set:
            if {"restart", "reiniciar"}.intersection(token_set):
                return "service.restart"
            if {"start", "iniciar"}.intersection(token_set):
                return "service.start"
            if {"stop", "parar"}.intersection(token_set):
                return "service.stop"
            return "service.inspect"
        if "apt" in token_set or "package" in token_set or "pacote" in token_set:
            return "package.manage"
        if "security" in token_set or "seguranca" in token_set or "segurança" in joined:
            return "security.audit"
        if "rede" in token_set or "network" in token_set:
            return "network.diagnose"
        return "general.assist"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mc-tone-analyzer",
        description="Analyze operator command tone and intent cluster",
    )
    p.add_argument("--text", required=True, help="Operator input text")
    p.add_argument("--mode", default="heuristic", choices=["heuristic", "transformer"])
    return p


def main() -> int:
    args = parser().parse_args()
    analyzer = ToneAnalyzer()
    result = analyzer.analyze(args.text, mode=args.mode)
    payload: dict[str, Any] = {
        "tone": result.tone,
        "confidence": result.confidence,
        "intent_cluster": result.intent_cluster,
        "frustration_score": result.frustration_score,
        "mode": result.mode,
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

