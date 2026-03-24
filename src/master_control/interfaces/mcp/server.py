from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import TextIO

from master_control.config import Settings
from master_control.core.runtime import MasterControlRuntime
from master_control.logging_utils import configure_logging

SUPPORTED_METHODS = frozenset(
    {
        "initialize",
        "ping",
        "doctor",
        "tools/list",
        "tools/call",
        "approvals/list",
        "approvals/get",
        "approvals/approve",
        "approvals/reject",
    }
)


@dataclass(frozen=True, slots=True)
class MCPError:
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
        }


class MasterControlMCPServer:
    """Experimental stdio MCP interface with approval-mediated write operations."""

    def __init__(self, runtime: MasterControlRuntime) -> None:
        self.runtime = runtime

    def run(
        self,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> None:
        stdin = input_stream or sys.stdin
        stdout = output_stream or sys.stdout
        for raw_line in stdin:
            line = raw_line.strip()
            if not line:
                continue
            response = self._handle_line(line)
            stdout.write(json.dumps(response, sort_keys=True) + "\n")
            stdout.flush()

    def _handle_line(self, line: str) -> dict[str, object]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            return self._error_response(
                request_id=None,
                error=MCPError("invalid_json", f"Invalid JSON request: {exc.msg}"),
            )

        if not isinstance(payload, dict):
            return self._error_response(
                request_id=None,
                error=MCPError("invalid_request", "Requests must be JSON objects."),
            )

        request_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params")
        if not isinstance(method, str) or not method:
            return self._error_response(
                request_id=request_id,
                error=MCPError("invalid_request", "Request is missing a string method."),
            )
        if method not in SUPPORTED_METHODS:
            return self._error_response(
                request_id=request_id,
                error=MCPError("unsupported_method", f"Unsupported method: {method}"),
            )

        try:
            result = self._dispatch(method, params)
        except ValueError as exc:
            return self._error_response(
                request_id=request_id,
                error=MCPError("invalid_params", str(exc)),
            )
        except Exception as exc:  # pragma: no cover
            return self._error_response(
                request_id=request_id,
                error=MCPError("runtime_error", str(exc)),
            )

        return {
            "id": request_id,
            "ok": True,
            "result": result,
        }

    def _dispatch(self, method: str, params: object) -> dict[str, object]:
        if method == "initialize":
            return {
                "server": {
                    "name": "master-control-mcp",
                    "mode": "experimental",
                    "transport": "stdio",
                },
                "capabilities": {
                    "tools": {
                        "mode": "approval_controlled",
                        "count": len(self._list_exposed_tools()),
                    },
                    "approvals": {
                        "mode": "explicit",
                        "statuses": ["pending", "executing", "completed", "failed", "rejected"],
                    },
                },
            }
        if method == "ping":
            return {"pong": True}
        if method == "doctor":
            return self.runtime.doctor()
        if method == "tools/list":
            return {"tools": self._list_exposed_tools()}
        if method == "tools/call":
            arguments = params if isinstance(params, dict) else {}
            tool_name = arguments.get("name")
            tool_arguments = arguments.get("arguments", {})
            if not isinstance(tool_name, str) or not tool_name:
                raise ValueError("tools/call requires params.name.")
            if not isinstance(tool_arguments, dict):
                raise ValueError("tools/call params.arguments must be an object.")
            return self.runtime.run_tool(
                tool_name,
                tool_arguments,
                audit_context={"source": "mcp_stdio"},
            )
        if method == "approvals/list":
            arguments = params if isinstance(params, dict) else {}
            status = arguments.get("status")
            limit = arguments.get("limit", 100)
            if status is not None and not isinstance(status, str):
                raise ValueError("approvals/list params.status must be a string when provided.")
            if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
                raise ValueError("approvals/list params.limit must be a positive integer.")
            return self.runtime.list_tool_approvals(status=status, limit=limit)
        if method == "approvals/get":
            arguments = params if isinstance(params, dict) else {}
            approval_id = arguments.get("id")
            if not isinstance(approval_id, int) or isinstance(approval_id, bool):
                raise ValueError("approvals/get requires params.id as an integer.")
            return self.runtime.get_tool_approval(approval_id)
        if method == "approvals/approve":
            arguments = params if isinstance(params, dict) else {}
            approval_id = arguments.get("id")
            if not isinstance(approval_id, int) or isinstance(approval_id, bool):
                raise ValueError("approvals/approve requires params.id as an integer.")
            return self.runtime.approve_tool_approval(approval_id)
        if method == "approvals/reject":
            arguments = params if isinstance(params, dict) else {}
            approval_id = arguments.get("id")
            if not isinstance(approval_id, int) or isinstance(approval_id, bool):
                raise ValueError("approvals/reject requires params.id as an integer.")
            return self.runtime.reject_tool_approval(approval_id)
        raise ValueError(f"Unsupported method: {method}")

    def _list_exposed_tools(self) -> list[dict[str, object]]:
        return [spec.as_dict() for spec in self.runtime.list_tools()]

    def _error_response(
        self,
        *,
        request_id: object,
        error: MCPError,
    ) -> dict[str, object]:
        return {
            "id": request_id,
            "ok": False,
            "error": error.as_dict(),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mc-mcp",
        description="Run the experimental Master Control MCP interface with approval flow.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    runtime = MasterControlRuntime(settings)
    runtime.bootstrap()
    MasterControlMCPServer(runtime).run()
    return 0
