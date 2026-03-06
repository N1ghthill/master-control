#!/usr/bin/env python3
"""Security-focused tests for privileged action loading."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mastercontrol.runtime.root_exec import (
    DEFAULT_ETC_ACTIONS,
    DEFAULT_REPO_ACTIONS,
    ensure_trusted_actions_file,
    resolve_actions_file,
)


class RootExecSecurityTests(unittest.TestCase):
    def test_resolve_actions_prefers_etc_for_root(self) -> None:
        with patch("mastercontrol.runtime.root_exec.os.geteuid", return_value=0):
            resolved = resolve_actions_file(None)
        self.assertEqual(resolved, DEFAULT_ETC_ACTIONS)

    def test_resolve_actions_uses_repo_fallback_for_non_root(self) -> None:
        with (
            patch("mastercontrol.runtime.root_exec.os.geteuid", return_value=1000),
            patch("mastercontrol.runtime.root_exec.Path.exists", return_value=False),
        ):
            resolved = resolve_actions_file(None)
        self.assertEqual(resolved, DEFAULT_REPO_ACTIONS)

    def test_trusted_actions_file_rejects_path_outside_trusted_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "actions.json"
            path.write_text('{"version":1,"actions":{}}', encoding="utf-8")

            with self.assertRaises(PermissionError):
                ensure_trusted_actions_file(path)

    def test_trusted_actions_file_rejects_non_root_owned_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trusted_dir = Path(tmp)
            path = trusted_dir / "actions.json"
            path.write_text('{"version":1,"actions":{}}', encoding="utf-8")

            with patch("mastercontrol.runtime.root_exec.TRUSTED_ACTIONS_DIR", trusted_dir):
                with self.assertRaises(PermissionError):
                    ensure_trusted_actions_file(path)


if __name__ == "__main__":
    unittest.main()
