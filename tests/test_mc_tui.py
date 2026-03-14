#!/usr/bin/env python3
"""Tests for local auto-executed flows in the terminal UI."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from mastercontrol.interface.mc_tui import TerminalUI


class _FakeInterface:
    def __init__(self) -> None:
        self.state = SimpleNamespace(
            mode="confirm",
            risk_level="medium",
            path_mode="auto",
            incident=False,
            llm_enabled=False,
            llm_model="qwen3:4b",
        )
        self._incidents = [
            {
                "incident_id": "inc-001",
                "fingerprint": "service.failure.cluster",
                "category": "service",
                "severity": "high",
                "status": "open",
                "latest_summary": "nginx.service entered failed state",
                "correlated_units": ("nginx.service",),
            },
            {
                "incident_id": "inc-002",
                "fingerprint": "security.auth.anomaly",
                "category": "security",
                "severity": "critical",
                "status": "contained",
                "latest_summary": "Authentication anomalies detected.",
                "correlated_units": ("ssh.service",),
            },
        ]
        self.calls: list[dict[str, object]] = []

    def _prepare_intent(self, line: str, use_llm: bool = True) -> str:
        del use_llm
        return line

    @staticmethod
    def _is_high_risk_action(mapped_action):  # type: ignore[no-untyped-def]
        return str((mapped_action or {}).get("action_risk", "unknown")) in {"high", "critical"}

    def run_intent(self, prepared: str, execute: bool, dry_run: bool, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "prepared": prepared,
                "execute": execute,
                "dry_run": dry_run,
                **kwargs,
            }
        )
        return {
            "message": "ok",
            "request_id": str(kwargs.get("request_id", "") or "req-1"),
            "path": {"path": "fast", "source": "selector", "confidence": 0.9},
            "tone": {"intent_cluster": "security.alerts.list", "intent_source": "heuristic"},
            "mapped_action": {
                "action_id": "security.alerts.list",
                "action_risk": "low",
                "requires_mutation": False,
            },
            "execution": {
                "outcome": "Recent security alerts: #1 high security.auth.anomaly.",
                "executed": not execute or True,
            },
        }

    def active_alert_status_line(self) -> str:
        return "alerts=2 status=elevated severity=high"

    def active_incident_snapshot(  # type: ignore[no-untyped-def]
        self,
        *,
        force: bool = False,
        incident_id: str = "",
        limit: int = 6,
        activity_limit: int = 5,
    ):
        del force, activity_limit
        incidents = [dict(row) for row in self._incidents[:limit]]
        selected = incident_id or incidents[0]["incident_id"]
        detail = next((dict(row) for row in incidents if row["incident_id"] == selected), None)
        if detail is not None:
            detail["alerts"] = [{"id": 1}]
            detail["activity"] = [
                {
                    "action_id": "security.watch.open",
                    "status_from": "",
                    "status_to": detail["status"],
                    "resolution_summary": detail["latest_summary"],
                }
            ]
        return {
            "incidents": incidents,
            "detail": detail,
            "selected_incident_id": selected if detail is not None else "",
        }


class TerminalUITests(unittest.TestCase):
    def test_status_line_includes_active_alert_summary(self) -> None:
        interface = _FakeInterface()
        ui = TerminalUI(interface, warmup_on_start=False)

        line = ui._status_line()

        self.assertIn("alerts=2", line)
        self.assertIn("severity=high", line)

    def test_autoexecuted_local_alert_flow_does_not_prompt_choice(self) -> None:
        interface = _FakeInterface()
        ui = TerminalUI(interface, warmup_on_start=False)
        ui._post = lambda event: event()

        ui._job_handle_intent("mostre os alertas de seguranca", use_llm=False)

        self.assertIsNone(ui.pending_choice)
        self.assertIsNone(ui.pending_high_risk)

    def test_dry_run_mode_uses_single_direct_execution_pass(self) -> None:
        interface = _FakeInterface()
        interface.state.mode = "dry-run"
        ui = TerminalUI(interface, warmup_on_start=False)
        ui._post = lambda event: event()

        ui._job_handle_intent("restart unbound.service", use_llm=False)

        self.assertEqual(len(interface.calls), 1)
        self.assertTrue(interface.calls[0]["execute"])
        self.assertTrue(interface.calls[0]["dry_run"])
        self.assertFalse(interface.calls[0]["allow_high_risk"])

    def test_execute_mode_sets_pending_high_risk_only_after_step_up_block(self) -> None:
        class _StepUpInterface(_FakeInterface):
            def run_intent(self, prepared: str, execute: bool, dry_run: bool, **kwargs):  # type: ignore[no-untyped-def]
                self.calls.append(
                    {
                        "prepared": prepared,
                        "execute": execute,
                        "dry_run": dry_run,
                        **kwargs,
                    }
                )
                blocked = execute and not dry_run and not bool(kwargs.get("allow_high_risk", False))
                return {
                    "message": "blocked" if blocked else "ok",
                    "request_id": "req-step-up",
                    "path": {"path": "deep", "source": "selector", "confidence": 0.92},
                    "tone": {"intent_cluster": "service.restart", "intent_source": "heuristic"},
                    "mapped_action": {
                        "action_id": "service.systemctl.restart",
                        "action_risk": "high",
                        "requires_mutation": True,
                    },
                    "execution": {
                        "outcome": "blocked" if blocked else "executed",
                        "executed": not blocked,
                        "blocked": blocked,
                        "command_error": "step_up_required" if blocked else "",
                    },
                }

        interface = _StepUpInterface()
        interface.state.mode = "execute"
        ui = TerminalUI(interface, warmup_on_start=False)
        ui._post = lambda event: event()

        ui._job_handle_intent("restart unbound.service", use_llm=False)

        self.assertEqual(len(interface.calls), 1)
        self.assertIsNotNone(ui.pending_high_risk)
        assert ui.pending_high_risk is not None
        self.assertEqual(ui.pending_high_risk.request_id, "req-step-up")

    def test_incident_snapshot_refresh_tracks_selection(self) -> None:
        interface = _FakeInterface()
        ui = TerminalUI(interface, warmup_on_start=False)

        ui._refresh_incident_snapshot(force=True)

        self.assertEqual(len(ui._incident_rows), 2)
        self.assertEqual(ui._selected_incident_id(), "inc-001")
        self.assertIsNotNone(ui._incident_detail)
        assert ui._incident_detail is not None
        self.assertEqual(ui._incident_detail["incident_id"], "inc-001")

        moved = ui._move_incident_selection(1)

        self.assertTrue(moved)
        self.assertEqual(ui._selected_incident_id(), "inc-002")
        assert ui._incident_detail is not None
        self.assertEqual(ui._incident_detail["incident_id"], "inc-002")

    def test_incident_panel_lines_include_selection_and_detail(self) -> None:
        interface = _FakeInterface()
        ui = TerminalUI(interface, warmup_on_start=False)
        ui._refresh_incident_snapshot(force=True)

        lines = ui._build_incident_panel_lines(48, 10)

        self.assertTrue(lines)
        joined = "\n".join(lines)
        self.assertIn("Incidentes ativos (2)", joined)
        self.assertIn("> open/high inc-001", joined)
        self.assertIn("fingerprint: service.failure.cluster", joined)
        self.assertIn("unidades: nginx.service", joined)


if __name__ == "__main__":
    unittest.main()
