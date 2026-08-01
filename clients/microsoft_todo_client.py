"""Bounded read-only Microsoft Graph client for Microsoft To Do."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlparse

import requests

from clients.microsoft_auth import (
    MicrosoftTodoAuthenticationRequiredError,
    MicrosoftTodoAuthenticationService,
    MicrosoftTodoNotConfiguredError,
)
from clients.microsoft_todo_models import (
    MicrosoftTodoAuthStatus,
    TodoDateTime,
    TodoTask,
    TodoTaskList,
    TodoTaskListsResult,
    TodoTasksResult,
)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
_MAX_LISTS = 50
_MAX_TASKS = 50
_TIMEOUT_SECONDS = 15
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class MicrosoftTodoInvalidInputError(ValueError):
    """Raised when a caller supplies an invalid opaque identifier."""


class MicrosoftTodoUpstreamError(RuntimeError):
    """Raised for sanitized Microsoft Graph failures."""


def _text(value: Any, limit: int) -> str:
    cleaned = _CONTROL_CHARS.sub("", str(value or "")).strip()
    return cleaned[:limit]


def _date_time(value: Any) -> TodoDateTime | None:
    if not isinstance(value, dict):
        return None
    date_time = _text(value.get("dateTime"), 64)
    if not date_time:
        return None
    return TodoDateTime(date_time=date_time, time_zone=_text(value.get("timeZone"), 64))


def _normalize_list(value: Any) -> TodoTaskList | None:
    if not isinstance(value, dict):
        return None
    identifier = _text(value.get("id"), 512)
    name = _text(value.get("displayName"), 300)
    if not identifier or not name:
        return None
    return TodoTaskList(id=identifier, display_name=name, is_owner=bool(value.get("isOwner")), is_shared=bool(value.get("isShared")), well_known_name=_text(value.get("wellknownListName"), 64))


def _normalize_task(value: Any) -> TodoTask | None:
    if not isinstance(value, dict):
        return None
    identifier = _text(value.get("id"), 512)
    title = _text(value.get("title"), 500)
    if not identifier or not title:
        return None
    status = _text(value.get("status"), 64)
    categories = [
        _text(item, 100)
        for item in (value.get("categories") or [])[:10]
        if isinstance(item, str) and _text(item, 100)
    ]
    return TodoTask(id=identifier, title=title, status=status, importance=_text(value.get("importance"), 32), is_completed=status.lower() == "completed", created_at=_text(value.get("createdDateTime"), 64), last_modified_at=_text(value.get("lastModifiedDateTime"), 64), due=_date_time(value.get("dueDateTime")), completed_at=_date_time(value.get("completedDateTime")), categories=tuple(categories))


class MicrosoftTodoClient:
    """Read task lists and tasks using only Microsoft Graph GET requests."""

    def __init__(
        self,
        auth: MicrosoftTodoAuthenticationService,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.auth = auth
        self.session = session or requests.Session()

    def get_status(self) -> MicrosoftTodoAuthStatus:
        return self.auth.status_snapshot()

    def _get_pages(self, url: str, *, limit: int, path_prefix: str) -> list[Any]:
        token = self.auth.acquire_access_token()
        items: list[Any] = []
        next_url: str | None = url
        while next_url and len(items) < limit:
            try:
                response = self.session.get(
                    next_url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=_TIMEOUT_SECONDS,
                )
            except requests.Timeout as exc:
                raise TimeoutError("Microsoft To Do request timed out.") from exc
            except requests.RequestException as exc:
                raise MicrosoftTodoUpstreamError(
                    "Microsoft To Do is unavailable."
                ) from exc
            if response.status_code == 401:
                self.auth.mark_authentication_required()
                raise MicrosoftTodoAuthenticationRequiredError(
                    "Reconnect Microsoft To Do in Settings."
                )
            if response.status_code >= 400:
                raise MicrosoftTodoUpstreamError(
                    "Microsoft To Do data is unavailable."
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise MicrosoftTodoUpstreamError(
                    "Microsoft To Do returned an invalid response."
                ) from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
                raise MicrosoftTodoUpstreamError(
                    "Microsoft To Do returned an invalid response."
                )
            items.extend(payload["value"][: max(0, limit - len(items))])
            candidate = payload.get("@odata.nextLink")
            next_url = self._safe_next_link(candidate, path_prefix) if candidate else None
        return items

    @staticmethod
    def _safe_next_link(value: Any, path_prefix: str) -> str:
        if not isinstance(value, str):
            raise MicrosoftTodoUpstreamError("Microsoft To Do pagination is invalid.")
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() != "graph.microsoft.com"
            or not parsed.path.startswith(path_prefix)
        ):
            raise MicrosoftTodoUpstreamError("Microsoft To Do pagination is invalid.")
        return value

    def list_task_lists(self) -> TodoTaskListsResult:
        path = "/v1.0/me/todo/lists"
        raw = self._get_pages(
            f"{GRAPH_ROOT}/me/todo/lists?$top={_MAX_LISTS}",
            limit=_MAX_LISTS,
            path_prefix=path,
        )
        lists = tuple(item for value in raw if (item := _normalize_list(value)))
        return TodoTaskListsResult(lists=lists)

    def list_tasks(
        self,
        list_id: str,
        *,
        include_completed: bool = False,
        max_results: int = 20,
    ) -> TodoTasksResult:
        identifier = _text(list_id, 512)
        if not identifier or identifier != list_id.strip():
            raise MicrosoftTodoInvalidInputError("A valid To Do list identifier is required.")
        limit = max(1, min(_MAX_TASKS, int(max_results)))
        encoded = quote(identifier, safe="")
        path = f"/v1.0/me/todo/lists/{encoded}/tasks"
        raw = self._get_pages(
            f"{GRAPH_ROOT}/me/todo/lists/{encoded}/tasks?$top={_MAX_TASKS}",
            limit=_MAX_TASKS,
            path_prefix=path,
        )
        tasks = [item for value in raw if (item := _normalize_task(value))]
        if not include_completed:
            tasks = [task for task in tasks if not task.is_completed]
        tasks = tasks[:limit]
        return TodoTasksResult(list_id=identifier, include_completed=include_completed, tasks=tuple(tasks))


    def close(self) -> None:
        """Release the reusable HTTP transport owned by the application lifespan."""
        self.session.close()

def get_microsoft_todo_client() -> MicrosoftTodoClient:
    if _CLIENT is None:
        raise MicrosoftTodoNotConfiguredError("Microsoft To Do is unavailable.")
    return _CLIENT


def set_microsoft_todo_client(client: MicrosoftTodoClient | None) -> None:
    """Install the lifespan-owned client for tools and routes."""
    global _CLIENT
    _CLIENT = client


_CLIENT: MicrosoftTodoClient | None = None
