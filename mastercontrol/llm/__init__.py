#!/usr/bin/env python3
"""LLM adapters for MasterControl."""

from .ollama_adapter import LLMInterpretation, OllamaAdapter, OllamaAdapterError

__all__ = ["LLMInterpretation", "OllamaAdapter", "OllamaAdapterError"]
