#!/usr/bin/env python3
"""Privileged execution planning for bootstrap pkexec and future broker mode."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from mastercontrol.contracts import PExecRequest, PExecResult
from mastercontrol.privilege.broker import DEFAULT_BROKER_SOCKET


class BootstrapPkexecTransport:
    """Plans commands for the current pkexec-based privileged path."""

    def __init__(
        self,
        *,
        exec_path: Path | None = None,
        actions_file: Path | None = None,
    ) -> None:
        self.exec_path = exec_path or Path("/usr/lib/mastercontrol/root-exec")
        self.actions_file = actions_file or Path("/etc/mastercontrol/actions.json")

    def build_command(self, request: PExecRequest) -> tuple[str, ...]:
        command: list[str] = []
        if not request.dry_run:
            command.extend(["pkexec", str(self.exec_path)])
        else:
            command.append(str(self.exec_path))

        command.extend(["--actions-file", str(self.actions_file), "exec", "--action", request.action_id])
        for key, value in sorted(request.args.items()):
            command.extend(["--arg", f"{key}={value}"])
        if request.request_id:
            command.extend(["--request-id", request.request_id])
        if request.dry_run:
            command.append("--dry-run")
        return tuple(command)


class PrivilegeBrokerTransport:
    """Plans commands for the Unix-socket broker client."""

    def __init__(
        self,
        *,
        socket_path: Path | None = None,
        python_bin: str | None = None,
    ) -> None:
        self.socket_path = socket_path or DEFAULT_BROKER_SOCKET
        self.python_bin = python_bin or sys.executable

    def build_command(self, request: PExecRequest) -> tuple[str, ...]:
        command = [
            self.python_bin,
            "-m",
            "mastercontrol.privilege.broker",
            "exec",
            "--socket",
            str(self.socket_path),
            "--action",
            request.action_id,
        ]
        for key, value in sorted(request.args.items()):
            command.extend(["--arg", f"{key}={value}"])
        if request.request_id:
            command.extend(["--request-id", request.request_id])
        if request.dry_run:
            command.append("--dry-run")
        return tuple(command)


class PExecPlanner:
    """Builds the transport command for privileged execution."""

    def __init__(
        self,
        transport: BootstrapPkexecTransport | None = None,
        broker_transport: PrivilegeBrokerTransport | None = None,
    ) -> None:
        self.transport = transport or BootstrapPkexecTransport()
        self.broker_transport = broker_transport or PrivilegeBrokerTransport()

    def plan(self, request: PExecRequest) -> PExecResult:
        if request.privilege_mode == "none":
            return PExecResult(
                ok=False,
                command=(),
                request_id=request.request_id,
                returncode=2,
                stderr="privilege mode 'none' cannot be routed through pexec",
                transport="none",
            )
        if request.privilege_mode == "broker":
            command = self.broker_transport.build_command(request)
            return PExecResult(
                ok=True,
                command=command,
                request_id=request.request_id,
                transport="broker",
            )

        command = self.transport.build_command(request)
        return PExecResult(
            ok=True,
            command=command,
            request_id=request.request_id,
            transport="pkexec_bootstrap",
        )

    @staticmethod
    def shell_preview(result: PExecResult) -> str:
        return shlex.join(result.command)
