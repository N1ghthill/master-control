from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from master_control.agent.observations import build_observation_freshness
from master_control.agent.session_context import build_session_context
from master_control.config import Settings
from master_control.providers.base import (
    ConversationMessage,
    ProviderError,
    ProviderRequest,
    SynthesisRequest,
)
from master_control.providers.openai_responses import OpenAIResponsesProvider, TransportResponse
from master_control.tools.base import RiskLevel, ToolSpec


class OpenAIResponsesProviderTest(unittest.TestCase):
    def test_provider_parses_submit_plan_function_call(self) -> None:
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
                "id": "resp_123",
                "model": "gpt-5.4",
                "output": [
                    {
                        "type": "function_call",
                        "name": "submit_plan",
                        "arguments": json.dumps(
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
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                },
            }
            return TransportResponse(
                status_code=200,
                body=json.dumps(body),
                headers={"x-request-id": "req_123"},
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="openai",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
                openai_api_key="test-key",
            )
            provider = OpenAIResponsesProvider(settings, transport=fake_transport)
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
                    ConversationMessage(
                        role="assistant", content="Posso verificar memória ou disco."
                    ),
                ),
                session_summary="tracked_unit: ssh\nlast_intent: inspect_logs",
                observation_freshness=build_observation_freshness(
                    (
                        {
                            "source": "memory_usage",
                            "key": "memory",
                            "value": {"memory_used_percent": 12.0},
                            "observed_at": "2026-03-17T20:00:00Z",
                            "expires_at": "2026-03-17T20:05:00Z",
                        },
                    )
                ),
                session_context=build_session_context(
                    "tracked_unit: ssh\nlast_intent: inspect_logs",
                    build_observation_freshness(
                        (
                            {
                                "source": "memory_usage",
                                "key": "memory",
                                "value": {"memory_used_percent": 12.0},
                                "observed_at": "2026-03-17T20:00:00Z",
                                "expires_at": "2026-03-17T20:05:00Z",
                            },
                        )
                    ),
                ),
            )

            response = provider.plan(request)

            self.assertEqual(response.message, "Vou verificar a memória.")
            self.assertEqual(response.response_id, "resp_123")
            self.assertEqual(response.decision.state, "needs_tools")
            self.assertEqual(response.decision.kind, "inspection_request")
            self.assertEqual(response.metadata["request_id"], "req_123")
            self.assertEqual(response.plan.intent, "inspect_memory")
            self.assertEqual(response.plan.steps[0].tool_name, "memory_usage")
            self.assertEqual(captured_payload["tool_choice"], "required")
            self.assertEqual(len(captured_payload["input"]), 3)
            self.assertEqual(captured_payload["input"][0]["role"], "user")
            self.assertEqual(captured_payload["input"][1]["role"], "assistant")
            self.assertEqual(captured_payload["input"][2]["content"], "mostre o uso de memoria")
            self.assertIn("Local session summary:", captured_payload["instructions"])
            self.assertIn("tracked_unit: ssh", captured_payload["instructions"])
            self.assertIn("Structured session context:", captured_payload["instructions"])
            self.assertIn('"last_intent": "inspect_logs"', captured_payload["instructions"])
            self.assertIn("Observation freshness:", captured_payload["instructions"])
            self.assertIn("memory", captured_payload["instructions"])
            self.assertIn("Always set decision.state", captured_payload["instructions"])
            self.assertIn("do not answer from memory alone", captured_payload["instructions"])
            self.assertIn("Interpret informal operator phrasing", captured_payload["instructions"])
            self.assertIn("comparative follow-ups", captured_payload["instructions"])
            self.assertIn(
                "restart or crash loops, dependency failures, environment failures",
                captured_payload["instructions"],
            )
            self.assertIn("tracked managed files", captured_payload["instructions"])
            self.assertIn("decision", captured_payload["tools"][0]["parameters"]["required"])

    def test_provider_requires_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="openai",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            provider = OpenAIResponsesProvider(settings)
            request = ProviderRequest(
                user_message="mostre o uso de memoria",
                available_tools=(),
            )

            with self.assertRaises(ProviderError):
                provider.plan(request)

    def test_provider_rejects_non_http_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="openai",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
                openai_api_key="test-key",
                openai_base_url="file:///tmp/openai",
            )
            provider = OpenAIResponsesProvider(settings)
            request = ProviderRequest(
                user_message="mostre o uso de memoria",
                available_tools=(),
            )

            with self.assertRaisesRegex(ProviderError, "http or https"):
                provider.plan(request)

    def test_provider_prefers_previous_response_id_over_local_history(self) -> None:
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
                "id": "resp_456",
                "model": "gpt-5.4",
                "output": [
                    {
                        "type": "function_call",
                        "name": "submit_plan",
                        "arguments": json.dumps(
                            {
                                "message": "Vou verificar a memória.",
                                "intent": "inspect_memory",
                                "decision": {
                                    "state": "complete",
                                    "kind": "evidence_sufficient",
                                    "reason": "The current context is already enough.",
                                },
                                "steps": [],
                            }
                        ),
                    }
                ],
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
                provider="openai",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
                openai_api_key="test-key",
            )
            provider = OpenAIResponsesProvider(settings, transport=fake_transport)
            request = ProviderRequest(
                user_message="e agora?",
                available_tools=(),
                conversation_history=(
                    ConversationMessage(role="user", content="mostre o uso de memoria"),
                    ConversationMessage(role="assistant", content="Memória usada: 10%."),
                ),
                session_summary="memory: memory 10% used, swap 0% used",
                previous_response_id="resp_prev",
            )

            provider.plan(request)

            self.assertEqual(captured_payload["previous_response_id"], "resp_prev")
            self.assertEqual(len(captured_payload["input"]), 1)
            self.assertEqual(captured_payload["input"][0]["content"], "e agora?")

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
                "id": "resp_syn_1",
                "model": "gpt-5.4",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "A memória está sob pressão e o serviço segue ativo.",
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 18,
                    "total_tokens": 138,
                },
            }
            return TransportResponse(
                status_code=200,
                body=json.dumps(body),
                headers={"x-request-id": "req_syn_1"},
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="openai",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
                openai_api_key="test-key",
            )
            provider = OpenAIResponsesProvider(settings, transport=fake_transport)

            response = provider.synthesize(
                SynthesisRequest(
                    user_message="o host esta lento",
                    planning_message="Vou verificar a memória e depois os processos.",
                    execution_observations=(
                        "memory_usage({}) -> memory=92.0%, swap=10.0%",
                        'top_processes({"limit": 5}) -> nginx(88.0%), python(20.0%)',
                    ),
                    rendered_results=(
                        "Memória usada: 92.0% (92 B de 100 B). Swap usada: 10.0% (10 B de 100 B).",
                        "Top processos por CPU: nginx (88.0% CPU), python (20.0% CPU).",
                    ),
                    previous_response_id="resp_prev",
                )
            )

            self.assertEqual(
                response.message, "A memória está sob pressão e o serviço segue ativo."
            )
            self.assertEqual(response.response_id, "resp_syn_1")
            self.assertEqual(response.metadata["purpose"], "response_synthesis")
            self.assertEqual(captured_payload["previous_response_id"], "resp_prev")
            self.assertNotIn("tools", captured_payload)
            self.assertIn("Execution observations:", captured_payload["input"][0]["content"])
            self.assertIn("Rendered tool results:", captured_payload["input"][0]["content"])
            self.assertIn("response synthesis layer", captured_payload["instructions"])


if __name__ == "__main__":
    unittest.main()
