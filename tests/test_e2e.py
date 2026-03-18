from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from master_control.agent.planner import ExecutionPlan, PlanStep
from master_control.app import MasterControlApp
from master_control.config import Settings
from master_control.providers.base import ProviderResponse
from master_control.tools.base import RiskLevel, Tool, ToolSpec


class StaticServicePlanProvider:
    name = "static"

    def diagnostics(self) -> dict[str, object]:
        return {"name": self.name, "ready": True}

    def plan(self, request) -> ProviderResponse:
        del request
        return ProviderResponse(
            message="Vou verificar o status do serviço.",
            plan=ExecutionPlan(
                intent="inspect_service_status",
                steps=(
                    PlanStep(
                        tool_name="service_status",
                        rationale="Inspect the requested service status before any action.",
                        arguments={"name": "nginx.service"},
                    ),
                ),
            ),
        )


class FailedServiceStatusTool(Tool):
    spec = ToolSpec(
        name="service_status",
        description="Fake unhealthy service status tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("name",),
    )

    def __init__(self) -> None:
        self.active_state = "failed"
        self.sub_state = "failed"

    def set_healthy(self) -> None:
        self.active_state = "active"
        self.sub_state = "running"

    def invoke(self, arguments):
        name = arguments.get("name", "nginx.service")
        return {
            "status": "ok",
            "service": name,
            "activestate": self.active_state,
            "substate": self.sub_state,
            "unitfilestate": "enabled",
        }


class SuccessfulRestartServiceTool(Tool):
    spec = ToolSpec(
        name="restart_service",
        description="Fake restart service tool for tests.",
        risk=RiskLevel.PRIVILEGED,
        arguments=("name",),
    )

    def __init__(self, status_tool: FailedServiceStatusTool) -> None:
        self.status_tool = status_tool

    def invoke(self, arguments):
        name = arguments.get("name", "nginx.service")
        self.status_tool.set_healthy()
        return {
            "status": "ok",
            "service": name,
            "preflight": {
                "service": name,
                "activestate": "failed",
                "substate": "failed",
            },
            "post_restart": {
                "service": name,
                "activestate": "active",
                "substate": "running",
            },
        }


class EndToEndFlowsTest(unittest.TestCase):
    def test_service_recommendation_flow_reaches_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            status_tool = FailedServiceStatusTool()
            restart_tool = SuccessfulRestartServiceTool(status_tool)
            app = MasterControlApp(settings, provider_override=StaticServicePlanProvider())
            app.registry.register(status_tool)
            app.registry.register(restart_tool)

            first = app.chat("verifique o nginx", new_session=True)
            recommendation_id = first["recommendations"]["active"][0]["id"]

            accepted = app.update_recommendation_status(recommendation_id, "accepted")
            self.assertIn("next_step", accepted)

            pending = app.run_recommendation_action(recommendation_id)
            self.assertTrue(pending["execution"]["pending_confirmation"])

            confirmed = app.run_recommendation_action(recommendation_id, confirmed=True)
            self.assertTrue(confirmed["execution"]["ok"])

            second = app.chat("verifique o nginx novamente", session_id=first["session_id"])
            self.assertEqual(len(second["recommendations"]["active"]), 0)
            resolved = app.list_session_recommendations(first["session_id"])
            self.assertEqual(resolved["recommendations"][0]["status"], "resolved")

    def test_config_write_and_restore_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            managed_root = state_dir / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "service.ini"
            config_path.write_text("[service]\nmode=old\n", encoding="utf-8")

            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            written = app.run_tool(
                "write_config_file",
                {"path": str(config_path), "content": "[service]\nmode=new\n"},
                confirmed=True,
                audit_context={"source": "e2e"},
            )
            self.assertTrue(written["ok"])
            backup_path = written["result"]["backup_path"]

            restored = app.run_tool(
                "restore_config_backup",
                {"path": str(config_path), "backup_path": backup_path},
                confirmed=True,
                audit_context={"source": "e2e"},
            )
            self.assertTrue(restored["ok"])
            self.assertEqual(config_path.read_text(encoding="utf-8"), "[service]\nmode=old\n")


if __name__ == "__main__":
    unittest.main()
