from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from master_control.config import Settings
from master_control.providers.availability import (
    HttpResponse,
    probe_ollama,
    resolve_auto_provider_backend,
)
from master_control.providers.factory import build_provider


class ProviderAvailabilityTest(unittest.TestCase):
    def test_probe_ollama_reports_installed_model(self) -> None:
        def fake_transport(
            url: str,
            headers: dict[str, str],
            timeout_s: float,
        ) -> HttpResponse:
            del url, headers, timeout_s
            body = {
                "models": [
                    {"name": "qwen2.5:7b"},
                    {"name": "qwen3:4b-instruct-2507-q4_K_M"},
                ]
            }
            return HttpResponse(status_code=200, body=json.dumps(body), headers={})

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="ollama",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
                ollama_model="qwen2.5:7b",
            )

            payload = probe_ollama(
                settings,
                transport=fake_transport,
                binary_lookup=lambda name: "/usr/bin/ollama" if name == "ollama" else None,
            )

        self.assertTrue(payload["available"])
        self.assertTrue(payload["model_present"])
        self.assertTrue(payload["binary_in_path"])
        self.assertIn("installed", payload["summary"])

    def test_probe_ollama_reports_unreachable_endpoint(self) -> None:
        def failing_transport(
            url: str,
            headers: dict[str, str],
            timeout_s: float,
        ) -> HttpResponse:
            del url, headers, timeout_s
            raise urllib.error.URLError("connection refused")

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="ollama",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
                ollama_model="qwen2.5:7b",
            )

            payload = probe_ollama(
                settings,
                transport=failing_transport,
                binary_lookup=lambda name: None,
            )

        self.assertFalse(payload["available"])
        self.assertFalse(payload["binary_in_path"])
        self.assertIn("connection refused", payload["summary"])

    def test_resolve_auto_prefers_ollama_before_openai(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="auto",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
                openai_api_key="test-key",
            )

            backend = resolve_auto_provider_backend(
                settings,
                checks={
                    "ollama": {"available": True},
                    "openai": {"available": True},
                    "heuristic": {"available": True},
                    "noop": {"available": True},
                },
            )

        self.assertEqual(backend, "ollama")

    def test_factory_uses_heuristic_when_auto_has_no_llm_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="auto",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )

            with patch(
                "master_control.providers.factory.collect_provider_checks",
                return_value={
                    "ollama": {"available": False},
                    "openai": {"available": False},
                    "heuristic": {"available": True},
                    "noop": {"available": True},
                },
            ):
                provider = build_provider(settings)

        self.assertEqual(provider.name, "heuristic")


if __name__ == "__main__":
    unittest.main()
