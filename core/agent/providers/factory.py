"""Shared constructor for registered Cortex inference adapters."""

from __future__ import annotations

from typing import Any

from core.agent.providers.contract import InferenceProvider, resolve_inference_provider


def create_provider(profile: Any, api_key: str | None = None) -> Any:
    """Build the adapter selected by the concrete catalog model profile."""
    provider: InferenceProvider = resolve_inference_provider(profile)
    if provider == "gemini":
        from core.agent.providers.gemini import GeminiProvider

        return GeminiProvider(api_key=api_key or "")
    if provider == "openrouter":
        from core.agent.providers.openrouter import OpenRouterProvider

        return OpenRouterProvider(api_key=api_key or "")
    if provider == "llama_cpp":
        from core.agent.providers.llama_cpp import LlamaCppProvider

        return LlamaCppProvider()
    raise ValueError(f"Unsupported inference provider: {provider!r}")
