from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from master_control.config import Settings
from master_control.agent.observations import build_observation_freshness
from master_control.providers.base import ConversationMessage, ProviderRequest, SynthesisRequest
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
                            "decision": {
                                "state": "needs_tools",
                                "kind": "inspection_request",
                                "reason": "Memory data is required before answering.",
                            },
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
                observation_freshness=build_observation_freshness(
                    (
                        {
                            "source": "service_status",
                            "key": "service",
                            "value": {"service": "ssh", "scope": "system"},
                            "observed_at": "2026-03-17T20:00:00Z",
                            "expires_at": "2026-03-17T20:03:00Z",
                        },
                    )
                ),
            )

            response = provider.plan(request)

            self.assertEqual(response.message, "Vou verificar a memória.")
            self.assertEqual(response.decision.state, "needs_tools")
            self.assertEqual(response.decision.kind, "inspection_request")
            self.assertEqual(response.plan.intent, "inspect_memory")
            self.assertEqual(response.plan.steps[0].tool_name, "memory_usage")
            self.assertEqual(captured_payload["format"]["type"], "object")
            self.assertFalse(captured_payload["stream"])
            self.assertEqual(captured_payload["messages"][0]["role"], "system")
            self.assertIn("Local session summary:", captured_payload["messages"][0]["content"])
            self.assertIn("Observation freshness:", captured_payload["messages"][0]["content"])
            self.assertIn("service", captured_payload["messages"][0]["content"])
            self.assertIn("Always set decision.state", captured_payload["messages"][0]["content"])
            self.assertIn("do not answer from memory alone", captured_payload["messages"][0]["content"])
            self.assertIn("decision", captured_payload["format"]["required"])

    def test_provider_can_synthesize_final_response(self) -> None:
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
                            "message": "A memória está alta e os processos quentes já foram identificados.",
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

            response = provider.synthesize(
                SynthesisRequest(
                    user_message="o host esta lento",
                    planning_message="Vou verificar a memória e os processos.",
                    execution_observations=("memory_usage({}) -> memory=92.0%, swap=10.0%",),
                    rendered_results=(
                        "Memória usada: 92.0% (92 B de 100 B). Swap usada: 10.0% (10 B de 100 B).",
                    ),
                )
            )

            self.assertEqual(
                response.message,
                "A memória está alta e os processos quentes já foram identificados.",
            )
            self.assertEqual(response.metadata["purpose"], "response_synthesis")
            self.assertEqual(captured_payload["format"]["required"], ["message"])
            self.assertIn(
                "response synthesis layer",
                captured_payload["messages"][0]["content"],
            )
            self.assertIn(
                "Rendered tool results:",
                captured_payload["messages"][1]["content"],
            )


if __name__ == "__main__":
    unittest.main()
