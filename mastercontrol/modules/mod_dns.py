#!/usr/bin/env python3
"""DNS operations module."""

from __future__ import annotations

import re
from typing import Any

from mastercontrol.modules.base import ModulePlan


class DNSModule:
    """Encapsulates DNS-related capabilities and execution planning."""

    MODULE_ID = "mod_dns"
    CAPABILITY_ACTION = {
        "dns.flush.negative": "dns.unbound.flush_negative",
        "dns.flush.bogus": "dns.unbound.flush_bogus",
        "dns.flush.all": "dns.unbound.flush_all",
    }

    def capabilities(self) -> list[str]:
        return sorted(self.CAPABILITY_ACTION.values())

    def resolve_capability(self, intent_text: str, intent_cluster: str) -> str | None:
        text = (intent_text or "").lower()
        tokens = set(re.findall(r"[a-z0-9_.:-]+", text))
        cluster = (intent_cluster or "").lower()

        dns_signal = cluster.startswith("dns.") or bool(
            tokens.intersection({"dns", "unbound", "resolver", "nxdomain", "cache", "dig", "nslookup"})
        )
        if not dns_signal:
            return None

        if "bogus" in tokens:
            return "dns.flush.bogus"
        if tokens.intersection({"negative", "nxdomain"}):
            return "dns.flush.negative"
        if tokens.intersection({"flush", "cache", "clear", "limpar", "reset"}):
            if tokens.intersection({"all", "tudo", "full", "completo"}):
                return "dns.flush.all"
            return "dns.flush.negative"
        return None

    def pre_check(self, capability: str) -> list[str]:
        checks = ["Check DNS service health and resolver responsiveness."]
        if capability.startswith("dns.flush"):
            checks.append("Ensure target cache scope is correct before flushing.")
        return checks

    def apply(self, capability: str, intent_text: str) -> dict[str, Any] | None:
        action_id = self.CAPABILITY_ACTION.get(capability)
        if action_id is None:
            return None
        return {
            "module_id": self.MODULE_ID,
            "capability": capability,
            "action_id": action_id,
            "args": {},
        }

    @staticmethod
    def verify(capability: str) -> list[str]:
        checks = ["Validate resolver answers for known domains after mutation."]
        if capability == "dns.flush.all":
            checks.append("Verify recursive resolution latency remains acceptable.")
        return checks

    @staticmethod
    def rollback(capability: str) -> str:
        if capability.startswith("dns.flush"):
            return "No direct rollback required; warm critical DNS entries via controlled queries."
        return "Rollback guidance unavailable."

    def plan(self, intent_text: str, intent_cluster: str) -> ModulePlan | None:
        capability = self.resolve_capability(intent_text=intent_text, intent_cluster=intent_cluster)
        if capability is None:
            return None
        action = self.apply(capability=capability, intent_text=intent_text)
        if action is None:
            return None
        return ModulePlan(
            module_id=self.MODULE_ID,
            capability=capability,
            action_id=str(action["action_id"]),
            args=dict(action.get("args", {})),
            pre_checks=self.pre_check(capability),
            verify_checks=self.verify(capability),
            rollback_hint=self.rollback(capability),
        )
