from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from master_control.config import Settings
from master_control.providers.base import ConversationMessage, ProviderRequest
from master_control.providers.ollama_chat import OllamaChatProvider, TransportResponse
from master_control.tools.base import RiskLevel, ToolSpec


class OllamaChatProviderTest(unittest.TestCase):
    def test_provider_parses_structured_plan_response(self) -> None:
        captured_payload: dict[str, object] = {}

        def fake_transport(
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
            timeout_s: float,
        ) -> TransportResponse:
            del url, headers, timeout_s
            captured_payload.update(payload)
            body = {
                "model": "qwen2.5:7b",
                "done": True,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "message": "Vou verificar a memória.",
                            "intent": "inspect_memory",
                            "steps": [
                                {
                                    "tool_name": "memory_usage",
                                    "rationale": "Check RAM pressure.",
                                    "arguments": {},
                                }
                            ],
                        }
                    ),
                },
            }
            return TransportResponse(
                status_code=200,
                body=json.dumps(body),
                headers={},
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="ollama",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
                ollama_model="qwen2.5:7b",
            )
            provider = OllamaChatProvider(settings, transport=fake_transport)
            request = ProviderRequest(
                user_message="mostre o uso de memoria",
                available_tools=(
                    ToolSpec(
                        name="memory_usage",
                        description="Inspect RAM usage.",
                        risk=RiskLevel.READ_ONLY,
                    ),
                ),
                conversation_history=(
                    ConversationMessage(role="user", content="como esta o host?"),
                    ConversationMessage(role="assistant", content="Posso verificar memória ou disco."),
                ),
                session_summary="tracked_unit: ssh\nlast_intent: inspect_logs",
            )

            response = provider.plan(request)

            self.assertEqual(response.message, "Vou verificar a memória.")
            self.assertEqual(response.plan.intent, "inspect_memory")
            self.assertEqual(response.plan.steps[0].tool_name, "memory_usage")
            self.assertEqual(captured_payload["format"]["type"], "object")
            self.assertFalse(captured_payload["stream"])
            self.assertEqual(captured_payload["messages"][0]["role"], "system")
            self.assertIn("Local session summary:", captured_payload["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
