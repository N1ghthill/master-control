from __future__ import annotations

from typing import Any

from master_control.bootstrap_prereqs import collect_bootstrap_python_diagnostics
from master_control.config import Settings
from master_control.core.runtime import MasterControlRuntime
from master_control.interfaces.agent.chat import MasterControlChatInterface
from master_control.providers.availability import collect_provider_checks
from master_control.providers.base import ProviderClient
from master_control.systemd_timer import collect_reconcile_timer_diagnostics


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
        self.runtime.bootstrap()
        provider_checks = collect_provider_checks(self.runtime.settings)
        store_diagnostics = self.runtime.store.diagnostics()
        timer_diagnostics = collect_reconcile_timer_diagnostics()
        bootstrap_python_diagnostics = collect_bootstrap_python_diagnostics("python3")
        active_provider_check = dict(
            provider_checks.get(
                self.runtime.provider.name,
                {
                    "name": self.runtime.provider.name,
                    "available": True,
                    "summary": "active provider has no dedicated health probe",
                },
            )
        )
        doctor_ok = bool(active_provider_check.get("available", False)) and bool(
            store_diagnostics.get("ok", False)
        )
        llm_provider_available = any(
            bool(provider_checks[name].get("available", False)) for name in ("ollama", "openai")
        )
        return {
            "ok": doctor_ok,
            "state_dir": str(self.runtime.settings.state_dir),
            "db_path": str(self.runtime.settings.db_path),
            "provider": self.runtime.settings.provider,
            "provider_backend": self.runtime.provider.name,
            "planner_mode": (
                "llm" if self.runtime.provider.name in {"openai", "ollama"} else "heuristic"
            ),
            "llm_provider_available": llm_provider_available,
            "active_provider_check": active_provider_check,
            "provider_checks": provider_checks,
            "provider_diagnostics": self.runtime.provider.diagnostics(),
            "store_diagnostics": store_diagnostics,
            "bootstrap_python_diagnostics": bootstrap_python_diagnostics,
            "reconcile_timer_diagnostics": timer_diagnostics,
            "audit_event_count": self.runtime.store.count_audit_events(),
            "session_count": len(self.runtime.store.list_sessions(limit=10_000)),
            "tools": [spec.name for spec in self.runtime.list_tools()],
        }

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
