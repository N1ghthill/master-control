#!/usr/bin/env python3
"""Incremental context engine for MasterControl."""

from __future__ import annotations

import datetime as dt
import json
import os
import platform
import re
import socket
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from mastercontrol.contracts import CONTEXT_TIER_ORDER, ContextSnapshot, ContextTier, normalize_context_tier, utc_now


@dataclass(frozen=True)
class CollectorSpec:
    collector_id: str
    tier: ContextTier
    ttl_s: int
    description: str


class ContextCollector(Protocol):
    spec: CollectorSpec

    def collect(self) -> ContextSnapshot:
        ...


class ContextStore(Protocol):
    def put(self, snapshot: ContextSnapshot) -> None:
        ...

    def get(self, source: str) -> ContextSnapshot | None:
        ...

    def needs_refresh(self, spec: CollectorSpec, now: dt.datetime | None = None) -> bool:
        ...

    def snapshots_up_to_tier(
        self,
        required_tier: ContextTier,
        now: dt.datetime | None = None,
    ) -> list[ContextSnapshot]:
        ...

    def snapshots_by_source(
        self,
        sources: list[str],
        now: dt.datetime | None = None,
    ) -> dict[str, ContextSnapshot]:
        ...

    def invalidate_sources(self, sources: list[str]) -> int:
        ...


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[list[str], int], CommandResult]


def default_command_runner(command: list[str], timeout_s: int = 2) -> CommandResult:
    try:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_s,
        )
    except FileNotFoundError:
        return CommandResult(returncode=127, stderr=f"missing command: {command[0]}")
    except subprocess.TimeoutExpired:
        return CommandResult(returncode=124, stderr="command timed out")
    return CommandResult(
        returncode=proc.returncode,
        stdout=(proc.stdout or "").strip(),
        stderr=(proc.stderr or "").strip(),
    )


def _slug(text: str) -> str:
    lowered = (text or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", ".", lowered).strip(".")
    return cleaned or "operator"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _detect_os_pretty(os_release_path: Path | None = None) -> str:
    path = os_release_path or Path("/etc/os-release")
    for line in _read_text(path).splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return platform.platform()


def _read_meminfo(meminfo_path: Path | None = None) -> dict[str, int]:
    values: dict[str, int] = {}
    path = meminfo_path or Path("/proc/meminfo")
    for line in _read_text(path).splitlines():
        key, sep, rest = line.partition(":")
        if not sep:
            continue
        number = rest.strip().split()[0] if rest.strip() else ""
        if number.isdigit():
            values[key.strip()] = int(number)
    return values


def _list_interfaces(sys_class_net_path: Path | None = None) -> list[str]:
    path = sys_class_net_path or Path("/sys/class/net")
    try:
        interfaces = [entry.name for entry in path.iterdir() if entry.is_dir()]
    except OSError:
        return []
    return sorted(interfaces)


def _read_nameservers(resolv_conf_path: Path | None = None) -> list[str]:
    path = resolv_conf_path or Path("/etc/resolv.conf")
    nameservers: list[str] = []
    for line in _read_text(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        head, _, tail = stripped.partition(" ")
        if head != "nameserver":
            continue
        value = tail.strip().split()[0] if tail.strip() else ""
        if value:
            nameservers.append(value)
    return nameservers


class SessionContextCollector:
    """Cheap hot-context collector for current operator session."""

    def __init__(
        self,
        operator_name: str,
        *,
        ttl_s: int = 15,
        env: dict[str, str] | None = None,
        cwd_provider: Callable[[], str] | None = None,
        hostname_provider: Callable[[], str] | None = None,
        now_provider: Callable[[], dt.datetime] | None = None,
        os_release_path: Path | None = None,
    ) -> None:
        self.operator_name = (operator_name or "Operator").strip() or "Operator"
        self.env = env or os.environ
        self.cwd_provider = cwd_provider or (lambda: str(Path.cwd()))
        self.hostname_provider = hostname_provider or socket.gethostname
        self.now_provider = now_provider or (lambda: dt.datetime.now().astimezone())
        self.os_release_path = os_release_path
        self.spec = CollectorSpec(
            collector_id=f"runtime.session.{_slug(self.operator_name)}",
            tier="hot",
            ttl_s=ttl_s,
            description="Current operator session and host snapshot",
        )

    def collect(self) -> ContextSnapshot:
        try:
            cwd = self.cwd_provider()
        except OSError:
            cwd = "unknown-cwd"
        payload = {
            "operator": self.operator_name,
            "hostname": self.hostname_provider() or "unknown-host",
            "os_pretty": _detect_os_pretty(self.os_release_path),
            "user": self.env.get("USER") or self.env.get("LOGNAME") or "unknown-user",
            "cwd": cwd,
            "session_id": self.env.get("XDG_SESSION_ID", ""),
            "tty": self.env.get("TTY", ""),
            "timestamp_local": self.now_provider().isoformat(timespec="seconds"),
        }
        return ContextSnapshot(
            source=self.spec.collector_id,
            tier=self.spec.tier,
            collected_at_utc=utc_now(),
            ttl_s=self.spec.ttl_s,
            payload=payload,
            summary=f"operator={payload['operator']}, host={payload['hostname']}, cwd={payload['cwd']}",
        )


class HostContextCollector:
    """Warm-context collector for host hardware and resource summary."""

    def __init__(
        self,
        *,
        ttl_s: int = 90,
        os_release_path: Path | None = None,
        meminfo_path: Path | None = None,
        loadavg_path: Path | None = None,
        uptime_path: Path | None = None,
        cpu_count_provider: Callable[[], int | None] | None = None,
        uname_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.os_release_path = os_release_path
        self.meminfo_path = meminfo_path
        self.loadavg_path = loadavg_path or Path("/proc/loadavg")
        self.uptime_path = uptime_path or Path("/proc/uptime")
        self.cpu_count_provider = cpu_count_provider or os.cpu_count
        self.uname_provider = uname_provider or platform.uname
        self.spec = CollectorSpec(
            collector_id="host.system",
            tier="warm",
            ttl_s=ttl_s,
            description="Host hardware and resource snapshot",
        )

    def collect(self) -> ContextSnapshot:
        uname = self.uname_provider()
        meminfo = _read_meminfo(self.meminfo_path)
        loadavg = _read_text(self.loadavg_path).strip().split()
        uptime_raw = _read_text(self.uptime_path).strip().split()
        payload = {
            "os_pretty": _detect_os_pretty(self.os_release_path),
            "kernel": getattr(uname, "release", ""),
            "architecture": getattr(uname, "machine", ""),
            "cpu_count": int(self.cpu_count_provider() or 0),
            "loadavg_1m": float(loadavg[0]) if loadavg else 0.0,
            "mem_total_mib": round(meminfo.get("MemTotal", 0) / 1024, 1),
            "mem_available_mib": round(meminfo.get("MemAvailable", 0) / 1024, 1),
            "uptime_s": int(float(uptime_raw[0])) if uptime_raw else 0,
        }
        return ContextSnapshot(
            source=self.spec.collector_id,
            tier=self.spec.tier,
            collected_at_utc=utc_now(),
            ttl_s=self.spec.ttl_s,
            payload=payload,
            summary=(
                f"kernel={payload['kernel'] or 'unknown'}, "
                f"arch={payload['architecture'] or 'unknown'}, "
                f"cpu={payload['cpu_count']}, load1={payload['loadavg_1m']:.2f}, "
                f"mem_avail_mib={payload['mem_available_mib']}"
            ),
        )


class NetworkContextCollector:
    """Warm-context collector for routing, interfaces and resolvers."""

    def __init__(
        self,
        *,
        ttl_s: int = 45,
        runner: CommandRunner | None = None,
        resolv_conf_path: Path | None = None,
        sys_class_net_path: Path | None = None,
    ) -> None:
        self.runner = runner or default_command_runner
        self.resolv_conf_path = resolv_conf_path
        self.sys_class_net_path = sys_class_net_path
        self.spec = CollectorSpec(
            collector_id="network.summary",
            tier="warm",
            ttl_s=ttl_s,
            description="Default route, interfaces and resolvers",
        )

    def collect(self) -> ContextSnapshot:
        route_result = self.runner(["ip", "route", "show", "default"], 2)
        default_route = route_result.stdout.splitlines()[0].strip() if route_result.stdout else ""
        nameservers = _read_nameservers(self.resolv_conf_path)
        interfaces = _list_interfaces(self.sys_class_net_path)
        payload = {
            "default_route": default_route,
            "nameservers": nameservers,
            "interfaces": interfaces,
            "route_status": route_result.returncode,
        }
        return ContextSnapshot(
            source=self.spec.collector_id,
            tier=self.spec.tier,
            collected_at_utc=utc_now(),
            ttl_s=self.spec.ttl_s,
            payload=payload,
            summary=(
                f"default_route={default_route or 'unknown'}, "
                f"nameservers={','.join(nameservers) or 'none'}, "
                f"interfaces={','.join(interfaces[:4]) or 'none'}"
            ),
        )


class ServiceContextCollector:
    """Warm-context collector for systemd state and failed units."""

    def __init__(
        self,
        *,
        ttl_s: int = 45,
        runner: CommandRunner | None = None,
    ) -> None:
        self.runner = runner or default_command_runner
        self.spec = CollectorSpec(
            collector_id="services.summary",
            tier="warm",
            ttl_s=ttl_s,
            description="systemd overall state and failed units",
        )

    def collect(self) -> ContextSnapshot:
        state_result = self.runner(["systemctl", "is-system-running"], 2)
        failed_result = self.runner(["systemctl", "--failed", "--no-legend", "--plain"], 3)
        state = state_result.stdout.splitlines()[0].strip() if state_result.stdout else state_result.stderr or "unknown"
        failed_units = []
        for line in failed_result.stdout.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("0 loaded units listed"):
                continue
            failed_units.append(stripped.split()[0])
        payload = {
            "system_state": state,
            "failed_units": failed_units,
            "failed_count": len(failed_units),
        }
        return ContextSnapshot(
            source=self.spec.collector_id,
            tier=self.spec.tier,
            collected_at_utc=utc_now(),
            ttl_s=self.spec.ttl_s,
            payload=payload,
            summary=(
                f"system_state={state}, failed_count={len(failed_units)}, "
                f"failed_units={','.join(failed_units[:3]) or 'none'}"
            ),
        )


class AlertJournalCollector:
    """Deep-context collector for recent warning/error journal events."""

    def __init__(
        self,
        *,
        ttl_s: int = 20,
        runner: CommandRunner | None = None,
    ) -> None:
        self.runner = runner or default_command_runner
        self.spec = CollectorSpec(
            collector_id="journal.alerts",
            tier="deep",
            ttl_s=ttl_s,
            description="Recent warning and error journal lines",
        )

    def collect(self) -> ContextSnapshot:
        journal_result = self.runner(
            ["journalctl", "-p", "warning", "-n", "5", "--no-pager", "-o", "short-iso"],
            4,
        )
        lines = [line.strip() for line in journal_result.stdout.splitlines() if line.strip()]
        payload = {
            "recent_warning_events": lines[:5],
            "warning_event_count": len(lines),
            "status": journal_result.returncode,
        }
        return ContextSnapshot(
            source=self.spec.collector_id,
            tier=self.spec.tier,
            collected_at_utc=utc_now(),
            ttl_s=self.spec.ttl_s,
            payload=payload,
            summary=f"recent_warning_events={len(lines)}, status={journal_result.returncode}",
        )


class InMemoryContextStore:
    """Stores snapshots and knows when they need refresh."""

    def __init__(self) -> None:
        self._snapshots: dict[str, ContextSnapshot] = {}

    def put(self, snapshot: ContextSnapshot) -> None:
        self._snapshots[snapshot.source] = snapshot

    def get(self, source: str) -> ContextSnapshot | None:
        return self._snapshots.get(source)

    def needs_refresh(self, spec: CollectorSpec, now: dt.datetime | None = None) -> bool:
        snapshot = self.get(spec.collector_id)
        if snapshot is None:
            return True
        return snapshot.is_stale(now=now)

    def snapshots_up_to_tier(self, required_tier: ContextTier, now: dt.datetime | None = None) -> list[ContextSnapshot]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        limit = CONTEXT_TIER_ORDER[normalize_context_tier(required_tier)]
        visible: list[ContextSnapshot] = []
        for snapshot in self._snapshots.values():
            if CONTEXT_TIER_ORDER[normalize_context_tier(snapshot.tier)] <= limit and not snapshot.is_stale(now=current):
                visible.append(snapshot)
        return sorted(visible, key=lambda item: (CONTEXT_TIER_ORDER[item.tier], item.source))

    def snapshots_by_source(
        self,
        sources: list[str],
        now: dt.datetime | None = None,
    ) -> dict[str, ContextSnapshot]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        selected: dict[str, ContextSnapshot] = {}
        for source in sources:
            snapshot = self._snapshots.get(source)
            if snapshot is None or snapshot.is_stale(now=current):
                continue
            selected[source] = snapshot
        return selected

    def invalidate_sources(self, sources: list[str]) -> int:
        removed = 0
        for source in dict.fromkeys(sources):
            if source in self._snapshots:
                removed += 1
                self._snapshots.pop(source, None)
        return removed


class SQLiteContextStore:
    """Persists context snapshots locally for reuse across requests and sessions."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (
            Path.home() / ".local" / "share" / "mastercontrol" / "mastercontrol.db"
        )
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
                    CREATE TABLE IF NOT EXISTS context_snapshots (
                        source TEXT PRIMARY KEY,
                        tier TEXT NOT NULL,
                        collected_at_utc TEXT NOT NULL,
                        ttl_s INTEGER NOT NULL,
                        payload_json TEXT NOT NULL,
                        summary TEXT NOT NULL DEFAULT '',
                        version INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_context_snapshots_tier
                    ON context_snapshots (tier, collected_at_utc);
                    """
                )

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> ContextSnapshot:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return ContextSnapshot(
            source=str(row["source"]),
            tier=normalize_context_tier(str(row["tier"])),
            collected_at_utc=str(row["collected_at_utc"]),
            ttl_s=int(row["ttl_s"]),
            payload=payload,
            summary=str(row["summary"] or ""),
            version=int(row["version"] or 1),
        )

    def put(self, snapshot: ContextSnapshot) -> None:
        payload_json = json.dumps(snapshot.payload, ensure_ascii=True, sort_keys=True)
        with closing(self._conn()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO context_snapshots (
                        source, tier, collected_at_utc, ttl_s,
                        payload_json, summary, version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source) DO UPDATE SET
                        tier=excluded.tier,
                        collected_at_utc=excluded.collected_at_utc,
                        ttl_s=excluded.ttl_s,
                        payload_json=excluded.payload_json,
                        summary=excluded.summary,
                        version=excluded.version,
                        updated_at=excluded.updated_at
                    """,
                    (
                        snapshot.source,
                        snapshot.tier,
                        snapshot.collected_at_utc,
                        int(snapshot.ttl_s),
                        payload_json,
                        snapshot.summary,
                        int(snapshot.version),
                        utc_now(),
                    ),
                )

    def get(self, source: str) -> ContextSnapshot | None:
        with closing(self._conn()) as conn:
            row = conn.execute(
                """
                SELECT source, tier, collected_at_utc, ttl_s, payload_json, summary, version
                FROM context_snapshots
                WHERE source = ?
                """,
                (source,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def needs_refresh(self, spec: CollectorSpec, now: dt.datetime | None = None) -> bool:
        snapshot = self.get(spec.collector_id)
        if snapshot is None:
            return True
        return snapshot.is_stale(now=now)

    def snapshots_up_to_tier(
        self,
        required_tier: ContextTier,
        now: dt.datetime | None = None,
    ) -> list[ContextSnapshot]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        limit = CONTEXT_TIER_ORDER[normalize_context_tier(required_tier)]
        with closing(self._conn()) as conn:
            rows = conn.execute(
                """
                SELECT source, tier, collected_at_utc, ttl_s, payload_json, summary, version
                FROM context_snapshots
                ORDER BY collected_at_utc DESC
                """
            ).fetchall()
        visible: list[ContextSnapshot] = []
        for row in rows:
            snapshot = self._row_to_snapshot(row)
            if CONTEXT_TIER_ORDER[normalize_context_tier(snapshot.tier)] > limit:
                continue
            if snapshot.is_stale(now=current):
                continue
            visible.append(snapshot)
        return sorted(
            visible,
            key=lambda item: (CONTEXT_TIER_ORDER[normalize_context_tier(item.tier)], item.source),
        )

    def snapshots_by_source(
        self,
        sources: list[str],
        now: dt.datetime | None = None,
    ) -> dict[str, ContextSnapshot]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        ordered_sources = [source for source in dict.fromkeys(sources) if source]
        if not ordered_sources:
            return {}
        placeholders = ", ".join("?" for _ in ordered_sources)
        with closing(self._conn()) as conn:
            rows = conn.execute(
                f"""
                SELECT source, tier, collected_at_utc, ttl_s, payload_json, summary, version
                FROM context_snapshots
                WHERE source IN ({placeholders})
                """,
                ordered_sources,
            ).fetchall()
        selected: dict[str, ContextSnapshot] = {}
        for row in rows:
            snapshot = self._row_to_snapshot(row)
            if snapshot.is_stale(now=current):
                continue
            selected[snapshot.source] = snapshot
        return selected

    def invalidate_sources(self, sources: list[str]) -> int:
        ordered_sources = [source for source in dict.fromkeys(sources) if source]
        if not ordered_sources:
            return 0
        placeholders = ", ".join("?" for _ in ordered_sources)
        with closing(self._conn()) as conn:
            with conn:
                cursor = conn.execute(
                    f"DELETE FROM context_snapshots WHERE source IN ({placeholders})",
                    ordered_sources,
                )
        return int(cursor.rowcount or 0)


class ContextEngine:
    """Collects only the minimum context tier required for a task."""

    def __init__(self, collectors: list[ContextCollector], store: ContextStore | None = None) -> None:
        self._collectors = {collector.spec.collector_id: collector for collector in collectors}
        self._store = store or InMemoryContextStore()

    @property
    def store(self) -> ContextStore:
        return self._store

    @staticmethod
    def required_tier(
        *,
        risk_level: str,
        requires_mutation: bool,
        diagnostics: bool,
        incident: bool,
        ambiguity: bool,
    ) -> ContextTier:
        if incident or diagnostics:
            return "deep"
        if ambiguity:
            return "warm"
        if risk_level in {"high", "critical"}:
            return "deep"
        if requires_mutation or risk_level == "medium":
            return "warm"
        return "hot"

    def ensure_context(
        self,
        required_tier: ContextTier,
        *,
        now: dt.datetime | None = None,
    ) -> list[ContextSnapshot]:
        current = now or dt.datetime.now(tz=dt.timezone.utc)
        limit = CONTEXT_TIER_ORDER[normalize_context_tier(required_tier)]

        for collector in self._collectors.values():
            tier_order = CONTEXT_TIER_ORDER[normalize_context_tier(collector.spec.tier)]
            if tier_order > limit:
                continue
            if not self._store.needs_refresh(collector.spec, now=current):
                continue
            snapshot = collector.collect()
            self._store.put(snapshot)

        return self._store.snapshots_up_to_tier(required_tier, now=current)


class StaticContextCollector:
    """Simple collector used to bootstrap and test the context engine."""

    def __init__(self, spec: CollectorSpec, payload: dict[str, object], summary: str = "") -> None:
        self.spec = spec
        self._payload = dict(payload)
        self._summary = summary

    def collect(self) -> ContextSnapshot:
        return ContextSnapshot(
            source=self.spec.collector_id,
            tier=self.spec.tier,
            collected_at_utc=utc_now(),
            ttl_s=self.spec.ttl_s,
            payload=dict(self._payload),
            summary=self._summary,
        )
