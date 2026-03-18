from __future__ import annotations

from master_control.config import Settings
from master_control.providers.availability import (
    collect_provider_checks,
    resolve_auto_provider_backend,
)
from master_control.providers.heuristic import HeuristicProvider
from master_control.providers.noop import NoopProvider
from master_control.providers.ollama_chat import OllamaChatProvider
from master_control.providers.openai_responses import OpenAIResponsesProvider


def build_provider(settings: Settings):
    normalized = settings.provider.strip().lower()
    if normalized == "auto":
        checks = collect_provider_checks(settings)
        selected_backend = resolve_auto_provider_backend(settings, checks=checks)
        if selected_backend == "ollama":
            return OllamaChatProvider(settings)
        if selected_backend == "openai":
            return OpenAIResponsesProvider(settings)
        return HeuristicProvider()
    if normalized == "openai":
        return OpenAIResponsesProvider(settings)
    if normalized == "ollama":
        return OllamaChatProvider(settings)
    if normalized in {"heuristic", "local"}:
        return HeuristicProvider()
    if normalized in {"none", "noop"}:
        return NoopProvider()
    return NoopProvider(reason=f"Provider '{settings.provider}' is not supported yet.")
