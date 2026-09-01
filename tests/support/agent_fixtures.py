"""Shared Agent Family Consolidation helpers for tests."""

from __future__ import annotations

from core.agent.catalog import build_concrete_agent, resolve_effort
from core.agent.model_catalog import get_model_profile
from core.settings.models import AgentSettings, CloudHostedToolsSettings, CloudSettings, LocalSettings

GEMMA_E2B_MODEL = "gemma-4-E2B-Q4_K_M.gguf"
GEMMA_E4B_MODEL = "gemma-4-E4B-Q4_K_M.gguf"
QWEN3_17B_MODEL = "qwen3:1.7b"
QWEN3_4B_MODEL = "qwen3:4b-instruct"
GEMINI_FLASH_MODEL = "gemini-3.6-flash"
GROK_43_MODEL = "grok-4.3"
GROK_45_MODEL = "grok-4.5"
GEMINI_FLASH_LITE_MODEL = "gemini-3.5-flash-lite"
EXPERIMENTAL_MODEL = "Qwen3.5-4B-Q4_K_M.gguf"
GEMMA_E2B_ALIAS = "gemma-4-e2b-16k"
GEMMA_E4B_ALIAS = "gemma-4-e4b-16k"


def cloud_settings(
    *,
    model: str = "gpt-5.6-luna",
    effort: str = "medium",
    google_search: bool = True,
    google_maps: bool = True,
    x_search: bool = True,
) -> AgentSettings:
    return AgentSettings(
        selected_model=model,
        cloud=CloudSettings(
            last_model=model,
            effort=effort,  # type: ignore[arg-type]
            hosted_tools=CloudHostedToolsSettings(
                google_search=google_search,
                google_maps=google_maps,
                x_search=x_search,
            ),
        ),
    )


def local_settings(
    *,
    model: str = GEMMA_E2B_MODEL,
    context_window: int | None = None,
    reasoning_mode: str = "none",
) -> AgentSettings:
    kwargs: dict[str, object] = {
        "last_model": model,
        "reasoning_mode": reasoning_mode,  # type: ignore[arg-type]
    }
    if context_window is not None:
        kwargs["context_window"] = context_window
    return AgentSettings(selected_model=model, local=LocalSettings(**kwargs))


def build_local_profile(
    *,
    model: str = GEMMA_E2B_MODEL,
    context_window: int | None = None,
    reasoning_mode: str | None = "none",
):
    profile = get_model_profile(model)
    assert profile is not None
    native = resolve_effort(profile, None)
    return build_concrete_agent(
        "apex",
        native_effort=native,
        local_context_window=context_window,
        local_reasoning_mode=reasoning_mode,  # type: ignore[arg-type]
        model_id=model,
    )


def build_cloud_profile(
    *,
    model: str = "gpt-5.6-luna",
    effort: str | None = "medium",
):
    profile = get_model_profile(model)
    assert profile is not None
    native = resolve_effort(profile, effort)  # type: ignore[arg-type]
    return build_concrete_agent(
        "apex",
        native_effort=native,
        model_id=model,
    )
