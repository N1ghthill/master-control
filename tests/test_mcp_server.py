from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from master_control.config import Settings
from master_control.core.runtime import MasterControlRuntime
from master_control.interfaces.mcp.server import MasterControlMCPServer


class MCPServerTest(unittest.TestCase):
    def test_list_tools_only_exposes_read_only_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="DEBUG",
                provider="heuristic",
                state_dir=Path(tmp_dir) / "state",
                db_path=Path(tmp_dir) / "state" / "mc.sqlite3",
            )
            runtime = MasterControlRuntime(settings)
            runtime.bootstrap()
            server = MasterControlMCPServer(runtime)

            payload = server._handle_line(json.dumps({"id": 1, "method": "tools/list"}))

            self.assertTrue(payload["ok"])
            result = payload["result"]
            assert isinstance(result, dict)
            tools = result["tools"]
            assert isinstance(tools, list)
            tool_names = [item["name"] for item in tools if isinstance(item, dict)]
            self.assertIn("system_info", tool_names)
            self.assertNotIn("write_config_file", tool_names)
            self.assertTrue(
                all(
                    isinstance(item, dict) and item.get("risk") == "read_only"
                    for item in tools
                )
            )

    def test_tools_call_runs_read_only_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="DEBUG",
                provider="heuristic",
                state_dir=Path(tmp_dir) / "state",
                db_path=Path(tmp_dir) / "state" / "mc.sqlite3",
            )
            runtime = MasterControlRuntime(settings)
            runtime.bootstrap()
            server = MasterControlMCPServer(runtime)

            payload = server._handle_line(
                json.dumps(
                    {
                        "id": "req-1",
                        "method": "tools/call",
                        "params": {"name": "system_info", "arguments": {}},
                    }
                )
            )

            self.assertTrue(payload["ok"])
            result = payload["result"]
            assert isinstance(result, dict)
            self.assertEqual(result["tool"], "system_info")
            self.assertTrue(result["ok"])

    def test_tools_call_blocks_mutating_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="DEBUG",
                provider="heuristic",
                state_dir=Path(tmp_dir) / "state",
                db_path=Path(tmp_dir) / "state" / "mc.sqlite3",
            )
            runtime = MasterControlRuntime(settings)
            runtime.bootstrap()
            server = MasterControlMCPServer(runtime)

            payload = server._handle_line(
                json.dumps(
                    {
                        "id": "req-2",
                        "method": "tools/call",
                        "params": {
                            "name": "write_config_file",
                            "arguments": {"path": "/tmp/demo.ini", "content": "x"},
                        },
                    }
                )
            )

            self.assertFalse(payload["ok"])
            error = payload["error"]
            assert isinstance(error, dict)
            self.assertEqual(error["code"], "invalid_params")


if __name__ == "__main__":
    unittest.main()
