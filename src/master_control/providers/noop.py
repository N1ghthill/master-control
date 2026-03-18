from __future__ import annotations

from master_control.providers.base import ProviderRequest, ProviderResponse


class NoopProvider:
    name = "noop"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or "No provider configured."

    def plan(self, request: ProviderRequest) -> ProviderResponse:
        del request
        return ProviderResponse(message=self.reason)

    def diagnostics(self) -> dict[str, object]:
        return {
            "name": self.name,
            "available": True,
            "mode": "static",
        }
