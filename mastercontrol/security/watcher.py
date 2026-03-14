#!/usr/bin/env python3
"""Continuous local security watch built on persisted system events."""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import uuid
from collections import Counter
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from mastercontrol.context import SQLiteContextStore, SystemEventMonitor
    from mastercontrol.contracts import IncidentRecord, normalize_incident_status
except ImportError:  # pragma: no cover
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from mastercontrol.context import SQLiteContextStore, SystemEventMonitor  # type: ignore
    from mastercontrol.contracts import IncidentRecord, normalize_incident_status  # type: ignore

SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
STATUS_FROM_SEVERITY = {
    "none": "stable",
    "low": "observe",
    "medium": "watch",
    "high": "elevated",
    "critical": "elevated",
}
AUTH_CONTAINMENT_UNIT = "ssh.service"
NETWORK_CONTAINMENT_UNITS = {
    "networkmanager": "NetworkManager.service",
    "systemd-networkd": "systemd-networkd.service",
    "systemd-resolved": "systemd-resolved.service",
}
ACTIVE_INCIDENT_STATUSES = {"open", "contained"}
SECURITY_WATCH_SCHEMA_VERSION = 3


def default_db_path() -> Path:
    return Path.home() / ".local" / "share" / "mastercontrol" / "mastercontrol.db"


@dataclass(frozen=True)
class SecurityAlertCandidate:
    fingerprint: str
    severity: str
    category: str
    summary: str
    recommendation: str
    event_ids: tuple[int, ...]
    sources: tuple[str, ...]
    event_count: int


@dataclass(frozen=True)
class SecurityWatchResult:
    ts_utc: str
    highest_severity: str
    vigilance_status: str
    alerts_emitted: int
    active_alerts: int
    event_sweep: dict[str, Any]
    alerts: tuple[SecurityAlertCandidate, ...]


class SecurityWatchEngine:
    """Generates prioritized local security alerts from persisted system events."""

    def __init__(
        self,
        *,
        db_path: Path | None = None,
        event_monitor: SystemEventMonitor | None = None,
        window_hours: int = 6,
        dedupe_window_minutes: int = 30,
    ) -> None:
        self.db_path = db_path or default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_monitor = event_monitor
        self.window_hours = max(1, min(window_hours, 24))
        self.dedupe_window_minutes = max(1, dedupe_window_minutes)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def schema_version(self) -> int:
        with closing(self._conn()) as conn:
            self._ensure_meta_table(conn)
            return self._load_schema_version(conn)

    def _init_db(self) -> None:
        with closing(self._conn()) as conn:
            with conn:
                self._ensure_meta_table(conn)
                start_version = self._load_schema_version(conn)
                for target, migration in (
                    (1, self._migrate_v1),
                    (2, self._migrate_v2),
                    (3, self._migrate_v3),
                ):
                    migration(conn)
                    if start_version < target:
                        self._set_schema_version(conn, target)
                if start_version > SECURITY_WATCH_SCHEMA_VERSION:
                    self._set_schema_version(conn, SECURITY_WATCH_SCHEMA_VERSION)

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            LIMIT 1
            """,
            (table,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        if not SecurityWatchEngine._table_exists(conn, table):
            return set()
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row[1]) for row in rows}

    @staticmethod
    def _ensure_columns(
        conn: sqlite3.Connection,
        table: str,
        columns: dict[str, str],
    ) -> None:
        existing = SecurityWatchEngine._table_columns(conn, table)
        for name, definition in columns.items():
            if name in existing:
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _ensure_meta_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS security_watch_meta (
                meta_key TEXT PRIMARY KEY,
                meta_value TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            )
            """
        )

    @staticmethod
    def _load_schema_version(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            """
            SELECT meta_value
            FROM security_watch_meta
            WHERE meta_key = 'schema_version'
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return 0
        try:
            return int(str(row["meta_value"]))
        except Exception:  # noqa: BLE001
            return 0

    @staticmethod
    def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
        current = dt.datetime.now(tz=dt.timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO security_watch_meta (meta_key, meta_value, updated_at_utc)
            VALUES ('schema_version', ?, ?)
            ON CONFLICT(meta_key) DO UPDATE SET
                meta_value = excluded.meta_value,
                updated_at_utc = excluded.updated_at_utc
            """,
            (str(int(version)), current),
        )

    def _migrate_v1(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS security_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                severity TEXT NOT NULL,
                category TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                summary TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'security-watch',
                status TEXT NOT NULL DEFAULT 'new',
                event_ids_json TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS security_silences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                silence_until_utc TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'operator'
            );

            CREATE INDEX IF NOT EXISTS idx_security_alerts_ts
            ON security_alerts (ts_utc DESC);

            CREATE INDEX IF NOT EXISTS idx_security_alerts_fingerprint
            ON security_alerts (fingerprint, ts_utc DESC);

            CREATE INDEX IF NOT EXISTS idx_security_silences_fingerprint
            ON security_silences (fingerprint, silence_until_utc DESC);
            """
        )
        self._ensure_columns(
            conn,
            "security_alerts",
            {
                "ts_utc": "TEXT NOT NULL DEFAULT ''",
                "severity": "TEXT NOT NULL DEFAULT 'low'",
                "category": "TEXT NOT NULL DEFAULT 'security'",
                "fingerprint": "TEXT NOT NULL DEFAULT ''",
                "summary": "TEXT NOT NULL DEFAULT ''",
                "recommendation": "TEXT NOT NULL DEFAULT ''",
                "source": "TEXT NOT NULL DEFAULT 'security-watch'",
                "status": "TEXT NOT NULL DEFAULT 'new'",
                "event_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "payload_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        )
        self._ensure_columns(
            conn,
            "security_silences",
            {
                "fingerprint": "TEXT NOT NULL DEFAULT ''",
                "reason": "TEXT NOT NULL DEFAULT ''",
                "created_at": "TEXT NOT NULL DEFAULT ''",
                "silence_until_utc": "TEXT NOT NULL DEFAULT ''",
                "source": "TEXT NOT NULL DEFAULT 'operator'",
            },
        )

    def _migrate_v2(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                opened_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                last_seen_at_utc TEXT NOT NULL,
                last_action_id TEXT NOT NULL DEFAULT '',
                operator_decision TEXT NOT NULL DEFAULT '',
                resolution_summary TEXT NOT NULL DEFAULT '',
                latest_summary TEXT NOT NULL DEFAULT '',
                alert_ids_json TEXT NOT NULL DEFAULT '[]',
                event_ids_json TEXT NOT NULL DEFAULT '[]',
                correlated_units_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_incidents_status_updated
            ON incidents (status, updated_at_utc DESC);

            CREATE INDEX IF NOT EXISTS idx_incidents_fingerprint
            ON incidents (fingerprint, category, updated_at_utc DESC);

            CREATE TABLE IF NOT EXISTS incident_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                ts_utc TEXT NOT NULL,
                status_from TEXT NOT NULL DEFAULT '',
                status_to TEXT NOT NULL DEFAULT '',
                action_id TEXT NOT NULL DEFAULT '',
                operator_id TEXT NOT NULL DEFAULT '',
                request_id TEXT NOT NULL DEFAULT '',
                operator_decision TEXT NOT NULL DEFAULT '',
                resolution_summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_incident_activity_incident
            ON incident_activity (incident_id, id DESC);
            """
        )
        self._ensure_columns(
            conn,
            "incidents",
            {
                "fingerprint": "TEXT NOT NULL DEFAULT ''",
                "category": "TEXT NOT NULL DEFAULT 'security'",
                "severity": "TEXT NOT NULL DEFAULT 'low'",
                "status": "TEXT NOT NULL DEFAULT 'open'",
                "opened_at_utc": "TEXT NOT NULL DEFAULT ''",
                "updated_at_utc": "TEXT NOT NULL DEFAULT ''",
                "last_seen_at_utc": "TEXT NOT NULL DEFAULT ''",
                "last_action_id": "TEXT NOT NULL DEFAULT ''",
                "operator_decision": "TEXT NOT NULL DEFAULT ''",
                "resolution_summary": "TEXT NOT NULL DEFAULT ''",
                "latest_summary": "TEXT NOT NULL DEFAULT ''",
                "alert_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "event_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "correlated_units_json": "TEXT NOT NULL DEFAULT '[]'",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        )
        self._ensure_columns(
            conn,
            "incident_activity",
            {
                "incident_id": "TEXT NOT NULL DEFAULT ''",
                "ts_utc": "TEXT NOT NULL DEFAULT ''",
                "status_from": "TEXT NOT NULL DEFAULT ''",
                "status_to": "TEXT NOT NULL DEFAULT ''",
                "action_id": "TEXT NOT NULL DEFAULT ''",
                "operator_id": "TEXT NOT NULL DEFAULT ''",
                "request_id": "TEXT NOT NULL DEFAULT ''",
                "operator_decision": "TEXT NOT NULL DEFAULT ''",
                "resolution_summary": "TEXT NOT NULL DEFAULT ''",
                "payload_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        )

    def _migrate_v3(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_security_alerts_status_ts
            ON security_alerts (status, ts_utc DESC);

            CREATE INDEX IF NOT EXISTS idx_security_silences_until
            ON security_silences (silence_until_utc DESC);

            CREATE INDEX IF NOT EXISTS idx_incidents_last_seen
            ON incidents (last_seen_at_utc DESC);

            CREATE INDEX IF NOT EXISTS idx_incident_activity_ts
            ON incident_activity (ts_utc DESC);
            """
        )
        if self._table_exists(conn, "system_events"):
            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_system_events_ts
                ON system_events (ts_utc DESC);

                CREATE INDEX IF NOT EXISTS idx_system_events_category_ts
                ON system_events (category, ts_utc DESC);
                """
            )

    def run_once(
        self,
        *,
        now: dt.datetime | None = None,
        max_events: int = 64,
    ) -> SecurityWatchResult:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        sweep_payload = self._run_event_sweep(current=current, max_events=max_events)
        alerts = self.evaluate_alerts(now=current, window_hours=self.window_hours)
        alerts_emitted = 0
        for alert in alerts:
            if self._store_alert(alert, current=current):
                alerts_emitted += 1
        self._refresh_incident_ledger(now=current, window_hours=max(self.window_hours, 24))

        highest = alerts[0].severity if alerts else "none"
        return SecurityWatchResult(
            ts_utc=current.isoformat(),
            highest_severity=highest,
            vigilance_status=STATUS_FROM_SEVERITY.get(highest, "stable"),
            alerts_emitted=alerts_emitted,
            active_alerts=len(alerts),
            event_sweep=sweep_payload,
            alerts=tuple(alerts),
        )

    def summarize_vigilance(
        self,
        *,
        category: str = "all",
        window_hours: int | None = None,
        now: dt.datetime | None = None,
    ) -> dict[str, Any]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        hours = max(1, min(window_hours or self.window_hours, 24))
        rows = self._load_system_events(now=current, window_hours=hours)
        filtered_rows = self._filter_rows(rows, category)
        alerts = self._filter_alerts(self._derive_alert_candidates(filtered_rows), category)
        highest = alerts[0].severity if alerts else "none"
        status = STATUS_FROM_SEVERITY.get(highest, "stable")
        counts = Counter(str(row["category"]) for row in filtered_rows)
        counts_text = ", ".join(f"{key}={counts[key]}" for key in sorted(counts)) or "none"

        if alerts:
            top = alerts[0]
            other = ""
            if len(alerts) > 1:
                other = " Additional: " + " | ".join(alert.summary for alert in alerts[1:3])
            summary = (
                f"Security vigilance status: {status}. Scope={category}, window={hours}h. "
                f"Signals: {counts_text}. Top alert: {top.summary} "
                f"Recommendation: {top.recommendation}{other}"
            )
        else:
            summary = (
                f"Security vigilance status: {status}. Scope={category}, window={hours}h. "
                f"Signals: {counts_text}. Recommendation: Keep monitoring normal host activity."
            )
        return {
            "status": status,
            "highest_severity": highest,
            "summary": summary,
            "alerts": [asdict(alert) for alert in alerts],
            "event_counts": dict(counts),
            "window_hours": hours,
            "category": category,
        }

    def build_incident_playbook(
        self,
        *,
        category: str = "all",
        severity: str = "all",
        fingerprint: str = "",
        limit: int = 3,
        window_hours: int = 24,
        now: dt.datetime | None = None,
    ) -> dict[str, Any]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        self._refresh_incident_ledger(now=current, window_hours=window_hours)
        alerts = self._load_active_alert_rows(
            category=category,
            severity=severity,
            fingerprint=fingerprint,
            window_hours=window_hours,
            now=current,
            limit=max(1, min(limit, 10)),
        )
        if not alerts:
            return {
                "status": "stable",
                "highest_severity": "none",
                "summary": "No active incidents matched the requested scope.",
                "alerts": [],
                "incidents": [],
                "recommendations": [],
                "category": category,
                "severity": severity,
                "fingerprint": fingerprint,
                "window_hours": max(1, min(window_hours, 72)),
            }

        highest = max(
            (str(row["severity"]) for row in alerts),
            key=lambda value: SEVERITY_ORDER.get(value, 0),
        )
        recommendations: list[dict[str, Any]] = []
        seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        for row in alerts:
            for item in self._recommendations_for_alert(row, now=current):
                key = (
                    str(item["action_id"]),
                    tuple(sorted((str(k), str(v)) for k, v in dict(item.get("args", {})).items())),
                )
                if key in seen:
                    continue
                seen.add(key)
                recommendations.append(item)

        incidents = self.list_incidents(
            limit=max(1, min(limit, 10)),
            status="active",
            category=category,
            severity=severity,
            fingerprint=fingerprint,
            now=current,
            sync=False,
        )
        status = STATUS_FROM_SEVERITY.get(highest, "stable")
        alert_text = " | ".join(
            f"#{row['id']} {row['severity']} {row['fingerprint']}: {row['summary']}"
            for row in alerts
        )
        incident_text = " | ".join(
            f"{row['incident_id']}[{row['status']}] {row['fingerprint']}"
            for row in incidents[:3]
        )
        if incident_text:
            incident_text = f" Active incident ledger: {incident_text}."
        if recommendations:
            response_text = " | ".join(
                f"{item['mode']} -> {item['action_id']}({', '.join(f'{k}={v}' for k, v in item['args'].items()) or 'no-args'})"
                for item in recommendations[:3]
            )
            summary = (
                f"Incident response posture: {status}. Active alerts: {alert_text}. "
                f"Recommended next actions: {response_text}{incident_text}"
            )
        else:
            summary = (
                f"Incident response posture: {status}. Active alerts: {alert_text}. "
                "No safe automated containment is currently suggested; continue with investigation."
                f"{incident_text}"
            )

        return {
            "status": status,
            "highest_severity": highest,
            "summary": summary,
            "alerts": [dict(row) for row in alerts],
            "incidents": incidents,
            "recommendations": recommendations,
            "category": category,
            "severity": severity,
            "fingerprint": fingerprint,
            "window_hours": max(1, min(window_hours, 72)),
        }

    def list_incidents(
        self,
        *,
        limit: int = 10,
        status: str = "active",
        category: str = "all",
        severity: str = "all",
        fingerprint: str = "",
        now: dt.datetime | None = None,
        sync: bool = True,
    ) -> list[dict[str, Any]]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        if sync:
            self._refresh_incident_ledger(now=current)
        rows = self._load_incident_rows(
            limit=limit,
            status=status,
            category=category,
            severity=severity,
            fingerprint=fingerprint,
        )
        return [asdict(self._row_to_incident(row)) for row in rows]

    def get_incident(
        self,
        incident_id: str,
        *,
        activity_limit: int = 10,
        now: dt.datetime | None = None,
        sync: bool = True,
    ) -> dict[str, Any] | None:
        incident_key = (incident_id or "").strip().lower()
        if not incident_key:
            return None
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        if sync:
            self._refresh_incident_ledger(now=current)
        row = self._load_incident_row_by_id(incident_key)
        if row is None:
            return None
        incident = asdict(self._row_to_incident(row))
        incident["alerts"] = self._load_alert_rows_for_ids(list(incident["alert_ids"]))
        incident["activity"] = self._load_incident_activity_rows(
            incident_key,
            limit=max(1, min(activity_limit, 20)),
        )
        return incident

    def update_incident_status(
        self,
        incident_id: str,
        *,
        status: str,
        operator_id: str = "",
        request_id: str = "",
        resolution_summary: str = "",
        now: dt.datetime | None = None,
        sync: bool = True,
    ) -> dict[str, Any]:
        incident_key = (incident_id or "").strip().lower()
        if not incident_key:
            return {
                "updated": 0,
                "incident": None,
                "summary": "Incident update requires an explicit incident_id.",
            }
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        if sync:
            self._refresh_incident_ledger(now=current)
        row = self._load_incident_row_by_id(incident_key)
        if row is None:
            return {
                "updated": 0,
                "incident": None,
                "summary": f"Incident '{incident_key}' was not found in the local ledger.",
            }

        incident = self._row_to_incident(row)
        target_status = normalize_incident_status(status)
        if target_status not in {"resolved", "dismissed", "open", "contained"}:
            return {
                "updated": 0,
                "incident": asdict(incident),
                "summary": f"Incident status '{status}' is not supported.",
            }

        alert_rows = self._load_alert_rows_for_ids(list(incident.alert_ids))
        self._set_alert_rows_acknowledged([int(row["id"]) for row in alert_rows])
        summary = (
            resolution_summary.strip()
            or f"Incident {incident.incident_id} marked as {target_status} by operator."
        )
        self._update_incident_state(
            incident_id=incident.incident_id,
            status=target_status,
            last_action_id=f"security.incident.{target_status}",
            operator_decision=target_status,
            resolution_summary=summary,
            current=current,
        )
        self._append_incident_activity(
            incident_id=incident.incident_id,
            current=current,
            status_from=incident.status,
            status_to=target_status,
            action_id=f"security.incident.{target_status}",
            operator_id=operator_id,
            request_id=request_id,
            operator_decision=target_status,
            resolution_summary=summary,
            payload={
                "incident_id": incident.incident_id,
                "acknowledged_alert_ids": [int(row["id"]) for row in alert_rows],
            },
        )
        refreshed = self.get_incident(
            incident.incident_id,
            activity_limit=10,
            now=current,
            sync=False,
        )
        return {
            "updated": 1,
            "incident": refreshed,
            "summary": summary,
        }

    def active_incident_summary(
        self,
        *,
        now: dt.datetime | None = None,
    ) -> dict[str, Any]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        incidents = self.list_incidents(limit=20, status="active", now=current)
        if not incidents:
            return {
                "active_incidents": 0,
                "highest_severity": "none",
                "status": "stable",
                "counts": {},
                "top_fingerprints": [],
                "summary": "incidents=0 status=stable",
            }

        highest = max(
            (str(row["severity"]) for row in incidents),
            key=lambda value: SEVERITY_ORDER.get(value, 0),
        )
        counts = Counter(str(row["status"]) for row in incidents)
        top_fingerprints = list(dict.fromkeys(str(row["fingerprint"]) for row in incidents[:3]))
        status = STATUS_FROM_SEVERITY.get(highest, "stable")
        parts = [
            f"incidents={len(incidents)}",
            f"status={status}",
            f"severity={highest}",
        ]
        if counts:
            parts.append(
                "[" + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)) + "]"
            )
        if top_fingerprints:
            parts.append(f"top={','.join(top_fingerprints)}")
        return {
            "active_incidents": len(incidents),
            "highest_severity": highest,
            "status": status,
            "counts": dict(counts),
            "top_fingerprints": top_fingerprints,
            "summary": " ".join(parts),
        }

    def prune_data(
        self,
        *,
        now: dt.datetime | None = None,
        system_event_days: int = 14,
        alert_days: int = 30,
        incident_days: int = 90,
        activity_days: int = 120,
        silence_days: int = 30,
    ) -> dict[str, Any]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        system_cutoff = (current - dt.timedelta(days=max(1, min(system_event_days, 365)))).isoformat()
        alert_cutoff = (current - dt.timedelta(days=max(1, min(alert_days, 365)))).isoformat()
        incident_cutoff = (current - dt.timedelta(days=max(1, min(incident_days, 730)))).isoformat()
        activity_cutoff = (current - dt.timedelta(days=max(1, min(activity_days, 730)))).isoformat()
        silence_cutoff = (current - dt.timedelta(days=max(1, min(silence_days, 365)))).isoformat()

        deleted = {
            "system_events": 0,
            "security_alerts": 0,
            "security_silences": 0,
            "incidents": 0,
            "incident_activity": 0,
        }
        preserved_active_incidents: list[str] = []
        preserved_alert_ids: list[int] = []

        with closing(self._conn()) as conn:
            with conn:
                active_rows = conn.execute(
                    f"""
                    SELECT incident_id, alert_ids_json
                    FROM incidents
                    WHERE status IN ({",".join("?" for _ in ACTIVE_INCIDENT_STATUSES)})
                    """
                    ,
                    sorted(ACTIVE_INCIDENT_STATUSES),
                ).fetchall()
                preserved_active_incidents = [str(row["incident_id"]) for row in active_rows]
                for row in active_rows:
                    preserved_alert_ids.extend(
                        self._decode_int_list(str(row["alert_ids_json"] or "[]"))
                    )

                if self._table_exists(conn, "system_events"):
                    deleted["system_events"] = conn.execute(
                        "DELETE FROM system_events WHERE ts_utc < ?",
                        (system_cutoff,),
                    ).rowcount

                deleted["security_silences"] = conn.execute(
                    """
                    DELETE FROM security_silences
                    WHERE silence_until_utc < ? AND created_at < ?
                    """,
                    (silence_cutoff, silence_cutoff),
                ).rowcount

                alert_params: list[Any] = [alert_cutoff]
                alert_sql = """
                    DELETE FROM security_alerts
                    WHERE ts_utc < ?
                      AND status <> 'new'
                """
                if preserved_alert_ids:
                    placeholders = ",".join("?" for _ in preserved_alert_ids)
                    alert_sql += f" AND id NOT IN ({placeholders})"
                    alert_params.extend(sorted(set(int(item) for item in preserved_alert_ids if int(item) > 0)))
                deleted["security_alerts"] = conn.execute(alert_sql, alert_params).rowcount

                incident_params: list[Any] = [incident_cutoff]
                incident_sql = """
                    DELETE FROM incidents
                    WHERE updated_at_utc < ?
                      AND status NOT IN ({})
                """.format(",".join("?" for _ in ACTIVE_INCIDENT_STATUSES))
                incident_params.extend(sorted(ACTIVE_INCIDENT_STATUSES))
                deleted["incidents"] = conn.execute(incident_sql, incident_params).rowcount

                activity_params: list[Any] = [activity_cutoff]
                activity_sql = """
                    DELETE FROM incident_activity
                    WHERE ts_utc < ?
                """
                if preserved_active_incidents:
                    placeholders = ",".join("?" for _ in preserved_active_incidents)
                    activity_sql += f" AND incident_id NOT IN ({placeholders})"
                    activity_params.extend(sorted(set(preserved_active_incidents)))
                deleted["incident_activity"] = conn.execute(activity_sql, activity_params).rowcount

                deleted["incident_activity"] += conn.execute(
                    """
                    DELETE FROM incident_activity
                    WHERE incident_id NOT IN (SELECT incident_id FROM incidents)
                    """,
                ).rowcount

        return {
            "ts_utc": current.isoformat(),
            "deleted": deleted,
            "preserved_active_incidents": sorted(set(preserved_active_incidents)),
            "preserved_alert_ids": sorted(set(int(item) for item in preserved_alert_ids if int(item) > 0)),
            "summary": (
                "Pruned retained watch data: "
                + ", ".join(f"{key}={value}" for key, value in deleted.items())
            ),
            "schema_version": self.schema_version(),
        }

    def record_incident_action(
        self,
        *,
        action_id: str,
        category: str = "all",
        severity: str = "all",
        fingerprint: str = "",
        unit: str = "",
        request_id: str = "",
        operator_id: str = "",
        dry_run: bool = False,
        success: bool = False,
        blocked: bool = False,
        command_error: str = "",
        outcome: str = "",
        now: dt.datetime | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        self._refresh_incident_ledger(now=current)
        rows = self._load_incident_rows(
            limit=20,
            status="active",
            category=category,
            severity=severity,
            fingerprint=fingerprint,
        )
        incident_rows = [
            row for row in rows if self._incident_matches_unit(row, unit=unit)
        ]
        if not incident_rows:
            return {
                "incidents_updated": 0,
                "incident_ids": [],
                "status": "none",
                "summary": "No active incident ledger rows matched this action.",
            }

        if blocked:
            decision = "containment_blocked"
        elif dry_run and success:
            decision = "containment_dry_run"
        elif success:
            decision = "contained"
        else:
            decision = "containment_failed"

        incident_ids: list[str] = []
        for row in incident_rows:
            incident_ids.append(str(row["incident_id"]))
            current_status = normalize_incident_status(str(row["status"]))
            next_status = current_status
            if success and not dry_run and action_id.startswith("service.systemctl."):
                next_status = "contained"
            self._update_incident_state(
                incident_id=str(row["incident_id"]),
                status=next_status,
                last_action_id=action_id,
                operator_decision=decision,
                resolution_summary=outcome if success or blocked else command_error or outcome,
                current=current,
            )
            self._append_incident_activity(
                incident_id=str(row["incident_id"]),
                current=current,
                status_from=current_status,
                status_to=next_status,
                action_id=action_id,
                operator_id=operator_id,
                request_id=request_id,
                operator_decision=decision,
                resolution_summary=outcome if success or blocked else command_error or outcome,
                payload={
                    "category": category,
                    "severity": severity,
                    "fingerprint": fingerprint,
                    "unit": unit,
                    "dry_run": dry_run,
                    "success": success,
                    "blocked": blocked,
                    "command_error": command_error,
                    "outcome": outcome,
                    "extra": extra or {},
                },
            )
        return {
            "incidents_updated": len(incident_ids),
            "incident_ids": incident_ids,
            "status": decision,
            "summary": f"Recorded action '{action_id}' against {len(incident_ids)} incident(s).",
        }

    def list_recent_alerts(
        self,
        *,
        limit: int = 10,
        window_hours: int = 24,
        category: str = "all",
        severity: str = "all",
        fingerprint: str = "",
        active_only: bool = False,
        now: dt.datetime | None = None,
    ) -> list[dict[str, Any]]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        cutoff = (current - dt.timedelta(hours=max(1, min(window_hours, 72)))).isoformat()
        where = "WHERE ts_utc >= ?"
        params: list[Any] = [cutoff]
        if category != "all":
            where += " AND category = ?"
            params.append(category)
        if severity != "all":
            where += " AND severity = ?"
            params.append(severity)
        if fingerprint:
            where += " AND fingerprint = ?"
            params.append(fingerprint)
        if active_only:
            where += " AND status = 'new'"
        limit_value = max(1, min(limit, 50))

        with closing(self._conn()) as conn:
            rows = conn.execute(
                f"""
                SELECT id, ts_utc, severity, category, fingerprint, summary, recommendation, status
                FROM security_alerts
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params + [limit_value],
            ).fetchall()
        return [dict(row) for row in rows]

    def validate_incident_containment(
        self,
        *,
        action_id: str,
        unit: str,
        category: str = "service",
        severity: str = "all",
        fingerprint: str = "",
        window_hours: int = 24,
        now: dt.datetime | None = None,
    ) -> dict[str, Any]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        self._refresh_incident_ledger(now=current, window_hours=window_hours)
        unit_key = (unit or "").strip().lower()
        if not unit_key:
            return {
                "allowed": False,
                "reason": "Incident containment requires an explicit systemd unit.",
                "matched_alerts": [],
                "derived_units": [],
            }

        category_key = (category or "service").strip().lower() or "service"
        action_key = (action_id or "").strip().lower()
        if category_key == "service":
            return self._validate_service_containment(
                action_id=action_key,
                unit=unit_key,
                severity=severity,
                fingerprint=fingerprint,
                window_hours=window_hours,
                now=current,
            )
        if category_key == "security":
            return self._validate_auth_containment(
                action_id=action_key,
                unit=unit_key,
                severity=severity,
                fingerprint=fingerprint,
                window_hours=window_hours,
                now=current,
            )
        if category_key == "network":
            return self._validate_network_containment(
                action_id=action_key,
                unit=unit_key,
                severity=severity,
                fingerprint=fingerprint,
                window_hours=window_hours,
                now=current,
            )
        return {
            "allowed": False,
            "reason": f"Automated containment is not supported for category '{category_key}'.",
            "matched_alerts": [],
            "derived_units": [],
        }

    def validate_service_containment(
        self,
        *,
        unit: str,
        category: str = "service",
        severity: str = "all",
        fingerprint: str = "",
        window_hours: int = 24,
        now: dt.datetime | None = None,
    ) -> dict[str, Any]:
        return self.validate_incident_containment(
            action_id="service.systemctl.restart",
            unit=unit,
            category=category,
            severity=severity,
            fingerprint=fingerprint,
            window_hours=window_hours,
            now=now,
        )

    def _validate_service_containment(
        self,
        *,
        action_id: str,
        unit: str,
        severity: str,
        fingerprint: str,
        window_hours: int,
        now: dt.datetime,
    ) -> dict[str, Any]:
        if action_id not in {"service.systemctl.restart", "service.systemctl.start", "service.systemctl.stop"}:
            return {
                "allowed": False,
                "reason": f"Unsupported service containment action '{action_id}'.",
                "matched_alerts": [],
                "derived_units": [],
            }
        alerts = self._load_active_alert_rows(
            category="service",
            severity=severity,
            fingerprint=fingerprint,
            window_hours=window_hours,
            now=now,
            limit=10,
        )
        if not alerts:
            scope = f"fingerprint '{fingerprint}'" if fingerprint else "service incidents"
            return {
                "allowed": False,
                "reason": f"No active {scope} matched this containment request.",
                "matched_alerts": [],
                "derived_units": [],
            }

        matched_alerts: list[dict[str, Any]] = []
        derived_units: set[str] = set()
        for row in alerts:
            units = self._derive_service_units_from_alert(row)
            derived_units.update(units)
            if unit in units:
                matched_alerts.append(dict(row))

        if not matched_alerts:
            known_units = ", ".join(sorted(derived_units)) or "none"
            return {
                "allowed": False,
                "reason": (
                    f"Active service incidents did not correlate the target unit '{unit}'. "
                    f"Derived impacted units: {known_units}."
                ),
                "matched_alerts": [],
                "derived_units": sorted(derived_units),
            }

        fingerprints = ", ".join(sorted({str(row['fingerprint']) for row in matched_alerts}))
        return {
            "allowed": True,
            "reason": (
                f"Matched active service incident(s) for '{unit}' via {fingerprints}. "
                "Containment may proceed with explicit approval."
            ),
            "matched_alerts": matched_alerts,
            "derived_units": sorted(derived_units),
        }

    def _validate_auth_containment(
        self,
        *,
        action_id: str,
        unit: str,
        severity: str,
        fingerprint: str,
        window_hours: int,
        now: dt.datetime,
    ) -> dict[str, Any]:
        if action_id != "service.systemctl.restart":
            return {
                "allowed": False,
                "reason": "Auth incident remediation is currently limited to restarting ssh.service.",
                "matched_alerts": [],
                "derived_units": [AUTH_CONTAINMENT_UNIT],
            }
        if unit != AUTH_CONTAINMENT_UNIT:
            return {
                "allowed": False,
                "reason": f"Auth incident remediation only supports '{AUTH_CONTAINMENT_UNIT}'.",
                "matched_alerts": [],
                "derived_units": [AUTH_CONTAINMENT_UNIT],
            }
        effective_fingerprint = fingerprint or "security.auth.anomaly"
        alerts = self._load_active_alert_rows(
            category="security",
            severity=severity,
            fingerprint=effective_fingerprint,
            window_hours=window_hours,
            now=now,
            limit=10,
        )
        if not alerts:
            return {
                "allowed": False,
                "reason": "No active authentication incident matched this remediation request.",
                "matched_alerts": [],
                "derived_units": [AUTH_CONTAINMENT_UNIT],
            }
        return {
            "allowed": True,
            "reason": (
                f"Matched active authentication incident(s) for '{AUTH_CONTAINMENT_UNIT}'. "
                "Remediation may proceed with explicit approval."
            ),
            "matched_alerts": [dict(row) for row in alerts],
            "derived_units": [AUTH_CONTAINMENT_UNIT],
        }

    def _validate_network_containment(
        self,
        *,
        action_id: str,
        unit: str,
        severity: str,
        fingerprint: str,
        window_hours: int,
        now: dt.datetime,
    ) -> dict[str, Any]:
        allowed_units = {canonical.lower() for canonical in NETWORK_CONTAINMENT_UNITS.values()}
        if action_id != "service.systemctl.restart":
            return {
                "allowed": False,
                "reason": "Network incident remediation is currently limited to restarting network stack services.",
                "matched_alerts": [],
                "derived_units": sorted(allowed_units),
            }
        if unit not in allowed_units:
            return {
                "allowed": False,
                "reason": (
                    "Network incident remediation only supports these units: "
                    + ", ".join(sorted(allowed_units))
                    + "."
                ),
                "matched_alerts": [],
                "derived_units": sorted(allowed_units),
            }
        effective_fingerprint = fingerprint or "network.instability"
        alerts = self._load_active_alert_rows(
            category="network",
            severity=severity,
            fingerprint=effective_fingerprint,
            window_hours=window_hours,
            now=now,
            limit=10,
        )
        if not alerts:
            return {
                "allowed": False,
                "reason": "No active network incident matched this remediation request.",
                "matched_alerts": [],
                "derived_units": sorted(allowed_units),
            }
        matched_alerts: list[dict[str, Any]] = []
        derived_units: set[str] = set()
        for row in alerts:
            units = self._derive_network_units_from_alert(row)
            derived_units.update(item.lower() for item in units)
            if unit in {item.lower() for item in units}:
                matched_alerts.append(dict(row))
        if not matched_alerts:
            known_units = ", ".join(sorted(derived_units)) or "none"
            return {
                "allowed": False,
                "reason": (
                    f"Active network incidents did not correlate the target unit '{unit}'. "
                    f"Derived impacted units: {known_units}."
                ),
                "matched_alerts": [],
                "derived_units": sorted(derived_units),
            }
        return {
            "allowed": True,
            "reason": (
                f"Matched active network incident(s) for '{unit}'. "
                "Remediation may proceed with explicit approval."
            ),
            "matched_alerts": matched_alerts,
            "derived_units": sorted(derived_units),
        }

    def acknowledge_alerts(
        self,
        *,
        alert_ids: list[int] | None = None,
        limit: int = 1,
        category: str = "all",
        severity: str = "all",
        fingerprint: str = "",
        operator_id: str = "",
        request_id: str = "",
        now: dt.datetime | None = None,
    ) -> dict[str, Any]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        rows = self._select_alert_rows(
            alert_ids=alert_ids or [],
            limit=limit,
            category=category,
            severity=severity,
            fingerprint=fingerprint,
            now=current,
        )
        if not rows:
            return {
                "acknowledged": 0,
                "alerts": [],
                "summary": "No matching security alerts found to acknowledge.",
            }
        alert_ids_resolved = [int(row["id"]) for row in rows]
        with closing(self._conn()) as conn:
            with conn:
                conn.executemany(
                    """
                    UPDATE security_alerts
                    SET status = 'acknowledged'
                    WHERE id = ?
                    """,
                    [(alert_id,) for alert_id in alert_ids_resolved],
                )
        alerts = [dict(row) for row in rows]
        summary = (
            f"Acknowledged {len(alerts)} security alert(s): "
            + " | ".join(f"#{row['id']}:{row['fingerprint']}" for row in alerts)
        )
        incident_update = self._close_incidents_for_alert_rows(
            rows,
            status="resolved",
            action_id="security.alerts.ack",
            operator_decision="acknowledged",
            resolution_summary=summary,
            operator_id=operator_id,
            request_id=request_id,
            current=current,
        )
        return {
            "acknowledged": len(alerts),
            "alerts": alerts,
            "summary": summary,
            "incident_update": incident_update,
        }

    def silence_alerts(
        self,
        *,
        alert_ids: list[int] | None = None,
        silence_hours: int = 6,
        limit: int = 1,
        category: str = "all",
        severity: str = "all",
        fingerprint: str = "",
        reason: str = "",
        operator_id: str = "",
        request_id: str = "",
        now: dt.datetime | None = None,
    ) -> dict[str, Any]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        rows = self._select_alert_rows(
            alert_ids=alert_ids or [],
            limit=limit,
            category=category,
            severity=severity,
            fingerprint=fingerprint,
            now=current,
        )
        if not rows:
            return {
                "silenced": 0,
                "fingerprints": [],
                "silence_until_utc": "",
                "summary": "No matching security alerts found to silence.",
            }
        silence_until = (current + dt.timedelta(hours=max(1, min(silence_hours, 168)))).isoformat()
        fingerprints = sorted({str(row["fingerprint"]) for row in rows})
        alert_ids_resolved = [int(row["id"]) for row in rows]
        note = (reason or "").strip()
        with closing(self._conn()) as conn:
            with conn:
                conn.executemany(
                    """
                    INSERT INTO security_silences (
                        fingerprint, reason, created_at, silence_until_utc, source
                    ) VALUES (?, ?, ?, ?, 'operator')
                    """,
                    [
                        (fingerprint, note, current.isoformat(), silence_until)
                        for fingerprint in fingerprints
                    ],
                )
                conn.executemany(
                    """
                    UPDATE security_alerts
                    SET status = 'silenced'
                    WHERE id = ?
                    """,
                    [(alert_id,) for alert_id in alert_ids_resolved],
                )
        summary = (
            f"Silenced {len(fingerprints)} security alert fingerprint(s) until {silence_until}: "
            + ", ".join(fingerprints)
        )
        incident_update = self._close_incidents_for_alert_rows(
            rows,
            status="dismissed",
            action_id="security.alerts.silence",
            operator_decision="silenced",
            resolution_summary=summary,
            operator_id=operator_id,
            request_id=request_id,
            current=current,
        )
        return {
            "silenced": len(fingerprints),
            "fingerprints": fingerprints,
            "silence_until_utc": silence_until,
            "alerts": [dict(row) for row in rows],
            "summary": summary,
            "incident_update": incident_update,
        }

    def active_alert_summary(
        self,
        *,
        window_hours: int = 24,
        now: dt.datetime | None = None,
    ) -> dict[str, Any]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        alerts = self.list_recent_alerts(
            limit=20,
            window_hours=window_hours,
            active_only=True,
            now=current,
        )
        highest = "none"
        if alerts:
            highest = max(
                (str(row["severity"]) for row in alerts),
                key=lambda value: SEVERITY_ORDER.get(value, 0),
            )
        status = STATUS_FROM_SEVERITY.get(highest, "stable")
        counts = Counter(str(row["severity"]) for row in alerts)
        counts_text = ", ".join(f"{key}={counts[key]}" for key in sorted(counts, key=lambda item: SEVERITY_ORDER.get(item, 0), reverse=True))
        top_fingerprints = list(dict.fromkeys(str(row["fingerprint"]) for row in alerts[:3]))
        summary = f"alerts=0 status={status}"
        if alerts:
            summary = f"alerts={len(alerts)} status={status} severity={highest}"
            if counts_text:
                summary += f" [{counts_text}]"
            if top_fingerprints:
                summary += f" top={','.join(top_fingerprints)}"
        return {
            "active_alerts": len(alerts),
            "highest_severity": highest,
            "status": status,
            "counts": dict(counts),
            "top_fingerprints": top_fingerprints,
            "summary": summary,
            "window_hours": max(1, min(window_hours, 72)),
        }

    def evaluate_alerts(
        self,
        *,
        now: dt.datetime | None = None,
        window_hours: int | None = None,
    ) -> list[SecurityAlertCandidate]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        rows = self._load_system_events(now=current, window_hours=window_hours or self.window_hours)
        return self._derive_alert_candidates(rows)

    def _run_event_sweep(self, *, current: dt.datetime, max_events: int) -> dict[str, Any]:
        if self.event_monitor is None:
            return {
                "scanned": False,
                "events_seen": 0,
                "relevant_events": 0,
                "invalidated_sources": [],
                "command_status": 0,
                "reason": "no_event_monitor",
            }
        result = self.event_monitor.sweep(now=current, max_events=max_events)
        return {
            "scanned": result.scanned,
            "events_seen": result.events_seen,
            "relevant_events": result.relevant_events,
            "invalidated_sources": list(result.invalidated_sources),
            "command_status": result.command_status,
            "reason": result.reason,
        }

    def _load_system_events(self, *, now: dt.datetime, window_hours: int) -> list[sqlite3.Row]:
        cutoff = (now - dt.timedelta(hours=max(1, min(window_hours, 72)))).isoformat()
        with closing(self._conn()) as conn:
            rows = conn.execute(
                """
                SELECT id, ts_utc, category, source, summary
                FROM system_events
                WHERE ts_utc >= ?
                ORDER BY id DESC
                """,
                (cutoff,),
            ).fetchall()
        return rows

    def _load_active_alert_rows(
        self,
        *,
        category: str,
        severity: str,
        fingerprint: str,
        window_hours: int,
        now: dt.datetime,
        limit: int,
    ) -> list[sqlite3.Row]:
        cutoff = (now - dt.timedelta(hours=max(1, min(window_hours, 72)))).isoformat()
        where = "WHERE ts_utc >= ? AND status = 'new'"
        params: list[Any] = [cutoff]
        category_key = (category or "all").strip().lower() or "all"
        severity_key = (severity or "all").strip().lower() or "all"
        fingerprint_key = (fingerprint or "").strip().lower()
        if category_key != "all":
            where += " AND category = ?"
            params.append(category_key)
        if severity_key != "all":
            where += " AND severity = ?"
            params.append(severity_key)
        if fingerprint_key:
            where += " AND fingerprint = ?"
            params.append(fingerprint_key)
        with closing(self._conn()) as conn:
            rows = conn.execute(
                f"""
                SELECT id, ts_utc, severity, category, fingerprint, summary, recommendation, status, event_ids_json
                FROM security_alerts
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params + [max(1, min(limit, 20))],
            ).fetchall()
        return rows

    @staticmethod
    def _filter_rows(rows: list[sqlite3.Row], category: str) -> list[sqlite3.Row]:
        category_key = (category or "all").strip().lower() or "all"
        if category_key == "all":
            return rows
        return [row for row in rows if str(row["category"]).strip().lower() == category_key]

    @staticmethod
    def _filter_alerts(alerts: list[SecurityAlertCandidate], category: str) -> list[SecurityAlertCandidate]:
        category_key = (category or "all").strip().lower() or "all"
        if category_key == "all":
            return alerts
        return [alert for alert in alerts if alert.category == category_key]

    def _derive_alert_candidates(self, rows: list[sqlite3.Row]) -> list[SecurityAlertCandidate]:
        if not rows:
            return []
        candidates: list[SecurityAlertCandidate] = []
        candidates.extend(self._auth_anomaly_alert(rows))
        candidates.extend(self._session_change_alert(rows))
        candidates.extend(self._service_failure_alert(rows))
        candidates.extend(self._network_instability_alert(rows))
        candidates.extend(self._device_change_alert(rows))
        candidates.sort(key=self._sort_key, reverse=True)
        return candidates

    def _recommendations_for_alert(
        self,
        row: sqlite3.Row,
        *,
        now: dt.datetime,
    ) -> list[dict[str, Any]]:
        category = str(row["category"])
        severity = str(row["severity"])
        fingerprint = str(row["fingerprint"])
        recommendations: list[dict[str, Any]] = [
            {
                "mode": "investigate",
                "action_id": "security.audit.recent_events",
                "args": {"category": category, "limit": "5"},
                "risk_level": "low",
                "requires_privilege": False,
                "fingerprint": fingerprint,
                "summary": f"Inspect recent {category} events before mutating the host.",
            },
            {
                "mode": "observe",
                "action_id": "security.vigilance.status",
                "args": {"category": category, "window_hours": "6"},
                "risk_level": "low",
                "requires_privilege": False,
                "fingerprint": fingerprint,
                "summary": "Refresh vigilance posture for the incident scope.",
            },
        ]

        if fingerprint == "service.failure.cluster":
            for unit in self._derive_service_units_from_alert(row)[:2]:
                recommendations.append(
                    {
                        "mode": "contain",
                        "action_id": "service.systemctl.restart",
                        "args": {
                            "unit": unit,
                            "category": "service",
                            "fingerprint": fingerprint,
                        },
                        "risk_level": "high" if severity in {"high", "critical"} else "medium",
                        "requires_privilege": True,
                        "fingerprint": fingerprint,
                        "summary": (
                            f"Restart {unit} only after validating it is the impacted service from the active incident."
                        ),
                    }
                )
        elif fingerprint == "security.auth.anomaly":
            recommendations.append(
                {
                    "mode": "remediate",
                    "action_id": "service.systemctl.restart",
                    "args": {
                        "unit": AUTH_CONTAINMENT_UNIT,
                        "category": "security",
                        "fingerprint": fingerprint,
                    },
                    "risk_level": "high",
                    "requires_privilege": True,
                    "fingerprint": fingerprint,
                    "summary": (
                        f"Restart {AUTH_CONTAINMENT_UNIT} only if the operator explicitly wants to recycle the SSH daemon."
                    ),
                }
            )
        elif fingerprint == "network.instability":
            for unit in self._derive_network_units_from_alert(row)[:2]:
                recommendations.append(
                    {
                        "mode": "remediate",
                        "action_id": "service.systemctl.restart",
                        "args": {
                            "unit": unit,
                            "category": "network",
                            "fingerprint": fingerprint,
                        },
                        "risk_level": "high" if severity in {"high", "critical"} else "medium",
                        "requires_privilege": True,
                        "fingerprint": fingerprint,
                        "summary": (
                            f"Restart {unit} only after confirming it matches the unstable network stack component."
                        ),
                    }
                )
        return recommendations

    def _auth_anomaly_alert(self, rows: list[sqlite3.Row]) -> list[SecurityAlertCandidate]:
        matched = [
            row
            for row in rows
            if str(row["category"]) == "security"
            and any(
                token in str(row["summary"] or "").lower()
                for token in (
                    "failed password",
                    "authentication failure",
                    "invalid user",
                    "not in sudoers",
                    "sudo: ",
                )
            )
        ]
        if not matched:
            return []
        summaries = " | ".join(str(row["summary"]) for row in matched[:2])
        severity = "critical" if any("root" in str(row["summary"]).lower() for row in matched) else "high"
        return [
            self._candidate(
                fingerprint="security.auth.anomaly",
                severity=severity,
                category="security",
                summary=f"Authentication anomalies detected ({len(matched)} event(s)): {summaries}",
                recommendation="Investigate authentication failures and validate whether access attempts were expected.",
                rows=matched,
            )
        ]

    def _session_change_alert(self, rows: list[sqlite3.Row]) -> list[SecurityAlertCandidate]:
        matched = [row for row in rows if str(row["source"]) == "dbus.login1"]
        if not matched:
            return []
        summaries = " | ".join(str(row["summary"]) for row in matched[:2])
        severity = "high" if any("root" in str(row["summary"]).lower() for row in matched) else "medium"
        return [
            self._candidate(
                fingerprint="security.session.change",
                severity=severity,
                category="security",
                summary=f"Login-session topology changed ({len(matched)} event(s)): {summaries}",
                recommendation="Review new or removed login sessions and confirm privileged sessions are legitimate.",
                rows=matched,
            )
        ]

    def _service_failure_alert(self, rows: list[sqlite3.Row]) -> list[SecurityAlertCandidate]:
        matched = [
            row
            for row in rows
            if str(row["category"]) == "service"
            and any(
                token in str(row["summary"] or "").lower()
                for token in ("failed", "restarting", "entered failed state")
            )
        ]
        if not matched:
            return []
        severity = "high" if len(matched) >= 3 else "medium"
        return [
            self._candidate(
                fingerprint="service.failure.cluster",
                severity=severity,
                category="service",
                summary=f"Service degradation detected ({len(matched)} failure-related event(s)).",
                recommendation="Inspect failed units and journal details before restarting or mutating services.",
                rows=matched,
            )
        ]

    def _network_instability_alert(self, rows: list[sqlite3.Row]) -> list[SecurityAlertCandidate]:
        matched = [row for row in rows if str(row["category"]) == "network"]
        if len(matched) < 3:
            return []
        severity = "high" if len(matched) >= 6 else "medium"
        return [
            self._candidate(
                fingerprint="network.instability",
                severity=severity,
                category="network",
                summary=f"Network instability pattern detected ({len(matched)} recent event(s)).",
                recommendation="Check routes, carrier status and DNS state before applying network changes.",
                rows=matched,
            )
        ]

    def _device_change_alert(self, rows: list[sqlite3.Row]) -> list[SecurityAlertCandidate]:
        matched = [row for row in rows if str(row["category"]) == "udev"]
        if not matched:
            return []
        severity = "medium" if len(matched) >= 2 else "low"
        return [
            self._candidate(
                fingerprint="device.topology.change",
                severity=severity,
                category="udev",
                summary=f"Device topology changed ({len(matched)} event(s)): {str(matched[0]['summary'])}",
                recommendation="Confirm recent interface, block-device or USB changes were expected on this host.",
                rows=matched,
            )
        ]

    @staticmethod
    def _candidate(
        *,
        fingerprint: str,
        severity: str,
        category: str,
        summary: str,
        recommendation: str,
        rows: list[sqlite3.Row],
    ) -> SecurityAlertCandidate:
        event_ids = tuple(sorted(int(row["id"]) for row in rows))
        sources = tuple(sorted({str(row["source"]) for row in rows}))
        return SecurityAlertCandidate(
            fingerprint=fingerprint,
            severity=severity,
            category=category,
            summary=summary,
            recommendation=recommendation,
            event_ids=event_ids,
            sources=sources,
            event_count=len(rows),
        )

    @staticmethod
    def _sort_key(alert: SecurityAlertCandidate) -> tuple[int, int]:
        return (SEVERITY_ORDER.get(alert.severity, 0), max(alert.event_ids or (0,)))

    def _store_alert(self, alert: SecurityAlertCandidate, *, current: dt.datetime) -> bool:
        if self._is_fingerprint_silenced(alert.fingerprint, current=current):
            return False
        cutoff = (current - dt.timedelta(minutes=self.dedupe_window_minutes)).isoformat()
        payload = json.dumps(asdict(alert), ensure_ascii=True, sort_keys=True)
        with closing(self._conn()) as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM security_alerts
                WHERE fingerprint = ? AND ts_utc >= ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (alert.fingerprint, cutoff),
            ).fetchone()
            if row is not None and str(row["payload_json"] or "") == payload:
                return False
            with conn:
                conn.execute(
                    """
                    INSERT INTO security_alerts (
                        ts_utc, severity, category, fingerprint, summary,
                        recommendation, source, status, event_ids_json, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, 'security-watch', 'new', ?, ?)
                    """,
                    (
                        current.isoformat(),
                        alert.severity,
                        alert.category,
                        alert.fingerprint,
                        alert.summary,
                        alert.recommendation,
                        json.dumps(list(alert.event_ids), ensure_ascii=True),
                        payload,
                    ),
                )
        return True

    def _load_incident_rows(
        self,
        *,
        limit: int,
        status: str,
        category: str,
        severity: str,
        fingerprint: str,
    ) -> list[sqlite3.Row]:
        status_key = (status or "active").strip().lower() or "active"
        category_key = (category or "all").strip().lower() or "all"
        severity_key = (severity or "all").strip().lower() or "all"
        fingerprint_key = (fingerprint or "").strip().lower()
        where: list[str] = []
        params: list[Any] = []
        if status_key == "active":
            placeholders = ",".join("?" for _ in ACTIVE_INCIDENT_STATUSES)
            where.append(f"status IN ({placeholders})")
            params.extend(sorted(ACTIVE_INCIDENT_STATUSES))
        elif status_key != "all":
            where.append("status = ?")
            params.append(status_key)
        if category_key != "all":
            where.append("category = ?")
            params.append(category_key)
        if severity_key != "all":
            where.append("severity = ?")
            params.append(severity_key)
        if fingerprint_key:
            where.append("fingerprint = ?")
            params.append(fingerprint_key)
        where_sql = ""
        if where:
            where_sql = "WHERE " + " AND ".join(where)
        with closing(self._conn()) as conn:
            return conn.execute(
                f"""
                SELECT incident_id, fingerprint, category, severity, status,
                       opened_at_utc, updated_at_utc, last_seen_at_utc, last_action_id,
                       operator_decision, resolution_summary, latest_summary,
                       alert_ids_json, event_ids_json, correlated_units_json
                FROM incidents
                {where_sql}
                ORDER BY updated_at_utc DESC, incident_id DESC
                LIMIT ?
                """,
                params + [max(1, min(limit, 50))],
            ).fetchall()

    def _load_incident_row_by_id(self, incident_id: str) -> sqlite3.Row | None:
        with closing(self._conn()) as conn:
            return conn.execute(
                """
                SELECT incident_id, fingerprint, category, severity, status,
                       opened_at_utc, updated_at_utc, last_seen_at_utc, last_action_id,
                       operator_decision, resolution_summary, latest_summary,
                       alert_ids_json, event_ids_json, correlated_units_json
                FROM incidents
                WHERE incident_id = ?
                LIMIT 1
                """,
                ((incident_id or "").strip().lower(),),
            ).fetchone()

    def _load_incident_activity_rows(self, incident_id: str, *, limit: int) -> list[dict[str, Any]]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                """
                SELECT ts_utc, status_from, status_to, action_id, operator_id,
                       request_id, operator_decision, resolution_summary, payload_json
                FROM incident_activity
                WHERE incident_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                ((incident_id or "").strip().lower(), max(1, min(limit, 20))),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"] or "{}"))
            except Exception:  # noqa: BLE001
                payload = {}
            out.append(
                {
                    "ts_utc": str(row["ts_utc"]),
                    "status_from": str(row["status_from"]),
                    "status_to": str(row["status_to"]),
                    "action_id": str(row["action_id"]),
                    "operator_id": str(row["operator_id"]),
                    "request_id": str(row["request_id"]),
                    "operator_decision": str(row["operator_decision"]),
                    "resolution_summary": str(row["resolution_summary"]),
                    "payload": payload,
                }
            )
        return out

    def _load_alert_rows_for_ids(self, alert_ids: list[int]) -> list[dict[str, Any]]:
        cleaned = [int(item) for item in alert_ids if int(item) > 0]
        if not cleaned:
            return []
        placeholders = ",".join("?" for _ in cleaned)
        with closing(self._conn()) as conn:
            rows = conn.execute(
                f"""
                SELECT id, ts_utc, severity, category, fingerprint, summary, recommendation, status
                FROM security_alerts
                WHERE id IN ({placeholders})
                ORDER BY id DESC
                """,
                cleaned,
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _decode_int_list(raw: str) -> tuple[int, ...]:
        try:
            data = json.loads(raw or "[]")
        except Exception:  # noqa: BLE001
            return ()
        if not isinstance(data, list):
            return ()
        out = []
        for item in data:
            if isinstance(item, int) or str(item).isdigit():
                out.append(int(item))
        return tuple(sorted(set(out)))

    @staticmethod
    def _decode_text_list(raw: str) -> tuple[str, ...]:
        try:
            data = json.loads(raw or "[]")
        except Exception:  # noqa: BLE001
            return ()
        if not isinstance(data, list):
            return ()
        return tuple(sorted({str(item).strip().lower() for item in data if str(item).strip()}))

    def _row_to_incident(self, row: sqlite3.Row) -> IncidentRecord:
        return IncidentRecord(
            incident_id=str(row["incident_id"]),
            fingerprint=str(row["fingerprint"]),
            category=str(row["category"]),
            severity=str(row["severity"]),
            status=normalize_incident_status(str(row["status"])),
            opened_at_utc=str(row["opened_at_utc"]),
            updated_at_utc=str(row["updated_at_utc"]),
            last_seen_at_utc=str(row["last_seen_at_utc"]),
            last_action_id=str(row["last_action_id"] or ""),
            operator_decision=str(row["operator_decision"] or ""),
            resolution_summary=str(row["resolution_summary"] or ""),
            latest_summary=str(row["latest_summary"] or ""),
            alert_ids=self._decode_int_list(str(row["alert_ids_json"] or "[]")),
            event_ids=self._decode_int_list(str(row["event_ids_json"] or "[]")),
            correlated_units=self._decode_text_list(str(row["correlated_units_json"] or "[]")),
        )

    def _refresh_incident_ledger(
        self,
        *,
        now: dt.datetime,
        window_hours: int = 72,
    ) -> None:
        cutoff = (now - dt.timedelta(hours=max(1, min(window_hours, 168)))).isoformat()
        with closing(self._conn()) as conn:
            rows = conn.execute(
                """
                SELECT id, ts_utc, severity, category, fingerprint, summary, recommendation,
                       status, event_ids_json, payload_json
                FROM security_alerts
                WHERE ts_utc >= ? AND status = 'new'
                ORDER BY ts_utc ASC, id ASC
                """,
                (cutoff,),
            ).fetchall()
        grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in rows:
            key = (str(row["fingerprint"]), str(row["category"]))
            grouped.setdefault(key, []).append(row)
        for alert_rows in grouped.values():
            self._upsert_incident_from_alert_rows(alert_rows=alert_rows, current=now)

    def _upsert_incident_from_alert_rows(
        self,
        *,
        alert_rows: list[sqlite3.Row],
        current: dt.datetime,
    ) -> None:
        if not alert_rows:
            return
        fingerprint = str(alert_rows[-1]["fingerprint"])
        category = str(alert_rows[-1]["category"])
        severity = max(
            (str(row["severity"]) for row in alert_rows),
            key=lambda value: SEVERITY_ORDER.get(value, 0),
        )
        alert_ids = sorted({int(row["id"]) for row in alert_rows})
        event_ids: set[int] = set()
        for row in alert_rows:
            event_ids.update(self._event_ids_from_alert(row))
        units = self._incident_units_for_alert_rows(alert_rows)
        latest_row = max(alert_rows, key=lambda row: (str(row["ts_utc"]), int(row["id"])))
        existing = self._find_active_incident_row(fingerprint=fingerprint, category=category)
        if existing is None:
            incident_id = f"inc-{uuid.uuid4().hex[:12]}"
            opened_at = str(alert_rows[0]["ts_utc"])
            with closing(self._conn()) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO incidents (
                            incident_id, fingerprint, category, severity, status,
                            opened_at_utc, updated_at_utc, last_seen_at_utc, last_action_id,
                            operator_decision, resolution_summary, latest_summary,
                            alert_ids_json, event_ids_json, correlated_units_json, metadata_json
                        ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?, '', '', '', ?, ?, ?, ?, '{}')
                        """,
                        (
                            incident_id,
                            fingerprint,
                            category,
                            severity,
                            opened_at,
                            current.isoformat(),
                            current.isoformat(),
                            str(latest_row["summary"]),
                            json.dumps(alert_ids, ensure_ascii=True),
                            json.dumps(sorted(event_ids), ensure_ascii=True),
                            json.dumps(units, ensure_ascii=True),
                        ),
                    )
            self._append_incident_activity(
                incident_id=incident_id,
                current=current,
                status_from="",
                status_to="open",
                action_id="security.watch.open",
                operator_id="security-watch",
                request_id="",
                operator_decision="opened",
                resolution_summary=str(latest_row["summary"]),
                payload={
                    "fingerprint": fingerprint,
                    "category": category,
                    "severity": severity,
                    "alert_ids": alert_ids,
                    "event_ids": sorted(event_ids),
                    "correlated_units": units,
                },
            )
            return

        incident = self._row_to_incident(existing)
        merged_alert_ids = sorted(set(incident.alert_ids).union(alert_ids))
        merged_event_ids = sorted(set(incident.event_ids).union(event_ids))
        merged_units = sorted(set(incident.correlated_units).union(units))
        next_severity = max(
            [incident.severity, severity],
            key=lambda value: SEVERITY_ORDER.get(value, 0),
        )
        with closing(self._conn()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE incidents
                    SET severity = ?,
                        updated_at_utc = ?,
                        last_seen_at_utc = ?,
                        latest_summary = ?,
                        alert_ids_json = ?,
                        event_ids_json = ?,
                        correlated_units_json = ?
                    WHERE incident_id = ?
                    """,
                    (
                        next_severity,
                        current.isoformat(),
                        current.isoformat(),
                        str(latest_row["summary"]),
                        json.dumps(merged_alert_ids, ensure_ascii=True),
                        json.dumps(merged_event_ids, ensure_ascii=True),
                        json.dumps(merged_units, ensure_ascii=True),
                        incident.incident_id,
                    ),
                )

    def _find_active_incident_row(self, *, fingerprint: str, category: str) -> sqlite3.Row | None:
        placeholders = ",".join("?" for _ in ACTIVE_INCIDENT_STATUSES)
        with closing(self._conn()) as conn:
            return conn.execute(
                f"""
                SELECT incident_id, fingerprint, category, severity, status,
                       opened_at_utc, updated_at_utc, last_seen_at_utc, last_action_id,
                       operator_decision, resolution_summary, latest_summary,
                       alert_ids_json, event_ids_json, correlated_units_json
                FROM incidents
                WHERE fingerprint = ? AND category = ? AND status IN ({placeholders})
                ORDER BY updated_at_utc DESC
                LIMIT 1
                """,
                [fingerprint, category, *sorted(ACTIVE_INCIDENT_STATUSES)],
            ).fetchone()

    def _incident_units_for_alert_rows(self, rows: list[sqlite3.Row]) -> list[str]:
        units: set[str] = set()
        for row in rows:
            category = str(row["category"])
            if category == "service":
                units.update(self._derive_service_units_from_alert(row))
            elif category == "network":
                units.update(item.lower() for item in self._derive_network_units_from_alert(row))
            elif category == "security":
                units.add(AUTH_CONTAINMENT_UNIT)
        return sorted(item.lower() for item in units if item)

    def _update_incident_state(
        self,
        *,
        incident_id: str,
        status: str,
        last_action_id: str,
        operator_decision: str,
        resolution_summary: str,
        current: dt.datetime,
    ) -> None:
        with closing(self._conn()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE incidents
                    SET status = ?,
                        updated_at_utc = ?,
                        last_seen_at_utc = ?,
                        last_action_id = ?,
                        operator_decision = ?,
                        resolution_summary = ?
                    WHERE incident_id = ?
                    """,
                    (
                        normalize_incident_status(status),
                        current.isoformat(),
                        current.isoformat(),
                        last_action_id,
                        operator_decision,
                        resolution_summary,
                        incident_id,
                    ),
                )

    def _append_incident_activity(
        self,
        *,
        incident_id: str,
        current: dt.datetime,
        status_from: str,
        status_to: str,
        action_id: str,
        operator_id: str,
        request_id: str,
        operator_decision: str,
        resolution_summary: str,
        payload: dict[str, Any],
    ) -> None:
        with closing(self._conn()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO incident_activity (
                        incident_id, ts_utc, status_from, status_to, action_id,
                        operator_id, request_id, operator_decision, resolution_summary, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        incident_id,
                        current.isoformat(),
                        status_from,
                        status_to,
                        action_id,
                        operator_id,
                        request_id,
                        operator_decision,
                        resolution_summary,
                        json.dumps(payload, ensure_ascii=True, sort_keys=True),
                    ),
                )

    def _close_incidents_for_alert_rows(
        self,
        rows: list[sqlite3.Row],
        *,
        status: str,
        action_id: str,
        operator_decision: str,
        resolution_summary: str,
        operator_id: str,
        request_id: str,
        current: dt.datetime,
    ) -> dict[str, Any]:
        self._refresh_incident_ledger(now=current)
        incident_ids: list[str] = []
        for row in rows:
            fingerprint = str(row["fingerprint"])
            category = str(row["category"])
            existing = self._find_active_incident_row(fingerprint=fingerprint, category=category)
            if existing is None:
                continue
            if self._remaining_active_alert_count(fingerprint=fingerprint, category=category) > 0:
                self._append_incident_activity(
                    incident_id=str(existing["incident_id"]),
                    current=current,
                    status_from=str(existing["status"]),
                    status_to=str(existing["status"]),
                    action_id=action_id,
                    operator_id=operator_id,
                    request_id=request_id,
                    operator_decision=operator_decision,
                    resolution_summary=resolution_summary,
                    payload={"alert_id": int(row["id"]), "scope_kept_open": True},
                )
                continue
            current_status = normalize_incident_status(str(existing["status"]))
            self._update_incident_state(
                incident_id=str(existing["incident_id"]),
                status=status,
                last_action_id=action_id,
                operator_decision=operator_decision,
                resolution_summary=resolution_summary,
                current=current,
            )
            self._append_incident_activity(
                incident_id=str(existing["incident_id"]),
                current=current,
                status_from=current_status,
                status_to=status,
                action_id=action_id,
                operator_id=operator_id,
                request_id=request_id,
                operator_decision=operator_decision,
                resolution_summary=resolution_summary,
                payload={"alert_id": int(row["id"])},
            )
            incident_ids.append(str(existing["incident_id"]))
        return {
            "incidents_updated": len(sorted(set(incident_ids))),
            "incident_ids": sorted(set(incident_ids)),
            "status": status,
        }

    def _remaining_active_alert_count(self, *, fingerprint: str, category: str) -> int:
        with closing(self._conn()) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM security_alerts
                WHERE fingerprint = ? AND category = ? AND status = 'new'
                """,
                (fingerprint, category),
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def _set_alert_rows_acknowledged(self, alert_ids: list[int]) -> None:
        cleaned = [int(item) for item in alert_ids if int(item) > 0]
        if not cleaned:
            return
        with closing(self._conn()) as conn:
            with conn:
                conn.executemany(
                    """
                    UPDATE security_alerts
                    SET status = CASE WHEN status = 'new' THEN 'acknowledged' ELSE status END
                    WHERE id = ?
                    """,
                    [(alert_id,) for alert_id in cleaned],
                )

    @staticmethod
    def _incident_matches_unit(row: sqlite3.Row, *, unit: str) -> bool:
        unit_key = (unit or "").strip().lower()
        if not unit_key:
            return True
        correlated_units = SecurityWatchEngine._decode_text_list(str(row["correlated_units_json"] or "[]"))
        if not correlated_units:
            return True
        return unit_key in correlated_units

    def _select_alert_rows(
        self,
        *,
        alert_ids: list[int],
        limit: int,
        category: str,
        severity: str,
        fingerprint: str,
        now: dt.datetime,
    ) -> list[sqlite3.Row]:
        alert_ids = [int(item) for item in alert_ids if int(item) > 0]
        category_key = (category or "all").strip().lower() or "all"
        severity_key = (severity or "all").strip().lower() or "all"
        fingerprint_key = (fingerprint or "").strip().lower()
        with closing(self._conn()) as conn:
            if alert_ids:
                placeholders = ",".join("?" for _ in alert_ids)
                params: list[Any] = list(alert_ids)
                where = f"WHERE id IN ({placeholders})"
                if category_key != "all":
                    where += " AND category = ?"
                    params.append(category_key)
                if severity_key != "all":
                    where += " AND severity = ?"
                    params.append(severity_key)
                if fingerprint_key:
                    where += " AND fingerprint = ?"
                    params.append(fingerprint_key)
                rows = conn.execute(
                    f"""
                    SELECT id, ts_utc, severity, category, fingerprint, summary, recommendation, status
                    FROM security_alerts
                    {where}
                    ORDER BY id DESC
                    """,
                    params,
                ).fetchall()
                return rows

            cutoff = (now - dt.timedelta(hours=72)).isoformat()
            params = [cutoff]
            where = "WHERE ts_utc >= ? AND status <> 'silenced'"
            if category_key != "all":
                where += " AND category = ?"
                params.append(category_key)
            if severity_key != "all":
                where += " AND severity = ?"
                params.append(severity_key)
            if fingerprint_key:
                where += " AND fingerprint = ?"
                params.append(fingerprint_key)
            rows = conn.execute(
                f"""
                SELECT id, ts_utc, severity, category, fingerprint, summary, recommendation, status
                FROM security_alerts
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params + [max(1, min(limit, 20))],
            ).fetchall()
            return rows

    def _is_fingerprint_silenced(self, fingerprint: str, *, current: dt.datetime) -> bool:
        with closing(self._conn()) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM security_silences
                WHERE fingerprint = ? AND silence_until_utc >= ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (fingerprint, current.isoformat()),
            ).fetchone()
        return row is not None

    @staticmethod
    def _event_ids_from_alert(row: sqlite3.Row) -> list[int]:
        try:
            raw = json.loads(str(row["event_ids_json"] or "[]"))
        except Exception:  # noqa: BLE001
            return []
        if not isinstance(raw, list):
            return []
        return [int(item) for item in raw if isinstance(item, int) or str(item).isdigit()]

    def _load_event_rows_for_ids(self, event_ids: list[int]) -> list[sqlite3.Row]:
        cleaned = [int(item) for item in event_ids if int(item) > 0]
        if not cleaned:
            return []
        placeholders = ",".join("?" for _ in cleaned)
        with closing(self._conn()) as conn:
            rows = conn.execute(
                f"""
                SELECT id, category, source, summary
                FROM system_events
                WHERE id IN ({placeholders})
                ORDER BY id DESC
                """,
                cleaned,
            ).fetchall()
        return rows

    def _derive_service_units_from_alert(self, row: sqlite3.Row) -> list[str]:
        units: set[str] = set()
        for event in self._load_event_rows_for_ids(self._event_ids_from_alert(row)):
            summary = str(event["summary"] or "").lower()
            for match in re.finditer(r"\b([a-z0-9@_.:-]+\.service)\b", summary):
                units.add(match.group(1))
            if str(event["source"]).lower() in {"systemd", "systemctl"}:
                source_summary = str(event["summary"] or "")
                if ".service" in source_summary.lower():
                    for match in re.finditer(r"\b([A-Za-z0-9@_.:-]+\.service)\b", source_summary):
                        units.add(match.group(1).lower())
        return sorted(units)

    def _derive_network_units_from_alert(self, row: sqlite3.Row) -> list[str]:
        units: set[str] = set()
        for event in self._load_event_rows_for_ids(self._event_ids_from_alert(row)):
            source = str(event["source"] or "").lower()
            summary = str(event["summary"] or "").lower()
            for token, canonical in NETWORK_CONTAINMENT_UNITS.items():
                if token in source or token in summary:
                    units.add(canonical)
        return sorted(units)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time

    parser = argparse.ArgumentParser(description="Run MasterControl local security watch.")
    parser.add_argument("--db-path", default="", help="SQLite DB path (defaults to ~/.local/share/mastercontrol/mastercontrol.db)")
    parser.add_argument("--window-hours", type=int, default=6, help="Event window for alert correlation.")
    parser.add_argument("--dedupe-minutes", type=int, default=30, help="Suppress identical alert payloads within this window.")
    parser.add_argument("--interval-sec", type=int, default=120, help="Sleep interval for --loop mode.")
    parser.add_argument("--max-events", type=int, default=64, help="Maximum journald events per sweep.")
    parser.add_argument("--loop", action="store_true", help="Keep running periodically instead of exiting after one sweep.")
    parser.add_argument("--prune", action="store_true", help="Prune retained watch data after each sweep.")
    parser.add_argument("--prune-only", action="store_true", help="Prune retained watch data and exit.")
    parser.add_argument("--system-event-retention-days", type=int, default=14, help="Retention window for system_events rows.")
    parser.add_argument("--alert-retention-days", type=int, default=30, help="Retention window for closed or acknowledged alerts.")
    parser.add_argument("--incident-retention-days", type=int, default=90, help="Retention window for non-active incidents.")
    parser.add_argument("--activity-retention-days", type=int, default=120, help="Retention window for incident activity rows.")
    parser.add_argument("--silence-retention-days", type=int, default=30, help="Retention window for expired silence rows.")
    args = parser.parse_args(argv)

    db_path = Path(args.db_path).expanduser() if args.db_path else default_db_path()
    store = SQLiteContextStore(db_path)
    event_monitor = SystemEventMonitor(db_path=db_path, store=store)
    engine = SecurityWatchEngine(
        db_path=db_path,
        event_monitor=event_monitor,
        window_hours=args.window_hours,
        dedupe_window_minutes=args.dedupe_minutes,
    )

    def _prune_payload() -> dict[str, Any]:
        return engine.prune_data(
            system_event_days=args.system_event_retention_days,
            alert_days=args.alert_retention_days,
            incident_days=args.incident_retention_days,
            activity_days=args.activity_retention_days,
            silence_days=args.silence_retention_days,
        )

    if args.prune_only:
        print(json.dumps(_prune_payload(), ensure_ascii=True, sort_keys=True))
        return 0

    while True:
        result = engine.run_once(max_events=args.max_events)
        payload = asdict(result)
        payload["alerts"] = [asdict(alert) for alert in result.alerts]
        payload["schema_version"] = engine.schema_version()
        if args.prune:
            payload["prune"] = _prune_payload()
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        if not args.loop:
            return 0
        time.sleep(max(args.interval_sec, 5))


if __name__ == "__main__":
    raise SystemExit(main())
