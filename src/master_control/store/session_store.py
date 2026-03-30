from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from master_control.core.observations import (
    compute_expires_at,
    deserialize_observation_value,
    serialize_observation_value,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS session_provider_state (
    session_id INTEGER PRIMARY KEY,
    provider_backend TEXT NOT NULL,
    previous_response_id TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS session_summaries (
    session_id INTEGER PRIMARY KEY,
    summary_text TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS session_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    dedupe_key TEXT NOT NULL,
    source_key TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL,
    action_kind TEXT,
    action_title TEXT,
    action_tool_name TEXT,
    action_arguments_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(id),
    UNIQUE(session_id, dedupe_key)
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    source TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    risk TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    audit_context_json TEXT NOT NULL,
    action_digest TEXT,
    summary TEXT NOT NULL,
    cli_command TEXT NOT NULL,
    chat_command TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    execution_payload_json TEXT,
    error_text TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);
"""


@dataclass(frozen=True, slots=True)
class ToolApprovalExecutionMatch:
    outcome: str
    approval: dict[str, object] | None


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA)
            self._migrate_schema(connection)
            self._ensure_indexes(connection)
            connection.commit()

    def diagnostics(self) -> dict[str, object]:
        with closing(self._connect()) as connection:
            foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
            busy_timeout_ms = int(connection.execute("PRAGMA busy_timeout").fetchone()[0])
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
            synchronous_raw = int(connection.execute("PRAGMA synchronous").fetchone()[0])
            integrity_check = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])

        synchronous_mode = {
            0: "OFF",
            1: "NORMAL",
            2: "FULL",
            3: "EXTRA",
        }.get(synchronous_raw, str(synchronous_raw))
        size_bytes = page_count * page_size
        return {
            "ok": foreign_keys == 1 and integrity_check == "ok",
            "path": str(self.path),
            "exists": self.path.exists(),
            "size_bytes": size_bytes,
            "foreign_keys": foreign_keys == 1,
            "busy_timeout_ms": busy_timeout_ms,
            "journal_mode": journal_mode,
            "synchronous": synchronous_mode,
            "integrity_check": integrity_check,
        }

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        self._ensure_columns(
            connection,
            "session_recommendations",
            {
                "action_kind": "TEXT",
                "action_title": "TEXT",
                "action_tool_name": "TEXT",
                "action_arguments_json": "TEXT",
            },
        )
        self._ensure_columns(
            connection,
            "observations",
            {
                "session_id": "INTEGER",
            },
        )
        self._ensure_columns(
            connection,
            "tool_approvals",
            {
                "action_digest": "TEXT",
            },
        )
        self._backfill_tool_approval_digests(connection)

    def _ensure_indexes(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_observations_session_key_id
            ON observations(session_id, key, id DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_approvals_status_id
            ON tool_approvals(status, id DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_approvals_match
            ON tool_approvals(tool_name, status, id DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_approvals_action_digest
            ON tool_approvals(action_digest, status, id DESC)
            """
        )

    def _ensure_columns(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        columns: dict[str, str],
    ) -> None:
        cursor = connection.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {str(row[1]) for row in cursor.fetchall()}
        for column_name, column_type in columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def _backfill_tool_approval_digests(self, connection: sqlite3.Connection) -> None:
        cursor = connection.execute(
            """
            SELECT id, tool_name, arguments_json, audit_context_json
            FROM tool_approvals
            WHERE action_digest IS NULL OR action_digest = ''
            """
        )
        rows = cursor.fetchall()
        for approval_id, tool_name, arguments_json, audit_context_json in rows:
            if not isinstance(tool_name, str):
                continue
            if not isinstance(arguments_json, str):
                arguments_json = "{}"
            if not isinstance(audit_context_json, str):
                audit_context_json = "{}"
            connection.execute(
                """
                UPDATE tool_approvals
                SET action_digest = ?
                WHERE id = ?
                """,
                (
                    _build_tool_approval_digest(
                        tool_name=tool_name,
                        arguments_json=arguments_json,
                        audit_context_json=audit_context_json,
                    ),
                    approval_id,
                ),
            )

    def record_audit_event(self, event_type: str, payload: dict[str, object]) -> None:
        serialized_payload = json.dumps(payload, sort_keys=True)
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO audit_events (event_type, payload) VALUES (?, ?)",
                (event_type, serialized_payload),
            )
            connection.commit()

    def list_audit_events(self, limit: int = 20) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                SELECT event_type, payload, created_at
                FROM audit_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        events: list[dict[str, object]] = []
        for event_type, payload, created_at in rows:
            events.append(
                {
                    "event_type": event_type,
                    "payload": json.loads(payload),
                    "created_at": created_at,
                }
            )
        return events

    def count_audit_events(self) -> int:
        with closing(self._connect()) as connection:
            cursor = connection.execute("SELECT COUNT(*) FROM audit_events")
            row = cursor.fetchone()
        return int(row[0]) if row is not None else 0

    def create_tool_approval(
        self,
        *,
        tool_name: str,
        risk: str,
        arguments: dict[str, object],
        audit_context: dict[str, object],
        summary: str,
        cli_command: str,
        chat_command: str,
    ) -> dict[str, object]:
        arguments_json, audit_context_json, action_digest = _serialize_tool_approval_identity(
            tool_name=tool_name,
            arguments=arguments,
            audit_context=audit_context,
        )
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = self._select_active_tool_approval_row_by_digest(
                connection, action_digest
            )
            if existing_row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO tool_approvals (
                        tool_name,
                        risk,
                        arguments_json,
                        audit_context_json,
                        action_digest,
                        summary,
                        cli_command,
                        chat_command
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tool_name,
                        risk,
                        arguments_json,
                        audit_context_json,
                        action_digest,
                        summary,
                        cli_command,
                        chat_command,
                    ),
                )
                approval_id = cursor.lastrowid
                if approval_id is None:
                    connection.rollback()
                    raise RuntimeError("SQLite did not return a tool approval id.")
                created_row = self._select_tool_approval_row(connection, int(approval_id))
                connection.commit()
                if created_row is None:
                    raise RuntimeError(f"Tool approval {approval_id} disappeared after insert.")
                return self._row_to_tool_approval(created_row)
            connection.commit()
        return self._row_to_tool_approval(existing_row)

    def list_tool_approvals(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            if status is None:
                cursor = connection.execute(
                    """
                    SELECT
                        id,
                        tool_name,
                        risk,
                        arguments_json,
                        audit_context_json,
                        summary,
                        cli_command,
                        chat_command,
                        status,
                        execution_payload_json,
                        error_text,
                        created_at,
                        updated_at,
                        resolved_at
                    FROM tool_approvals
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            else:
                cursor = connection.execute(
                    """
                    SELECT
                        id,
                        tool_name,
                        risk,
                        arguments_json,
                        audit_context_json,
                        summary,
                        cli_command,
                        chat_command,
                        status,
                        execution_payload_json,
                        error_text,
                        created_at,
                        updated_at,
                        resolved_at
                    FROM tool_approvals
                    WHERE status = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (status, limit),
                )
            rows = cursor.fetchall()
        return [self._row_to_tool_approval(row) for row in rows]

    def get_tool_approval(self, approval_id: int) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    tool_name,
                    risk,
                    arguments_json,
                    audit_context_json,
                    summary,
                    cli_command,
                    chat_command,
                    status,
                    execution_payload_json,
                    error_text,
                    created_at,
                    updated_at,
                    resolved_at
                FROM tool_approvals
                WHERE id = ?
                """,
                (approval_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_tool_approval(row)

    def claim_tool_approval(self, approval_id: int) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE tool_approvals
                SET status = 'executing', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending'
                """,
                (approval_id,),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            cursor = connection.execute(
                """
                SELECT
                    id,
                    tool_name,
                    risk,
                    arguments_json,
                    audit_context_json,
                    summary,
                    cli_command,
                    chat_command,
                    status,
                    execution_payload_json,
                    error_text,
                    created_at,
                    updated_at,
                    resolved_at
                FROM tool_approvals
                WHERE id = ?
                """,
                (approval_id,),
            )
            row = cursor.fetchone()
            connection.commit()
        if row is None:
            return None
        return self._row_to_tool_approval(row)

    def claim_latest_matching_tool_approval(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        audit_context: dict[str, object],
    ) -> dict[str, object] | None:
        match = self.prepare_matching_tool_approval_for_execution(
            tool_name=tool_name,
            arguments=arguments,
            audit_context=audit_context,
        )
        if match.outcome != "claimed":
            return None
        return match.approval

    def prepare_matching_tool_approval_for_execution(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        audit_context: dict[str, object],
    ) -> ToolApprovalExecutionMatch:
        _, _, action_digest = _serialize_tool_approval_identity(
            tool_name=tool_name,
            arguments=arguments,
            audit_context=audit_context,
        )
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select_active_tool_approval_row_by_digest(connection, action_digest)
            if row is None:
                connection.rollback()
                return ToolApprovalExecutionMatch(outcome="none", approval=None)
            if str(row[8]) == "executing":
                connection.commit()
                return ToolApprovalExecutionMatch(
                    outcome="already_executing",
                    approval=self._row_to_tool_approval(row),
                )
            approval_id = _coerce_int(row[0], "tool approval id")
            cursor = connection.execute(
                """
                UPDATE tool_approvals
                SET status = 'executing', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending'
                """,
                (approval_id,),
            )
            if cursor.rowcount != 1:
                current_row = self._select_active_tool_approval_row_by_digest(
                    connection, action_digest
                )
                if current_row is None:
                    connection.rollback()
                    return ToolApprovalExecutionMatch(outcome="none", approval=None)
                connection.commit()
                outcome = "already_executing" if str(current_row[8]) == "executing" else "none"
                approval = self._row_to_tool_approval(current_row) if outcome != "none" else None
                return ToolApprovalExecutionMatch(outcome=outcome, approval=approval)
            claimed_row = self._select_tool_approval_row(connection, approval_id)
            connection.commit()
        if claimed_row is None:
            return ToolApprovalExecutionMatch(outcome="none", approval=None)
        return ToolApprovalExecutionMatch(
            outcome="claimed",
            approval=self._row_to_tool_approval(claimed_row),
        )

    def finish_tool_approval(
        self,
        approval_id: int,
        *,
        status: str,
        execution_payload: dict[str, object],
    ) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE tool_approvals
                SET
                    status = ?,
                    execution_payload_json = ?,
                    error_text = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    resolved_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'executing'
                """,
                (
                    status,
                    json.dumps(execution_payload, sort_keys=True),
                    str(execution_payload.get("error"))
                    if isinstance(execution_payload.get("error"), str)
                    else None,
                    approval_id,
                ),
            )
            connection.commit()
            if cursor.rowcount != 1:
                return None
        return self.get_tool_approval(approval_id)

    def reject_tool_approval(self, approval_id: int) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE tool_approvals
                SET
                    status = 'rejected',
                    updated_at = CURRENT_TIMESTAMP,
                    resolved_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending'
                """,
                (approval_id,),
            )
            connection.commit()
            if cursor.rowcount != 1:
                return None
        return self.get_tool_approval(approval_id)

    def create_session(self) -> int:
        with closing(self._connect()) as connection:
            cursor = connection.execute("INSERT INTO sessions DEFAULT VALUES")
            connection.commit()
            session_id = cursor.lastrowid
            if session_id is None:
                raise RuntimeError("SQLite did not return a session id.")
            return session_id

    def append_conversation_message(self, session_id: int, role: str, content: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO conversation_messages (session_id, role, content)
                VALUES (?, ?, ?)
                """,
                (session_id, role, content),
            )
            connection.commit()

    def list_conversation_messages(
        self,
        session_id: int,
        *,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                SELECT role, content, created_at
                FROM conversation_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
            rows = cursor.fetchall()

        messages = [
            {
                "role": role,
                "content": content,
                "created_at": created_at,
            }
            for role, content, created_at in reversed(rows)
        ]
        return messages

    def get_session_summary(self, session_id: int) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                SELECT summary_text, updated_at
                FROM session_summaries
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return None
        summary_text, updated_at = row
        return {
            "session_id": session_id,
            "summary_text": summary_text,
            "updated_at": updated_at,
        }

    def record_observation(
        self,
        session_id: int,
        source: str,
        key: str,
        value: dict[str, object],
        *,
        observed_at: str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        observed_at_value = observed_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
        expires_at_value = compute_expires_at(
            observed_at=datetime.fromisoformat(observed_at_value.replace("Z", "+00:00")),
            ttl_seconds=ttl_seconds,
        )
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO observations (session_id, source, key, value, observed_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    source,
                    key,
                    serialize_observation_value(value),
                    observed_at_value,
                    expires_at_value,
                ),
            )
            connection.commit()

    def list_latest_observations(self, session_id: int) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                SELECT o.source, o.key, o.value, o.observed_at, o.expires_at
                FROM observations AS o
                INNER JOIN (
                    SELECT key, MAX(id) AS max_id
                    FROM observations
                    WHERE session_id = ?
                    GROUP BY key
                ) AS latest
                    ON latest.max_id = o.id
                WHERE o.session_id = ?
                ORDER BY o.id DESC
                """,
                (session_id, session_id),
            )
            rows = cursor.fetchall()

        observations: list[dict[str, object]] = []
        for source, key, value, observed_at, expires_at in rows:
            observations.append(
                {
                    "source": source,
                    "key": key,
                    "value": deserialize_observation_value(value),
                    "observed_at": observed_at,
                    "expires_at": expires_at,
                }
            )
        return observations

    def list_recent_observations(
        self,
        session_id: int,
        *,
        limit_per_key: int = 2,
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                SELECT source, key, value, observed_at, expires_at
                FROM observations
                WHERE session_id = ?
                ORDER BY id DESC
                """,
                (session_id,),
            )
            rows = cursor.fetchall()

        observations: list[dict[str, object]] = []
        counts_by_key: dict[str, int] = {}
        for source, key, value, observed_at, expires_at in rows:
            if not isinstance(key, str):
                continue
            seen = counts_by_key.get(key, 0)
            if seen >= limit_per_key:
                continue
            counts_by_key[key] = seen + 1
            observations.append(
                {
                    "source": source,
                    "key": key,
                    "value": deserialize_observation_value(value),
                    "observed_at": observed_at,
                    "expires_at": expires_at,
                }
            )
        return observations

    def upsert_session_summary(self, session_id: int, summary_text: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO session_summaries (session_id, summary_text, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    summary_text = excluded.summary_text,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, summary_text),
            )
            connection.commit()

    def list_session_recommendations(
        self,
        session_id: int,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            if status is None:
                cursor = connection.execute(
                    """
                    SELECT
                        id,
                        session_id,
                        dedupe_key,
                        source_key,
                        severity,
                        message,
                        status,
                        action_kind,
                        action_title,
                        action_tool_name,
                        action_arguments_json,
                        created_at,
                        updated_at,
                        last_seen_at
                    FROM session_recommendations
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                )
            else:
                cursor = connection.execute(
                    """
                    SELECT
                        id,
                        session_id,
                        dedupe_key,
                        source_key,
                        severity,
                        message,
                        status,
                        action_kind,
                        action_title,
                        action_tool_name,
                        action_arguments_json,
                        created_at,
                        updated_at,
                        last_seen_at
                    FROM session_recommendations
                    WHERE session_id = ? AND status = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (session_id, status, limit),
                )
            rows = cursor.fetchall()
        return [self._row_to_recommendation(row) for row in rows]

    def get_recommendation(self, recommendation_id: int) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    session_id,
                    dedupe_key,
                    source_key,
                    severity,
                    message,
                    status,
                    action_kind,
                    action_title,
                    action_tool_name,
                    action_arguments_json,
                    created_at,
                    updated_at,
                    last_seen_at
                FROM session_recommendations
                WHERE id = ?
                """,
                (recommendation_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_recommendation(row)

    def update_recommendation_status(
        self,
        recommendation_id: int,
        status: str,
    ) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE session_recommendations
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, recommendation_id),
            )
            connection.commit()
        return self.get_recommendation(recommendation_id)

    def sync_session_recommendations(
        self,
        session_id: int,
        candidates: list[dict[str, object]],
    ) -> dict[str, list[dict[str, object]]]:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    session_id,
                    dedupe_key,
                    source_key,
                    severity,
                    message,
                    status,
                    action_kind,
                    action_title,
                    action_tool_name,
                    action_arguments_json,
                    created_at,
                    updated_at,
                    last_seen_at
                FROM session_recommendations
                WHERE session_id = ?
                """,
                (session_id,),
            )
            existing_rows = cursor.fetchall()
            existing_by_key = {row[2]: self._row_to_recommendation(row) for row in existing_rows}

            new_ids: list[int] = []
            reopened_ids: list[int] = []
            active_keys: set[str] = set()

            for candidate in candidates:
                dedupe_key = str(candidate["dedupe_key"])
                active_keys.add(dedupe_key)
                existing = existing_by_key.get(dedupe_key)
                action_payload = candidate.get("action")
                action_kind = None
                action_title = None
                action_tool_name = None
                action_arguments_json = None
                if isinstance(action_payload, dict):
                    raw_kind = action_payload.get("kind")
                    raw_title = action_payload.get("title")
                    raw_tool_name = action_payload.get("tool_name")
                    raw_arguments = action_payload.get("arguments")
                    action_kind = str(raw_kind) if raw_kind else None
                    action_title = str(raw_title) if raw_title else None
                    action_tool_name = str(raw_tool_name) if raw_tool_name else None
                    if isinstance(raw_arguments, dict):
                        action_arguments_json = json.dumps(raw_arguments, sort_keys=True)
                if existing is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO session_recommendations (
                            session_id,
                            dedupe_key,
                            source_key,
                            severity,
                            message,
                            status,
                            action_kind,
                            action_title,
                            action_tool_name,
                            action_arguments_json,
                            updated_at,
                            last_seen_at
                        )
                        VALUES (
                            ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            session_id,
                            dedupe_key,
                            str(candidate["source_key"]),
                            str(candidate["severity"]),
                            str(candidate["message"]),
                            action_kind,
                            action_title,
                            action_tool_name,
                            action_arguments_json,
                        ),
                    )
                    recommendation_id = cursor.lastrowid
                    if recommendation_id is None:
                        raise RuntimeError("SQLite did not return a recommendation id.")
                    new_ids.append(recommendation_id)
                    continue

                next_status = existing["status"]
                if next_status in {"dismissed", "resolved"}:
                    next_status = "open"
                    reopened_ids.append(_coerce_int(existing["id"], "recommendation id"))

                connection.execute(
                    """
                    UPDATE session_recommendations
                    SET
                        source_key = ?,
                        severity = ?,
                        message = ?,
                        action_kind = ?,
                        action_title = ?,
                        action_tool_name = ?,
                        action_arguments_json = ?,
                        status = ?,
                        updated_at = CURRENT_TIMESTAMP,
                        last_seen_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        str(candidate["source_key"]),
                        str(candidate["severity"]),
                        str(candidate["message"]),
                        action_kind,
                        action_title,
                        action_tool_name,
                        action_arguments_json,
                        next_status,
                        existing["id"],
                    ),
                )

            auto_resolved_ids: list[int] = []
            if active_keys:
                auto_resolved_ids = _select_recommendation_ids_excluding_keys(
                    connection,
                    session_id=session_id,
                    active_keys=sorted(active_keys),
                )
                _mark_recommendations_resolved(connection, auto_resolved_ids)
            else:
                cursor = connection.execute(
                    """
                    SELECT id
                    FROM session_recommendations
                    WHERE session_id = ?
                      AND status IN ('open', 'accepted')
                    """,
                    (session_id,),
                )
                auto_resolved_ids = [int(row[0]) for row in cursor.fetchall()]
                _mark_recommendations_resolved(connection, auto_resolved_ids)

            connection.commit()

        all_items = self.list_session_recommendations(session_id, limit=200)
        by_id = {_coerce_int(item["id"], "recommendation id"): item for item in all_items}
        active_items = [item for item in all_items if item["status"] in {"open", "accepted"}]
        return {
            "active": active_items,
            "new": [by_id[item_id] for item_id in new_ids if item_id in by_id],
            "reopened": [by_id[item_id] for item_id in reopened_ids if item_id in by_id],
            "auto_resolved": [by_id[item_id] for item_id in auto_resolved_ids if item_id in by_id],
        }

    def update_session_provider_state(
        self,
        session_id: int,
        provider_backend: str,
        previous_response_id: str | None,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO session_provider_state (
                    session_id,
                    provider_backend,
                    previous_response_id,
                    updated_at
                )
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    provider_backend = excluded.provider_backend,
                    previous_response_id = excluded.previous_response_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, provider_backend, previous_response_id),
            )
            connection.commit()

    def get_session_provider_state(self, session_id: int) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                SELECT provider_backend, previous_response_id, updated_at
                FROM session_provider_state
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return None
        provider_backend, previous_response_id, updated_at = row
        return {
            "session_id": session_id,
            "provider_backend": provider_backend,
            "previous_response_id": previous_response_id,
            "updated_at": updated_at,
        }

    def session_exists(self, session_id: int) -> bool:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "SELECT 1 FROM sessions WHERE id = ? LIMIT 1",
                (session_id,),
            )
            row = cursor.fetchone()
        return row is not None

    def list_sessions(self, limit: int = 20) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                SELECT
                    s.id,
                    s.created_at,
                    COALESCE(state.provider_backend, '') AS provider_backend,
                    state.previous_response_id,
                    state.updated_at,
                    summaries.summary_text,
                    summaries.updated_at,
                    COUNT(messages.id) AS message_count,
                    MAX(messages.created_at) AS last_message_at
                FROM sessions AS s
                LEFT JOIN session_provider_state AS state
                    ON state.session_id = s.id
                LEFT JOIN session_summaries AS summaries
                    ON summaries.session_id = s.id
                LEFT JOIN conversation_messages AS messages
                    ON messages.session_id = s.id
                GROUP BY
                    s.id,
                    s.created_at,
                    state.provider_backend,
                    state.previous_response_id,
                    state.updated_at
                    ,
                    summaries.summary_text,
                    summaries.updated_at
                ORDER BY s.id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        sessions: list[dict[str, object]] = []
        for (
            session_id,
            created_at,
            provider_backend,
            previous_response_id,
            updated_at,
            summary_text,
            summary_updated_at,
            message_count,
            last_message_at,
        ) in rows:
            sessions.append(
                {
                    "session_id": session_id,
                    "created_at": created_at,
                    "provider_backend": provider_backend or None,
                    "previous_response_id": previous_response_id,
                    "updated_at": updated_at,
                    "summary_text": summary_text,
                    "summary_updated_at": summary_updated_at,
                    "message_count": message_count,
                    "last_message_at": last_message_at,
                }
            )
        return sessions

    def _row_to_recommendation(self, row: tuple[object, ...]) -> dict[str, object]:
        action_kind = row[7]
        action_title = row[8]
        action_tool_name = row[9]
        action_arguments_json = row[10]
        action: dict[str, object] | None = None
        if isinstance(action_tool_name, str) and action_tool_name:
            parsed_arguments: dict[str, object] = {}
            if isinstance(action_arguments_json, str) and action_arguments_json:
                try:
                    raw_arguments = json.loads(action_arguments_json)
                except json.JSONDecodeError:
                    raw_arguments = {}
                if isinstance(raw_arguments, dict):
                    parsed_arguments = raw_arguments
            action = {
                "kind": action_kind or "run_tool",
                "tool_name": action_tool_name,
                "title": action_title,
                "arguments": parsed_arguments,
            }

        return {
            "id": row[0],
            "session_id": row[1],
            "dedupe_key": row[2],
            "source_key": row[3],
            "severity": row[4],
            "message": row[5],
            "status": row[6],
            "action": action,
            "created_at": row[11],
            "updated_at": row[12],
            "last_seen_at": row[13],
        }

    def _row_to_tool_approval(self, row: tuple[object, ...]) -> dict[str, object]:
        arguments = _deserialize_json_object(row[3])
        audit_context = _deserialize_json_object(row[4])
        execution = _deserialize_json_object(row[9]) if row[9] is not None else None
        return {
            "id": row[0],
            "tool": row[1],
            "risk": row[2],
            "arguments": arguments,
            "audit_context": audit_context,
            "summary": row[5],
            "cli_command": row[6],
            "chat_command": row[7],
            "status": row[8],
            "execution": execution,
            "error": row[10],
            "created_at": row[11],
            "updated_at": row[12],
            "resolved_at": row[13],
        }

    def _select_tool_approval_row(
        self,
        connection: sqlite3.Connection,
        approval_id: int,
    ) -> tuple[object, ...] | None:
        cursor = connection.execute(
            """
            SELECT
                id,
                tool_name,
                risk,
                arguments_json,
                audit_context_json,
                summary,
                cli_command,
                chat_command,
                status,
                execution_payload_json,
                error_text,
                created_at,
                updated_at,
                resolved_at
            FROM tool_approvals
            WHERE id = ?
            """,
            (approval_id,),
        )
        return cursor.fetchone()

    def _select_active_tool_approval_row_by_digest(
        self,
        connection: sqlite3.Connection,
        action_digest: str,
    ) -> tuple[object, ...] | None:
        cursor = connection.execute(
            """
            SELECT
                id,
                tool_name,
                risk,
                arguments_json,
                audit_context_json,
                summary,
                cli_command,
                chat_command,
                status,
                execution_payload_json,
                error_text,
                created_at,
                updated_at,
                resolved_at
            FROM tool_approvals
            WHERE action_digest = ?
              AND status IN ('pending', 'executing')
            ORDER BY
                CASE status
                    WHEN 'pending' THEN 0
                    ELSE 1
                END,
                id DESC
            LIMIT 1
            """,
            (action_digest,),
        )
        return cursor.fetchone()


def _coerce_int(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"Expected integer-compatible value for {label}, got {type(value).__name__}.")


def _placeholder_csv(count: int) -> str:
    if count <= 0:
        raise ValueError("SQL placeholder counts must be positive.")
    return ", ".join("?" for _ in range(count))


def _select_recommendation_ids_excluding_keys(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    active_keys: list[str],
) -> list[int]:
    placeholders = _placeholder_csv(len(active_keys))
    # The query text is static apart from a placeholder count derived from trusted key counts.
    query = (  # nosec B608
        "SELECT id "
        "FROM session_recommendations "
        "WHERE session_id = ? "
        "AND status IN ('open', 'accepted') "
        f"AND dedupe_key NOT IN ({placeholders})"
    )
    parameters = [session_id, *active_keys]
    cursor = connection.execute(query, parameters)
    return [int(row[0]) for row in cursor.fetchall()]


def _mark_recommendations_resolved(
    connection: sqlite3.Connection,
    recommendation_ids: list[int],
) -> None:
    if not recommendation_ids:
        return
    placeholders = _placeholder_csv(len(recommendation_ids))
    # The query text is static apart from a placeholder count derived from selected row ids.
    query = (  # nosec B608
        "UPDATE session_recommendations "
        "SET status = 'resolved', updated_at = CURRENT_TIMESTAMP "
        f"WHERE id IN ({placeholders})"
    )
    connection.execute(query, recommendation_ids)


def _deserialize_json_object(value: object) -> dict[str, object]:
    if not isinstance(value, str) or not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _serialize_tool_approval_identity(
    *,
    tool_name: str,
    arguments: dict[str, object],
    audit_context: dict[str, object],
) -> tuple[str, str, str]:
    arguments_json = json.dumps(arguments, sort_keys=True)
    audit_context_json = json.dumps(audit_context, sort_keys=True)
    return (
        arguments_json,
        audit_context_json,
        _build_tool_approval_digest(
            tool_name=tool_name,
            arguments_json=arguments_json,
            audit_context_json=audit_context_json,
        ),
    )


def _build_tool_approval_digest(
    *,
    tool_name: str,
    arguments_json: str,
    audit_context_json: str,
) -> str:
    digest_input = f"{tool_name}\x1f{arguments_json}\x1f{audit_context_json}"
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
