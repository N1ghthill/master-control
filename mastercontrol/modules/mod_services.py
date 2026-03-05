#!/usr/bin/env python3
"""Service operations module."""

from __future__ import annotations

import re
from typing import Any

from mastercontrol.modules.base import ModulePlan


class ServiceModule:
    """Encapsulates system service operations with allowlisted actions."""

    MODULE_ID = "mod_services"
    CAPABILITY_ACTION = {
        "service.restart": "service.systemctl.restart",
        "service.start": "service.systemctl.start",
        "service.stop": "service.systemctl.stop",
    }

    KNOWN_UNITS = {
        "unbound": "unbound.service",
        "ssh": "ssh.service",
        "sshd": "ssh.service",
        "nginx": "nginx.service",
        "apache2": "apache2.service",
        "networkmanager": "NetworkManager.service",
        "systemd-resolved": "systemd-resolved.service",
        "docker": "docker.service",
    }

    def capabilities(self) -> list[str]:
        return sorted(self.CAPABILITY_ACTION.values())

    def resolve_capability(self, intent_text: str, intent_cluster: str) -> str | None:
        text = (intent_text or "").lower()
        cluster = (intent_cluster or "").lower()

        if cluster in self.CAPABILITY_ACTION:
            return cluster
        if "restart" in text or "reiniciar" in text or "reload" in text:
            return "service.restart"
        if "start" in text or "iniciar" in text:
            return "service.start"
        if "stop" in text or "parar" in text:
            return "service.stop"
        return None

    def extract_unit(self, intent_text: str) -> str | None:
        text = (intent_text or "").lower()
        for key, unit in self.KNOWN_UNITS.items():
            if re.search(rf"\b{re.escape(key)}\b", text):
                return unit
        match = re.search(r"\b([a-z0-9@_.:-]+\.service)\b", text)
        if match:
            return match.group(1)
        return None

    def pre_check(self, capability: str, unit: str) -> list[str]:
        checks = [
            f"Validate target unit and current state before mutation ({unit}).",
            f"Check recent health/journal for {unit} before action.",
        ]
        if capability == "service.stop":
            checks.append("Confirm impact scope for dependent units before stop.")
        return checks

    def apply(self, capability: str, unit: str) -> dict[str, Any] | None:
        action_id = self.CAPABILITY_ACTION.get(capability)
        if action_id is None:
            return None
        return {
            "module_id": self.MODULE_ID,
            "capability": capability,
            "action_id": action_id,
            "args": {"unit": unit},
        }

    @staticmethod
    def verify(capability: str, unit: str) -> list[str]:
        if capability == "service.stop":
            return [f"Verify {unit} is inactive and no critical dependency broke unexpectedly."]
        return [f"Verify {unit} is active and healthy after mutation."]

    @staticmethod
    def rollback(capability: str, unit: str) -> str:
        if capability == "service.stop":
            return f"If stop caused impact, start {unit} and validate dependencies."
        if capability == "service.start":
            return f"If start caused instability, stop {unit} and inspect journal logs."
        return f"If restart failed, run service start for {unit} and inspect journalctl for root cause."

    def plan(self, intent_text: str, intent_cluster: str) -> ModulePlan | None:
        capability = self.resolve_capability(intent_text=intent_text, intent_cluster=intent_cluster)
        if capability is None:
            return None
        unit = self.extract_unit(intent_text=intent_text)
        if unit is None:
            return None
        action = self.apply(capability=capability, unit=unit)
        if action is None:
            return None
        return ModulePlan(
            module_id=self.MODULE_ID,
            capability=capability,
            action_id=str(action["action_id"]),
            args=dict(action.get("args", {})),
            pre_checks=self.pre_check(capability=capability, unit=unit),
            verify_checks=self.verify(capability=capability, unit=unit),
            rollback_hint=self.rollback(capability=capability, unit=unit),
        )
