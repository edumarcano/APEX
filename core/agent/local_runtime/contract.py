"""Provider-neutral contracts for local inference runtime backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict, runtime_checkable

from core.agent.providers.contract import LocalInferenceProvider

LocalModelState = Literal[
    "unloaded",
    "loading",
    "loaded",
    "sleeping",
    "failed",
    "unknown",
]

ResourceGateReason = Literal["insufficient_ram", "cpu_overloaded"]


class SystemVitals(TypedDict):
    cpu: float
    ram: float


@dataclass(frozen=True, slots=True)
class LocalModelRef:
    provider: LocalInferenceProvider
    model: str


class LocalRuntimeModel(TypedDict):
    provider: LocalInferenceProvider
    name: str
    model: str
    state: LocalModelState
    size_bytes: int | None
    size_vram_bytes: int | None
    processor: str | None
    context: str | None
    context_window: int | None
    expires_at: str | None


class LocalRuntimeSnapshot(TypedDict):
    provider: LocalInferenceProvider
    reachable: bool
    installed_models: list[str]
    loaded_models: list[LocalRuntimeModel]
    sampled_at: float


@runtime_checkable
class LocalModelProfile(Protocol):
    provider: LocalInferenceProvider
    runtime: Literal["local"]
    api_model: str
    runtime_model_id: str
    context_window: int
    generation_timeout: int | float
    ram_limit: float
    cpu_limit: float
    high_resource: bool


@runtime_checkable
class LocalRuntimeBackend(Protocol):
    provider: LocalInferenceProvider

    @property
    def enabled(self) -> bool: ...

    @property
    def idle_unload_seconds(self) -> int: ...

    @property
    def manual_unload_enabled(self) -> bool: ...

    def get_status_snapshot(
        self,
        *,
        force_refresh: bool = False,
    ) -> LocalRuntimeSnapshot: ...

    def is_model_resident(self, model: str) -> bool: ...

    def load_model(self, profile: LocalModelProfile) -> bool: ...

    def unload_model(self, model: str) -> bool: ...

    def invalidate_status_snapshot(self) -> None: ...
