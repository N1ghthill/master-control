#!/usr/bin/env python3
"""Network diagnostic operations module."""

from __future__ import annotations

import re
from typing import Any

from mastercontrol.modules.base import ModulePlan


class NetworkModule:
    """Encapsulates low-risk network diagnostics."""

    MODULE_ID = "mod_network"
    CAPABILITY_ACTION = {
        "network.ping": "network.diagnose.ping",
        "network.resolve": "network.diagnose.resolve",
        "network.route.default": "network.diagnose.route_default",
    }

    KEYWORDS_ROUTE = {"route", "rota", "gateway", "default-route", "default"}
    KEYWORDS_PING = {"ping", "latency", "latencia", "conectividade", "connectivity"}
    KEYWORDS_RESOLVE = {"resolve", "resolver", "lookup", "nslookup", "getent", "host"}
    IGNORE_TOKENS = {
        "network",
        "rede",
        "diagnose",
        "diagnosticar",
        "check",
        "verify",
        "verificar",
        "ping",
        "resolve",
        "resolver",
        "lookup",
        "nslookup",
        "getent",
        "host",
        "route",
        "rota",
        "gateway",
        "default",
    }

    def capabilities(self) -> list[str]:
        return sorted(self.CAPABILITY_ACTION.values())

    def resolve_capability(self, intent_text: str, intent_cluster: str) -> str | None:
        text = (intent_text or "").lower()
        tokens = set(re.findall(r"[a-z0-9_.:-]+", text))
        cluster = (intent_cluster or "").lower()

        network_signal = cluster.startswith("network.") or bool(
            tokens.intersection(self.KEYWORDS_ROUTE | self.KEYWORDS_PING | self.KEYWORDS_RESOLVE)
        )
        if not network_signal:
            return None

        if tokens.intersection(self.KEYWORDS_ROUTE):
            return "network.route.default"
        if tokens.intersection(self.KEYWORDS_RESOLVE):
            return "network.resolve"
        if tokens.intersection(self.KEYWORDS_PING):
            return "network.ping"
        return None

    def extract_host(self, intent_text: str, capability: str) -> str | None:
        if capability == "network.route.default":
            return None
        text = (intent_text or "").lower()

        ip_match = re.search(
            r"\b((?:25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])(?:\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9]?[0-9])){3})\b",
            text,
        )
        if ip_match:
            return ip_match.group(1)

        for token in re.findall(r"[a-z0-9.-]+", text):
            if token in self.IGNORE_TOKENS:
                continue
            if re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", token):
                return token
        return None

    def pre_check(self, capability: str, host: str | None) -> list[str]:
        if capability == "network.route.default":
            return ["Ensure route inspection scope is read-only and diagnostic."]
        target = host or "<host>"
        if capability == "network.resolve":
            return [f"Validate target host format before resolver lookup ({target})."]
        return [f"Validate target host before connectivity probe ({target})."]

    def apply(self, capability: str, host: str | None) -> dict[str, Any] | None:
        action_id = self.CAPABILITY_ACTION.get(capability)
        if action_id is None:
            return None
        args: dict[str, str] = {}
        if capability in {"network.ping", "network.resolve"}:
            if not host:
                return None
            args["host"] = host
        return {
            "module_id": self.MODULE_ID,
            "capability": capability,
            "action_id": action_id,
            "args": args,
        }

    @staticmethod
    def verify(capability: str, host: str | None) -> list[str]:
        if capability == "network.route.default":
            return ["Verify default route output is present and parsable."]
        target = host or "<host>"
        if capability == "network.resolve":
            return [f"Verify resolver returned at least one address for {target}."]
        return [f"Verify ping output produced packet statistics for {target}."]

    @staticmethod
    def rollback(capability: str, host: str | None) -> str:
        _ = capability
        _ = host
        return "No rollback required for read-only network diagnostics."

    def plan(self, intent_text: str, intent_cluster: str) -> ModulePlan | None:
        capability = self.resolve_capability(intent_text=intent_text, intent_cluster=intent_cluster)
        if capability is None:
            return None
        host = self.extract_host(intent_text=intent_text, capability=capability)
        action = self.apply(capability=capability, host=host)
        if action is None:
            return None
        return ModulePlan(
            module_id=self.MODULE_ID,
            capability=capability,
            action_id=str(action["action_id"]),
            args=dict(action.get("args", {})),
            pre_checks=self.pre_check(capability=capability, host=host),
            verify_checks=self.verify(capability=capability, host=host),
            rollback_hint=self.rollback(capability=capability, host=host),
        )

