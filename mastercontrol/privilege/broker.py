#!/usr/bin/env python3
"""Unix-socket privilege broker for MasterControl."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import sqlite3
import stat
import struct
import sys
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

try:
    from mastercontrol.runtime.root_exec import (
        append_audit_log,
        ensure_trusted_actions_file,
        exec_action,
        parse_kv,
        resolve_actions_file,
    )
except ImportError:  # pragma: no cover
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from mastercontrol.runtime.root_exec import (  # type: ignore
        append_audit_log,
        ensure_trusted_actions_file,
        exec_action,
        parse_kv,
        resolve_actions_file,
    )


DEFAULT_BROKER_SOCKET = Path("/run/mastercontrol/privilege-broker.sock")
DEFAULT_BROKER_AUDIT_LOG = Path("/var/log/mastercontrol/privilege-broker.log")
DEFAULT_APPROVAL_DB = Path("/var/lib/mastercontrol/privilege-broker.db")
MAX_MESSAGE_BYTES = 65536
ExecutorFn = Callable[[Path, str, dict[str, str], str | None, bool, Path], tuple[dict[str, Any], int]]


def utc_now() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat()


def parse_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def broker_socket_available(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except (FileNotFoundError, PermissionError, OSError):
        return False
    return stat.S_ISSOCK(mode)


class PrivilegeBrokerClient:
    """Simple JSON client for the local privilege broker."""

    def __init__(self, *, socket_path: Path | None = None, timeout_s: int = 35) -> None:
        self.socket_path = socket_path or DEFAULT_BROKER_SOCKET
        self.timeout_s = max(1, timeout_s)

    def issue_approval(
        self,
        *,
        action_id: str,
        args: dict[str, str],
        request_id: str = "",
        operator_id: str = "",
        session_id: str = "",
        approval_scope: str = "single_action",
        risk_level: str = "medium",
        ttl_s: int = 120,
    ) -> tuple[dict[str, Any], int]:
        payload = {
            "command": "approve",
            "action_id": action_id,
            "args": dict(args),
            "request_id": request_id or "",
            "operator_id": operator_id or "",
            "session_id": session_id or "",
            "approval_scope": approval_scope or "single_action",
            "risk_level": risk_level or "medium",
            "ttl_s": int(ttl_s),
        }
        return self._send_request(payload)

    def exec_action(
        self,
        *,
        action_id: str,
        args: dict[str, str],
        request_id: str = "",
        approval_token: str = "",
        dry_run: bool = False,
    ) -> tuple[dict[str, Any], int]:
        payload = {
            "command": "exec",
            "action_id": action_id,
            "args": dict(args),
            "request_id": request_id or "",
            "approval_token": approval_token or "",
            "dry_run": bool(dry_run),
        }
        return self._send_request(payload)

    def _send_request(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as client:
            client.settimeout(self.timeout_s)
            client.connect(str(self.socket_path))
            client.sendall(json.dumps(payload, ensure_ascii=True).encode("utf-8") + b"\n")
            data = self._recv_message(client)

        response = json.loads(data.decode("utf-8"))
        returncode = int(response.get("returncode", 0 if response.get("ok") else 1))
        return response, returncode

    @staticmethod
    def _recv_message(client: socket.socket) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = client.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_MESSAGE_BYTES:
                raise ValueError("broker response exceeded maximum size")
        if not chunks:
            raise ValueError("empty response from privilege broker")
        return b"".join(chunks)


class PrivilegeBrokerServer:
    """Unix-socket server delegating allowlisted root actions."""

    def __init__(
        self,
        *,
        socket_path: Path | None = None,
        actions_file: Path | None = None,
        audit_log: Path | None = None,
        approval_db: Path | None = None,
        executor: ExecutorFn | None = None,
        socket_mode: int = 0o660,
        inherited_socket: socket.socket | None = None,
    ) -> None:
        self.socket_path = socket_path or DEFAULT_BROKER_SOCKET
        self.actions_file = actions_file or resolve_actions_file(None)
        self.audit_log = audit_log or DEFAULT_BROKER_AUDIT_LOG
        self.approval_db = approval_db or DEFAULT_APPROVAL_DB
        self.executor = executor or exec_action
        self.socket_mode = socket_mode
        self.inherited_socket = inherited_socket
        self._init_approval_db()

    def serve_once(self, *, timeout_s: float | None = None) -> int:
        try:
            with self._listen_socket() as server:
                if timeout_s is not None:
                    server.settimeout(timeout_s)
                conn, _ = server.accept()
                with closing(conn):
                    response, returncode = self._serve_connection(conn)
                    self._send_response(conn, response)
                    return returncode
        finally:
            self._cleanup_socket()

    def serve_forever(self, *, poll_timeout_s: float = 0.5) -> int:
        last_returncode = 0
        try:
            with self._listen_socket() as server:
                server.settimeout(max(poll_timeout_s, 0.1))
                while True:
                    try:
                        conn, _ = server.accept()
                    except socket.timeout:
                        continue
                    with closing(conn):
                        response, last_returncode = self._serve_connection(conn)
                        self._send_response(conn, response)
        finally:
            self._cleanup_socket()
        return last_returncode

    def _init_approval_db(self) -> None:
        self.approval_db.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.approval_db)) as conn:
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS approval_tokens (
                        token_id TEXT PRIMARY KEY,
                        created_at_utc TEXT NOT NULL,
                        expires_at_utc TEXT NOT NULL,
                        operator_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        action_id TEXT NOT NULL,
                        args_json TEXT NOT NULL,
                        approval_scope TEXT NOT NULL,
                        risk_level TEXT NOT NULL,
                        peer_uid INTEGER NOT NULL DEFAULT -1,
                        status TEXT NOT NULL DEFAULT 'issued',
                        used_at_utc TEXT NOT NULL DEFAULT '',
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    );

                    CREATE INDEX IF NOT EXISTS idx_approval_tokens_expires
                    ON approval_tokens (expires_at_utc DESC);
                    """
                )

    def _serve_connection(self, conn: socket.socket) -> tuple[dict[str, Any], int]:
        peer = self._peer_identity(conn)
        try:
            request = self._read_request(conn)
            command = str(request.get("command", "exec")).strip().lower() or "exec"
            if command == "approve":
                payload, returncode = self._handle_approval_request(request, peer=peer)
            elif command == "exec":
                payload, returncode = self._handle_exec_request(request, peer=peer)
            else:
                raise ValueError(f"unknown broker command '{command}'")
        except Exception as exc:  # noqa: BLE001
            payload = {
                "ok": False,
                "error": str(exc),
                "request_id": "",
            }
            returncode = 2

        payload = dict(payload)
        payload.setdefault("request_id", str(payload.get("request_id", "")).strip())
        payload["returncode"] = int(payload.get("returncode", returncode))
        payload["transport"] = "broker"
        if peer:
            payload["broker_peer"] = peer
        return payload, int(payload["returncode"])

    def _handle_approval_request(
        self,
        request: dict[str, Any],
        *,
        peer: dict[str, int],
    ) -> tuple[dict[str, Any], int]:
        action_id = str(request.get("action_id", "")).strip()
        if not action_id:
            raise ValueError("missing action_id")
        args = {
            str(key): str(value)
            for key, value in dict(request.get("args", {})).items()
        }
        request_id = str(request.get("request_id", "")).strip()
        operator_id = str(request.get("operator_id", "")).strip()
        session_id = str(request.get("session_id", "")).strip()
        approval_scope = str(request.get("approval_scope", "single_action")).strip().lower() or "single_action"
        risk_level = str(request.get("risk_level", "medium")).strip().lower() or "medium"
        ttl_s = max(30, min(int(request.get("ttl_s", 120) or 120), 900))
        token_id = uuid.uuid4().hex
        now = utc_now()
        expires_at = (parse_utc(now) + dt.timedelta(seconds=ttl_s)).isoformat()
        peer_uid = int(peer.get("uid", -1))

        with closing(sqlite3.connect(self.approval_db)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO approval_tokens (
                        token_id, created_at_utc, expires_at_utc, operator_id, session_id,
                        request_id, action_id, args_json, approval_scope, risk_level,
                        peer_uid, status, used_at_utc, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'issued', '', ?)
                    """,
                    (
                        token_id,
                        now,
                        expires_at,
                        operator_id,
                        session_id,
                        request_id,
                        action_id,
                        self._args_json(args),
                        approval_scope,
                        risk_level,
                        peer_uid,
                        json.dumps({"peer": peer}, ensure_ascii=True, sort_keys=True),
                    ),
                )

        audit = {
            "ts_utc": now,
            "event": "approval_issued",
            "request_id": request_id,
            "action_id": action_id,
            "approval_scope": approval_scope,
            "risk_level": risk_level,
            "operator_id": operator_id,
            "session_id": session_id,
            "peer": peer,
            "approval_ref": token_id[:12],
            "expires_at_utc": expires_at,
        }
        append_audit_log(audit, self.audit_log)
        return {
            "ok": True,
            "request_id": request_id,
            "action_id": action_id,
            "approval_token": token_id,
            "approval_ref": token_id[:12],
            "approval_scope": approval_scope,
            "risk_level": risk_level,
            "expires_at_utc": expires_at,
        }, 0

    def _handle_exec_request(
        self,
        request: dict[str, Any],
        *,
        peer: dict[str, int],
    ) -> tuple[dict[str, Any], int]:
        action_id = str(request.get("action_id", "")).strip()
        if not action_id:
            raise ValueError("missing action_id")
        args = {
            str(key): str(value)
            for key, value in dict(request.get("args", {})).items()
        }
        request_id = str(request.get("request_id", "")).strip()
        dry_run = bool(request.get("dry_run", False))
        approval_token = str(request.get("approval_token", "")).strip()
        approval_payload: dict[str, Any] = {}
        if not dry_run:
            approval_payload = self._consume_approval_token(
                token_id=approval_token,
                action_id=action_id,
                args=args,
                request_id=request_id,
                peer_uid=int(peer.get("uid", -1)),
            )

        payload, returncode = self.executor(
            self.actions_file,
            action_id,
            args,
            request_id or None,
            dry_run,
            self.audit_log,
        )
        payload = dict(payload)
        if approval_payload:
            payload["approval_ref"] = approval_payload["approval_ref"]
            payload["approval_scope"] = approval_payload["approval_scope"]
        return payload, returncode

    def _consume_approval_token(
        self,
        *,
        token_id: str,
        action_id: str,
        args: dict[str, str],
        request_id: str,
        peer_uid: int,
    ) -> dict[str, Any]:
        if not token_id:
            raise PermissionError("missing approval token")

        now = utc_now()
        args_json = self._args_json(args)
        with closing(sqlite3.connect(self.approval_db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT token_id, created_at_utc, expires_at_utc, operator_id, session_id, request_id,
                       action_id, args_json, approval_scope, risk_level, peer_uid, status, used_at_utc
                FROM approval_tokens
                WHERE token_id = ?
                """,
                (token_id,),
            ).fetchone()
            if row is None:
                raise PermissionError("unknown approval token")

            expires_at = str(row["expires_at_utc"] or "")
            if parse_utc(expires_at) <= parse_utc(now):
                with conn:
                    conn.execute(
                        "UPDATE approval_tokens SET status = 'expired' WHERE token_id = ?",
                        (token_id,),
                    )
                raise PermissionError("approval token expired")

            status = str(row["status"] or "issued")
            if status != "issued":
                raise PermissionError(f"approval token is not usable ({status})")
            if str(row["action_id"] or "") != action_id:
                raise PermissionError("approval token does not match action_id")
            if str(row["args_json"] or "") != args_json:
                raise PermissionError("approval token does not match action arguments")
            expected_uid = int(row["peer_uid"] or -1)
            if expected_uid >= 0 and peer_uid >= 0 and expected_uid != peer_uid:
                raise PermissionError("approval token peer mismatch")

            approval_scope = str(row["approval_scope"] or "single_action")
            original_request_id = str(row["request_id"] or "")
            if approval_scope != "time_window" and original_request_id and request_id and original_request_id != request_id:
                raise PermissionError("approval token request_id mismatch")

            with conn:
                if approval_scope == "single_action":
                    conn.execute(
                        """
                        UPDATE approval_tokens
                        SET status = 'used', used_at_utc = ?
                        WHERE token_id = ?
                        """,
                        (now, token_id),
                    )

        audit = {
            "ts_utc": now,
            "event": "approval_used",
            "request_id": request_id,
            "action_id": action_id,
            "approval_scope": approval_scope,
            "risk_level": str(row["risk_level"] or "medium"),
            "operator_id": str(row["operator_id"] or ""),
            "session_id": str(row["session_id"] or ""),
            "peer_uid": peer_uid,
            "approval_ref": token_id[:12],
        }
        append_audit_log(audit, self.audit_log)
        return {
            "approval_ref": token_id[:12],
            "approval_scope": approval_scope,
            "operator_id": str(row["operator_id"] or ""),
            "session_id": str(row["session_id"] or ""),
        }

    @staticmethod
    def _args_json(args: dict[str, str]) -> str:
        return json.dumps(dict(sorted(args.items())), ensure_ascii=True, sort_keys=True)

    @staticmethod
    def _send_response(conn: socket.socket, payload: dict[str, Any]) -> None:
        conn.sendall(json.dumps(payload, ensure_ascii=True).encode("utf-8"))

    @staticmethod
    def _read_request(conn: socket.socket) -> dict[str, Any]:
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(8192)
            if not chunk:
                break
            data += chunk
            if len(data) > MAX_MESSAGE_BYTES:
                raise ValueError("broker request exceeded maximum size")
        if not data:
            raise ValueError("empty request")
        request = json.loads(data.decode("utf-8").strip())
        if not isinstance(request, dict):
            raise ValueError("broker request must be a JSON object")
        return request

    def _listen_socket(self) -> socket.socket:
        if self.inherited_socket is not None:
            return self.inherited_socket
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, self.socket_mode)
        server.listen(16)
        return server

    def _cleanup_socket(self) -> None:
        if self.inherited_socket is not None:
            return
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except FileNotFoundError:
            return

    @staticmethod
    def _peer_identity(conn: socket.socket) -> dict[str, int]:
        if not hasattr(socket, "SO_PEERCRED"):
            return {}
        raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", raw)
        return {"pid": pid, "uid": uid, "gid": gid}


def systemd_activated_socket() -> socket.socket | None:
    listen_pid = int(os.environ.get("LISTEN_PID", "0") or 0)
    listen_fds = int(os.environ.get("LISTEN_FDS", "0") or 0)
    if listen_pid != os.getpid() or listen_fds < 1:
        return None
    return socket.fromfd(3, socket.AF_UNIX, socket.SOCK_STREAM)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mc-privilege-broker",
        description="MasterControl privilege broker over a local Unix socket.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run the local privilege broker server.")
    serve.add_argument("--socket", default=str(DEFAULT_BROKER_SOCKET), help="Unix socket path.")
    serve.add_argument("--actions-file", default=None, help="Path to actions.json.")
    serve.add_argument("--audit-log", default=str(DEFAULT_BROKER_AUDIT_LOG), help="Audit log path.")
    serve.add_argument("--approval-db", default=str(DEFAULT_APPROVAL_DB), help="Approval token SQLite DB.")
    serve.add_argument("--once", action="store_true", help="Serve a single request and exit.")
    serve.add_argument("--socket-mode", default="660", help="Octal mode for the Unix socket.")
    serve.add_argument("--accept-timeout", type=float, default=30.0, help="Accept timeout for --once.")

    approve = sub.add_parser("approve", help="Issue a short-lived approval token.")
    approve.add_argument("--socket", default=str(DEFAULT_BROKER_SOCKET), help="Unix socket path.")
    approve.add_argument("--action", required=True, help="Action ID")
    approve.add_argument("--arg", action="append", default=[], help="Action arg KEY=VALUE")
    approve.add_argument("--request-id", default="", help="Correlation ID for audit")
    approve.add_argument("--operator-id", default="", help="Operator identifier")
    approve.add_argument("--session-id", default="", help="Session identifier")
    approve.add_argument("--approval-scope", default="single_action", help="Approval scope")
    approve.add_argument("--risk-level", default="medium", help="Risk level")
    approve.add_argument("--ttl-sec", type=int, default=120, help="Approval TTL in seconds")

    client = sub.add_parser("exec", help="Send one action request to the local broker.")
    client.add_argument("--socket", default=str(DEFAULT_BROKER_SOCKET), help="Unix socket path.")
    client.add_argument("--action", required=True, help="Action ID")
    client.add_argument("--arg", action="append", default=[], help="Action arg KEY=VALUE")
    client.add_argument("--request-id", default="", help="Correlation ID for audit")
    client.add_argument("--approval-token", default="", help="Short-lived approval token for real execution")
    client.add_argument("--dry-run", action="store_true", help="Validate only")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "serve":
        actions_file = resolve_actions_file(args.actions_file)
        if os.geteuid() == 0:
            actions_file = ensure_trusted_actions_file(actions_file)
        inherited_socket = systemd_activated_socket()
        server = PrivilegeBrokerServer(
            socket_path=Path(args.socket),
            actions_file=actions_file,
            audit_log=Path(args.audit_log),
            approval_db=Path(args.approval_db),
            socket_mode=int(str(args.socket_mode), 8),
            inherited_socket=inherited_socket,
        )
        if args.once:
            return server.serve_once(timeout_s=max(float(args.accept_timeout), 1.0))
        return server.serve_forever()

    client = PrivilegeBrokerClient(socket_path=Path(args.socket))
    if args.cmd == "approve":
        payload, returncode = client.issue_approval(
            action_id=args.action,
            args=parse_kv(args.arg),
            request_id=str(args.request_id or ""),
            operator_id=str(args.operator_id or ""),
            session_id=str(args.session_id or ""),
            approval_scope=str(args.approval_scope or "single_action"),
            risk_level=str(args.risk_level or "medium"),
            ttl_s=int(args.ttl_sec or 120),
        )
    else:
        payload, returncode = client.exec_action(
            action_id=args.action,
            args=parse_kv(args.arg),
            request_id=str(args.request_id or ""),
            approval_token=str(args.approval_token or ""),
            dry_run=bool(args.dry_run),
        )
    print(json.dumps(payload, ensure_ascii=True))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
