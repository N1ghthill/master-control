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


class MixedHotProcessTool(Tool):
    spec = ToolSpec(
        name="top_processes",
        description="Fake mixed hot process tool for tests.",
        risk=RiskLevel.READ_ONLY,
        arguments=("limit",),
    )

    def invoke(self, arguments):
        del arguments
        return {
            "status": "ok",
            "processes": [
                {"command": "python3", "cpu_percent": 91.0},
                {"command": "python3", "cpu_percent": 88.0},
                {"command": "nginx", "cpu_percent": 88.0},
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
            "scope": arguments.get("scope", "system"),
            "activestate": "active",
            "substate": "running",
            "unitfilestate": "enabled",
        }


class NoCorrelationProcessUnitTool(Tool):
    spec = ToolSpec(
        name="process_to_unit",
        description="Fake correlation tool without a match.",
        risk=RiskLevel.READ_ONLY,
        arguments=("name", "limit"),
    )

    def invoke(self, arguments):
        return {
            "status": "ok",
            "query": {"name": arguments.get("name"), "limit": arguments.get("limit", 3)},
            "matched_process_count": 1,
            "resolved_count": 0,
            "primary_match": None,
            "units": [],
            "correlations": [
                {
                    "pid": 123,
                    "command": arguments.get("name", "nginx"),
                    "cpu_percent": 88.0,
                    "unit": None,
                    "scope": None,
                    "cgroup_path": "/system.slice",
                }
            ],
        }


class CorrelatedProcessUnitTool(Tool):
    spec = ToolSpec(
        name="process_to_unit",
        description="Fake correlation tool with a match.",
        risk=RiskLevel.READ_ONLY,
        arguments=("name", "limit"),
    )

    def invoke(self, arguments):
        return {
            "status": "ok",
            "query": {"name": arguments.get("name"), "limit": arguments.get("limit", 3)},
            "matched_process_count": 1,
            "resolved_count": 1,
            "primary_match": {
                "pid": 123,
                "command": arguments.get("name", "nginx"),
                "unit": "nginx.service",
                "scope": "system",
            },
            "units": [
                {
                    "unit": "nginx.service",
                    "scope": "system",
                    "pid_count": 1,
                    "pids": [123],
                    "commands": [arguments.get("name", "nginx")],
                }
            ],
            "correlations": [
                {
                    "pid": 123,
                    "command": arguments.get("name", "nginx"),
                    "cpu_percent": 88.0,
                    "unit": "nginx.service",
                    "scope": "system",
                    "cgroup_path": "/system.slice/nginx.service",
                }
            ],
        }


class CorrelatedScopeProcessUnitTool(Tool):
    spec = ToolSpec(
        name="process_to_unit",
        description="Fake correlation tool with a user scope match that is not a service.",
        risk=RiskLevel.READ_ONLY,
        arguments=("name", "limit"),
    )

    def invoke(self, arguments):
        return {
            "status": "ok",
            "query": {"name": arguments.get("name"), "limit": arguments.get("limit", 3)},
            "matched_process_count": 1,
            "resolved_count": 1,
            "primary_match": {
                "pid": 123,
                "command": arguments.get("name", "python3"),
                "unit": "ptyxis-session.scope",
                "scope": "user",
            },
            "units": [
                {
                    "unit": "ptyxis-session.scope",
                    "scope": "user",
                    "pid_count": 1,
                    "pids": [123],
                    "commands": [arguments.get("name", "python3")],
                }
            ],
            "correlations": [
                {
                    "pid": 123,
                    "command": arguments.get("name", "python3"),
                    "cpu_percent": 88.0,
                    "unit": "ptyxis-session.scope",
                    "scope": "user",
                    "cgroup_path": "/user.slice/ptyxis-session.scope",
                }
            ],
        }


class MultiStepChatTest(unittest.TestCase):
    def test_heuristic_provider_diagnosis_does_not_infer_service_from_hot_process(self) -> None:
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
            app.registry.register(NoCorrelationProcessUnitTool())

            payload = app.chat("o host esta lento", new_session=True)

            executed_tools = [item["tool"] for item in payload["executions"]]
            self.assertEqual(executed_tools, ["memory_usage", "top_processes", "process_to_unit"])
            self.assertIn("Resumo do diagnóstico:", payload["message"])
            self.assertIn("nginx", payload["message"])
            self.assertTrue(
                all(
                    not isinstance(item.get("action"), dict)
                    or item["action"].get("tool_name") != "restart_service"
                    for item in payload["recommendations"]["active"]
                )
            )

    def test_heuristic_provider_diagnosis_checks_service_when_request_names_it(self) -> None:
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
            app.registry.register(CorrelatedProcessUnitTool())

            payload = app.chat("o host esta lento no servico nginx", new_session=True)

            executed_tools = [item["tool"] for item in payload["executions"]]
            self.assertEqual(executed_tools, ["memory_usage", "top_processes", "service_status"])
            self.assertEqual(payload["executions"][2]["arguments"]["name"], "nginx")
            self.assertIn("Serviço", payload["message"])

    def test_heuristic_provider_uses_process_correlation_before_service_status(self) -> None:
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
            app.registry.register(CorrelatedProcessUnitTool())
            app.registry.register(HealthyServiceTool())

            payload = app.chat("o host esta lento", new_session=True)

            executed_tools = [item["tool"] for item in payload["executions"]]
            self.assertEqual(
                executed_tools,
                ["memory_usage", "top_processes", "process_to_unit", "service_status"],
            )
            self.assertEqual(payload["executions"][2]["result"]["primary_match"]["unit"], "nginx.service")
            self.assertEqual(payload["executions"][3]["arguments"]["name"], "nginx.service")
            self.assertEqual(payload["turn_decision"]["state"], "complete")
            self.assertEqual(payload["turn_decision"]["kind"], "evidence_sufficient")
            self.assertIn("nginx.service", payload["message"])

    def test_heuristic_provider_prefers_service_relevant_process_lead(self) -> None:
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
            app.registry.register(MixedHotProcessTool())
            app.registry.register(CorrelatedProcessUnitTool())
            app.registry.register(HealthyServiceTool())

            payload = app.chat("o host esta lento", new_session=True)

            executed_tools = [item["tool"] for item in payload["executions"]]
            self.assertEqual(
                executed_tools,
                ["memory_usage", "top_processes", "process_to_unit", "service_status"],
            )
            self.assertEqual(payload["executions"][2]["arguments"]["name"], "nginx")
            self.assertEqual(payload["executions"][3]["arguments"]["name"], "nginx.service")

    def test_heuristic_provider_does_not_treat_scope_correlation_as_service(self) -> None:
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
            app.registry.register(CorrelatedScopeProcessUnitTool())
            app.registry.register(HealthyServiceTool())

            payload = app.chat("o host esta lento", new_session=True)

            executed_tools = [item["tool"] for item in payload["executions"]]
            self.assertEqual(executed_tools, ["memory_usage", "top_processes", "process_to_unit"])
            self.assertEqual(payload["turn_decision"]["state"], "complete")
            self.assertNotIn("service_status", executed_tools)
            self.assertIn("ptyxis-session.scope", payload["message"])
            self.assertNotIn("Falha em `service_status`", payload["message"])


if __name__ == "__main__":
    unittest.main()
