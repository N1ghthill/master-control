from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from master_control.store.session_store import SessionStore


class SessionStoreInfrastructureTest(unittest.TestCase):
    def test_store_diagnostics_report_wal_and_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SessionStore(Path(tmp_dir) / "mc.sqlite3")
            store.initialize()

            diagnostics = store.diagnostics()

            self.assertTrue(diagnostics["ok"])
            self.assertEqual(diagnostics["journal_mode"], "wal")
            self.assertEqual(diagnostics["synchronous"], "NORMAL")
            self.assertEqual(diagnostics["integrity_check"], "ok")
            self.assertTrue(diagnostics["foreign_keys"])

    def test_store_connections_enable_foreign_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SessionStore(Path(tmp_dir) / "mc.sqlite3")
            store.initialize()

            with closing(store._connect()) as connection:
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 1)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO conversation_messages (session_id, role, content)
                        VALUES (?, ?, ?)
                        """,
                        (999, "user", "orphan"),
                    )
                    connection.commit()


if __name__ == "__main__":
    unittest.main()
