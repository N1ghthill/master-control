from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from master_control.app import MasterControlApp
from master_control.config import Settings
from master_control.tools.base import RiskLevel, Tool, ToolSpec


class HighMemoryTool(Tool):
    spec = ToolSpec(
        name="memory_usage",
        description="Fake high memory tool for tests.",
        risk=RiskLevel.READ_ONLY,
    )

    def invoke(self, arguments):
        del arguments
        return {
            "memory_total_bytes": 100,
            "memory_used_bytes": 92,
            "memory_used_percent": 92.0,
            "swap_total_bytes": 100,
            "swap_used_bytes": 10,
            "swap_used_percent": 10.0,
        }


class HotProcessTool(Tool):
    spec = ToolSpec(
        name="top_processes",
        description="Fake hot process tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("limit",),
    )

    def invoke(self, arguments):
        del arguments
        return {
            "status": "ok",
            "processes": [
                {"command": "nginx", "cpu_percent": 88.0},
                {"command": "python", "cpu_percent": 20.0},
            ],
        }


class HealthyServiceTool(Tool):
    spec = ToolSpec(
        name="service_status",
        description="Fake healthy service status tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("name",),
    )

    def invoke(self, arguments):
        name = arguments.get("name", "nginx")
        return {
            "status": "ok",
            "service": name,
            "activestate": "active",
            "substate": "running",
            "unitfilestate": "enabled",
        }


class MultiStepChatTest(unittest.TestCase):
    def test_heuristic_provider_executes_multi_step_diagnosis_within_one_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.registry.register(HighMemoryTool())
            app.registry.register(HotProcessTool())
            app.registry.register(HealthyServiceTool())

            payload = app.chat("o host esta lento", new_session=True)

            executed_tools = [item["tool"] for item in payload["executions"]]
            self.assertEqual(executed_tools, ["memory_usage", "top_processes", "service_status"])
            self.assertIn("Resumo do diagnóstico:", payload["message"])
            self.assertIn("nginx", payload["message"])


if __name__ == "__main__":
    unittest.main()
