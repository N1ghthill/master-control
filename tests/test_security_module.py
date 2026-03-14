#!/usr/bin/env python3
"""Tests for the local security audit module."""

from __future__ import annotations

import unittest

from mastercontrol.modules.mod_security import SecurityModule


class SecurityModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = SecurityModule()

    def test_plan_resolves_security_audit_cluster(self) -> None:
        plan = self.module.plan(
            intent_text="faca uma auditoria de seguranca",
            intent_cluster="security.audit",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.module_id, "mod_security")
        self.assertEqual(plan.action_id, "security.audit.recent_events")
        self.assertEqual(plan.args["category"], "security")

    def test_plan_extracts_specific_scope(self) -> None:
        plan = self.module.plan(
            intent_text="audite eventos de rede 10",
            intent_cluster="security.audit",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.args["category"], "network")
        self.assertEqual(plan.args["limit"], "10")

    def test_plan_resolves_security_vigilance_cluster(self) -> None:
        plan = self.module.plan(
            intent_text="vigie o sistema contra intrusos por 12 horas",
            intent_cluster="security.vigilance",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.action_id, "security.vigilance.status")
        self.assertEqual(plan.args["category"], "security")
        self.assertEqual(plan.args["window_hours"], "12")

    def test_plan_lists_recent_alerts(self) -> None:
        plan = self.module.plan(
            intent_text="mostre os alertas de seguranca 10",
            intent_cluster="general.assist",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.action_id, "security.alerts.list")
        self.assertEqual(plan.args["limit"], "10")

    def test_plan_acknowledges_alert_by_id(self) -> None:
        plan = self.module.plan(
            intent_text="reconheca o alerta 12",
            intent_cluster="general.assist",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.action_id, "security.alerts.ack")
        self.assertEqual(plan.args["alert_ids"], "12")

    def test_plan_acknowledges_alerts_by_fingerprint_and_severity(self) -> None:
        plan = self.module.plan(
            intent_text="reconheca os alertas high fingerprint service.failure.cluster",
            intent_cluster="general.assist",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.action_id, "security.alerts.ack")
        self.assertEqual(plan.args["severity"], "high")
        self.assertEqual(plan.args["fingerprint"], "service.failure.cluster")
        self.assertEqual(plan.args["limit"], "10")

    def test_plan_silences_alert_by_id_and_window(self) -> None:
        plan = self.module.plan(
            intent_text="silencie o alerta 12 por 24 horas",
            intent_cluster="general.assist",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.action_id, "security.alerts.silence")
        self.assertEqual(plan.args["alert_ids"], "12")
        self.assertEqual(plan.args["silence_hours"], "24")

    def test_plan_silences_alerts_by_severity_without_id(self) -> None:
        plan = self.module.plan(
            intent_text="silencie os alertas criticos por 24 horas",
            intent_cluster="general.assist",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.action_id, "security.alerts.silence")
        self.assertEqual(plan.args["severity"], "critical")
        self.assertEqual(plan.args["limit"], "10")

    def test_plan_builds_incident_playbook(self) -> None:
        plan = self.module.plan(
            intent_text="responda ao incidente de seguranca",
            intent_cluster="security.incident",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.action_id, "security.incident.plan")
        self.assertEqual(plan.args["window_hours"], "6")
        self.assertEqual(plan.args["limit"], "5")

    def test_plan_lists_incident_ledger_rows(self) -> None:
        plan = self.module.plan(
            intent_text="liste os incidentes status resolved 10",
            intent_cluster="security.incident",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.action_id, "security.incident.list")
        self.assertEqual(plan.args["status"], "resolved")
        self.assertEqual(plan.args["limit"], "10")

    def test_plan_shows_incident_detail_by_id(self) -> None:
        plan = self.module.plan(
            intent_text="mostre o incidente inc-123abc",
            intent_cluster="security.incident",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.action_id, "security.incident.show")
        self.assertEqual(plan.args["incident_id"], "inc-123abc")

    def test_plan_resolves_incident_by_id(self) -> None:
        plan = self.module.plan(
            intent_text="resolva o incidente inc-123abc",
            intent_cluster="security.incident",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.action_id, "security.incident.resolve")
        self.assertEqual(plan.args["incident_id"], "inc-123abc")

    def test_plan_dismisses_incident_by_id(self) -> None:
        plan = self.module.plan(
            intent_text="descarte o incidente inc-123abc",
            intent_cluster="security.incident",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.action_id, "security.incident.dismiss")
        self.assertEqual(plan.args["incident_id"], "inc-123abc")

    def test_plan_maps_controlled_incident_containment_to_service_action(self) -> None:
        plan = self.module.plan(
            intent_text="responda ao incidente reiniciando nginx.service",
            intent_cluster="security.incident",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.capability, "security.incident.contain")
        self.assertEqual(plan.action_id, "service.systemctl.restart")
        self.assertEqual(plan.args["category"], "service")
        self.assertEqual(plan.args["unit"], "nginx.service")

    def test_plan_maps_auth_incident_remediation_to_ssh_restart(self) -> None:
        plan = self.module.plan(
            intent_text="responda ao incidente reiniciando ssh.service",
            intent_cluster="security.incident",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.capability, "security.incident.contain")
        self.assertEqual(plan.action_id, "service.systemctl.restart")
        self.assertEqual(plan.args["category"], "security")
        self.assertEqual(plan.args["unit"], "ssh.service")

    def test_plan_maps_network_incident_remediation_to_networkmanager_restart(self) -> None:
        plan = self.module.plan(
            intent_text="responda ao incidente reiniciando networkmanager",
            intent_cluster="security.incident",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.capability, "security.incident.contain")
        self.assertEqual(plan.action_id, "service.systemctl.restart")
        self.assertEqual(plan.args["category"], "network")
        self.assertEqual(plan.args["unit"], "NetworkManager.service")


if __name__ == "__main__":
    unittest.main()
