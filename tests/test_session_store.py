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

    def test_tool_approval_lifecycle_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SessionStore(Path(tmp_dir) / "mc.sqlite3")
            store.initialize()

            created = store.create_tool_approval(
                tool_name="write_config_file",
                risk="mutating_safe",
                arguments={"path": "/tmp/demo.ini", "content": "key=value\n"},
                audit_context={"source": "test"},
                summary="Confirme a execução.",
                cli_command="mc tool write_config_file --confirm",
                chat_command="/tool write_config_file confirm",
            )

            self.assertEqual(created["status"], "pending")
            self.assertIsNone(created["execution"])

            claimed = store.claim_tool_approval(int(created["id"]))
            assert claimed is not None
            self.assertEqual(claimed["status"], "executing")

            finalized = store.finish_tool_approval(
                int(created["id"]),
                status="completed",
                execution_payload={"ok": True, "result": {"changed": True}},
            )
            assert finalized is not None
            self.assertEqual(finalized["status"], "completed")
            self.assertEqual(finalized["execution"], {"ok": True, "result": {"changed": True}})

    def test_claim_latest_matching_tool_approval_selects_pending_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SessionStore(Path(tmp_dir) / "mc.sqlite3")
            store.initialize()

            first = store.create_tool_approval(
                tool_name="write_config_file",
                risk="mutating_safe",
                arguments={"path": "/tmp/demo.ini", "content": "old"},
                audit_context={"source": "test"},
                summary="first",
                cli_command="first",
                chat_command="first",
            )
            second = store.create_tool_approval(
                tool_name="write_config_file",
                risk="mutating_safe",
                arguments={"path": "/tmp/demo.ini", "content": "old"},
                audit_context={"source": "test"},
                summary="second",
                cli_command="second",
                chat_command="second",
            )

            claimed = store.claim_latest_matching_tool_approval(
                tool_name="write_config_file",
                arguments={"path": "/tmp/demo.ini", "content": "old"},
                audit_context={"source": "test"},
            )

            assert claimed is not None
            self.assertEqual(claimed["id"], second["id"])
            self.assertEqual(claimed["status"], "executing")
            self.assertEqual(store.get_tool_approval(int(first["id"]))["status"], "pending")


if __name__ == "__main__":
    unittest.main()
