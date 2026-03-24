from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from master_control.config import Settings
from master_control.core.runtime import MasterControlRuntime
from master_control.interfaces.mcp.server import MasterControlMCPServer


class MCPServerTest(unittest.TestCase):
    def test_list_tools_exposes_read_and_write_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            server = self._build_server(Path(tmp_dir))

            payload = server._handle_line(json.dumps({"id": 1, "method": "tools/list"}))

            self.assertTrue(payload["ok"])
            result = payload["result"]
            assert isinstance(result, dict)
            tools = result["tools"]
            assert isinstance(tools, list)
            tool_names = [item["name"] for item in tools if isinstance(item, dict)]
            self.assertIn("system_info", tool_names)
            self.assertIn("write_config_file", tool_names)
            self.assertIn("approval_list", tool_names)
            self.assertIn("approval_approve", tool_names)

    def test_tools_call_runs_read_only_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            server = self._build_server(Path(tmp_dir))

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

    def test_tools_call_returns_pending_approval_for_mutating_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            managed_root = root / "state" / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "demo.ini"
            config_path.write_text("[main]\nkey=old\n", encoding="utf-8")

            server = self._build_server(root)
            payload = server._handle_line(
                json.dumps(
                    {
                        "id": "req-2",
                        "method": "tools/call",
                        "params": {
                            "name": "write_config_file",
                            "arguments": {
                                "path": str(config_path),
                                "content": "[main]\nkey=new\n",
                            },
                        },
                    }
                )
            )

            self.assertTrue(payload["ok"])
            result = payload["result"]
            assert isinstance(result, dict)
            self.assertFalse(result["ok"])
            self.assertTrue(result["pending_confirmation"])
            approval = result["approval"]
            assert isinstance(approval, dict)
            self.assertEqual(approval["status"], "pending")
            self.assertEqual(approval["tool"], "write_config_file")

    def test_approvals_approve_executes_pending_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            managed_root = root / "state" / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "demo.ini"
            config_path.write_text("[main]\nkey=old\n", encoding="utf-8")

            server = self._build_server(root)
            pending = server._handle_line(
                json.dumps(
                    {
                        "id": "req-3",
                        "method": "tools/call",
                        "params": {
                            "name": "write_config_file",
                            "arguments": {
                                "path": str(config_path),
                                "content": "[main]\nkey=new\n",
                            },
                        },
                    }
                )
            )
            approval_id = pending["result"]["approval"]["id"]

            listed = server._handle_line(
                json.dumps(
                    {
                        "id": "req-4",
                        "method": "approvals/list",
                        "params": {"status": "pending"},
                    }
                )
            )
            self.assertTrue(listed["ok"])
            approvals = listed["result"]["approvals"]
            assert isinstance(approvals, list)
            self.assertEqual(approvals[0]["id"], approval_id)

            approved = server._handle_line(
                json.dumps(
                    {
                        "id": "req-5",
                        "method": "approvals/approve",
                        "params": {"id": approval_id},
                    }
                )
            )

            self.assertTrue(approved["ok"])
            result = approved["result"]
            assert isinstance(result, dict)
            self.assertTrue(result["execution"]["ok"])
            self.assertEqual(result["approval"]["status"], "completed")
            self.assertEqual(config_path.read_text(encoding="utf-8"), "[main]\nkey=new\n")

            fetched = server._handle_line(
                json.dumps(
                    {
                        "id": "req-6",
                        "method": "approvals/get",
                        "params": {"id": approval_id},
                    }
                )
            )
            self.assertTrue(fetched["ok"])
            self.assertEqual(fetched["result"]["status"], "completed")

    def test_approvals_reject_closes_pending_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            managed_root = root / "state" / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "demo.ini"
            config_path.write_text("[main]\nkey=old\n", encoding="utf-8")

            server = self._build_server(root)
            pending = server._handle_line(
                json.dumps(
                    {
                        "id": "req-7",
                        "method": "tools/call",
                        "params": {
                            "name": "write_config_file",
                            "arguments": {
                                "path": str(config_path),
                                "content": "[main]\nkey=new\n",
                            },
                        },
                    }
                )
            )
            approval_id = pending["result"]["approval"]["id"]

            rejected = server._handle_line(
                json.dumps(
                    {
                        "id": "req-8",
                        "method": "approvals/reject",
                        "params": {"id": approval_id},
                    }
                )
            )

            self.assertTrue(rejected["ok"])
            self.assertEqual(rejected["result"]["status"], "rejected")
            self.assertEqual(config_path.read_text(encoding="utf-8"), "[main]\nkey=old\n")

    def test_repeated_mutating_request_reuses_same_pending_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            managed_root = root / "state" / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "demo.ini"
            config_path.write_text("[main]\nkey=old\n", encoding="utf-8")

            server = self._build_server(root)
            first = server._handle_line(
                json.dumps(
                    {
                        "id": "req-9",
                        "method": "tools/call",
                        "params": {
                            "name": "write_config_file",
                            "arguments": {
                                "path": str(config_path),
                                "content": "[main]\nkey=new\n",
                            },
                        },
                    }
                )
            )
            second = server._handle_line(
                json.dumps(
                    {
                        "id": "req-10",
                        "method": "tools/call",
                        "params": {
                            "name": "write_config_file",
                            "arguments": {
                                "path": str(config_path),
                                "content": "[main]\nkey=new\n",
                            },
                        },
                    }
                )
            )

            first_approval_id = first["result"]["approval"]["id"]
            second_approval_id = second["result"]["approval"]["id"]
            self.assertEqual(first_approval_id, second_approval_id)

            listed = server._handle_line(
                json.dumps(
                    {
                        "id": "req-11",
                        "method": "approvals/list",
                        "params": {"status": "pending"},
                    }
                )
            )
            self.assertEqual(len(listed["result"]["approvals"]), 1)

    def test_jsonrpc_initialize_and_tool_flow_is_standard_mcp_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            managed_root = root / "state" / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "demo.ini"
            config_path.write_text("[main]\nkey=old\n", encoding="utf-8")

            server = self._build_server(root)

            initialized = server._handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "test-client", "version": "1.0.0"},
                        },
                    }
                )
            )
            assert initialized is not None
            self.assertEqual(initialized["jsonrpc"], "2.0")
            self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")
            self.assertIn("serverInfo", initialized["result"])

            notification = server._handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    }
                )
            )
            self.assertIsNone(notification)

            listed = server._handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                    }
                )
            )
            assert listed is not None
            tool_names = [item["name"] for item in listed["result"]["tools"]]
            self.assertIn("system_info", tool_names)
            self.assertIn("write_config_file", tool_names)
            self.assertIn("approval_list", tool_names)
            self.assertIn("approval_approve", tool_names)

            read_only = server._handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "system_info", "arguments": {}},
                    }
                )
            )
            assert read_only is not None
            self.assertEqual(read_only["jsonrpc"], "2.0")
            self.assertNotIn("isError", read_only["result"])

            pending = server._handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {
                            "name": "write_config_file",
                            "arguments": {
                                "path": str(config_path),
                                "content": "[main]\nkey=new\n",
                            },
                        },
                    }
                )
            )
            assert pending is not None
            structured_pending = pending["result"]["structuredContent"]
            approval_id = structured_pending["approval"]["id"]
            self.assertTrue(structured_pending["pending_confirmation"])

            fetched = server._handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 5,
                        "method": "tools/call",
                        "params": {
                            "name": "approval_get",
                            "arguments": {"id": approval_id},
                        },
                    }
                )
            )
            assert fetched is not None
            structured_fetched = fetched["result"]["structuredContent"]
            self.assertEqual(structured_fetched["status"], "pending")

            approved = server._handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 6,
                        "method": "tools/call",
                        "params": {
                            "name": "approval_approve",
                            "arguments": {"id": approval_id},
                        },
                    }
                )
            )
            assert approved is not None
            structured_approved = approved["result"]["structuredContent"]
            self.assertEqual(structured_approved["approval"]["status"], "completed")
            self.assertTrue(structured_approved["execution"]["ok"])
            self.assertEqual(config_path.read_text(encoding="utf-8"), "[main]\nkey=new\n")

    def _build_server(self, root: Path) -> MasterControlMCPServer:
        state_dir = root / "state"
        settings = Settings(
            app_name="master-control",
            log_level="DEBUG",
            provider="heuristic",
            state_dir=state_dir,
            db_path=state_dir / "mc.sqlite3",
        )
        runtime = MasterControlRuntime(settings)
        runtime.bootstrap()
        return MasterControlMCPServer(runtime)


if __name__ == "__main__":
    unittest.main()
