#!/usr/bin/env python3
"""Shared contracts for operational modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ModulePlan:
    module_id: str
    capability: str
    action_id: str
    args: dict[str, str]
    pre_checks: list[str]
    verify_checks: list[str]
    rollback_hint: str


class OperationalModule(Protocol):
    MODULE_ID: str

    def capabilities(self) -> list[str]:
        ...

    def plan(self, intent_text: str, intent_cluster: str) -> ModulePlan | None:
        ...

