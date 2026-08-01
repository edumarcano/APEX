"""Stable contracts shared by the Microsoft To Do integration layers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

MicrosoftAuthState = Literal[
    "not-configured",
    "disconnected",
    "authorizing",
    "connected",
    "authentication-required",
    "degraded",
]
MicrosoftTodoAuthErrorCode = Literal[
    "app-configuration",
    "permission",
    "request",
    "cancelled",
    "expired",
    "sign-in-failed",
    "initialization-failed",
]


@dataclass(frozen=True)
class MicrosoftTodoAuthConfig:
    """Non-secret configuration for the local public-client application."""

    client_id: str
    tenant_id: str
    cache_path: Path


@dataclass(frozen=True)
class MicrosoftTodoAuthStatus:
    configured: bool
    state: MicrosoftAuthState
    permission: Literal["Tasks.Read"] = "Tasks.Read"
    auth_error_code: MicrosoftTodoAuthErrorCode | None = None
    auth_error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MicrosoftTodoDeviceAuthorization:
    verification_uri: str
    user_code: str
    expires_at: str
    state: Literal["authorizing"] = "authorizing"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TodoDateTime:
    date_time: str
    time_zone: str


@dataclass(frozen=True)
class TodoTaskList:
    id: str
    display_name: str
    is_owner: bool
    is_shared: bool
    well_known_name: str


@dataclass(frozen=True)
class TodoTask:
    id: str
    title: str
    status: str
    importance: str
    is_completed: bool
    created_at: str
    last_modified_at: str
    due: TodoDateTime | None
    completed_at: TodoDateTime | None
    categories: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TodoTaskListsResult:
    lists: tuple[TodoTaskList, ...]

    @property
    def list_count(self) -> int:
        return len(self.lists)

    def to_dict(self) -> dict[str, Any]:
        return {"list_count": self.list_count, "lists": [asdict(item) for item in self.lists]}


@dataclass(frozen=True)
class TodoTasksResult:
    list_id: str
    include_completed: bool
    tasks: tuple[TodoTask, ...]

    @property
    def task_count(self) -> int:
        return len(self.tasks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "list_id": self.list_id,
            "include_completed": self.include_completed,
            "task_count": self.task_count,
            "tasks": [asdict(item) for item in self.tasks],
        }
