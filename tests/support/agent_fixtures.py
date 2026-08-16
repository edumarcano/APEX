"""Shared Agent Family Consolidation helpers for tests."""

from __future__ import annotations

from core.agent.catalog import build_concrete_agent, resolve_effort
from core.agent.model_catalog import get_model_profile
from core.settings.models import (
    AgentSettings,
    FelisSettings,
    PantheraHostedToolsSettings,
    PantheraSettings,
)

APODEMUS_MODEL = "gemma-4-E2B-Q4_K_M.gguf"
NEOTOMA_MODEL = "gemma-4-E4B-Q4_K_M.gguf"
SOREX_MODEL = "qwen3:1.7b"
MUS_MODEL = "qwen3:4b-instruct"
NEOFELIS_MODEL = "gemini-3.6-flash"
DELPHINUS_MODEL = "grok-4.3"
ORCINUS_MODEL = "grok-4.5"
ACINONYX_MODEL = "gemini-3.5-flash-lite"
EXPERIMENTAL_MODEL = "Qwen3.5-4B-Q4_K_M.gguf"
GEMMA_E2B_ALIAS = "gemma-4-e2b-16k"
GEMMA_E4B_ALIAS = "gemma-4-e4b-16k"


def panthera_settings(
    *,
    model: str = "gpt-5.6-luna",
    effort: str = "focused",
    google_search: bool = True,
    google_maps: bool = True,
    x_search: bool = True,
) -> AgentSettings:
    return AgentSettings(
        agent="panthera",
        panthera=PantheraSettings(
            model=model,
            effort=effort,  # type: ignore[arg-type]
            hosted_tools=PantheraHostedToolsSettings(
                google_search=google_search,
                google_maps=google_maps,
                x_search=x_search,
            ),
        ),
    )


def felis_settings(
    *,
    model: str = APODEMUS_MODEL,
    context_window: int | None = None,
    reasoning_mode: str = "none",
) -> AgentSettings:
    kwargs: dict[str, object] = {
        "model": model,
        "reasoning_mode": reasoning_mode,  # type: ignore[arg-type]
    }
    if context_window is not None:
        kwargs["context_window"] = context_window
    return AgentSettings(agent="felis", felis=FelisSettings(**kwargs))


def build_felis_profile(
    *,
    model: str = APODEMUS_MODEL,
    context_window: int | None = None,
    reasoning_mode: str | None = "none",
):
    profile = get_model_profile(model)
    assert profile is not None
    _apex, native = resolve_effort(profile, None)
    return build_concrete_agent(
        "felis",
        native_effort=native,
        local_context_window=context_window,
        local_reasoning_mode=reasoning_mode,  # type: ignore[arg-type]
        model_id=model,
    )


def build_panthera_profile(
    *,
    model: str = "gpt-5.6-luna",
    effort: str | None = "focused",
):
    profile = get_model_profile(model)
    assert profile is not None
    _apex, native = resolve_effort(profile, effort)  # type: ignore[arg-type]
    return build_concrete_agent(
        "panthera",
        native_effort=native,
        model_id=model,
    )
