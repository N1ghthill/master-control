from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from master_control.validation_bundle import create_validation_bundle


class ValidationBundleTest(unittest.TestCase):
    def test_create_validation_bundle_redacts_sensitive_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            report_dir = tmp_path / "host-validation" / "20260320T120000Z-rainbow"
            report_dir.mkdir(parents=True)
            report_path = report_dir / "report.json"
            payload = {
                "generated_at": "2026-03-20T12:00:00+00:00",
                "overall_ok": True,
                "repo_root": "/home/alice/src/master-control",
                "run_dir": str(report_dir),
                "report_path": str(report_path),
                "host_profile": {
                    "hostname": "rainbow",
                    "system": "Linux",
                    "release": "6.12.0",
                    "python": "3.13.1",
                },
                "settings": {
                    "provider": "heuristic",
                    "state_dir": f"{report_dir}/state",
                    "db_path": f"{report_dir}/state/mc.sqlite3",
                },
                "doctor": {
                    "ok": True,
                    "provider": "heuristic",
                    "state_dir": f"{report_dir}/state",
                    "db_path": f"{report_dir}/state/mc.sqlite3",
                    "store_diagnostics": {
                        "path": f"{report_dir}/state/mc.sqlite3",
                    },
                    "provider_checks": {
                        "ollama": {
                            "binary_path": "/home/alice/.local/bin/ollama",
                        }
                    },
                },
                "baseline": {
                    "enabled": True,
                    "all_ok": True,
                    "commands": [],
                },
                "workflows": {
                    "slow_host": {
                        "ok": True,
                        "executed_tools": ["memory_usage", "top_processes"],
                        "message_excerpt": "Resumo do diagnóstico em rainbow.",
                    },
                    "failed_service": {
                        "ok": True,
                        "executed_tools": ["failed_services"],
                        "failed_services_tool": {"unit_count": 1, "status": "ok"},
                        "notes": ["Host returned one failed service."],
                    },
                    "managed_config": {
                        "ok": True,
                        "config_path": f"{report_dir}/state/managed-configs/app.ini",
                        "backup_path": f"{report_dir}/state/config-backups/app.ini.bak",
                        "recommendation_keys_after_write": [
                            "config_verification_available",
                        ],
                    },
                },
            }
            report_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

            artifacts = create_validation_bundle(
                report_path=report_path,
                output_dir=tmp_path / "bundles",
            )

            self.assertTrue(artifacts.bundle_dir.exists())
            self.assertTrue(artifacts.archive_path.exists())
            self.assertTrue(artifacts.redacted_report_path.exists())
            self.assertTrue(artifacts.summary_path.exists())

            redacted = json.loads(artifacts.redacted_report_path.read_text(encoding="utf-8"))
            self.assertEqual(redacted["host_profile"]["hostname"], "<redacted-host>")
            self.assertEqual(redacted["repo_root"], "<repo-root>")
            self.assertEqual(redacted["run_dir"], "<validation-run>")
            self.assertEqual(redacted["report_path"], "<report-path>")
            self.assertEqual(redacted["settings"]["state_dir"], "<state-dir>")
            self.assertEqual(redacted["settings"]["db_path"], "<db-path>")
            self.assertEqual(
                redacted["workflows"]["managed_config"]["config_path"],
                "<managed-config-path>",
            )
            self.assertEqual(
                redacted["workflows"]["managed_config"]["backup_path"],
                "<managed-config-backup>",
            )
            self.assertEqual(
                redacted["doctor"]["provider_checks"]["ollama"]["binary_path"],
                "<abs-path>",
            )
            self.assertNotIn("rainbow", json.dumps(redacted))
            self.assertNotIn("/home/alice", json.dumps(redacted))

            summary = artifacts.summary_path.read_text(encoding="utf-8")
            self.assertIn("overall_ok: True", summary)
            self.assertIn("slow_host: ok", summary)
            self.assertIn("failed_service: ok", summary)
            self.assertIn("managed_config: ok", summary)
            self.assertIn("Host returned one failed service.", summary)
            self.assertNotIn("rainbow", summary)
            self.assertNotIn("/home/alice", summary)


if __name__ == "__main__":
    unittest.main()
