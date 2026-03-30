from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from master_control.bootstrap_validation import run_bootstrap_validation

FIXED_NOW = datetime(2026, 3, 20, 11, 45, 12, tzinfo=timezone.utc)


def _argument_value(command: tuple[str, ...], flag: str) -> str:
    index = command.index(flag)
    return command[index + 1]


class BootstrapValidationTest(unittest.TestCase):
    def test_run_bootstrap_validation_writes_report_and_confirms_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            repo_root.mkdir()
            (repo_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (repo_root / "uninstall.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            output_dir = Path(tmp_dir) / "reports"

            def fake_run(
                command: tuple[str, ...],
                *,
                cwd: Path,
                text: bool,
                capture_output: bool,
                check: bool,
            ) -> subprocess.CompletedProcess[str]:
                del cwd, text, capture_output, check
                executable = command[0]
                if executable.endswith("uninstall.sh"):
                    prefix = Path(_argument_value(command, "--prefix"))
                    bin_dir = Path(_argument_value(command, "--bin-dir"))
                    state_dir = Path(_argument_value(command, "--state-dir"))
                    wrapper_path = bin_dir / "mc"
                    manifest_path = prefix / "install-manifest.env"
                    venv_dir = prefix / "venv"
                    if wrapper_path.exists():
                        wrapper_path.unlink()
                    if manifest_path.exists():
                        manifest_path.unlink()
                    if venv_dir.exists():
                        for child in sorted(venv_dir.rglob("*"), reverse=True):
                            if child.is_file():
                                child.unlink()
                            else:
                                child.rmdir()
                        venv_dir.rmdir()
                    if state_dir.exists():
                        state_dir.rmdir()
                    return subprocess.CompletedProcess(command, 0, "removed\n", "")
                if executable.endswith("install.sh"):
                    prefix = Path(_argument_value(command, "--prefix"))
                    bin_dir = Path(_argument_value(command, "--bin-dir"))
                    state_dir = Path(_argument_value(command, "--state-dir"))
                    (prefix / "venv").mkdir(parents=True, exist_ok=True)
                    bin_dir.mkdir(parents=True, exist_ok=True)
                    state_dir.mkdir(parents=True, exist_ok=True)
                    (bin_dir / "mc").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
                    (prefix / "install-manifest.env").write_text("manifest\n", encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, "installed\n", "")
                if executable.endswith("/mc") and command[2] == "doctor":
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        json.dumps({"ok": True, "provider": "heuristic"}),
                        "",
                    )
                if executable.endswith("/mc") and command[2] == "validate-host-profile":
                    report_path = (
                        Path(_argument_value(command, "--output-dir"))
                        / "20260320T114512Z-beta-host"
                        / "report.json"
                    )
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    payload = {
                        "overall_ok": True,
                        "report_path": str(report_path),
                    }
                    report_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
                raise AssertionError(f"Unexpected command: {command}")

            with patch("master_control.bootstrap_validation._utc_now", return_value=FIXED_NOW):
                with patch(
                    "master_control.bootstrap_validation.socket.gethostname",
                    return_value="Beta Host",
                ):
                    with patch(
                        "master_control.bootstrap_validation._build_host_profile",
                        return_value={
                            "hostname": "beta-host",
                            "system": "Linux",
                            "python": "3.13.12",
                        },
                    ):
                        with patch(
                            "master_control.bootstrap_validation.subprocess.run",
                            side_effect=fake_run,
                        ):
                            result = run_bootstrap_validation(
                                output_dir=output_dir,
                                repo_root=repo_root,
                            )

            expected_run_dir = output_dir / "20260320T114512Z-beta-host"
            expected_report_path = expected_run_dir / "report.json"
            self.assertEqual(result.report_path, expected_report_path)
            self.assertTrue(expected_report_path.exists())
            self.assertTrue(result.report["overall_ok"])
            self.assertEqual(result.report["repo_root"], str(repo_root.resolve()))
            self.assertTrue(result.report["commands"]["install"]["ok"])
            self.assertTrue(result.report["commands"]["doctor"]["ok"])
            self.assertTrue(result.report["commands"]["validate_host_profile"]["ok"])
            self.assertTrue(result.report["commands"]["uninstall"]["ok"])
            self.assertEqual(
                result.report["commands"]["doctor"]["payload"]["provider"], "heuristic"
            )
            self.assertTrue(
                result.report["commands"]["validate_host_profile"]["payload"]["overall_ok"]
            )
            self.assertTrue(result.report["cleanup"]["wrapper_missing"])
            self.assertTrue(result.report["cleanup"]["venv_missing"])
            self.assertTrue(result.report["cleanup"]["state_missing"])
            self.assertTrue(result.report["cleanup"]["manifest_missing"])

            report_on_disk = json.loads(expected_report_path.read_text(encoding="utf-8"))
            self.assertEqual(report_on_disk, result.report)

    def test_run_bootstrap_validation_fails_when_inner_validation_or_cleanup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            repo_root.mkdir()
            (repo_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (repo_root / "uninstall.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            output_dir = Path(tmp_dir) / "reports"

            def fake_run(
                command: tuple[str, ...],
                *,
                cwd: Path,
                text: bool,
                capture_output: bool,
                check: bool,
            ) -> subprocess.CompletedProcess[str]:
                del cwd, text, capture_output, check
                executable = command[0]
                if executable.endswith("uninstall.sh"):
                    prefix = Path(_argument_value(command, "--prefix"))
                    state_dir = Path(_argument_value(command, "--state-dir"))
                    manifest_path = prefix / "install-manifest.env"
                    if manifest_path.exists():
                        manifest_path.unlink()
                    if state_dir.exists():
                        state_dir.rmdir()
                    return subprocess.CompletedProcess(command, 0, "removed\n", "")
                if executable.endswith("install.sh"):
                    prefix = Path(_argument_value(command, "--prefix"))
                    bin_dir = Path(_argument_value(command, "--bin-dir"))
                    state_dir = Path(_argument_value(command, "--state-dir"))
                    (prefix / "venv").mkdir(parents=True, exist_ok=True)
                    bin_dir.mkdir(parents=True, exist_ok=True)
                    state_dir.mkdir(parents=True, exist_ok=True)
                    (bin_dir / "mc").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
                    (prefix / "install-manifest.env").write_text("manifest\n", encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, "installed\n", "")
                if executable.endswith("/mc") and command[2] == "doctor":
                    return subprocess.CompletedProcess(command, 0, json.dumps({"ok": True}), "")
                if executable.endswith("/mc") and command[2] == "validate-host-profile":
                    payload = {
                        "overall_ok": False,
                        "report_path": str(
                            Path(_argument_value(command, "--output-dir")) / "bad" / "report.json"
                        ),
                    }
                    return subprocess.CompletedProcess(command, 1, json.dumps(payload), "")
                raise AssertionError(f"Unexpected command: {command}")

            with patch("master_control.bootstrap_validation._utc_now", return_value=FIXED_NOW):
                with patch(
                    "master_control.bootstrap_validation.socket.gethostname",
                    return_value="Beta Host",
                ):
                    with patch(
                        "master_control.bootstrap_validation._build_host_profile",
                        return_value={"hostname": "beta-host"},
                    ):
                        with patch(
                            "master_control.bootstrap_validation.subprocess.run",
                            side_effect=fake_run,
                        ):
                            result = run_bootstrap_validation(
                                output_dir=output_dir,
                                repo_root=repo_root,
                            )

            self.assertFalse(result.report["overall_ok"])
            self.assertTrue(result.report["commands"]["install"]["ok"])
            self.assertTrue(result.report["commands"]["doctor"]["ok"])
            self.assertFalse(result.report["commands"]["validate_host_profile"]["ok"])
            self.assertTrue(result.report["commands"]["uninstall"]["ok"])
            self.assertFalse(result.report["cleanup"]["ok"])
            self.assertFalse(result.report["cleanup"]["wrapper_missing"])
            self.assertFalse(result.report["cleanup"]["venv_missing"])

    def test_run_bootstrap_validation_requires_repo_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(ValueError):
                run_bootstrap_validation(
                    output_dir=Path(tmp_dir) / "reports",
                    repo_root=Path(tmp_dir) / "missing-repo",
                )


if __name__ == "__main__":
    unittest.main()
