from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from master_control.app import MasterControlApp
from master_control.config import Settings


class RuntimePolicyIntegrationTest(unittest.TestCase):
    def test_policy_can_disable_tool_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            policy_path = state_dir / "policy.toml"
            policy_path.write_text(
                textwrap.dedent(
                    """
                    version = 1

                    [tools.system_info]
                    enabled = false
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            app = self._build_app(state_dir, policy_path=policy_path)
            payload = app.run_tool("system_info")

            self.assertFalse(payload["ok"])
            self.assertIn("disabled by operator policy", payload["error"])
            self.assertTrue(app.doctor()["policy_diagnostics"]["ok"])

    def test_policy_can_require_confirmation_for_read_only_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            policy_path = state_dir / "policy.toml"
            policy_path.write_text(
                textwrap.dedent(
                    """
                    version = 1

                    [tools.system_info]
                    require_confirmation = true
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            app = self._build_app(state_dir, policy_path=policy_path)
            pending = app.run_tool("system_info")

            self.assertFalse(pending["ok"])
            self.assertTrue(pending["pending_confirmation"])

            confirmed = app.run_tool("system_info", confirmed=True)
            self.assertTrue(confirmed["ok"])

    def test_policy_can_constrain_service_targets_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            policy_path = state_dir / "policy.toml"
            policy_path.write_text(
                textwrap.dedent(
                    """
                    version = 1

                    [tools.restart_service]
                    allowed_scopes = ["system"]
                    service_patterns = ["demo.service"]
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            app = self._build_app(state_dir, policy_path=policy_path)
            payload = app.run_tool(
                "restart_service",
                {"name": "nginx.service", "scope": "system"},
                confirmed=True,
            )

            self.assertFalse(payload["ok"])
            self.assertIn("limited by policy", payload["error"])

    def test_policy_can_define_custom_config_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            policy_path = state_dir / "policy.toml"
            custom_root = state_dir / "custom-configs"
            custom_root.mkdir(parents=True, exist_ok=True)
            config_path = custom_root / "service.ini"
            config_path.write_text("[service]\nmode=old\n", encoding="utf-8")

            policy_path.write_text(
                textwrap.dedent(
                    """
                    version = 1

                    [[config_targets]]
                    name = "custom_ini"
                    description = "Operator-managed custom INI files."
                    roots = ["$STATE_DIR/custom-configs"]
                    file_globs = ["*.ini"]
                    validator = "ini_parse"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            app = self._build_app(state_dir, policy_path=policy_path)
            payload = app.run_tool(
                "write_config_file",
                {"path": str(config_path), "content": "[service]\nmode=new\n"},
                confirmed=True,
            )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["result"]["target"], "custom_ini")
            self.assertEqual(config_path.read_text(encoding="utf-8"), "[service]\nmode=new\n")

    def test_invalid_policy_fails_closed_and_surfaces_in_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            policy_path = state_dir / "policy.toml"
            policy_path.write_text('version = "broken"\n', encoding="utf-8")

            app = self._build_app(state_dir, policy_path=policy_path)
            doctor = app.doctor()
            payload = app.run_tool("system_info")

            self.assertFalse(doctor["ok"])
            self.assertFalse(doctor["policy_diagnostics"]["ok"])
            self.assertIn("must be an integer", doctor["policy_diagnostics"]["error"])
            self.assertFalse(payload["ok"])
            self.assertIn("Policy load error", payload["error"])

    def _build_app(self, state_dir: Path, *, policy_path: Path) -> MasterControlApp:
        settings = Settings(
            app_name="master-control",
            log_level="INFO",
            provider="none",
            state_dir=state_dir,
            db_path=state_dir / "mc.sqlite3",
            policy_path=policy_path,
        )
        return MasterControlApp(settings)


if __name__ == "__main__":
    unittest.main()
