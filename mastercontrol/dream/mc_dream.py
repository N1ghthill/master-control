#!/usr/bin/env python3
"""Nightly offline insight generator for MasterControl."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def default_db_path() -> Path:
    return Path.home() / ".local" / "share" / "mastercontrol" / "mastercontrol.db"


def utc_now() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat()


class DreamEngine:
    """Produces suggestions from historical command events."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dream_insights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    insight_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new'
                )
                """
            )

    def run(self, operator_id: str, window_days: int = 7) -> dict[str, Any]:
        rows = self._load_events(operator_id=operator_id, window_days=window_days)
        insights = []
        insights.extend(self._pattern_repetition(rows))
        insights.extend(self._risk_correction(rows))
        insights.extend(self._error_hotspots(rows))

        for item in insights:
            self._store_insight(operator_id, item["type"], item)

        return {
            "ts_utc": utc_now(),
            "operator_id": operator_id,
            "window_days": window_days,
            "insights": insights,
            "count": len(insights),
        }

    def _load_events(self, operator_id: str, window_days: int) -> list[sqlite3.Row]:
        cutoff = (dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(days=window_days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM command_events
                WHERE operator_id = ? AND ts_utc >= ?
                ORDER BY ts_utc ASC, id ASC
                """,
                (operator_id, cutoff),
            ).fetchall()
        return rows

    def _store_insight(self, operator_id: str, insight_type: str, payload: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO dream_insights (ts_utc, operator_id, insight_type, payload_json, status)
                VALUES (?, ?, ?, ?, 'new')
                """,
                (
                    utc_now(),
                    operator_id,
                    insight_type,
                    json.dumps(payload, ensure_ascii=True),
                ),
            )

    @staticmethod
    def _pattern_repetition(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        if len(rows) < 6:
            return []
        seq_counter = Counter()
        seq_success = defaultdict(int)

        for i in range(len(rows) - 1):
            a = rows[i]["intent_cluster"]
            b = rows[i + 1]["intent_cluster"]
            key = f"{a}>{b}"
            seq_counter[key] += 1
            if int(rows[i]["success"]) == 1 and int(rows[i + 1]["success"]) == 1:
                seq_success[key] += 1

        insights = []
        for key, freq in seq_counter.most_common(5):
            if freq < 4:
                continue
            success_rate = round(seq_success[key] / freq, 3)
            if success_rate < 0.7:
                continue
            left, right = key.split(">", 1)
            alias = f"{left.split('.')[0]}.reset" if left.startswith("dns") else f"{left}.pipeline"
            insights.append(
                {
                    "type": "pattern_repetition",
                    "command_sequence": [left, right],
                    "frequency": freq,
                    "success_rate": success_rate,
                    "suggested_alias": alias,
                }
            )
        return insights

    @staticmethod
    def _risk_correction(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        if not rows:
            return []
        high_forced = 0
        high_total = 0
        for row in rows:
            if row["risk_level"] in {"high", "critical"}:
                high_total += 1
                if int(row["forced_path"]) == 1:
                    high_forced += 1
        if high_total == 0:
            return []
        rate = high_forced / high_total
        if rate < 0.3:
            return []
        return [
            {
                "type": "risk_correction",
                "observation": f"Forced path in high-risk operations: {high_forced}/{high_total}",
                "suggestion": "Require mandatory step-up for forced path on high-risk actions.",
                "forced_rate": round(rate, 3),
            }
        ]

    @staticmethod
    def _error_hotspots(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        if not rows:
            return []
        err_counter = Counter()
        total_counter = Counter()
        for row in rows:
            cluster = row["intent_cluster"]
            total_counter[cluster] += 1
            if row["command_error"]:
                err_counter[cluster] += 1

        insights = []
        for cluster, err_count in err_counter.most_common(4):
            total = total_counter[cluster]
            if total < 3:
                continue
            rate = err_count / total
            if rate < 0.35:
                continue
            insights.append(
                {
                    "type": "error_hotspot",
                    "intent_cluster": cluster,
                    "error_rate": round(rate, 3),
                    "suggestion": "Offer guided confirmation and clearer pre-checks for this intent.",
                }
            )
        return insights


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mc-dream",
        description="Generate offline operational insights from recent events",
    )
    p.add_argument("--db", default=None, help="SQLite database path")
    p.add_argument("--operator-id", required=True)
    p.add_argument("--window-days", type=int, default=7)
    return p


def main() -> int:
    args = parser().parse_args()
    engine = DreamEngine(Path(args.db) if args.db else None)
    result = engine.run(operator_id=args.operator_id, window_days=max(args.window_days, 1))
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

