"""LiteRT-specific model profile and runtime tuning contracts.

Artifact names and paths intentionally live here rather than in the generic
Agent catalog.  Checkpoint 3 uses test-injected profiles; production mappings
are added at the Checkpoint 4 boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from core.config import (
    LITERT_ENGINE_LOAD_TIMEOUT,
    LITERT_MIN_FREE_RAM_MICROTUS_MB,
    LITERT_MIN_FREE_RAM_MUSTELA_MB,
    LITERT_MODEL_DIR,
    LITERT_MICROTUS_TIMEOUT,
    LITERT_MUSTELA_TIMEOUT,
)


@dataclass(frozen=True, slots=True)
class LiteRTModelConfig:
    """Provider-specific repository/artifact and resource mapping."""

    agent_key: str
    repository: str
    artifact_filename: str
    tier: Literal["lightweight", "balanced"]
    context_window: int
    final_answer_max_tokens: int
    max_tool_turns: int
    max_tool_calls: int
    generation_timeout: int
    minimum_free_ram_mb: int


LITERT_MODEL_CONFIGS: dict[str, LiteRTModelConfig] = {
    "microtus": LiteRTModelConfig(
        agent_key="microtus",
        repository="litert-community/gemma-4-E2B-it-litert-lm",
        artifact_filename="gemma-4-E2B-it.litertlm",
        tier="lightweight",
        context_window=8192,
        final_answer_max_tokens=768,
        max_tool_turns=3,
        max_tool_calls=4,
        generation_timeout=LITERT_MICROTUS_TIMEOUT,
        minimum_free_ram_mb=LITERT_MIN_FREE_RAM_MICROTUS_MB,
    ),
    "mustela": LiteRTModelConfig(
        agent_key="mustela",
        repository="litert-community/gemma-4-E4B-it-litert-lm",
        artifact_filename="gemma-4-E4B-it.litertlm",
        tier="balanced",
        context_window=8192,
        final_answer_max_tokens=1024,
        max_tool_turns=4,
        max_tool_calls=6,
        generation_timeout=LITERT_MUSTELA_TIMEOUT,
        minimum_free_ram_mb=LITERT_MIN_FREE_RAM_MUSTELA_MB,
    ),
}


def get_litert_model_config(agent_key: str) -> LiteRTModelConfig:
    try:
        return LITERT_MODEL_CONFIGS[agent_key]
    except KeyError as exc:
        raise KeyError(f"Unknown LiteRT Agent key: {agent_key!r}") from exc


def resolve_litert_artifact(
    agent_key: str,
    model_dir: str | Path | None = None,
) -> Path:
    """Resolve exactly one expected artifact without downloads or recursion."""
    config = get_litert_model_config(agent_key)
    root = Path(model_dir) if model_dir is not None else Path(LITERT_MODEL_DIR)
    return root / config.artifact_filename


def artifact_resolution_reason(agent_key: str, model_dir: str | Path | None = None) -> str:
    """Return sanitized corrective setup copy for a missing artifact."""
    artifact = resolve_litert_artifact(agent_key, model_dir)
    if artifact.is_file():
        return ""
    return f"Install the expected LiteRT model artifact '{artifact.name}' in the configured model directory."


class LiteRTModelProfile(BaseModel):
    provider: Literal["litert"] = "litert"
    display_name: str = Field(description="Visual name surfaced in HUD UI components.")
    agent_version: str = Field(description="Version of the named Apex Agent identity.")
    api_model: str = Field(description="LiteRT repository model identifier.")
    tier: Literal["lightweight", "balanced", "capable"]
    stability: Literal["stable", "preview"]
    max_tool_turns: int = Field(default=3, ge=1)
    max_tool_calls: int = Field(default=4, ge=1)
    system_instruction: str
    context_window: int = Field(default=8192, ge=1)
    final_answer_max_tokens: int = Field(default=768, ge=1)
    generation_timeout: int = Field(default=120, ge=1)
    engine_load_timeout: int = Field(default=LITERT_ENGINE_LOAD_TIMEOUT, ge=1)
    artifact_path: str | None = Field(
        default=None,
        exclude=True,
        description="Resolved local artifact path; never part of generic Agent metadata.",
    )
    cpu_backend: Literal["cpu"] = "cpu"
    minimum_free_ram_mb: int | None = Field(default=None, ge=0)
