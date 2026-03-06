#!/usr/bin/env python3
"""Tests for DNS module capability resolution."""

from __future__ import annotations

import unittest

from mastercontrol.modules.mod_dns import DNSModule


class DNSModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = DNSModule()

    def test_resolve_all_scope_with_todo(self) -> None:
        capability = self.module.resolve_capability(
            intent_text="limpar todo o cache dns",
            intent_cluster="dns.flush",
        )
        self.assertEqual(capability, "dns.flush.all")

    def test_resolve_all_scope_with_todos(self) -> None:
        capability = self.module.resolve_capability(
            intent_text="limpar todos os caches do unbound",
            intent_cluster="dns.flush",
        )
        self.assertEqual(capability, "dns.flush.all")

    def test_resolve_bogus_scope(self) -> None:
        capability = self.module.resolve_capability(
            intent_text="limpar cache bogus do unbound",
            intent_cluster="dns.flush",
        )
        self.assertEqual(capability, "dns.flush.bogus")

    def test_plan_maps_all_scope_to_flush_all_action(self) -> None:
        plan = self.module.plan(
            intent_text="flush all dns cache",
            intent_cluster="dns.flush",
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.module_id, "mod_dns")
        self.assertEqual(plan.capability, "dns.flush.all")
        self.assertEqual(plan.action_id, "dns.unbound.flush_all")


if __name__ == "__main__":
    unittest.main()
