from __future__ import annotations

from master_control.core.runtime import MasterControlRuntime


class MasterControlChatInterface:
    """Chat-facing adapter over the runtime's conversational workflow."""

    def __init__(self, runtime: MasterControlRuntime) -> None:
        self.runtime = runtime

    def start_chat_session(
        self,
        *,
        session_id: int | None = None,
        new_session: bool = False,
    ) -> int:
        return self.runtime.start_chat_session(
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
        return self.runtime.chat(
            user_input,
            session_id=session_id,
            new_session=new_session,
        )

    def handle_message(self, user_input: str) -> str:
        return self.runtime.handle_message(user_input)
