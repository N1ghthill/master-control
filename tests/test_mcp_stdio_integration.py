from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


class MCPStdioIntegrationTest(unittest.TestCase):
    def test_stdio_server_round_trips_initialize_and_write_approval_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir) / "state"
            managed_root = state_dir / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "demo.ini"
            config_path.write_text("[main]\nkey=old\n", encoding="utf-8")

            with self._start_server(state_dir) as process:
                initialize = self._request(process, {"id": 1, "method": "initialize"})
                self.assertTrue(initialize["ok"])
                self.assertEqual(initialize["result"]["server"]["transport"], "stdio")

                listed = self._request(process, {"id": 2, "method": "tools/list"})
                self.assertTrue(listed["ok"])
                tools = listed["result"]["tools"]
                tool_names = [item["name"] for item in tools if isinstance(item, dict)]
                self.assertIn("system_info", tool_names)
                self.assertIn("write_config_file", tool_names)

                read_only = self._request(
                    process,
                    {
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "system_info", "arguments": {}},
                    },
                )
                self.assertTrue(read_only["ok"])
                self.assertTrue(read_only["result"]["ok"])

                pending = self._request(
                    process,
                    {
                        "id": 4,
                        "method": "tools/call",
                        "params": {
                            "name": "write_config_file",
                            "arguments": {
                                "path": str(config_path),
                                "content": "[main]\nkey=new\n",
                            },
                        },
                    },
                )
                self.assertTrue(pending["ok"])
                self.assertFalse(pending["result"]["ok"])
                self.assertTrue(pending["result"]["pending_confirmation"])
                approval_id = pending["result"]["approval"]["id"]

                fetched = self._request(
                    process,
                    {
                        "id": 5,
                        "method": "approvals/get",
                        "params": {"id": approval_id},
                    },
                )
                self.assertTrue(fetched["ok"])
                self.assertEqual(fetched["result"]["status"], "pending")

                approved = self._request(
                    process,
                    {
                        "id": 6,
                        "method": "approvals/approve",
                        "params": {"id": approval_id},
                    },
                )
                self.assertTrue(approved["ok"])
                self.assertTrue(approved["result"]["execution"]["ok"])
                self.assertEqual(approved["result"]["approval"]["status"], "completed")
                self.assertEqual(config_path.read_text(encoding="utf-8"), "[main]\nkey=new\n")

    def _request(
        self,
        process: subprocess.Popen[str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            stderr = ""
            if process.stderr is not None:
                stderr = process.stderr.read()
            raise AssertionError(f"MCP server closed the pipe unexpectedly. stderr={stderr!r}")
        return json.loads(line)

    def _start_server(self, state_dir: Path):
        env = os.environ.copy()
        env["MC_STATE_DIR"] = str(state_dir)
        env["MC_DB_PATH"] = str(state_dir / "mc.sqlite3")
        env["MC_PROVIDER"] = "heuristic"
        command = [sys.executable, "-m", "master_control", "mcp-serve"]
        return _ManagedProcess(
            subprocess.Popen(
                command,
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )


class _ManagedProcess:
    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.process = process

    def __enter__(self) -> subprocess.Popen[str]:
        return self.process

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        if self.process.stdout is not None:
            self.process.stdout.close()
        if self.process.stderr is not None:
            self.process.stderr.close()


if __name__ == "__main__":
    unittest.main()
