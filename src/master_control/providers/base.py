from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from master_control.agent.planner import ExecutionPlan
from master_control.tools.base import ToolSpec


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    role: str
    content: str
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    user_message: str
    available_tools: tuple[ToolSpec, ...]
    conversation_history: tuple[ConversationMessage, ...] = ()
    session_summary: str | None = None
    previous_response_id: str | None = None
    system_prompt: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    message: str
    plan: ExecutionPlan | None = None
    response_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a valid plan."""


class ProviderClient(Protocol):
    name: str

    def plan(self, request: ProviderRequest) -> ProviderResponse:
        """Return a structured provider response for the given request."""

    def diagnostics(self) -> dict[str, object]:
        """Return non-secret diagnostics for doctor output."""
