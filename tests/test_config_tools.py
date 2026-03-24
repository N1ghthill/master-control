from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from master_control.app import MasterControlApp
from master_control.config import Settings


class ConfigToolsTest(unittest.TestCase):
    def test_read_config_file_reads_managed_ini(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            managed_root = state_dir / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "app.ini"
            config_path.write_text("[main]\nkey=value\n", encoding="utf-8")

            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.run_tool(
                "read_config_file",
                {"path": str(config_path)},
            )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["result"]["target"], "managed_ini")
            self.assertIn("key=value", payload["result"]["content"])

    def test_write_config_file_requires_confirmation_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            managed_root = state_dir / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "app.ini"
            config_path.write_text("[main]\nkey=old\n", encoding="utf-8")

            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            pending = app.run_tool(
                "write_config_file",
                {"path": str(config_path), "content": "[main]\nkey=new\n"},
            )
            self.assertFalse(pending["ok"])
            self.assertTrue(pending["pending_confirmation"])
            self.assertIn("--confirm", pending["approval"]["cli_command"])
            approval_id = pending["approval"]["id"]
            approval = app.get_tool_approval(int(approval_id))
            self.assertEqual(approval["status"], "pending")

            confirmed = app.run_tool(
                "write_config_file",
                {"path": str(config_path), "content": "[main]\nkey=new\n"},
                confirmed=True,
            )
            self.assertTrue(confirmed["ok"])
            self.assertTrue(confirmed["result"]["changed"])
            self.assertIsNotNone(confirmed["result"]["backup_path"])
            self.assertEqual(config_path.read_text(encoding="utf-8"), "[main]\nkey=new\n")
            resolved_approval = app.get_tool_approval(int(approval_id))
            self.assertEqual(resolved_approval["status"], "completed")
            self.assertTrue(resolved_approval["execution"]["ok"])

    def test_restore_config_backup_restores_previous_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            managed_root = state_dir / "managed-configs"
            managed_root.mkdir(parents=True, exist_ok=True)
            config_path = managed_root / "app.ini"
            config_path.write_text("[main]\nkey=old\n", encoding="utf-8")

            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            write_payload = app.run_tool(
                "write_config_file",
                {"path": str(config_path), "content": "[main]\nkey=new\n"},
                confirmed=True,
            )
            backup_path = write_payload["result"]["backup_path"]

            restore_payload = app.run_tool(
                "restore_config_backup",
                {"path": str(config_path), "backup_path": backup_path},
                confirmed=True,
            )

            self.assertTrue(restore_payload["ok"])
            self.assertEqual(config_path.read_text(encoding="utf-8"), "[main]\nkey=old\n")

    def test_write_config_file_rejects_paths_outside_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="none",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            payload = app.run_tool(
                "write_config_file",
                {"path": str(state_dir / "outside.ini"), "content": "[main]\nkey=value\n"},
                confirmed=True,
            )

            self.assertFalse(payload["ok"])
            self.assertIn("not managed by the config policy", payload["error"])


if __name__ == "__main__":
    unittest.main()
