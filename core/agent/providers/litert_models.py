"""LiteRT-specific model profile and runtime tuning contracts.

Artifact names and paths intentionally live here rather than in the generic
Agent catalog.  Checkpoint 3 uses test-injected profiles; production mappings
are added at the Checkpoint 4 boundary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    engine_load_timeout: int = Field(default=300, ge=1)
    artifact_path: str | None = Field(
        default=None,
        description="Resolved local artifact path; never part of generic Agent metadata.",
    )
    cpu_backend: Literal["cpu"] = "cpu"
    minimum_free_ram_mb: int | None = Field(default=None, ge=0)
