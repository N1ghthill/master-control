#!/usr/bin/env python3
"""Module registry and resolution policy for MasterControl."""

from __future__ import annotations

from dataclasses import dataclass

from mastercontrol.modules.base import ModulePlan, OperationalModule


@dataclass
class ResolutionResult:
    plan: ModulePlan | None
    attempted_modules: list[str]


class ModuleRegistry:
    """Resolve operational plan by intent cluster and module priority."""

    CLUSTER_PRIORITY = {
        "dns.": ("mod_dns", "mod_network", "mod_services", "mod_packages", "mod_security"),
        "network.": ("mod_network", "mod_security", "mod_dns", "mod_services", "mod_packages"),
        "service.": ("mod_services", "mod_security", "mod_packages", "mod_network", "mod_dns"),
        "package.": ("mod_packages", "mod_security", "mod_services", "mod_network", "mod_dns"),
        "security.": ("mod_security", "mod_services", "mod_network", "mod_packages", "mod_dns"),
    }

    def __init__(self, modules: list[OperationalModule]) -> None:
        self._modules = {m.MODULE_ID: m for m in modules}
        self._fallback_order = [m.MODULE_ID for m in modules]

    def resolve(self, intent_text: str, intent_cluster: str) -> ResolutionResult:
        cluster = (intent_cluster or "").strip().lower()
        ordered_ids = self._ordered_modules_for_cluster(cluster)

        attempted: list[str] = []
        for module_id in ordered_ids:
            module = self._modules.get(module_id)
            if module is None:
                continue
            attempted.append(module_id)
            plan = module.plan(intent_text=intent_text, intent_cluster=intent_cluster)
            if plan is not None:
                return ResolutionResult(plan=plan, attempted_modules=attempted)

        return ResolutionResult(plan=None, attempted_modules=attempted)

    def module_ids(self) -> list[str]:
        return list(self._fallback_order)

    def _ordered_modules_for_cluster(self, cluster: str) -> list[str]:
        for prefix, preferred in self.CLUSTER_PRIORITY.items():
            if cluster.startswith(prefix):
                merged: list[str] = []
                for module_id in list(preferred) + self._fallback_order:
                    if module_id not in merged and module_id in self._modules:
                        merged.append(module_id)
                return merged
        return [m for m in self._fallback_order if m in self._modules]
