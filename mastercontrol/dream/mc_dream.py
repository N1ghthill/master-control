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
            conn.executescript(
                """
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

    def run(self, operator_id: str, window_days: int = 7) -> dict[str, Any]:
        rows = self._load_events(operator_id=operator_id, window_days=window_days)
        insights = []
        insights.extend(self._pattern_repetition(rows))
        insights.extend(self._risk_correction(rows))
        insights.extend(self._error_hotspots(rows))
        learned_rules = self._derive_learned_rules(rows)

        for item in insights:
            self._store_insight(operator_id, item["type"], item)
        for rule in learned_rules:
            self._upsert_rule(operator_id=operator_id, rule=rule)

        return {
            "ts_utc": utc_now(),
            "operator_id": operator_id,
            "window_days": window_days,
            "insights": insights,
            "count": len(insights),
            "learned_rules": learned_rules,
            "rules_count": len(learned_rules),
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

    def _upsert_rule(self, operator_id: str, rule: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO learned_rules (
                    operator_id, rule_key, intent_cluster, day_of_week, hour_start, hour_end,
                    recommended_path, confidence_delta, reason, source, enabled, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'dream', 1, ?)
                ON CONFLICT(operator_id, rule_key) DO UPDATE SET
                    intent_cluster=excluded.intent_cluster,
                    day_of_week=excluded.day_of_week,
                    hour_start=excluded.hour_start,
                    hour_end=excluded.hour_end,
                    recommended_path=excluded.recommended_path,
                    confidence_delta=excluded.confidence_delta,
                    reason=excluded.reason,
                    source='dream',
                    enabled=1,
                    updated_at=excluded.updated_at
                """,
                (
                    operator_id,
                    str(rule["rule_key"]),
                    str(rule["intent_cluster"]),
                    str(rule.get("day_of_week", "*")),
                    int(rule.get("hour_start", -1)),
                    int(rule.get("hour_end", -1)),
                    str(rule["recommended_path"]),
                    float(rule["confidence_delta"]),
                    str(rule["reason"]),
                    utc_now(),
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

    @staticmethod
    def _derive_learned_rules(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        if len(rows) < 10:
            return []

        by_cluster: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            cluster = str(row["intent_cluster"] or "").strip()
            if not cluster or cluster == "unknown":
                continue
            by_cluster[cluster].append(row)

        rules: list[dict[str, Any]] = []
        for cluster, items in by_cluster.items():
            if len(items) < 5:
                continue

            path_counts = Counter(str(it["selected_path"]) for it in items)
            preferred_path, preferred_count = path_counts.most_common(1)[0]
            confidence_path = preferred_count / len(items)
            if confidence_path < 0.65:
                continue

            success_rate = sum(int(it["success"]) for it in items) / len(items)
            if success_rate < 0.75:
                continue

            dow_counts = Counter()
            hours: list[int] = []
            for it in items:
                try:
                    ts = dt.datetime.fromisoformat(str(it["ts_utc"]))
                except ValueError:
                    continue
                dow = ts.strftime("%a").lower()[:3]
                dow_counts[dow] += 1
                hours.append(ts.hour)

            if hours:
                hour_counts = Counter(hours)
                top_hours = [h for h, _ in hour_counts.most_common(6)]
                hour_start = min(top_hours)
                hour_end = max(top_hours)
            else:
                hour_start = -1
                hour_end = -1

            day_of_week = "*"
            if dow_counts:
                top_day, top_day_count = dow_counts.most_common(1)[0]
                if top_day_count / len(items) >= 0.5:
                    day_of_week = top_day

            delta = 0.0
            if preferred_path == "fast":
                delta = 0.08
            elif preferred_path == "fast_with_confirm":
                delta = 0.05
            elif preferred_path == "deep":
                delta = 0.06

            if delta == 0.0:
                continue

            rule_key = f"dream.{cluster}.{preferred_path}"
            reason = (
                f"Historical pattern favors {preferred_path} for {cluster} "
                f"(success_rate={success_rate:.2f}, freq={len(items)})."
            )
            rules.append(
                {
                    "rule_key": rule_key,
                    "intent_cluster": cluster,
                    "day_of_week": day_of_week,
                    "hour_start": hour_start,
                    "hour_end": hour_end,
                    "recommended_path": preferred_path,
                    "confidence_delta": round(delta, 3),
                    "reason": reason,
                }
            )
        return rules[:15]


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
