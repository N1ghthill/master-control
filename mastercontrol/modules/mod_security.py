#!/usr/bin/env python3
"""Security audit module backed by persisted local system events."""

from __future__ import annotations

import re

from mastercontrol.modules.base import ModulePlan
from mastercontrol.modules.mod_services import ServiceModule


class SecurityModule:
    """Plans local security audits using persisted event intelligence."""

    MODULE_ID = "mod_security"
    AUDIT_ACTION_ID = "security.audit.recent_events"
    VIGILANCE_ACTION_ID = "security.vigilance.status"
    ALERTS_LIST_ACTION_ID = "security.alerts.list"
    ALERTS_ACK_ACTION_ID = "security.alerts.ack"
    ALERTS_SILENCE_ACTION_ID = "security.alerts.silence"
    INCIDENT_LIST_ACTION_ID = "security.incident.list"
    INCIDENT_SHOW_ACTION_ID = "security.incident.show"
    INCIDENT_RESOLVE_ACTION_ID = "security.incident.resolve"
    INCIDENT_DISMISS_ACTION_ID = "security.incident.dismiss"
    INCIDENT_PLAN_ACTION_ID = "security.incident.plan"
    INCIDENT_CONTAIN_CAPABILITY = "security.incident.contain"

    CATEGORY_KEYWORDS = {
        "security": {"security", "seguranca", "audit", "auditar", "auth", "login", "ssh", "sudo", "intruso", "intrusos"},
        "network": {"network", "rede", "firewall", "porta", "portas", "dns", "dhcp"},
        "service": {"service", "servico", "systemd", "daemon", "unit"},
        "package": {"apt", "dpkg", "package", "pacote", "upgrade", "install", "remove"},
        "udev": {"udev", "hardware", "usb", "device", "dispositivo", "interface", "nic"},
        "dbus": {"dbus", "session", "sessao", "sessoes", "login1", "busctl", "loginctl"},
    }
    VIGILANCE_KEYWORDS = {
        "vigia",
        "vigiar",
        "vigie",
        "monitor",
        "monitore",
        "monitorar",
        "vigilancia",
        "watch",
        "intruso",
        "intrusos",
        "proteger",
        "protecao",
    }
    INCIDENT_KEYWORDS = {
        "incident",
        "incidente",
        "incidentes",
        "response",
        "resposta",
        "respond",
        "responder",
        "responda",
        "contain",
        "containment",
        "contencao",
        "conter",
        "contenha",
        "mitigar",
        "mitigue",
        "remediar",
        "remedie",
    }
    INCIDENT_LIST_KEYWORDS = {"listar", "lista", "mostrar", "mostre", "show", "status", "ativos", "ativas", "abertos", "abertas"}
    INCIDENT_SHOW_KEYWORDS = {"mostrar", "mostre", "show", "detalhe", "detalhes", "status"}
    INCIDENT_RESOLVE_KEYWORDS = {"resolve", "resolver", "resolva", "fechar", "feche", "encerrar", "encerre", "finalizar", "finalize"}
    INCIDENT_DISMISS_KEYWORDS = {"dismiss", "dismissed", "dispensar", "dispense", "descartar", "descarte", "ignorar", "ignore"}
    ALERT_LIST_KEYWORDS = {"alerta", "alertas", "alerts", "listar", "lista", "mostrar", "mostre", "recentes"}
    ALERT_ACK_KEYWORDS = {"ack", "acknowledge", "reconhecer", "reconheca", "ciente", "confirmar", "marcar"}
    ALERT_SILENCE_KEYWORDS = {"silenciar", "silencie", "silence", "mute", "suprimir", "calar", "ignorar"}
    SEVERITY_ALIASES = {
        "critical": {"critical", "critico", "critica", "criticos", "criticas"},
        "high": {"high", "alto", "alta", "altos", "altas"},
        "medium": {"medium", "medio", "media", "medios", "medias"},
        "low": {"low", "baixo", "baixa", "baixos", "baixas"},
    }
    INCIDENT_STATUS_ALIASES = {
        "active": {"active", "ativo", "ativos", "ativa", "ativas"},
        "open": {"open", "aberto", "abertos", "aberta", "abertas"},
        "contained": {"contained", "contido", "contidos", "contida", "contidas"},
        "resolved": {"resolved", "resolvido", "resolvidos", "resolvida", "resolvidas"},
        "dismissed": {"dismissed", "descartado", "descartados", "descartada", "descartadas"},
        "all": {"all", "todos", "todas"},
    }
    INCIDENT_UNIT_SCOPES = {
        "ssh.service": "security",
        "networkmanager.service": "network",
        "systemd-networkd.service": "network",
        "systemd-resolved.service": "network",
    }
    INCIDENT_CONTAINMENT_RULES = {
        "service": {
            "capabilities": {"service.restart", "service.start", "service.stop"},
            "units": set(),
        },
        "security": {
            "capabilities": {"service.restart"},
            "units": {"ssh.service"},
        },
        "network": {
            "capabilities": {"service.restart"},
            "units": {"networkmanager.service", "systemd-networkd.service", "systemd-resolved.service"},
        },
    }

    def capabilities(self) -> list[str]:
        return [
            self.AUDIT_ACTION_ID,
            self.VIGILANCE_ACTION_ID,
            self.ALERTS_LIST_ACTION_ID,
            self.ALERTS_ACK_ACTION_ID,
            self.ALERTS_SILENCE_ACTION_ID,
            self.INCIDENT_LIST_ACTION_ID,
            self.INCIDENT_SHOW_ACTION_ID,
            self.INCIDENT_RESOLVE_ACTION_ID,
            self.INCIDENT_DISMISS_ACTION_ID,
            self.INCIDENT_PLAN_ACTION_ID,
            self.INCIDENT_CONTAIN_CAPABILITY,
        ]

    def resolve_capability(self, intent_text: str, intent_cluster: str) -> str | None:
        text = (intent_text or "").lower()
        cluster = (intent_cluster or "").lower()
        tokens = set(re.findall(r"[a-z0-9_.:-]+", text))
        has_alert_terms = bool(tokens.intersection({"alerta", "alertas", "alerts"}))
        if cluster.startswith("security.alerts.silence") or (has_alert_terms and tokens.intersection(self.ALERT_SILENCE_KEYWORDS)):
            return self.ALERTS_SILENCE_ACTION_ID
        if cluster.startswith("security.alerts.ack") or (has_alert_terms and tokens.intersection(self.ALERT_ACK_KEYWORDS)):
            return self.ALERTS_ACK_ACTION_ID
        if cluster.startswith("security.alerts") or (has_alert_terms and tokens.intersection(self.ALERT_LIST_KEYWORDS)):
            return self.ALERTS_LIST_ACTION_ID
        has_incident_terms = cluster.startswith("security.incident") or bool(tokens.intersection(self.INCIDENT_KEYWORDS))
        if has_incident_terms:
            incident_id = self.extract_incident_id(intent_text)
            if cluster.startswith(self.INCIDENT_DISMISS_ACTION_ID) or (
                incident_id and tokens.intersection(self.INCIDENT_DISMISS_KEYWORDS)
            ):
                return self.INCIDENT_DISMISS_ACTION_ID
            if cluster.startswith(self.INCIDENT_RESOLVE_ACTION_ID) or (
                incident_id and tokens.intersection(self.INCIDENT_RESOLVE_KEYWORDS)
            ):
                return self.INCIDENT_RESOLVE_ACTION_ID
            if cluster.startswith(self.INCIDENT_SHOW_ACTION_ID):
                return self.INCIDENT_SHOW_ACTION_ID
            if incident_id and not tokens.intersection(self.INCIDENT_RESOLVE_KEYWORDS | self.INCIDENT_DISMISS_KEYWORDS):
                return self.INCIDENT_SHOW_ACTION_ID
            if cluster.startswith(self.INCIDENT_LIST_ACTION_ID) or self._looks_like_incident_listing(tokens):
                return self.INCIDENT_LIST_ACTION_ID
            requested_category = self.extract_category(intent_text)
            fingerprint = self.extract_fingerprint(intent_text)
            if self._resolve_incident_service_action(
                intent_text=intent_text,
                requested_category=requested_category,
                fingerprint=fingerprint,
            ) is not None:
                return self.INCIDENT_CONTAIN_CAPABILITY
            return self.INCIDENT_PLAN_ACTION_ID
        if cluster.startswith("security.vigilance"):
            return self.VIGILANCE_ACTION_ID
        if any(token in text for token in self.VIGILANCE_KEYWORDS):
            return self.VIGILANCE_ACTION_ID
        if cluster.startswith("security."):
            return self.AUDIT_ACTION_ID
        if any(token in text for token in {"security", "seguranca", "audit", "auditar", "hardening"}):
            return self.AUDIT_ACTION_ID
        return None

    def extract_category(self, intent_text: str) -> str:
        text = (intent_text or "").lower()
        tokens = set(re.findall(r"[a-z0-9_.:-]+", text))
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            if tokens.intersection(keywords):
                return category
        return "all"

    @staticmethod
    def extract_limit(intent_text: str) -> str:
        text = (intent_text or "").lower()
        match = re.search(r"\b(3|5|10|20|50)\b", text)
        if match:
            return match.group(1)
        return "5"

    @staticmethod
    def extract_activity_limit(intent_text: str) -> str:
        text = (intent_text or "").lower()
        match = re.search(r"\b(5|10|20)\b", text)
        if match:
            return match.group(1)
        return "10"

    @staticmethod
    def extract_window_hours(intent_text: str) -> str:
        text = (intent_text or "").lower()
        match = re.search(r"\b(1|3|6|12|24)\s*(h|hora|horas)\b", text)
        if match:
            return match.group(1)
        return "6"

    @staticmethod
    def extract_alert_ids(intent_text: str) -> list[str]:
        text = (intent_text or "").lower()
        hour_match = re.search(r"\b(1|3|6|12|24)\s*(h|hora|horas)\b", text)
        excluded: tuple[int, int] | None = hour_match.span(1) if hour_match else None
        ids: list[str] = []
        for match in re.finditer(r"\b\d+\b", text):
            if excluded is not None and match.span() == excluded:
                continue
            value = match.group(0)
            if value not in ids:
                ids.append(value)
        return ids

    @classmethod
    def extract_severity(cls, intent_text: str) -> str:
        text = (intent_text or "").lower()
        tokens = set(re.findall(r"[a-z0-9_.:-]+", text))
        for severity, aliases in cls.SEVERITY_ALIASES.items():
            if tokens.intersection(aliases):
                return severity
        return "all"

    @staticmethod
    def extract_fingerprint(intent_text: str) -> str:
        text = (intent_text or "").strip().lower()
        explicit = re.search(r"\b(?:fingerprint|assinatura)\s+([a-z0-9][a-z0-9_.:-]+)\b", text)
        if explicit:
            return explicit.group(1)
        for token in re.findall(r"[a-z0-9_.:-]+", text):
            if token.count(".") >= 2:
                return token
        return ""

    @staticmethod
    def extract_incident_id(intent_text: str) -> str:
        text = (intent_text or "").strip().lower()
        match = re.search(r"\b(inc-[a-z0-9-]+)\b", text)
        if not match:
            return ""
        return match.group(1)

    @classmethod
    def extract_incident_status(cls, intent_text: str) -> str:
        text = (intent_text or "").strip().lower()
        explicit = re.search(r"\b(?:status|estado)\s+([a-z_]+)\b", text)
        if explicit:
            token = explicit.group(1)
            for status, aliases in cls.INCIDENT_STATUS_ALIASES.items():
                if token in aliases:
                    return status
        tokens = set(re.findall(r"[a-z0-9_.:-]+", text))
        for status, aliases in cls.INCIDENT_STATUS_ALIASES.items():
            if tokens.intersection(aliases):
                return status
        return "active"

    @classmethod
    def _looks_like_incident_listing(cls, tokens: set[str]) -> bool:
        if tokens.intersection(cls.INCIDENT_LIST_KEYWORDS):
            return True
        status_aliases = set().union(*cls.INCIDENT_STATUS_ALIASES.values())
        return bool(tokens.intersection(status_aliases))

    @staticmethod
    def pre_check(capability: str, category: str) -> list[str]:
        scope = category if category != "all" else "all categories"
        if capability == SecurityModule.INCIDENT_LIST_ACTION_ID:
            return [
                f"Inspect persisted incident ledger rows for {scope}.",
                "Summarize active or historical incidents with current status, severity and latest operator decision.",
            ]
        if capability == SecurityModule.INCIDENT_SHOW_ACTION_ID:
            return [
                "Resolve the requested incident ledger row by incident_id.",
                "Load current status, correlated evidence and recent activity trail before summarizing.",
            ]
        if capability == SecurityModule.INCIDENT_RESOLVE_ACTION_ID:
            return [
                "Resolve the requested incident ledger row by incident_id.",
                "Close matching open alert rows locally so the incident does not reopen from stale evidence.",
            ]
        if capability == SecurityModule.INCIDENT_DISMISS_ACTION_ID:
            return [
                "Resolve the requested incident ledger row by incident_id.",
                "Record the operator dismissal locally and close matching open alert rows without mutating the host.",
            ]
        if capability == SecurityModule.ALERTS_LIST_ACTION_ID:
            return [
                f"Inspect persisted security alerts for {scope}.",
                "Summarize open alerts by severity, fingerprint and operator recommendation.",
            ]
        if capability == SecurityModule.ALERTS_ACK_ACTION_ID:
            return [
                f"Resolve persisted alert rows for {scope}.",
                "Acknowledge only matching local alert records without mutating the host.",
            ]
        if capability == SecurityModule.ALERTS_SILENCE_ACTION_ID:
            return [
                f"Resolve recurring alert fingerprints for {scope}.",
                "Create local silence windows so repeated identical alerts stop resurfacing temporarily.",
            ]
        if capability == SecurityModule.VIGILANCE_ACTION_ID:
            return [
                f"Inspect persisted recent system events for {scope}.",
                "Correlate auth, login-session, network, service, package and device changes into a vigilance posture.",
            ]
        return [
            f"Inspect persisted system events for {scope}.",
            "Correlate recent auth, service, package, network and device changes before summarizing.",
        ]

    @staticmethod
    def verify(capability: str, category: str, detail: str) -> list[str]:
        scope = category if category != "all" else "all categories"
        if capability == SecurityModule.INCIDENT_LIST_ACTION_ID:
            return [f"Verify incident listing includes up to {detail} ledger row(s) for {scope}."]
        if capability == SecurityModule.INCIDENT_SHOW_ACTION_ID:
            return [f"Verify incident detail includes status, evidence and up to {detail} activity row(s)."]
        if capability == SecurityModule.INCIDENT_RESOLVE_ACTION_ID:
            return ["Verify the requested incident ledger row moved to resolved and matching open alerts were closed locally."]
        if capability == SecurityModule.INCIDENT_DISMISS_ACTION_ID:
            return ["Verify the requested incident ledger row moved to dismissed and matching open alerts were closed locally."]
        if capability == SecurityModule.ALERTS_LIST_ACTION_ID:
            return [f"Verify alert listing includes up to {detail} recent alert row(s) for {scope}."]
        if capability == SecurityModule.ALERTS_ACK_ACTION_ID:
            return [f"Verify matching alert row(s) for {scope} moved to acknowledged status."]
        if capability == SecurityModule.ALERTS_SILENCE_ACTION_ID:
            return [f"Verify recurring alert fingerprints for {scope} are silenced for the next {detail}h."]
        if capability == SecurityModule.VIGILANCE_ACTION_ID:
            return [f"Verify vigilance status covers the last {detail}h of {scope} and names the strongest signal."]
        return [f"Verify audit summary includes latest {detail} event(s) for {scope}."]

    @staticmethod
    def rollback() -> str:
        return "No rollback required for local read-only security audit."

    @classmethod
    def _fingerprint_scope(cls, fingerprint: str) -> str:
        fp = (fingerprint or "").strip().lower()
        if fp.startswith("security."):
            return "security"
        if fp.startswith("network."):
            return "network"
        if fp.startswith("service."):
            return "service"
        return "all"

    @classmethod
    def _unit_scope(cls, unit: str) -> str:
        return cls.INCIDENT_UNIT_SCOPES.get((unit or "").strip().lower(), "service")

    @classmethod
    def _effective_incident_scope(
        cls,
        *,
        requested_category: str,
        fingerprint: str,
        unit: str,
    ) -> str:
        category = (requested_category or "all").strip().lower() or "all"
        if category != "all":
            return category
        fp_scope = cls._fingerprint_scope(fingerprint)
        if fp_scope != "all":
            return fp_scope
        return cls._unit_scope(unit)

    def _resolve_incident_service_action(
        self,
        *,
        intent_text: str,
        requested_category: str,
        fingerprint: str,
    ) -> dict[str, str] | None:
        service_module = ServiceModule()
        capability = service_module.resolve_capability(
            intent_text=intent_text,
            intent_cluster="general.assist",
        )
        if capability not in service_module.CAPABILITY_ACTION:
            return None
        unit = service_module.extract_unit(intent_text=intent_text)
        if unit is None:
            return None
        category = self._effective_incident_scope(
            requested_category=requested_category,
            fingerprint=fingerprint,
            unit=unit,
        )
        rules = self.INCIDENT_CONTAINMENT_RULES.get(category)
        if rules is None:
            return None
        if capability not in set(rules["capabilities"]):
            return None
        allowed_units = {str(item).strip().lower() for item in set(rules["units"])}
        if allowed_units and unit.strip().lower() not in allowed_units:
            return None
        return {
            "capability": capability,
            "action_id": service_module.CAPABILITY_ACTION[capability],
            "unit": unit,
            "category": category,
            "rollback_hint": service_module.rollback(capability=capability, unit=unit),
        }

    def plan(self, intent_text: str, intent_cluster: str) -> ModulePlan | None:
        capability = self.resolve_capability(intent_text=intent_text, intent_cluster=intent_cluster)
        if capability is None:
            return None
        category = self.extract_category(intent_text)
        severity = self.extract_severity(intent_text)
        fingerprint = self.extract_fingerprint(intent_text)
        incident_id = self.extract_incident_id(intent_text)
        args = {"category": category}
        if severity != "all":
            args["severity"] = severity
        if fingerprint:
            args["fingerprint"] = fingerprint
        verify_detail = "5"
        if capability == self.INCIDENT_LIST_ACTION_ID:
            status = self.extract_incident_status(intent_text)
            limit = self.extract_limit(intent_text)
            args = {"status": status, "limit": limit}
            if category != "all":
                args["category"] = category
            if severity != "all":
                args["severity"] = severity
            if fingerprint:
                args["fingerprint"] = fingerprint
            return ModulePlan(
                module_id=self.MODULE_ID,
                capability=capability,
                action_id=capability,
                args=args,
                pre_checks=self.pre_check(capability, category),
                verify_checks=self.verify(capability, category, limit),
                rollback_hint="No rollback required for local incident listing.",
            )
        if capability == self.INCIDENT_SHOW_ACTION_ID:
            if not incident_id:
                return None
            activity_limit = self.extract_activity_limit(intent_text)
            return ModulePlan(
                module_id=self.MODULE_ID,
                capability=capability,
                action_id=capability,
                args={"incident_id": incident_id, "activity_limit": activity_limit},
                pre_checks=self.pre_check(capability, category),
                verify_checks=self.verify(capability, category, activity_limit),
                rollback_hint="No rollback required for local incident inspection.",
            )
        if capability in {self.INCIDENT_RESOLVE_ACTION_ID, self.INCIDENT_DISMISS_ACTION_ID}:
            if not incident_id:
                return None
            return ModulePlan(
                module_id=self.MODULE_ID,
                capability=capability,
                action_id=capability,
                args={"incident_id": incident_id},
                pre_checks=self.pre_check(capability, category),
                verify_checks=self.verify(capability, category, "1"),
                rollback_hint="No rollback required for local incident state transition.",
            )
        if capability == self.INCIDENT_CONTAIN_CAPABILITY:
            service_action = self._resolve_incident_service_action(
                intent_text=intent_text,
                requested_category=category,
                fingerprint=fingerprint,
            )
            if service_action is None:
                return None
            unit = str(service_action["unit"])
            incident_scope = str(service_action["category"])
            args = {
                "category": incident_scope,
                "unit": unit,
            }
            if severity != "all":
                args["severity"] = severity
            if fingerprint:
                args["fingerprint"] = fingerprint
            pre_checks = [
                f"Correlate active {incident_scope} incident alerts with target unit {unit}.",
                "Require explicit operator confirmation before containment or remediation.",
                f"Validate recent journal and failed-unit context for {unit} before mutation.",
            ]
            verify_checks = [
                f"Verify containment action for {unit} only runs when there is an active matching {incident_scope} incident.",
                f"Verify {unit} health and alert posture immediately after the action.",
            ]
            return ModulePlan(
                module_id=self.MODULE_ID,
                capability=capability,
                action_id=str(service_action["action_id"]),
                args=args,
                pre_checks=pre_checks,
                verify_checks=verify_checks,
                rollback_hint=str(service_action["rollback_hint"]),
            )
        if capability == self.INCIDENT_PLAN_ACTION_ID:
            window_hours = self.extract_window_hours(intent_text)
            limit = self.extract_limit(intent_text)
            args["window_hours"] = window_hours
            args["limit"] = limit
            verify_detail = limit
            return ModulePlan(
                module_id=self.MODULE_ID,
                capability=capability,
                action_id=capability,
                args=args,
                pre_checks=[
                    "Inspect active security alerts and recent system events before proposing response.",
                    "Prefer the minimum safe response set and avoid speculative containment.",
                ],
                verify_checks=[
                    f"Verify incident playbook covers up to {limit} active alert(s) in the last {window_hours}h.",
                ],
                rollback_hint="No rollback required for local incident planning.",
            )
        if capability == self.VIGILANCE_ACTION_ID:
            window_hours = self.extract_window_hours(intent_text)
            args["window_hours"] = window_hours
            verify_detail = window_hours
        elif capability == self.ALERTS_SILENCE_ACTION_ID:
            window_hours = self.extract_window_hours(intent_text)
            args["silence_hours"] = window_hours
            alert_ids = self.extract_alert_ids(intent_text)
            if alert_ids:
                args["alert_ids"] = ",".join(alert_ids)
            elif severity != "all" or fingerprint:
                args["limit"] = "10"
            verify_detail = window_hours
        elif capability == self.ALERTS_ACK_ACTION_ID:
            alert_ids = self.extract_alert_ids(intent_text)
            if alert_ids:
                args["alert_ids"] = ",".join(alert_ids)
            else:
                args["limit"] = "10" if (severity != "all" or fingerprint) else "1"
            verify_detail = str(len(alert_ids) or int(args.get("limit", "1")))
        elif capability == self.ALERTS_LIST_ACTION_ID:
            limit = self.extract_limit(intent_text)
            args["limit"] = limit
            verify_detail = limit
        else:
            limit = self.extract_limit(intent_text)
            args["limit"] = limit
            verify_detail = limit
        return ModulePlan(
            module_id=self.MODULE_ID,
            capability=capability,
            action_id=capability,
            args=args,
            pre_checks=self.pre_check(capability, category),
            verify_checks=self.verify(capability, category, verify_detail),
            rollback_hint=self.rollback(),
        )
