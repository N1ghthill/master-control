#!/usr/bin/env python3
"""Incremental system event monitoring for context invalidation."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mastercontrol.context.contextd import CommandRunner, ContextStore, default_command_runner
from mastercontrol.contracts import parse_utc, utc_now


@dataclass(frozen=True)
class SystemEvent:
    cursor: str
    ts_utc: str
    category: str
    source: str
    summary: str
    invalidated_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventSweepResult:
    scanned: bool
    events_seen: int = 0
    relevant_events: int = 0
    invalidated_sources: tuple[str, ...] = ()
    command_status: int = 0
    reason: str = ""


class SystemEventMonitor:
    """Scans journald incrementally and invalidates affected context snapshots."""

    SELF_EVENT_UNITS = {
        "mastercontrol-security-watch.service",
        "mastercontrol-privilege-broker.service",
    }
    SELF_EVENT_IDENTIFIERS = {
        "mc-security-watch",
        "mc-privilege-broker",
        "mastercontrol",
    }

    def __init__(
        self,
        db_path: Path,
        store: ContextStore,
        *,
        runner: CommandRunner | None = None,
        monitor_id: str = "journal.core",
        min_interval_s: int = 15,
        bootstrap_lookback_s: int = 300,
        udev_interval_s: int = 90,
        dbus_interval_s: int = 45,
    ) -> None:
        self.db_path = db_path
        self.store = store
        self.runner = runner or default_command_runner
        self.monitor_id = monitor_id
        self.min_interval_s = max(min_interval_s, 0)
        self.bootstrap_lookback_s = max(bootstrap_lookback_s, 30)
        self.udev_interval_s = max(udev_interval_s, self.min_interval_s)
        self.dbus_interval_s = max(dbus_interval_s, self.min_interval_s)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._conn()) as conn:
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS event_monitor_state (
                        monitor_id TEXT PRIMARY KEY,
                        last_cursor TEXT NOT NULL DEFAULT '',
                        last_run_utc TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS system_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        monitor_id TEXT NOT NULL,
                        cursor TEXT,
                        ts_utc TEXT NOT NULL,
                        category TEXT NOT NULL,
                        source TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        invalidated_sources_json TEXT NOT NULL,
                        raw_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_system_events_ts
                    ON system_events (ts_utc DESC);

                    CREATE TABLE IF NOT EXISTS event_source_state (
                        source_id TEXT PRIMARY KEY,
                        state_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )

    def sweep(
        self,
        *,
        now: dt.datetime | None = None,
        max_events: int = 64,
        min_interval_s: int | None = None,
    ) -> EventSweepResult:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        interval = self.min_interval_s if min_interval_s is None else max(min_interval_s, 0)
        state = self._load_state()
        last_run_utc = str(state["last_run_utc"]).strip()
        if last_run_utc:
            elapsed = current - parse_utc(last_run_utc)
            if elapsed.total_seconds() < interval:
                return EventSweepResult(
                    scanned=False,
                    command_status=0,
                    reason="min_interval_not_elapsed",
                )

        command = self._build_command(
            current=current,
            last_cursor=str(state["last_cursor"]).strip(),
            max_events=max(max_events, 1),
        )
        result = self.runner(command, 5)
        if result.returncode != 0:
            self._save_state(
                last_cursor=str(state["last_cursor"]).strip(),
                last_run_utc=current.isoformat(),
                updated_at=current.isoformat(),
            )
            return EventSweepResult(
                scanned=False,
                command_status=result.returncode,
                reason=result.stderr or "journal_scan_failed",
            )

        raw_entries = self._parse_json_lines(result.stdout)
        classified: list[tuple[dict[str, Any], SystemEvent]] = []
        invalidated: set[str] = set()
        last_cursor = str(state["last_cursor"]).strip()
        for entry in raw_entries:
            cursor = str(entry.get("__CURSOR", "")).strip()
            if cursor:
                last_cursor = cursor
            event = self._classify_event(entry)
            if event is None:
                continue
            classified.append((entry, event))
            invalidated.update(event.invalidated_sources)

        for entry, event in classified:
            self._record_event(event, entry)

        udev_events = self._sweep_udev_changes(current)
        for entry, event in udev_events:
            classified.append((entry, event))
            invalidated.update(event.invalidated_sources)
            self._record_event(event, entry)

        dbus_events = self._sweep_login1_sessions(current)
        for entry, event in dbus_events:
            classified.append((entry, event))
            invalidated.update(event.invalidated_sources)
            self._record_event(event, entry)

        invalidated_sources = tuple(sorted(invalidated))
        if invalidated_sources:
            self.store.invalidate_sources(list(invalidated_sources))

        self._save_state(
            last_cursor=last_cursor,
            last_run_utc=current.isoformat(),
            updated_at=current.isoformat(),
        )
        return EventSweepResult(
            scanned=True,
            events_seen=len(raw_entries),
            relevant_events=len(classified),
            invalidated_sources=invalidated_sources,
            command_status=result.returncode,
            reason="ok",
        )

    def _load_state(self) -> dict[str, str]:
        with closing(self._conn()) as conn:
            row = conn.execute(
                """
                SELECT monitor_id, last_cursor, last_run_utc
                FROM event_monitor_state
                WHERE monitor_id = ?
                """,
                (self.monitor_id,),
            ).fetchone()
        if row is not None:
            return {
                "monitor_id": str(row["monitor_id"] or self.monitor_id),
                "last_cursor": str(row["last_cursor"] or ""),
                "last_run_utc": str(row["last_run_utc"] or ""),
            }
        return {
            "monitor_id": self.monitor_id,
            "last_cursor": "",
            "last_run_utc": "",
        }

    def _save_state(self, *, last_cursor: str, last_run_utc: str, updated_at: str | None = None) -> None:
        updated = updated_at or utc_now()
        with closing(self._conn()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO event_monitor_state (monitor_id, last_cursor, last_run_utc, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(monitor_id) DO UPDATE SET
                        last_cursor=excluded.last_cursor,
                        last_run_utc=excluded.last_run_utc,
                        updated_at=excluded.updated_at
                    """,
                    (self.monitor_id, last_cursor, last_run_utc, updated),
                )

    def _load_source_state(self, source_id: str) -> tuple[dict[str, Any] | None, str]:
        with closing(self._conn()) as conn:
            row = conn.execute(
                """
                SELECT state_json, updated_at
                FROM event_source_state
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchone()
        if row is None:
            return None, ""
        try:
            payload = json.loads(str(row["state_json"] or "{}"))
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return payload, str(row["updated_at"] or "")

    def _save_source_state(
        self,
        source_id: str,
        payload: dict[str, Any],
        *,
        updated_at: str | None = None,
    ) -> None:
        updated = updated_at or utc_now()
        with closing(self._conn()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO event_source_state (source_id, state_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(source_id) DO UPDATE SET
                        state_json=excluded.state_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        source_id,
                        json.dumps(payload, ensure_ascii=True, sort_keys=True),
                        updated,
                    ),
                )

    def _build_command(self, *, current: dt.datetime, last_cursor: str, max_events: int) -> list[str]:
        command = ["journalctl", "--no-pager", "-o", "json", "-n", str(max_events)]
        if last_cursor:
            command.extend(["--after-cursor", last_cursor])
            return command
        since = current - dt.timedelta(seconds=self.bootstrap_lookback_s)
        command.extend(["--since", since.isoformat(timespec="seconds")])
        return command

    @staticmethod
    def _parse_json_lines(stdout: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                entries.append(value)
        return entries

    def _record_event(self, event: SystemEvent, raw_entry: dict[str, Any]) -> None:
        with closing(self._conn()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO system_events (
                        monitor_id, cursor, ts_utc, category, source, summary,
                        invalidated_sources_json, raw_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.monitor_id,
                        event.cursor or None,
                        event.ts_utc,
                        event.category,
                        event.source,
                        event.summary,
                        json.dumps(list(event.invalidated_sources), ensure_ascii=True),
                        json.dumps(raw_entry, ensure_ascii=True, sort_keys=True),
                        utc_now(),
                    ),
                )

    def _sweep_udev_changes(self, current: dt.datetime) -> list[tuple[dict[str, Any], SystemEvent]]:
        previous_state, updated_at = self._load_source_state("udev.export_db")
        if updated_at:
            elapsed = current - parse_utc(updated_at)
            if elapsed.total_seconds() < self.udev_interval_s:
                return []

        result = self.runner(["udevadm", "info", "--export-db"], 5)
        if result.returncode != 0:
            return []

        current_state = self._parse_udev_export_db(result.stdout)
        self._save_source_state(
            "udev.export_db",
            current_state,
            updated_at=current.isoformat(),
        )
        if previous_state is None or current_state == previous_state:
            return []

        previous_net = set(previous_state.get("net", []))
        current_net = set(current_state.get("net", []))
        previous_block = set(previous_state.get("block", []))
        current_block = set(current_state.get("block", []))
        previous_usb = set(previous_state.get("usb", []))
        current_usb = set(current_state.get("usb", []))

        invalidated: set[str] = set()
        changes: list[str] = []
        if previous_net != current_net:
            invalidated.update({"network.summary", "host.system"})
            changes.append(
                "net:" + ",".join(sorted(current_net)) if current_net else "net:empty"
            )
        if previous_block != current_block:
            invalidated.add("host.system")
            changes.append(
                "block:" + ",".join(sorted(current_block)) if current_block else "block:empty"
            )
        if previous_usb != current_usb:
            invalidated.add("host.system")
            changes.append(
                "usb:" + ",".join(sorted(current_usb)) if current_usb else "usb:empty"
            )
        if not invalidated:
            return []

        event = SystemEvent(
            cursor="",
            ts_utc=current.isoformat(),
            category="udev",
            source="udevadm",
            summary="udev topology changed: " + "; ".join(changes),
            invalidated_sources=tuple(sorted(invalidated)),
        )
        raw_entry = {
            "source": "udevadm",
            "previous_state": previous_state,
            "current_state": current_state,
        }
        return [(raw_entry, event)]

    def _sweep_login1_sessions(self, current: dt.datetime) -> list[tuple[dict[str, Any], SystemEvent]]:
        previous_state, updated_at = self._load_source_state("dbus.login1.sessions")
        if updated_at:
            elapsed = current - parse_utc(updated_at)
            if elapsed.total_seconds() < self.dbus_interval_s:
                return []

        current_state = self._load_login1_session_state()
        if current_state is None:
            return []

        self._save_source_state(
            "dbus.login1.sessions",
            current_state,
            updated_at=current.isoformat(),
        )
        if previous_state is None or current_state == previous_state:
            return []

        previous_sessions = {
            str(item.get("session", "")): item
            for item in previous_state.get("sessions", [])
            if isinstance(item, dict) and item.get("session")
        }
        current_sessions = {
            str(item.get("session", "")): item
            for item in current_state.get("sessions", [])
            if isinstance(item, dict) and item.get("session")
        }

        added = sorted(session_id for session_id in current_sessions if session_id not in previous_sessions)
        removed = sorted(session_id for session_id in previous_sessions if session_id not in current_sessions)
        changed = sorted(
            session_id
            for session_id in current_sessions
            if session_id in previous_sessions and current_sessions[session_id] != previous_sessions[session_id]
        )
        if not added and not removed and not changed:
            return []

        changes: list[str] = []
        if added:
            changes.append("added=" + ",".join(self._session_label(current_sessions[item]) for item in added[:4]))
        if removed:
            changes.append("removed=" + ",".join(self._session_label(previous_sessions[item]) for item in removed[:4]))
        if changed:
            changes.append("changed=" + ",".join(self._session_label(current_sessions[item]) for item in changed[:4]))

        event = SystemEvent(
            cursor="",
            ts_utc=current.isoformat(),
            category="security",
            source="dbus.login1",
            summary="login1 sessions changed: " + "; ".join(changes),
            invalidated_sources=("journal.alerts",),
        )
        raw_entry = {
            "source": "dbus.login1",
            "previous_state": previous_state,
            "current_state": current_state,
        }
        return [(raw_entry, event)]

    def _load_login1_session_state(self) -> dict[str, Any] | None:
        busctl_command = [
            "busctl",
            "--json=short",
            "call",
            "org.freedesktop.login1",
            "/org/freedesktop/login1",
            "org.freedesktop.login1.Manager",
            "ListSessionsEx",
        ]
        result = self.runner(busctl_command, 5)
        if result.returncode == 0:
            parsed = self._parse_login1_busctl_json(result.stdout)
            if parsed is not None:
                return parsed

        fallback = self.runner(["loginctl", "list-sessions", "--json=short"], 5)
        if fallback.returncode != 0:
            return None
        return self._parse_loginctl_sessions_json(fallback.stdout)

    def _classify_event(self, entry: dict[str, Any]) -> SystemEvent | None:
        message = self._entry_text(entry, "MESSAGE")
        if not message:
            return None
        message_l = message.lower()
        unit = self._entry_text(entry, "_SYSTEMD_UNIT", "UNIT").lower()
        ident = self._entry_text(entry, "SYSLOG_IDENTIFIER", "_COMM").lower()
        if self._is_self_event(unit=unit, ident=ident):
            return None
        cursor = self._entry_text(entry, "__CURSOR")
        ts_utc = self._entry_ts(entry)

        invalidated: set[str] = set()
        category = "system"
        source = ident or unit or "journal"

        if unit or ident in {"systemd", "systemctl"}:
            if any(
                token in message_l
                for token in (
                    "started ",
                    "stopped ",
                    "reloaded ",
                    "restart",
                    "restarting",
                    "failed ",
                    "entered failed state",
                    "deactivated successfully",
                )
            ):
                invalidated.update({"services.summary", "journal.alerts"})
                category = "service"

        if ident in {"apt", "apt-get", "dpkg", "unattended-upgrade"} or any(
            token in message_l for token in ("apt ", "apt-get", "dpkg", "package ")
        ):
            invalidated.update({"host.system", "services.summary", "journal.alerts"})
            category = "package"

        if ident in {"networkmanager", "systemd-networkd", "dhclient", "ifup", "ifdown"} or any(
            token in message_l
            for token in (
                "link is up",
                "link is down",
                "network is unreachable",
                "dhcp",
                "carrier",
                "default route",
                "nameserver",
                "resolv.conf",
                "route",
                "dns",
            )
        ):
            invalidated.update({"network.summary", "journal.alerts"})
            category = "network"

        if ident in {"sudo", "su", "sshd", "polkitd"} or any(
            token in message_l
            for token in (
                "failed password",
                "authentication failure",
                "invalid user",
                "session opened for user",
                "session closed for user",
                "not in sudoers",
            )
        ):
            invalidated.add("journal.alerts")
            category = "security"

        if not invalidated:
            return None

        return SystemEvent(
            cursor=cursor,
            ts_utc=ts_utc,
            category=category,
            source=source,
            summary=message.strip()[:240],
            invalidated_sources=tuple(sorted(invalidated)),
        )

    @classmethod
    def _is_self_event(cls, *, unit: str, ident: str) -> bool:
        unit_key = (unit or "").strip().lower()
        ident_key = (ident or "").strip().lower()
        if unit_key in cls.SELF_EVENT_UNITS:
            return True
        if ident_key in cls.SELF_EVENT_IDENTIFIERS:
            return True
        if unit_key.startswith("mastercontrol-"):
            return True
        if ident_key.startswith("mc-") and "mastercontrol" in unit_key:
            return True
        return False

    @staticmethod
    def _entry_text(entry: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = entry.get(key, "")
            if isinstance(value, list):
                value = " ".join(str(item) for item in value)
            text = str(value or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _entry_ts(entry: dict[str, Any]) -> str:
        raw = str(entry.get("__REALTIME_TIMESTAMP") or entry.get("_SOURCE_REALTIME_TIMESTAMP") or "").strip()
        if raw.isdigit():
            value = dt.datetime.fromtimestamp(int(raw) / 1_000_000, tz=dt.timezone.utc)
            return value.isoformat()
        return utc_now()

    @staticmethod
    def _parse_udev_export_db(stdout: str) -> dict[str, list[str]]:
        state = {"net": [], "block": [], "usb": []}
        current: dict[str, str] = {}

        def flush(entry: dict[str, str]) -> None:
            subsystem = str(entry.get("SUBSYSTEM", "")).strip().lower()
            if subsystem == "net":
                name = entry.get("INTERFACE") or entry.get("N") or entry.get("DEVNAME") or ""
                if name:
                    state["net"].append(name)
            elif subsystem == "block":
                name = entry.get("DEVNAME") or entry.get("N") or ""
                if name:
                    state["block"].append(name)
            elif subsystem == "usb":
                name = entry.get("ID_MODEL") or entry.get("PRODUCT") or entry.get("DEVNAME") or entry.get("P") or ""
                if name:
                    state["usb"].append(name)

        for line in stdout.splitlines() + [""]:
            stripped = line.rstrip()
            if not stripped:
                if current:
                    flush(current)
                current = {}
                continue
            if stripped.startswith("N: "):
                current["N"] = stripped[3:].strip()
                continue
            if stripped.startswith("P: "):
                current["P"] = stripped[3:].strip()
                continue
            if stripped.startswith("E: "):
                key, _, value = stripped[3:].partition("=")
                current[key.strip()] = value.strip()

        for key in state:
            state[key] = sorted(set(item for item in state[key] if item))
        return state

    @classmethod
    def _parse_login1_busctl_json(cls, stdout: str) -> dict[str, Any] | None:
        stripped = stdout.strip()
        if not stripped:
            return None
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if not isinstance(raw, dict):
            return None
        data = raw.get("data", [])
        if not isinstance(data, list) or not data:
            return {"sessions": []}
        rows = data[0]
        if not isinstance(rows, list):
            return {"sessions": []}
        sessions: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 10:
                continue
            sessions.append(
                cls._normalize_login_session(
                    {
                        "session": row[0],
                        "uid": row[1],
                        "user": row[2],
                        "seat": row[3],
                        "leader": row[4],
                        "class": row[5],
                        "tty": row[6],
                        "idle": row[7],
                        "since_mono": row[8],
                        "object_path": row[9],
                    }
                )
            )
        return {"sessions": cls._sort_sessions(sessions)}

    @classmethod
    def _parse_loginctl_sessions_json(cls, stdout: str) -> dict[str, Any] | None:
        stripped = stdout.strip()
        if not stripped:
            return None
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if not isinstance(raw, list):
            return None
        sessions: list[dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            sessions.append(cls._normalize_login_session(row))
        return {"sessions": cls._sort_sessions(sessions)}

    @staticmethod
    def _sort_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            sessions,
            key=lambda item: (
                str(item.get("session", "")),
                str(item.get("user", "")),
                str(item.get("tty", "")),
            ),
        )

    @staticmethod
    def _normalize_login_session(row: dict[str, Any]) -> dict[str, Any]:
        def _clean_text(value: Any) -> str:
            return str(value or "").strip()

        uid_value = row.get("uid", 0)
        leader_value = row.get("leader", 0)
        since_value = row.get("since_mono", row.get("since", 0))
        try:
            uid = int(uid_value)
        except Exception:  # noqa: BLE001
            uid = 0
        try:
            leader = int(leader_value)
        except Exception:  # noqa: BLE001
            leader = 0
        try:
            since_mono = int(since_value or 0)
        except Exception:  # noqa: BLE001
            since_mono = 0
        return {
            "session": _clean_text(row.get("session")),
            "uid": uid,
            "user": _clean_text(row.get("user")),
            "seat": _clean_text(row.get("seat")),
            "leader": leader,
            "class": _clean_text(row.get("class")),
            "tty": _clean_text(row.get("tty")),
            "idle": bool(row.get("idle", False)),
            "since_mono": since_mono,
            "object_path": _clean_text(row.get("object_path")),
        }

    @staticmethod
    def _session_label(session: dict[str, Any]) -> str:
        user = str(session.get("user", "")).strip() or "unknown"
        session_id = str(session.get("session", "")).strip() or "?"
        session_class = str(session.get("class", "")).strip() or "unknown"
        tty = str(session.get("tty", "")).strip()
        if tty:
            return f"{session_id}:{user}@{tty}/{session_class}"
        return f"{session_id}:{user}/{session_class}"
