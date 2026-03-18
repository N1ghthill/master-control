from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from master_control.app import MasterControlApp
from master_control.cli import main
from master_control.config import Settings


class CliObservationCommandTest(unittest.TestCase):
    def test_observations_command_renders_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "memory_usage",
                "memory",
                {"memory_used_percent": 12.0, "swap_used_percent": 0.0},
                observed_at="2026-03-18T01:00:00Z",
                ttl_seconds=300,
            )

            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "MC_STATE_DIR": tmp_dir,
                    "MC_DB_PATH": str(state_dir / "mc.sqlite3"),
                    "MC_PROVIDER": "heuristic",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    exit_code = main(["--json", "observations", "--session-id", str(session_id)])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["session_id"], session_id)
            self.assertEqual(payload["observations"][0]["key"], "memory")

    def test_observations_command_renders_text_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=state_dir,
                db_path=state_dir / "mc.sqlite3",
            )
            app = MasterControlApp(settings)
            app.bootstrap()
            session_id = app.store.create_session()
            app.store.record_observation(
                session_id,
                "service_status",
                "service",
                {"service": "nginx", "scope": "system"},
                observed_at="2026-03-18T01:00:00Z",
                ttl_seconds=180,
            )

            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "MC_STATE_DIR": tmp_dir,
                    "MC_DB_PATH": str(state_dir / "mc.sqlite3"),
                    "MC_PROVIDER": "heuristic",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    exit_code = main(["observations", "--session-id", str(session_id)])

            output = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn(f"Session {session_id} observations", output)
            self.assertIn("service:", output)
            self.assertIn("source=service_status", output)


if __name__ == "__main__":
    unittest.main()
