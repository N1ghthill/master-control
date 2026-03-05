#!/usr/bin/env python3
"""Package operations module."""

from __future__ import annotations

import re
from typing import Any

from mastercontrol.modules.base import ModulePlan


class PackageModule:
    """Encapsulates apt package operations with allowlisted actions."""

    MODULE_ID = "mod_packages"
    CAPABILITY_ACTION = {
        "package.update": "package.apt.update",
        "package.install": "package.apt.install_one",
        "package.remove": "package.apt.remove_one",
    }

    def capabilities(self) -> list[str]:
        return sorted(self.CAPABILITY_ACTION.values())

    def resolve_capability(self, intent_text: str, intent_cluster: str) -> str | None:
        text = (intent_text or "").lower()
        cluster = (intent_cluster or "").lower()
        tokens = set(re.findall(r"[a-z0-9_.:-]+", text))

        if cluster in self.CAPABILITY_ACTION:
            return cluster
        if "apt" in tokens and "update" in tokens:
            return "package.update"
        if tokens.intersection({"install", "instalar"}) and tokens.intersection({"apt", "package", "pacote"}):
            return "package.install"
        if tokens.intersection({"remove", "remover", "desinstalar", "purge"}) and tokens.intersection(
            {"apt", "package", "pacote"}
        ):
            return "package.remove"
        return None

    def extract_package(self, intent_text: str, capability: str) -> str | None:
        if capability == "package.update":
            return None

        text = (intent_text or "").lower()
        text = re.sub(r"\s+", " ", text).strip()

        cmd_match = re.search(
            r"\bapt(?:-get)?\s+(?:install|remove|purge)\s+(?:-y\s+)?(?:--\s+)?([a-z0-9][a-z0-9+.-]*)\b",
            text,
        )
        if cmd_match:
            candidate = cmd_match.group(1)
            if self._is_package_name(candidate):
                return candidate

        if capability == "package.install":
            keyword_re = r"\b(?:install|instalar)\b"
        else:
            keyword_re = r"\b(?:remove|remover|desinstalar|purge)\b"
        match = re.search(keyword_re, text)
        if not match:
            return None
        tail = text[match.end() :].strip()
        for token in re.findall(r"[a-z0-9+.-]+", tail):
            if token in {"package", "pacote", "apt", "apt-get", "de", "o", "a"}:
                continue
            if self._is_package_name(token):
                return token
        return None

    @staticmethod
    def _is_package_name(name: str) -> bool:
        return bool(re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", name))

    def pre_check(self, capability: str, package: str | None) -> list[str]:
        if capability == "package.update":
            return [
                "Check apt lock state and repository reachability before update.",
                "Confirm package index refresh is required for current task.",
            ]
        pkg = package or "<package>"
        if capability == "package.install":
            return [
                f"Validate requested package name and repository availability ({pkg}).",
                f"Check whether {pkg} is already installed to avoid redundant mutation.",
            ]
        return [
            f"Validate requested package name and current install state ({pkg}).",
            f"Check reverse-dependency impact before removing {pkg}.",
        ]

    def apply(self, capability: str, package: str | None) -> dict[str, Any] | None:
        action_id = self.CAPABILITY_ACTION.get(capability)
        if action_id is None:
            return None
        args: dict[str, str] = {}
        if capability in {"package.install", "package.remove"}:
            if not package:
                return None
            args["package"] = package
        return {
            "module_id": self.MODULE_ID,
            "capability": capability,
            "action_id": action_id,
            "args": args,
        }

    @staticmethod
    def verify(capability: str, package: str | None) -> list[str]:
        if capability == "package.update":
            return ["Verify apt metadata refresh completed successfully."]
        pkg = package or "<package>"
        if capability == "package.install":
            return [f"Verify {pkg} is installed and package manager state is consistent."]
        return [f"Verify {pkg} is removed and no broken dependencies remain."]

    @staticmethod
    def rollback(capability: str, package: str | None) -> str:
        if capability == "package.update":
            return "No direct rollback for index update; proceed with pinned versions if needed."
        pkg = package or "<package>"
        if capability == "package.install":
            return f"If install caused issues, remove {pkg} and revalidate dependencies."
        return f"If removal caused issues, reinstall {pkg} and revalidate dependencies."

    def plan(self, intent_text: str, intent_cluster: str) -> ModulePlan | None:
        capability = self.resolve_capability(intent_text=intent_text, intent_cluster=intent_cluster)
        if capability is None:
            return None
        package = self.extract_package(intent_text=intent_text, capability=capability)
        action = self.apply(capability=capability, package=package)
        if action is None:
            return None
        return ModulePlan(
            module_id=self.MODULE_ID,
            capability=capability,
            action_id=str(action["action_id"]),
            args=dict(action.get("args", {})),
            pre_checks=self.pre_check(capability=capability, package=package),
            verify_checks=self.verify(capability=capability, package=package),
            rollback_hint=self.rollback(capability=capability, package=package),
        )
