from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import TextIO

from master_control import __version__
from master_control.config import Settings
from master_control.core.runtime import MasterControlRuntime
from master_control.logging_utils import configure_logging
from master_control.tools.base import RiskLevel, ToolSpec

LEGACY_SUPPORTED_METHODS = frozenset(
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

JSONRPC_SUPPORTED_REQUEST_METHODS = frozenset(
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

JSONRPC_VERSION = "2.0"
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

APPROVAL_LIST_TOOL = "approval_list"
APPROVAL_GET_TOOL = "approval_get"
APPROVAL_APPROVE_TOOL = "approval_approve"
APPROVAL_REJECT_TOOL = "approval_reject"


@dataclass(frozen=True, slots=True)
class LegacyMCPError:
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class JSONRPCError:
    code: int
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
        }


class MasterControlMCPServer:
    """MCP stdio interface with approval-mediated write operations."""

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
            if response is None:
                continue
            stdout.write(json.dumps(response, sort_keys=True) + "\n")
            stdout.flush()

    def _handle_line(self, line: str) -> dict[str, object] | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            return self._legacy_error_response(
                request_id=None,
                error=LegacyMCPError("invalid_json", f"Invalid JSON request: {exc.msg}"),
            )

        if not isinstance(payload, dict):
            return self._legacy_error_response(
                request_id=None,
                error=LegacyMCPError("invalid_request", "Requests must be JSON objects."),
            )

        jsonrpc_version = payload.get("jsonrpc")
        if jsonrpc_version is None:
            return self._handle_legacy_request(payload)
        if jsonrpc_version != JSONRPC_VERSION:
            return self._jsonrpc_error_response(
                request_id=payload.get("id"),
                error=JSONRPCError(
                    JSONRPC_INVALID_REQUEST,
                    f"Unsupported JSON-RPC version: {jsonrpc_version}",
                ),
            )
        return self._handle_jsonrpc_request(payload)

    def _handle_legacy_request(self, payload: dict[str, object]) -> dict[str, object]:
        request_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params")
        if not isinstance(method, str) or not method:
            return self._legacy_error_response(
                request_id=request_id,
                error=LegacyMCPError("invalid_request", "Request is missing a string method."),
            )
        if method not in LEGACY_SUPPORTED_METHODS:
            return self._legacy_error_response(
                request_id=request_id,
                error=LegacyMCPError("unsupported_method", f"Unsupported method: {method}"),
            )

        try:
            result = self._dispatch_legacy(method, params)
        except ValueError as exc:
            return self._legacy_error_response(
                request_id=request_id,
                error=LegacyMCPError("invalid_params", str(exc)),
            )
        except Exception as exc:  # pragma: no cover
            return self._legacy_error_response(
                request_id=request_id,
                error=LegacyMCPError("runtime_error", str(exc)),
            )

        return {
            "id": request_id,
            "ok": True,
            "result": result,
        }

    def _handle_jsonrpc_request(self, payload: dict[str, object]) -> dict[str, object] | None:
        request_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params")
        if not isinstance(method, str) or not method:
            return self._jsonrpc_error_response(
                request_id=request_id,
                error=JSONRPCError(JSONRPC_INVALID_REQUEST, "Request is missing a string method."),
            )
        if request_id is None:
            if method == "notifications/initialized":
                return None
            return None
        if method not in JSONRPC_SUPPORTED_REQUEST_METHODS:
            return self._jsonrpc_error_response(
                request_id=request_id,
                error=JSONRPCError(
                    JSONRPC_METHOD_NOT_FOUND,
                    f"Unsupported method: {method}",
                ),
            )

        try:
            result = self._dispatch_jsonrpc(method, params)
        except ValueError as exc:
            return self._jsonrpc_error_response(
                request_id=request_id,
                error=JSONRPCError(JSONRPC_INVALID_PARAMS, str(exc)),
            )
        except Exception as exc:  # pragma: no cover
            return self._jsonrpc_error_response(
                request_id=request_id,
                error=JSONRPCError(JSONRPC_INTERNAL_ERROR, str(exc)),
            )

        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": result,
        }

    def _dispatch_legacy(self, method: str, params: object) -> dict[str, object]:
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
                        "count": len(self._list_exposed_tools(standard_mcp=False)),
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
            return {"tools": self._list_exposed_tools(standard_mcp=False)}
        if method == "tools/call":
            arguments = params if isinstance(params, dict) else {}
            tool_name = arguments.get("name")
            tool_arguments = arguments.get("arguments", {})
            if not isinstance(tool_name, str) or not tool_name:
                raise ValueError("tools/call requires params.name.")
            if not isinstance(tool_arguments, dict):
                raise ValueError("tools/call params.arguments must be an object.")
            return self._call_legacy_tool(tool_name, tool_arguments)
        if method == "approvals/list":
            status, limit = self._coerce_approval_list_params(params)
            return self.runtime.list_tool_approvals(status=status, limit=limit)
        if method == "approvals/get":
            approval_id = self._coerce_approval_id(params, method="approvals/get")
            return self.runtime.get_tool_approval(approval_id)
        if method == "approvals/approve":
            approval_id = self._coerce_approval_id(params, method="approvals/approve")
            return self.runtime.approve_tool_approval(approval_id)
        if method == "approvals/reject":
            approval_id = self._coerce_approval_id(params, method="approvals/reject")
            return self.runtime.reject_tool_approval(approval_id)
        raise ValueError(f"Unsupported method: {method}")

    def _dispatch_jsonrpc(self, method: str, params: object) -> dict[str, object]:
        if method == "initialize":
            arguments = params if isinstance(params, dict) else {}
            protocol_version = arguments.get("protocolVersion")
            if not isinstance(protocol_version, str) or not protocol_version:
                raise ValueError("initialize requires params.protocolVersion.")
            return {
                "protocolVersion": protocol_version,
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "master-control",
                    "version": __version__,
                },
                "instructions": (
                    "Master Control exposes bounded Linux host tools and approval tools over MCP. "
                    "Mutating host tools return pending approval payloads; use approval_list, "
                    "approval_get, approval_approve, and approval_reject to inspect and resolve them."
                ),
            }
        if method == "ping":
            return {}
        if method == "doctor":
            return self.runtime.doctor()
        if method == "tools/list":
            return {"tools": self._list_exposed_tools(standard_mcp=True)}
        if method == "tools/call":
            arguments = params if isinstance(params, dict) else {}
            tool_name = arguments.get("name")
            tool_arguments = arguments.get("arguments", {})
            if not isinstance(tool_name, str) or not tool_name:
                raise ValueError("tools/call requires params.name.")
            if not isinstance(tool_arguments, dict):
                raise ValueError("tools/call params.arguments must be an object.")
            return self._call_standard_tool(tool_name, tool_arguments)
        if method == "approvals/list":
            status, limit = self._coerce_approval_list_params(params)
            return self.runtime.list_tool_approvals(status=status, limit=limit)
        if method == "approvals/get":
            approval_id = self._coerce_approval_id(params, method="approvals/get")
            return self.runtime.get_tool_approval(approval_id)
        if method == "approvals/approve":
            approval_id = self._coerce_approval_id(params, method="approvals/approve")
            return self.runtime.approve_tool_approval(approval_id)
        if method == "approvals/reject":
            approval_id = self._coerce_approval_id(params, method="approvals/reject")
            return self.runtime.reject_tool_approval(approval_id)
        raise ValueError(f"Unsupported method: {method}")

    def _call_legacy_tool(
        self,
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        if tool_name == APPROVAL_LIST_TOOL:
            status, limit = self._coerce_approval_list_tool_arguments(arguments)
            return self.runtime.list_tool_approvals(status=status, limit=limit)
        if tool_name == APPROVAL_GET_TOOL:
            approval_id = self._coerce_approval_tool_id(arguments, tool_name=tool_name)
            return self.runtime.get_tool_approval(approval_id)
        if tool_name == APPROVAL_APPROVE_TOOL:
            approval_id = self._coerce_approval_tool_id(arguments, tool_name=tool_name)
            return self.runtime.approve_tool_approval(approval_id)
        if tool_name == APPROVAL_REJECT_TOOL:
            approval_id = self._coerce_approval_tool_id(arguments, tool_name=tool_name)
            return self.runtime.reject_tool_approval(approval_id)
        return self.runtime.run_tool(
            tool_name,
            arguments,
            audit_context={"source": "mcp_stdio"},
        )

    def _call_standard_tool(
        self,
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        if tool_name == APPROVAL_LIST_TOOL:
            status, limit = self._coerce_approval_list_tool_arguments(arguments)
            payload = self.runtime.list_tool_approvals(status=status, limit=limit)
            return self._build_standard_tool_result(payload, is_error=False)
        if tool_name == APPROVAL_GET_TOOL:
            approval_id = self._coerce_approval_tool_id(arguments, tool_name=tool_name)
            payload = self.runtime.get_tool_approval(approval_id)
            return self._build_standard_tool_result(payload, is_error=False)
        if tool_name == APPROVAL_APPROVE_TOOL:
            approval_id = self._coerce_approval_tool_id(arguments, tool_name=tool_name)
            payload = self.runtime.approve_tool_approval(approval_id)
            return self._build_standard_tool_result(payload, is_error=False)
        if tool_name == APPROVAL_REJECT_TOOL:
            approval_id = self._coerce_approval_tool_id(arguments, tool_name=tool_name)
            payload = self.runtime.reject_tool_approval(approval_id)
            return self._build_standard_tool_result(payload, is_error=False)

        payload = self.runtime.run_tool(
            tool_name,
            arguments,
            audit_context={"source": "mcp_stdio"},
        )
        is_error = bool(payload.get("ok")) is False and not bool(payload.get("pending_confirmation"))
        return self._build_standard_tool_result(payload, is_error=is_error)

    def _list_exposed_tools(self, *, standard_mcp: bool) -> list[dict[str, object]]:
        host_specs = self.runtime.list_tools()
        if standard_mcp:
            return [
                *[self._host_tool_to_standard_mcp(spec) for spec in host_specs],
                *self._approval_tools_standard_mcp(),
            ]
        return [
            *[spec.as_dict() for spec in host_specs],
            *self._approval_tools_legacy(),
        ]

    def _host_tool_to_standard_mcp(self, spec: ToolSpec) -> dict[str, object]:
        properties: dict[str, object] = {argument: {} for argument in spec.arguments}
        annotations = {
            "readOnlyHint": spec.risk == RiskLevel.READ_ONLY,
            "idempotentHint": spec.risk == RiskLevel.READ_ONLY,
            "openWorldHint": False,
        }
        return {
            "name": spec.name,
            "description": spec.description,
            "inputSchema": {
                "type": "object",
                "properties": properties,
            },
            "annotations": annotations,
            "_meta": {
                "master-control/risk": spec.risk.value,
            },
        }

    def _approval_tools_legacy(self) -> list[dict[str, object]]:
        return [
            {
                "name": APPROVAL_LIST_TOOL,
                "description": "List active or historical approvals.",
                "risk": RiskLevel.READ_ONLY.value,
                "arguments": ["status", "limit"],
            },
            {
                "name": APPROVAL_GET_TOOL,
                "description": "Fetch a specific approval by id.",
                "risk": RiskLevel.READ_ONLY.value,
                "arguments": ["id"],
            },
            {
                "name": APPROVAL_APPROVE_TOOL,
                "description": "Approve and execute a pending approval by id.",
                "risk": RiskLevel.MUTATING_SAFE.value,
                "arguments": ["id"],
            },
            {
                "name": APPROVAL_REJECT_TOOL,
                "description": "Reject a pending approval by id.",
                "risk": RiskLevel.MUTATING_SAFE.value,
                "arguments": ["id"],
            },
        ]

    def _approval_tools_standard_mcp(self) -> list[dict[str, object]]:
        return [
            self._approval_tool_definition(
                name=APPROVAL_LIST_TOOL,
                description="List active or historical approvals.",
                properties={
                    "status": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                read_only=True,
            ),
            self._approval_tool_definition(
                name=APPROVAL_GET_TOOL,
                description="Fetch a specific approval by id.",
                properties={
                    "id": {"type": "integer"},
                },
                required=("id",),
                read_only=True,
            ),
            self._approval_tool_definition(
                name=APPROVAL_APPROVE_TOOL,
                description="Approve and execute a pending approval by id.",
                properties={
                    "id": {"type": "integer"},
                },
                required=("id",),
                read_only=False,
            ),
            self._approval_tool_definition(
                name=APPROVAL_REJECT_TOOL,
                description="Reject a pending approval by id.",
                properties={
                    "id": {"type": "integer"},
                },
                required=("id",),
                read_only=False,
            ),
        ]

    def _approval_tool_definition(
        self,
        *,
        name: str,
        description: str,
        properties: dict[str, object],
        required: tuple[str, ...] = (),
        read_only: bool,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": name,
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": properties,
            },
            "annotations": {
                "readOnlyHint": read_only,
                "idempotentHint": read_only,
                "openWorldHint": False,
            },
            "_meta": {
                "master-control/risk": (
                    RiskLevel.READ_ONLY.value if read_only else RiskLevel.MUTATING_SAFE.value
                ),
            },
        }
        if required:
            payload["inputSchema"]["required"] = list(required)  # type: ignore[index]
        return payload

    def _build_standard_tool_result(
        self,
        payload: dict[str, object],
        *,
        is_error: bool,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "content": [
                {
                    "type": "text",
                    "text": self._render_standard_tool_text(payload),
                }
            ],
            "structuredContent": payload,
        }
        if is_error:
            result["isError"] = True
        return result

    def _render_standard_tool_text(self, payload: dict[str, object]) -> str:
        approval = payload.get("approval")
        if isinstance(approval, dict):
            approval_id = approval.get("id")
            approval_status = approval.get("status")
            if payload.get("pending_confirmation"):
                return f"Approval required. approval_id={approval_id}, status={approval_status}."
            if payload.get("approval_in_progress"):
                return f"Approval {approval_id} is already executing."
        if payload.get("ok") is False:
            error = payload.get("error")
            if isinstance(error, str) and error:
                return error
            return "Tool execution failed."
        result = payload.get("result")
        if isinstance(result, dict):
            try:
                return json.dumps(result, sort_keys=True)
            except TypeError:
                return str(result)
        try:
            return json.dumps(payload, sort_keys=True)
        except TypeError:
            return str(payload)

    def _coerce_approval_list_params(self, params: object) -> tuple[str | None, int]:
        arguments = params if isinstance(params, dict) else {}
        status = arguments.get("status")
        limit = arguments.get("limit", 100)
        if status is not None and not isinstance(status, str):
            raise ValueError("approvals/list params.status must be a string when provided.")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("approvals/list params.limit must be a positive integer.")
        return status, limit

    def _coerce_approval_id(self, params: object, *, method: str) -> int:
        arguments = params if isinstance(params, dict) else {}
        approval_id = arguments.get("id")
        if not isinstance(approval_id, int) or isinstance(approval_id, bool):
            raise ValueError(f"{method} requires params.id as an integer.")
        return approval_id

    def _coerce_approval_list_tool_arguments(
        self,
        arguments: dict[str, object],
    ) -> tuple[str | None, int]:
        status = arguments.get("status")
        limit = arguments.get("limit", 100)
        if status is not None and not isinstance(status, str):
            raise ValueError("approval_list requires 'status' to be a string when provided.")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("approval_list requires 'limit' to be a positive integer.")
        return status, limit

    def _coerce_approval_tool_id(
        self,
        arguments: dict[str, object],
        *,
        tool_name: str,
    ) -> int:
        approval_id = arguments.get("id")
        if not isinstance(approval_id, int) or isinstance(approval_id, bool):
            raise ValueError(f"{tool_name} requires 'id' as an integer.")
        return approval_id

    def _legacy_error_response(
        self,
        *,
        request_id: object,
        error: LegacyMCPError,
    ) -> dict[str, object]:
        return {
            "id": request_id,
            "ok": False,
            "error": error.as_dict(),
        }

    def _jsonrpc_error_response(
        self,
        *,
        request_id: object,
        error: JSONRPCError,
    ) -> dict[str, object]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": error.as_dict(),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mc-mcp",
        description="Run the Master Control MCP interface with approval flow.",
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
