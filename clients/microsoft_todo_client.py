"""Bounded Microsoft Graph client for read-only tools and internal task writes."""

from __future__ import annotations

import re
import unicodedata
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
    TodoTaskCreateRequest,
    TodoTaskPatchRequest,
    TodoTaskList,
    TodoTaskListsResult,
    TodoTasksResult,
    UNSET,
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


class MicrosoftTodoNotFoundError(MicrosoftTodoUpstreamError):
    """Raised when Microsoft Graph confirms a requested task does not exist."""


class MicrosoftTodoPermissionError(MicrosoftTodoUpstreamError):
    """Raised when Microsoft Graph denies an authorized task operation."""


class MicrosoftTodoThrottledError(MicrosoftTodoUpstreamError):
    """Raised when Graph throttles a request without retrying it locally."""


class MicrosoftTodoAmbiguousWriteError(MicrosoftTodoUpstreamError):
    """Raised when a write may have reached Graph but cannot be trusted as complete."""


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


def _validated_text(value: Any, *, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MicrosoftTodoInvalidInputError(f"A non-blank {field} is required.")
    if (
        _CONTROL_CHARS.search(value)
        or any(unicodedata.category(character) == "Cc" for character in value)
        or len(value) > limit
    ):
        raise MicrosoftTodoInvalidInputError(f"The {field} is invalid.")
    return value


def _validated_identifier(value: Any, *, label: str) -> str:
    identifier = _validated_text(value, field=f"To Do {label} identifier", limit=512)
    if identifier != identifier.strip():
        raise MicrosoftTodoInvalidInputError(
            f"The To Do {label} identifier is invalid."
        )
    return identifier


def _graph_date_time(value: TodoDateTime) -> dict[str, str]:
    if not isinstance(value, TodoDateTime):
        raise MicrosoftTodoInvalidInputError("A valid To Do due date is required.")
    return {
        "dateTime": _validated_text(value.date_time, field="due date", limit=64),
        "timeZone": _validated_text(value.time_zone, field="due time zone", limit=64),
    }


def _create_payload(request: TodoTaskCreateRequest) -> dict[str, Any]:
    if not isinstance(request, TodoTaskCreateRequest):
        raise MicrosoftTodoInvalidInputError("A valid To Do create request is required.")
    payload: dict[str, Any] = {
        "title": _validated_text(request.title, field="task title", limit=500),
    }
    if request.due is not None:
        payload["dueDateTime"] = _graph_date_time(request.due)
    if request.importance is not None:
        if request.importance not in {"low", "normal", "high"}:
            raise MicrosoftTodoInvalidInputError("The task importance is invalid.")
        payload["importance"] = request.importance
    return payload


def _patch_payload(request: TodoTaskPatchRequest) -> dict[str, Any]:
    if not isinstance(request, TodoTaskPatchRequest):
        raise MicrosoftTodoInvalidInputError("A valid To Do update request is required.")
    payload: dict[str, Any] = {}
    if request.title is not UNSET:
        payload["title"] = _validated_text(request.title, field="task title", limit=500)
    if request.due is not UNSET:
        payload["dueDateTime"] = (
            None if request.due is None else _graph_date_time(request.due)
        )
    if request.importance is not UNSET:
        if request.importance not in {"low", "normal", "high"}:
            raise MicrosoftTodoInvalidInputError("The task importance is invalid.")
        payload["importance"] = request.importance
    if request.status is not UNSET:
        if request.status not in {"notStarted", "completed"}:
            raise MicrosoftTodoInvalidInputError("The task status is invalid.")
        payload["status"] = request.status
    if not payload:
        raise MicrosoftTodoInvalidInputError("At least one task field must be updated.")
    return payload


class MicrosoftTodoClient:
    """Read tasks and provide unexposed, approval-ready Graph write primitives."""

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

    def _request(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        write: bool = False,
    ) -> Any:
        token = self.auth.acquire_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            request = getattr(self.session, method)
            return request(url, headers=headers, timeout=_TIMEOUT_SECONDS, **(
                {"json": payload} if payload is not None else {}
            ))
        except requests.Timeout as exc:
            if write:
                raise MicrosoftTodoAmbiguousWriteError(
                    "Microsoft To Do write outcome is unknown."
                ) from exc
            raise TimeoutError("Microsoft To Do request timed out.") from exc
        except requests.RequestException as exc:
            if write:
                raise MicrosoftTodoAmbiguousWriteError(
                    "Microsoft To Do write outcome is unknown."
                ) from exc
            raise MicrosoftTodoUpstreamError("Microsoft To Do is unavailable.") from exc

    def _raise_response_error(self, response: Any, *, write: bool) -> None:
        status_code = response.status_code
        if status_code == 401:
            self.auth.mark_authentication_required()
            raise MicrosoftTodoAuthenticationRequiredError(
                "Reconnect Microsoft To Do in Settings."
            )
        if status_code == 400:
            raise MicrosoftTodoInvalidInputError("Microsoft rejected the task request.")
        if status_code == 403:
            raise MicrosoftTodoPermissionError("Microsoft denied the task operation.")
        if status_code == 404:
            raise MicrosoftTodoNotFoundError("The Microsoft To Do task was not found.")
        if status_code == 429:
            raise MicrosoftTodoThrottledError("Microsoft To Do is temporarily throttled.")
        if status_code >= 500 and write:
            raise MicrosoftTodoAmbiguousWriteError(
                "Microsoft To Do write outcome is unknown."
            )
        if status_code >= 400:
            raise MicrosoftTodoUpstreamError("Microsoft To Do is unavailable.")

    @staticmethod
    def _task_from_response(response: Any, *, write: bool = False) -> TodoTask:
        try:
            payload = response.json()
        except ValueError as exc:
            if write:
                raise MicrosoftTodoAmbiguousWriteError(
                    "Microsoft To Do write outcome is unknown."
                ) from exc
            raise MicrosoftTodoUpstreamError(
                "Microsoft To Do returned an invalid response."
            ) from exc
        task = _normalize_task(payload)
        if task is not None:
            return task
        if write:
            raise MicrosoftTodoAmbiguousWriteError(
                "Microsoft To Do write outcome is unknown."
            )
        raise MicrosoftTodoUpstreamError("Microsoft To Do returned an invalid response.")

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
        identifier = _validated_identifier(list_id, label="list")
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

    def get_task(self, list_id: str, task_id: str) -> TodoTask:
        """Read one exact task for future action verification."""
        list_identifier = _validated_identifier(list_id, label="list")
        task_identifier = _validated_identifier(task_id, label="task")
        url = (
            f"{GRAPH_ROOT}/me/todo/lists/{quote(list_identifier, safe='')}/tasks/"
            f"{quote(task_identifier, safe='')}"
        )
        response = self._request("get", url)
        if response.status_code != 200:
            self._raise_response_error(response, write=False)
            raise MicrosoftTodoUpstreamError("Microsoft To Do returned an invalid response.")
        return self._task_from_response(response)

    def create_task(self, list_id: str, request: TodoTaskCreateRequest) -> TodoTask:
        """Create one task without retrying an uncertain Graph write."""
        list_identifier = _validated_identifier(list_id, label="list")
        response = self._request(
            "post",
            f"{GRAPH_ROOT}/me/todo/lists/{quote(list_identifier, safe='')}/tasks",
            payload=_create_payload(request),
            write=True,
        )
        if response.status_code != 201:
            self._raise_response_error(response, write=True)
            raise MicrosoftTodoAmbiguousWriteError(
                "Microsoft To Do write outcome is unknown."
            )
        return self._task_from_response(response, write=True)

    def patch_task(
        self,
        list_id: str,
        task_id: str,
        request: TodoTaskPatchRequest,
    ) -> TodoTask:
        """Patch supported fields on one task without retrying an uncertain write."""
        list_identifier = _validated_identifier(list_id, label="list")
        task_identifier = _validated_identifier(task_id, label="task")
        url = (
            f"{GRAPH_ROOT}/me/todo/lists/{quote(list_identifier, safe='')}/tasks/"
            f"{quote(task_identifier, safe='')}"
        )
        response = self._request(
            "patch", url, payload=_patch_payload(request), write=True
        )
        if response.status_code != 200:
            self._raise_response_error(response, write=True)
            raise MicrosoftTodoAmbiguousWriteError(
                "Microsoft To Do write outcome is unknown."
            )
        return self._task_from_response(response, write=True)

    def delete_task(self, list_id: str, task_id: str) -> None:
        """Delete one task; callers must use an exact read to verify absence."""
        list_identifier = _validated_identifier(list_id, label="list")
        task_identifier = _validated_identifier(task_id, label="task")
        url = (
            f"{GRAPH_ROOT}/me/todo/lists/{quote(list_identifier, safe='')}/tasks/"
            f"{quote(task_identifier, safe='')}"
        )
        response = self._request("delete", url, write=True)
        if response.status_code != 204:
            self._raise_response_error(response, write=True)
            raise MicrosoftTodoAmbiguousWriteError(
                "Microsoft To Do write outcome is unknown."
            )


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
