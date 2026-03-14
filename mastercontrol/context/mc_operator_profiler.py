#!/usr/bin/env python3
"""Local operator profiler for adaptive path decisions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_PATH = {"fast", "deep", "fast_with_confirm"}
VALID_RISK = {"low", "medium", "high", "critical"}


def utc_now() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat()


def default_db_path() -> Path:
    return Path.home() / ".local" / "share" / "mastercontrol" / "mastercontrol.db"


@dataclass
class OperatorEvent:
    operator_id: str
    intent_text: str
    intent_cluster: str
    risk_level: str
    selected_path: str
    success: bool
    latency_ms: int
    command_error: str = ""
    forced_path: bool = False
    incident: bool = False


class OperatorProfiler:
    """Records operator behavior and computes compact profile snapshots."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_db_path()
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
                    CREATE TABLE IF NOT EXISTS command_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts_utc TEXT NOT NULL,
                        operator_id TEXT NOT NULL,
                        intent_text TEXT NOT NULL,
                        intent_cluster TEXT NOT NULL,
                        risk_level TEXT NOT NULL,
                        selected_path TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        latency_ms INTEGER NOT NULL,
                        command_error TEXT NOT NULL DEFAULT '',
                        forced_path INTEGER NOT NULL DEFAULT 0,
                        incident INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS operator_patterns (
                        operator_id TEXT PRIMARY KEY,
                        active_hours TEXT NOT NULL,
                        common_intents TEXT NOT NULL,
                        error_prone_commands TEXT NOT NULL,
                        path_preference TEXT NOT NULL,
                        tone_sensitivity REAL NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS dream_insights (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts_utc TEXT NOT NULL,
                        operator_id TEXT NOT NULL,
                        insight_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'new'
                    );

                    CREATE TABLE IF NOT EXISTS learned_rules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        operator_id TEXT NOT NULL,
                        rule_key TEXT NOT NULL,
                        intent_cluster TEXT NOT NULL,
                        day_of_week TEXT NOT NULL DEFAULT '*',
                        hour_start INTEGER NOT NULL DEFAULT -1,
                        hour_end INTEGER NOT NULL DEFAULT -1,
                        recommended_path TEXT NOT NULL,
                        confidence_delta REAL NOT NULL DEFAULT 0.0,
                        reason TEXT NOT NULL,
                        source TEXT NOT NULL DEFAULT 'dream',
                        enabled INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT NOT NULL,
                        UNIQUE(operator_id, rule_key)
                    );
                    """
                )

    def record_event(self, event: OperatorEvent) -> None:
        risk = event.risk_level if event.risk_level in VALID_RISK else "medium"
        path = event.selected_path if event.selected_path in VALID_PATH else "deep"
        with closing(self._conn()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO command_events (
                        ts_utc, operator_id, intent_text, intent_cluster, risk_level,
                        selected_path, success, latency_ms, command_error, forced_path, incident
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now(),
                        event.operator_id,
                        event.intent_text.strip(),
                        event.intent_cluster.strip() or "unknown",
                        risk,
                        path,
                        int(bool(event.success)),
                        int(max(event.latency_ms, 0)),
                        event.command_error.strip(),
                        int(bool(event.forced_path)),
                        int(bool(event.incident)),
                    ),
                )
        self.refresh_profile(event.operator_id)

    def refresh_profile(self, operator_id: str) -> dict[str, Any]:
        rows = self._recent_events(operator_id=operator_id, limit=500)
        profile = self._compute_profile(operator_id=operator_id, rows=rows)

        with closing(self._conn()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO operator_patterns (
                        operator_id, active_hours, common_intents, error_prone_commands,
                        path_preference, tone_sensitivity, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(operator_id) DO UPDATE SET
                        active_hours=excluded.active_hours,
                        common_intents=excluded.common_intents,
                        error_prone_commands=excluded.error_prone_commands,
                        path_preference=excluded.path_preference,
                        tone_sensitivity=excluded.tone_sensitivity,
                        updated_at=excluded.updated_at
                    """,
                    (
                        operator_id,
                        profile["active_hours"],
                        json.dumps(profile["common_intents"], ensure_ascii=True),
                        json.dumps(profile["error_prone_commands"], ensure_ascii=True),
                        profile["path_preference"],
                        float(profile["tone_sensitivity"]),
                        utc_now(),
                    ),
                )
        return profile

    def get_profile(self, operator_id: str) -> dict[str, Any]:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT * FROM operator_patterns WHERE operator_id = ?",
                (operator_id,),
            ).fetchone()
        if row is None:
            return self.refresh_profile(operator_id)
        return {
            "operator_id": row["operator_id"],
            "active_hours": row["active_hours"],
            "common_intents": json.loads(row["common_intents"]),
            "error_prone_commands": json.loads(row["error_prone_commands"]),
            "path_preference": row["path_preference"],
            "tone_sensitivity": float(row["tone_sensitivity"]),
            "updated_at": row["updated_at"],
        }

    def _recent_events(self, operator_id: str, limit: int = 500) -> list[sqlite3.Row]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM command_events
                WHERE operator_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (operator_id, limit),
            ).fetchall()
        return rows

    def _compute_profile(self, operator_id: str, rows: list[sqlite3.Row]) -> dict[str, Any]:
        if not rows:
            return {
                "operator_id": operator_id,
                "active_hours": "unknown",
                "common_intents": [],
                "error_prone_commands": [],
                "path_preference": "balanced",
                "tone_sensitivity": 0.5,
                "updated_at": utc_now(),
            }

        hours = []
        intents = Counter()
        errors = Counter()
        paths = Counter()
        risk_plus_path = defaultdict(int)

        for row in rows:
            ts = row["ts_utc"]
            try:
                hour = dt.datetime.fromisoformat(ts).hour
                hours.append(hour)
            except ValueError:
                pass
            intents[row["intent_cluster"]] += 1
            paths[row["selected_path"]] += 1
            if row["command_error"]:
                errors[row["intent_cluster"]] += 1
            key = f"{row['risk_level']}|{row['selected_path']}"
            risk_plus_path[key] += 1

        active_hours = self._active_hour_window(hours)
        common_intents = [name for name, _ in intents.most_common(5)]
        error_prone = [name for name, _ in errors.most_common(5)]
        path_pref = self._path_preference(paths=paths, risk_plus_path=risk_plus_path)
        tone_sensitivity = self._tone_sensitivity(rows)

        return {
            "operator_id": operator_id,
            "active_hours": active_hours,
            "common_intents": common_intents,
            "error_prone_commands": error_prone,
            "path_preference": path_pref,
            "tone_sensitivity": tone_sensitivity,
            "updated_at": utc_now(),
        }

    @staticmethod
    def _active_hour_window(hours: list[int]) -> str:
        if not hours:
            return "unknown"
        counter = Counter(hours)
        top = sorted([h for h, _ in counter.most_common(6)])
        if not top:
            return "unknown"
        return f"{top[0]:02d}:00-{top[-1]:02d}:59"

    @staticmethod
    def _path_preference(paths: Counter[str], risk_plus_path: dict[str, int]) -> str:
        total = sum(paths.values()) or 1
        deep_rate = paths.get("deep", 0) / total
        fast_rate = paths.get("fast", 0) / total
        fwc_rate = paths.get("fast_with_confirm", 0) / total

        medium_fast_confirm = risk_plus_path.get("medium|fast_with_confirm", 0)
        medium_total = sum(v for k, v in risk_plus_path.items() if k.startswith("medium|")) or 1
        medium_confirm_rate = medium_fast_confirm / medium_total

        if deep_rate >= 0.45:
            return "deep_when_uncertain"
        if fast_rate >= 0.55 and medium_confirm_rate < 0.40:
            return "fast_default"
        if fwc_rate >= 0.45:
            return "confirm_heavy"
        return "balanced"

    @staticmethod
    def _tone_sensitivity(rows: list[sqlite3.Row]) -> float:
        if not rows:
            return 0.5
        error_count = sum(1 for r in rows if r["command_error"])
        forced_count = sum(1 for r in rows if int(r["forced_path"]) == 1)
        incident_count = sum(1 for r in rows if int(r["incident"]) == 1)
        n = len(rows)
        score = 0.5 + (error_count / n) * 0.25 + (incident_count / n) * 0.2 + (forced_count / n) * 0.05
        return round(max(0.1, min(score, 0.95)), 3)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mc-operator-profiler",
        description="Record operator events and derive behavior profile",
    )
    p.add_argument("--db", default=None, help="SQLite database path")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="Record command event")
    r.add_argument("--operator-id", required=True)
    r.add_argument("--intent-text", required=True)
    r.add_argument("--intent-cluster", default="unknown")
    r.add_argument("--risk-level", default="medium", choices=sorted(VALID_RISK))
    r.add_argument("--selected-path", default="deep", choices=sorted(VALID_PATH))
    r.add_argument("--success", action="store_true")
    r.add_argument("--latency-ms", type=int, default=0)
    r.add_argument("--command-error", default="")
    r.add_argument("--forced-path", action="store_true")
    r.add_argument("--incident", action="store_true")

    g = sub.add_parser("profile", help="Get operator profile snapshot")
    g.add_argument("--operator-id", required=True)

    sub.add_parser("init", help="Initialize database schema")
    return p


def main() -> int:
    args = parser().parse_args()
    profiler = OperatorProfiler(Path(args.db) if args.db else None)

    if args.cmd == "init":
        print(json.dumps({"ok": True, "db_path": str(profiler.db_path)}, ensure_ascii=True))
        return 0

    if args.cmd == "record":
        event = OperatorEvent(
            operator_id=args.operator_id,
            intent_text=args.intent_text,
            intent_cluster=args.intent_cluster,
            risk_level=args.risk_level,
            selected_path=args.selected_path,
            success=bool(args.success),
            latency_ms=int(args.latency_ms),
            command_error=args.command_error,
            forced_path=bool(args.forced_path),
            incident=bool(args.incident),
        )
        profiler.record_event(event)
        profile = profiler.get_profile(args.operator_id)
        print(json.dumps({"ok": True, "profile": profile}, ensure_ascii=True, indent=2))
        return 0

    if args.cmd == "profile":
        profile = profiler.get_profile(args.operator_id)
        print(json.dumps(profile, ensure_ascii=True, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
