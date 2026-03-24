from __future__ import annotations

from typing import Any

from master_control.config import Settings
from master_control.core.runtime import MasterControlRuntime
from master_control.interfaces.agent.chat import MasterControlChatInterface
from master_control.providers.base import ProviderClient


class MasterControlApp:
    """Compatibility facade over the runtime and chat interface."""

    def __init__(
        self,
        settings: Settings,
        *,
        provider_override: ProviderClient | None = None,
    ) -> None:
        self.runtime = MasterControlRuntime(
            settings,
            provider_override=provider_override,
        )
        self.chat_interface = MasterControlChatInterface(self.runtime)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.runtime, name)

    def doctor(self) -> dict[str, object]:
        return self.runtime.doctor()

    def start_chat_session(
        self,
        *,
        session_id: int | None = None,
        new_session: bool = False,
    ) -> int:
        return self.chat_interface.start_chat_session(
            session_id=session_id,
            new_session=new_session,
        )

    def chat(
        self,
        user_input: str,
        *,
        session_id: int | None = None,
        new_session: bool = False,
    ) -> dict[str, object]:
        return self.chat_interface.chat(
            user_input,
            session_id=session_id,
            new_session=new_session,
        )

    def handle_message(self, user_input: str) -> str:
        return self.chat_interface.handle_message(user_input)
