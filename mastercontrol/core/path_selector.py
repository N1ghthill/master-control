#!/usr/bin/env python3
"""Autonomous path selector for MasterControl."""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from mastercontrol.context.contextd import SQLiteContextStore

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
    rule_applied: bool = False
    rule_key: str = ""
    context_signals: tuple[str, ...] = ()


class PathSelector:
    """Decides execution path without operator intervention."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (Path.home() / ".local" / "share" / "mastercontrol" / "mastercontrol.db")
        self.context_store = SQLiteContextStore(self.db_path)

    def decide(
        self,
        intent: str,
        risk_level: str,
        incident: bool,
        intent_cluster: str = "",
        operator_id: str = "",
        now: dt.datetime | None = None,
    ) -> PathDecision:
        intent_norm = (intent or "").strip().lower()
        risk = risk_level.lower().strip()
        if risk not in VALID_RISK:
            risk = "medium"

        tokens = [w for w in intent_norm.replace("/", " ").replace("-", " ").split() if w]
        complexity = self._complexity_score(tokens)
        confidence = self._confidence(tokens=tokens, complexity=complexity, risk=risk, incident=incident)

        if incident:
            decision = PathDecision(
                path="deep",
                confidence=confidence,
                reason="Incident context detected; forcing deep path.",
                complexity_score=complexity,
            )
        elif risk in {"high", "critical"}:
            decision = PathDecision(
                path="fast_with_confirm",
                confidence=confidence,
                reason="High-risk action requires confirmation with explicit plan.",
                complexity_score=complexity,
            )
        elif risk == "low" and complexity <= 1 and confidence >= 0.78:
            decision = PathDecision(
                path="fast",
                confidence=confidence,
                reason="Low-risk and low-complexity request with high confidence.",
                complexity_score=complexity,
            )
        elif risk == "medium" and complexity <= 2 and confidence >= 0.65:
            decision = PathDecision(
                path="fast_with_confirm",
                confidence=confidence,
                reason="Medium-risk request suitable for quick plan with confirmation.",
                complexity_score=complexity,
            )
        else:
            decision = PathDecision(
                path="deep",
                confidence=confidence,
                reason="Context or complexity indicates deeper reasoning is safer.",
                complexity_score=complexity,
            )
        decision = self._apply_learned_rules(
            decision=decision,
            risk_level=risk,
            incident=incident,
            intent_cluster=intent_cluster,
            operator_id=operator_id,
        )
        return self._apply_environment_signals(
            decision=decision,
            intent=intent_norm,
            risk_level=risk,
            incident=incident,
            intent_cluster=intent_cluster,
            now=now,
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

    def _apply_learned_rules(
        self,
        decision: PathDecision,
        risk_level: str,
        incident: bool,
        intent_cluster: str,
        operator_id: str,
    ) -> PathDecision:
        rule = self._pick_rule(operator_id=operator_id, intent_cluster=intent_cluster)
        if rule is None:
            return decision

        new_path = decision.path
        recommended_path = str(rule["recommended_path"]).strip()
        delta = float(rule["confidence_delta"])
        if recommended_path in VALID_PATH and self._can_apply_path(
            current_path=decision.path,
            recommended_path=recommended_path,
            risk_level=risk_level,
            incident=incident,
        ):
            new_path = recommended_path
        new_conf = max(0.05, min(decision.confidence + delta, 0.99))

        changed = (new_path != decision.path) or (abs(new_conf - decision.confidence) >= 0.01)
        if not changed:
            return decision

        base_reason = decision.reason.rstrip(".")
        learned_reason = str(rule["reason"]).strip() or "learned behavior rule"
        reason = f"{base_reason}. Learned rule applied: {learned_reason}."
        return PathDecision(
            path=new_path,
            confidence=new_conf,
            reason=reason,
            complexity_score=decision.complexity_score,
            rule_applied=True,
            rule_key=str(rule["rule_key"]),
            context_signals=decision.context_signals,
        )

    def _apply_environment_signals(
        self,
        decision: PathDecision,
        *,
        intent: str,
        risk_level: str,
        incident: bool,
        intent_cluster: str,
        now: dt.datetime | None = None,
    ) -> PathDecision:
        domains = self._infer_domains(intent=intent, intent_cluster=intent_cluster)
        if not domains and risk_level == "low" and not incident:
            return decision

        snapshots = self.context_store.snapshots_by_source(
            ["host.system", "network.summary", "services.summary", "journal.alerts"],
            now=now,
        )
        if not snapshots:
            return decision

        severity = 0
        signals: list[str] = []

        if domains.intersection({"services", "packages", "system", "diagnostics"}) or risk_level in {"medium", "high", "critical"}:
            service_snapshot = snapshots.get("services.summary")
            if service_snapshot is not None:
                payload = service_snapshot.payload
                state = str(payload.get("system_state", "")).strip().lower()
                failed_count = int(payload.get("failed_count", 0) or 0)
                service_parts: list[str] = []
                service_severity = 0
                if state and state != "running":
                    service_parts.append(f"systemd={state}")
                    service_severity += 1 if state == "degraded" else 2
                if failed_count > 0:
                    service_parts.append(f"failed_units={failed_count}")
                    service_severity += 1 if failed_count < 3 else 2
                if service_parts:
                    signals.append("service state " + ", ".join(service_parts))
                    severity += service_severity

        if domains.intersection({"network", "diagnostics"}):
            network_snapshot = snapshots.get("network.summary")
            if network_snapshot is not None:
                payload = network_snapshot.payload
                default_route = str(payload.get("default_route", "")).strip()
                route_status = int(payload.get("route_status", 0) or 0)
                nameservers = payload.get("nameservers", [])
                network_parts: list[str] = []
                network_severity = 0
                if route_status != 0 or not default_route:
                    network_parts.append("default_route=missing")
                    network_severity += 2
                if not nameservers:
                    network_parts.append("nameservers=none")
                    network_severity += 1
                if network_parts:
                    signals.append("network state " + ", ".join(network_parts))
                    severity += network_severity

        if domains.intersection({"services", "packages", "system", "diagnostics"}) or risk_level in {"medium", "high", "critical"}:
            host_snapshot = snapshots.get("host.system")
            if host_snapshot is not None:
                payload = host_snapshot.payload
                mem_total = float(payload.get("mem_total_mib", 0.0) or 0.0)
                mem_available = float(payload.get("mem_available_mib", 0.0) or 0.0)
                cpu_count = int(payload.get("cpu_count", 0) or 0)
                loadavg = float(payload.get("loadavg_1m", 0.0) or 0.0)
                host_parts: list[str] = []
                host_severity = 0
                if mem_total > 0:
                    mem_ratio = mem_available / mem_total
                    if mem_ratio <= 0.10:
                        host_parts.append(f"mem_available_mib={mem_available:.1f}/{mem_total:.1f}")
                        host_severity += 2 if mem_ratio <= 0.05 else 1
                if cpu_count > 0 and loadavg >= max(cpu_count, 1) * 1.25:
                    host_parts.append(f"loadavg_1m={loadavg:.2f}/{cpu_count}cpu")
                    host_severity += 1
                if host_parts:
                    signals.append("host pressure " + ", ".join(host_parts))
                    severity += host_severity

        if incident or "diagnostics" in domains or risk_level in {"high", "critical"}:
            journal_snapshot = snapshots.get("journal.alerts")
            if journal_snapshot is not None:
                warning_count = int(journal_snapshot.payload.get("warning_event_count", 0) or 0)
                if warning_count > 0:
                    signals.append(f"journal warnings={warning_count}")
                    severity += 2 if warning_count >= 3 else 1

        if not signals:
            return decision

        new_path = decision.path
        if severity >= 4:
            new_path = "deep"
        elif new_path == "fast":
            new_path = "fast_with_confirm"
        elif new_path == "fast_with_confirm" and severity >= 3:
            new_path = "deep"

        new_confidence = max(0.05, min(decision.confidence - min(0.2, severity * 0.04), 0.99))
        reason = (
            f"{decision.reason.rstrip('.')}. Environment signals applied: "
            f"{'; '.join(signals)}."
        )
        return PathDecision(
            path=new_path,
            confidence=new_confidence,
            reason=reason,
            complexity_score=decision.complexity_score,
            rule_applied=decision.rule_applied,
            rule_key=decision.rule_key,
            context_signals=tuple(signals),
        )

    @staticmethod
    def _infer_domains(intent: str, intent_cluster: str) -> set[str]:
        cluster = (intent_cluster or "").strip().lower()
        tokens = set(intent.replace("/", " ").replace("-", " ").split())
        domains: set[str] = set()

        if cluster.startswith(("network.", "dns.")) or tokens.intersection(
            {"network", "rede", "route", "rota", "ping", "resolver", "resolve", "dns", "gateway"}
        ):
            domains.add("network")
        if cluster.startswith("service.") or tokens.intersection(
            {"service", "services", "systemctl", "daemon", "unit", "restart", "start", "stop", "status"}
        ):
            domains.add("services")
        if cluster.startswith("package.") or tokens.intersection(
            {"apt", "dpkg", "package", "packages", "install", "remove", "upgrade", "build", "compile"}
        ):
            domains.add("packages")
        if cluster.startswith("security.") or tokens.intersection(
            {"security", "seguranca", "intruso", "intrusion", "audit", "auditoria"}
        ):
            domains.update({"diagnostics", "system"})
        if cluster.endswith(".inspect") or tokens.intersection(
            {"diagnose", "diagnosticar", "investigar", "analisar", "incident", "incidente", "log", "journal"}
        ):
            domains.add("diagnostics")
        if cluster and cluster != "general.assist":
            domains.add("system")
        return domains

    @staticmethod
    def _can_apply_path(
        current_path: str,
        recommended_path: str,
        risk_level: str,
        incident: bool,
    ) -> bool:
        if incident and recommended_path == "fast":
            return False
        if risk_level in {"high", "critical"} and recommended_path == "fast":
            return False
        if risk_level in {"high", "critical"} and current_path == "fast_with_confirm" and recommended_path == "deep":
            return True
        return True

    def _pick_rule(self, operator_id: str, intent_cluster: str) -> sqlite3.Row | None:
        op = (operator_id or "").strip().lower()
        cluster = (intent_cluster or "").strip().lower()
        if not op or not cluster or not self.db_path.exists():
            return None

        now = dt.datetime.now()
        dow = now.strftime("%a").lower()[:3]
        hour = now.hour

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT rule_key, recommended_path, confidence_delta, reason,
                       day_of_week, hour_start, hour_end
                FROM learned_rules
                WHERE operator_id = ?
                  AND enabled = 1
                  AND (intent_cluster = ? OR intent_cluster = '*')
                """,
                (op, cluster),
            ).fetchall()
        except Exception:  # noqa: BLE001
            return None
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

        if not rows:
            return None

        candidates: list[sqlite3.Row] = []
        for row in rows:
            day = str(row["day_of_week"]).strip().lower()
            if day not in {"*", dow}:
                continue
            start = int(row["hour_start"])
            end = int(row["hour_end"])
            if not self._hour_matches(hour=hour, start=start, end=end):
                continue
            candidates.append(row)

        if not candidates:
            return None
        return sorted(candidates, key=lambda r: abs(float(r["confidence_delta"])), reverse=True)[0]

    @staticmethod
    def _hour_matches(hour: int, start: int, end: int) -> bool:
        if start < 0 or end < 0:
            return True
        if start <= end:
            return start <= hour <= end
        return hour >= start or hour <= end
