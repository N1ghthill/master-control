from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from master_control.agent.planner import ExecutionPlan, PlanStep
from master_control.app import MasterControlApp
from master_control.config import Settings
from master_control.providers.base import ProviderRequest, ProviderResponse, SynthesisRequest


class FakeOpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        self.calls: list[ProviderRequest] = []

    def diagnostics(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ready": True,
        }

    def plan(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append(request)
        response_id = f"resp_{len(self.calls)}"
        return ProviderResponse(
            message="Vou verificar a memória do sistema.",
            plan=ExecutionPlan(
                intent="inspect_memory",
                steps=(
                    PlanStep(
                        tool_name="memory_usage",
                        rationale="Check RAM usage.",
                    ),
                ),
            ),
            response_id=response_id,
        )


class FakeSynthesisOpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        self.plan_calls: list[ProviderRequest] = []
        self.synthesis_calls: list[SynthesisRequest] = []

    def diagnostics(self) -> dict[str, object]:
        return {"name": self.name, "ready": True}

    def plan(self, request: ProviderRequest) -> ProviderResponse:
        self.plan_calls.append(request)
        if len(self.plan_calls) == 1:
            return ProviderResponse(
                message="Vou verificar a memória do sistema.",
                plan=ExecutionPlan(
                    intent="inspect_memory",
                    steps=(
                        PlanStep(
                            tool_name="memory_usage",
                            rationale="Check RAM usage.",
                        ),
                    ),
                ),
                response_id="resp_plan_1",
            )
        return ProviderResponse(
            message="Já tenho dados suficientes para responder.",
            plan=None,
            response_id="resp_plan_2",
        )

    def synthesize(self, request: SynthesisRequest) -> ProviderResponse:
        self.synthesis_calls.append(request)
        return ProviderResponse(
            message="A memória está dentro do resumo final sintetizado pelo provider.",
            response_id="resp_syn_1",
            metadata={"model": "fake-openai", "purpose": "response_synthesis"},
        )


class SessionContextTest(unittest.TestCase):
    def test_previous_response_id_is_reused_when_session_is_resumed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="openai",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            first_provider = FakeOpenAIProvider()
            first_app = MasterControlApp(settings, provider_override=first_provider)

            first_payload = first_app.chat("mostre o uso de memoria", new_session=True)
            session_id = first_payload["session_id"]

            second_provider = FakeOpenAIProvider()
            second_app = MasterControlApp(settings, provider_override=second_provider)
            second_app.chat("e agora me mostre de novo", session_id=session_id)

            self.assertEqual(first_provider.calls[0].previous_response_id, None)
            self.assertEqual(second_provider.calls[0].previous_response_id, "resp_2")
            self.assertGreater(len(second_provider.calls[0].conversation_history), 0)
            self.assertIsNotNone(second_provider.calls[0].session_summary)

    def test_list_sessions_returns_provider_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="openai",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            provider = FakeOpenAIProvider()
            app = MasterControlApp(settings, provider_override=provider)

            payload = app.chat("mostre o uso de memoria", new_session=True)
            sessions = app.list_sessions(limit=10)

            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["session_id"], payload["session_id"])
            self.assertEqual(sessions[0]["provider_backend"], "openai")
            self.assertEqual(sessions[0]["previous_response_id"], "resp_2")
            self.assertIsInstance(sessions[0]["summary_text"], str)

    def test_session_summary_survives_beyond_short_history_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="heuristic",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            app = MasterControlApp(settings)

            first_payload = app.chat("me mostre os logs do ssh 5 linhas", new_session=True)
            session_id = first_payload["session_id"]

            app.bootstrap()
            for index in range(10):
                app.store.append_conversation_message(session_id, "user", f"mensagem {index}")
                app.store.append_conversation_message(session_id, "assistant", f"resposta {index}")

            resumed_app = MasterControlApp(settings)
            follow_up = resumed_app.chat("agora 2 linhas", session_id=session_id)

            self.assertEqual(follow_up["plan"]["steps"][0]["arguments"]["unit"], "ssh")

    def test_synthesis_response_id_is_persisted_for_resumed_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                app_name="master-control",
                log_level="INFO",
                provider="openai",
                state_dir=Path(tmp_dir),
                db_path=Path(tmp_dir) / "mc.sqlite3",
            )
            provider = FakeSynthesisOpenAIProvider()
            app = MasterControlApp(settings, provider_override=provider)

            payload = app.chat("mostre o uso de memoria", new_session=True)
            sessions = app.list_sessions(limit=10)

            self.assertIn("resumo final sintetizado", payload["message"])
            self.assertEqual(len(provider.synthesis_calls), 1)
            self.assertEqual(provider.synthesis_calls[0].previous_response_id, "resp_plan_2")
            self.assertTrue(provider.synthesis_calls[0].rendered_results)
            self.assertEqual(sessions[0]["previous_response_id"], "resp_syn_1")


if __name__ == "__main__":
    unittest.main()
