from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class InstallScriptsIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.install_script = cls.repo_root / "install.sh"
        cls.uninstall_script = cls.repo_root / "uninstall.sh"

    def test_install_and_uninstall_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prefix = root / "prefix"
            bin_dir = root / "bin"
            state_dir = root / "state"
            wrapper_path = bin_dir / "mc"

            first_install = self._run_script(
                self.install_script,
                "--prefix",
                str(prefix),
                "--bin-dir",
                str(bin_dir),
                "--state-dir",
                str(state_dir),
                "--python",
                sys.executable,
                "--provider",
                "heuristic",
            )
            self.assertEqual(first_install.returncode, 0, self._render_failure(first_install))
            self.assertTrue(wrapper_path.exists())
            self.assertIn(
                "# master-control-wrapper: managed",
                wrapper_path.read_text(encoding="utf-8"),
            )

            second_install = self._run_script(
                self.install_script,
                "--prefix",
                str(prefix),
                "--bin-dir",
                str(bin_dir),
                "--state-dir",
                str(state_dir),
                "--python",
                sys.executable,
                "--provider",
                "heuristic",
            )
            self.assertEqual(second_install.returncode, 0, self._render_failure(second_install))
            self.assertTrue(wrapper_path.exists())

            first_uninstall = self._run_script(
                self.uninstall_script,
                "--prefix",
                str(prefix),
                "--bin-dir",
                str(bin_dir),
                "--state-dir",
                str(state_dir),
                "--purge-state",
            )
            self.assertEqual(first_uninstall.returncode, 0, self._render_failure(first_uninstall))
            self.assertFalse(wrapper_path.exists())
            self.assertFalse((prefix / "venv").exists())
            self.assertFalse(state_dir.exists())

            second_uninstall = self._run_script(
                self.uninstall_script,
                "--prefix",
                str(prefix),
                "--bin-dir",
                str(bin_dir),
                "--state-dir",
                str(state_dir),
                "--purge-state",
            )
            self.assertEqual(second_uninstall.returncode, 0, self._render_failure(second_uninstall))
            self.assertFalse(wrapper_path.exists())

    def test_install_refuses_to_overwrite_unmanaged_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prefix = root / "prefix"
            bin_dir = root / "bin"
            state_dir = root / "state"
            wrapper_path = bin_dir / "mc"
            bin_dir.mkdir(parents=True, exist_ok=True)
            wrapper_path.write_text("#!/usr/bin/env bash\necho foreign-wrapper\n", encoding="utf-8")

            install_result = self._run_script(
                self.install_script,
                "--prefix",
                str(prefix),
                "--bin-dir",
                str(bin_dir),
                "--state-dir",
                str(state_dir),
                "--python",
                sys.executable,
                "--provider",
                "heuristic",
            )
            self.assertNotEqual(install_result.returncode, 0)
            self.assertIn("not managed by Master Control", install_result.stderr)
            self.assertEqual(
                wrapper_path.read_text(encoding="utf-8"),
                "#!/usr/bin/env bash\necho foreign-wrapper\n",
            )
            self.assertFalse((prefix / "venv").exists())

    def _run_script(self, script_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        return subprocess.run(
            [str(script_path), *args],
            cwd=self.repo_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def _render_failure(self, result: subprocess.CompletedProcess[str]) -> str:
        return (
            f"exit={result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
