from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from master_control.bootstrap_prereqs import collect_bootstrap_python_diagnostics


class BootstrapPrereqsTest(unittest.TestCase):
    def test_collect_bootstrap_python_diagnostics_reports_actionable_debian_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            os_release_path = Path(tmp_dir) / "os-release"
            os_release_path.write_text('ID="debian"\n', encoding="utf-8")

            def fake_run(command: list[str], *, capture_output: bool, text: bool, check: bool):
                del capture_output, text, check
                if command[1:] == [
                    "-c",
                    "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
                ]:
                    return _CompletedProcess(0, "3.11.9\n", "")
                if command[1:] == ["-c", "import ensurepip"]:
                    return _CompletedProcess(1, "", "No module named ensurepip")
                raise AssertionError(f"Unexpected command: {command}")

            with patch("master_control.bootstrap_prereqs.OS_RELEASE_PATH", os_release_path):
                with patch(
                    "master_control.bootstrap_prereqs.shutil.which", return_value="/usr/bin/python3"
                ):
                    with patch(
                        "master_control.bootstrap_prereqs.subprocess.run", side_effect=fake_run
                    ):
                        diagnostics = collect_bootstrap_python_diagnostics("python3")

        self.assertTrue(diagnostics["python_found"])
        self.assertTrue(diagnostics["meets_minimum"])
        self.assertFalse(diagnostics["ensurepip_available"])
        self.assertEqual(diagnostics["install_hint"], "run: apt install python3.11-venv")
        self.assertIn(
            "python3 3.11.9 found, but stdlib venv is unavailable", diagnostics["summary"]
        )

    def test_collect_bootstrap_python_diagnostics_reports_ready_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            os_release_path = Path(tmp_dir) / "os-release"
            os_release_path.write_text('ID="debian"\n', encoding="utf-8")

            def fake_run(command: list[str], *, capture_output: bool, text: bool, check: bool):
                del capture_output, text, check
                if command[1:] == [
                    "-c",
                    "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
                ]:
                    return _CompletedProcess(0, "3.11.9\n", "")
                if command[1:] == ["-c", "import ensurepip"]:
                    return _CompletedProcess(0, "", "")
                raise AssertionError(f"Unexpected command: {command}")

            with patch("master_control.bootstrap_prereqs.OS_RELEASE_PATH", os_release_path):
                with patch(
                    "master_control.bootstrap_prereqs.shutil.which", return_value="/usr/bin/python3"
                ):
                    with patch(
                        "master_control.bootstrap_prereqs.subprocess.run", side_effect=fake_run
                    ):
                        diagnostics = collect_bootstrap_python_diagnostics("python3")

        self.assertTrue(diagnostics["venv_ready"])
        self.assertIsNone(diagnostics["install_hint"])
        self.assertEqual(
            diagnostics["summary"],
            "python3 3.11.9 ready for stdlib venv bootstrap.",
        )

    def test_collect_bootstrap_python_diagnostics_reports_missing_python(self) -> None:
        with patch("master_control.bootstrap_prereqs.shutil.which", return_value=None):
            diagnostics = collect_bootstrap_python_diagnostics("python3")

        self.assertFalse(diagnostics["python_found"])
        self.assertEqual(diagnostics["summary"], "python3 not found on PATH.")


class _CompletedProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
