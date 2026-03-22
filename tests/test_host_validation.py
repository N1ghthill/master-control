from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from master_control.config import Settings
from master_control.host_validation import CommandResult, run_host_validation

FIXED_NOW = datetime(2026, 3, 19, 20, 27, 19, tzinfo=timezone.utc)


class FakeApp:
    instances: list["FakeApp"] = []

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bootstrap_called = False
        type(self).instances.append(self)

    def bootstrap(self) -> None:
        self.bootstrap_called = True

    def doctor(self) -> dict[str, object]:
        return {
            "ok": True,
            "provider": self.settings.provider,
        }


class HostValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeApp.instances.clear()

    def test_run_host_validation_writes_report_and_scopes_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "reports"
            base_settings = Settings(
                app_name="master-control",
                log_level="DEBUG",
                provider="openai",
                state_dir=Path(tmp_dir) / "base-state",
                db_path=Path(tmp_dir) / "base-state" / "mc.sqlite3",
            )

            with patch("master_control.host_validation.MasterControlApp", FakeApp):
                with patch("master_control.host_validation._utc_now", return_value=FIXED_NOW):
                    with patch(
                        "master_control.host_validation.socket.gethostname",
                        return_value="Beta Host",
                    ):
                        with patch(
                            "master_control.host_validation._build_host_profile",
                            return_value={
                                "hostname": "beta-host",
                                "system": "Linux",
                                "python": "3.13.12",
                            },
                        ):
                            with patch(
                                "master_control.host_validation._validate_slow_host_workflow",
                                return_value={"ok": True, "step": "slow_host"},
                            ):
                                with patch(
                                    "master_control.host_validation._validate_failed_service_workflow",
                                    return_value={"ok": True, "step": "failed_service"},
                                ):
                                    with patch(
                                        "master_control.host_validation._validate_managed_config_workflow",
                                        return_value={"ok": True, "step": "managed_config"},
                                    ):
                                        result = run_host_validation(
                                            output_dir=output_dir,
                                            provider="heuristic",
                                            base_settings=base_settings,
                                        )

            self.assertEqual(len(FakeApp.instances), 1)
            app = FakeApp.instances[0]
            expected_run_dir = output_dir / "20260319T202719Z-beta-host"
            expected_state_dir = expected_run_dir / "state"
            expected_report_path = expected_run_dir / "report.json"

            self.assertTrue(app.bootstrap_called)
            self.assertEqual(app.settings.provider, "heuristic")
            self.assertEqual(app.settings.log_level, "DEBUG")
            self.assertEqual(app.settings.state_dir, expected_state_dir)
            self.assertEqual(app.settings.db_path, expected_state_dir / "mc.sqlite3")
            self.assertEqual(result.report_path, expected_report_path)
            self.assertTrue(expected_report_path.exists())
            self.assertTrue(result.report["overall_ok"])
            self.assertEqual(result.report["report_path"], str(expected_report_path))
            self.assertEqual(result.report["repo_root"], str(Path.cwd().resolve()))
            self.assertFalse(result.report["baseline"]["enabled"])
            self.assertEqual(result.report["baseline"]["commands"], [])
            self.assertEqual(result.report["settings"]["provider"], "heuristic")
            self.assertEqual(result.report["settings"]["state_dir"], str(expected_state_dir))

            report_on_disk = json.loads(expected_report_path.read_text(encoding="utf-8"))
            self.assertEqual(report_on_disk, result.report)

    def test_run_host_validation_fails_when_baseline_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "reports"

            with patch("master_control.host_validation.MasterControlApp", FakeApp):
                with patch("master_control.host_validation._utc_now", return_value=FIXED_NOW):
                    with patch(
                        "master_control.host_validation.socket.gethostname",
                        return_value="Beta Host",
                    ):
                        with patch(
                            "master_control.host_validation._build_host_profile",
                            return_value={"hostname": "beta-host"},
                        ):
                            with patch(
                                "master_control.host_validation._validate_slow_host_workflow",
                                return_value={"ok": True},
                            ):
                                with patch(
                                    "master_control.host_validation._validate_failed_service_workflow",
                                    return_value={"ok": True},
                                ):
                                    with patch(
                                        "master_control.host_validation._validate_managed_config_workflow",
                                        return_value={"ok": True},
                                    ):
                                        with patch(
                                            "master_control.host_validation._run_baseline_commands",
                                            return_value=(
                                                CommandResult(
                                                    command="ruff",
                                                    exit_code=0,
                                                    stdout="",
                                                    stderr="",
                                                ),
                                                CommandResult(
                                                    command="pytest",
                                                    exit_code=1,
                                                    stdout="",
                                                    stderr="failed",
                                                ),
                                            ),
                                        ):
                                            result = run_host_validation(
                                                output_dir=output_dir,
                                                run_baseline=True,
                                            )

            self.assertFalse(result.report["overall_ok"])
            self.assertTrue(result.report["baseline"]["enabled"])
            self.assertFalse(result.report["baseline"]["all_ok"])
            self.assertEqual(
                [item["ok"] for item in result.report["baseline"]["commands"]],
                [True, False],
            )


if __name__ == "__main__":
    unittest.main()
