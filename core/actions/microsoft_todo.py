"""Microsoft To Do handlers for approval-gated task creation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from clients.microsoft_auth import (
    MicrosoftTodoAuthenticationRequiredError,
    MicrosoftTodoNotConfiguredError,
)
from clients.microsoft_todo_client import (
    MicrosoftTodoAmbiguousWriteError,
    MicrosoftTodoClient,
    MicrosoftTodoInvalidInputError,
    MicrosoftTodoNotFoundError,
    MicrosoftTodoPermissionError,
    MicrosoftTodoThrottledError,
    MicrosoftTodoUpstreamError,
)
from clients.microsoft_todo_models import TodoDateTime, TodoTaskCreateRequest
from core.actions.models import ActionRecord, ExecutionOutcome, VerificationOutcome


class CreateMicrosoftTodoTaskExecutor:
    """Create exactly one task from an immutable approved proposal."""

    def __init__(self, client: MicrosoftTodoClient) -> None:
        self._client = client

    def execute(self, action: ActionRecord) -> ExecutionOutcome:
        arguments = action.proposal.arguments
        try:
            list_id = _required_text(arguments.get("list_id"))
            request = TodoTaskCreateRequest(
                title=_required_text(arguments.get("title")),
                due=_due_from_arguments(arguments.get("due")),
                importance=_importance_from_arguments(arguments.get("importance")),
            )
            task = self._client.create_task(list_id, request)
        except MicrosoftTodoAmbiguousWriteError:
            return ExecutionOutcome(None, "microsoft_todo_create_outcome_unknown", {})
        except MicrosoftTodoInvalidInputError:
            return ExecutionOutcome(False, "microsoft_todo_invalid_input", {})
        except MicrosoftTodoAuthenticationRequiredError:
            return ExecutionOutcome(False, "microsoft_todo_authentication_required", {})
        except MicrosoftTodoNotConfiguredError:
            return ExecutionOutcome(False, "microsoft_todo_not_configured", {})
        except MicrosoftTodoPermissionError:
            return ExecutionOutcome(False, "microsoft_todo_permission_denied", {})
        except MicrosoftTodoNotFoundError:
            return ExecutionOutcome(False, "microsoft_todo_list_not_found", {})
        except MicrosoftTodoThrottledError:
            return ExecutionOutcome(False, "microsoft_todo_throttled", {})
        except (MicrosoftTodoUpstreamError, TimeoutError):
            return ExecutionOutcome(False, "microsoft_todo_upstream_unavailable", {})
        return ExecutionOutcome(
            True,
            "microsoft_todo_task_created",
            {"list_id": list_id, "task_id": task.id},
        )


class CreateMicrosoftTodoTaskVerifier:
    """Verify a created task through an exact Microsoft Graph read-back."""

    def __init__(self, client: MicrosoftTodoClient) -> None:
        self._client = client

    def verify(
        self,
        action: ActionRecord,
        execution_evidence: Mapping[str, object],
    ) -> VerificationOutcome:
        list_id = execution_evidence.get("list_id")
        task_id = execution_evidence.get("task_id")
        if not _is_nonblank_text(list_id) or not _is_nonblank_text(task_id):
            return VerificationOutcome(False, "microsoft_todo_execution_evidence_missing", {})

        expected_list_id = action.proposal.arguments.get("list_id")
        if list_id != expected_list_id:
            return VerificationOutcome(False, "microsoft_todo_task_mismatch", {"fields": ["list_id"]})

        try:
            task = self._client.get_task(list_id, task_id)
        except MicrosoftTodoNotFoundError:
            return VerificationOutcome(False, "microsoft_todo_task_not_found", {})
        except (
            MicrosoftTodoAuthenticationRequiredError,
            MicrosoftTodoNotConfiguredError,
            MicrosoftTodoInvalidInputError,
            MicrosoftTodoPermissionError,
            MicrosoftTodoThrottledError,
            MicrosoftTodoUpstreamError,
            TimeoutError,
        ):
            return VerificationOutcome(False, "microsoft_todo_verification_unavailable", {})

        mismatches: list[str] = []
        arguments = action.proposal.arguments
        if task.id != task_id:
            mismatches.append("task_id")
        if task.title != arguments.get("title"):
            mismatches.append("title")
        if task.importance != _importance_from_arguments(arguments.get("importance")):
            mismatches.append("importance")
        if not _matches_due(task.due, arguments.get("due")):
            mismatches.append("due")
        if task.is_completed:
            mismatches.append("status")
        if mismatches:
            return VerificationOutcome(
                False,
                "microsoft_todo_task_mismatch",
                {"fields": mismatches},
            )
        return VerificationOutcome(True, "microsoft_todo_task_verified", {})


def _required_text(value: object) -> str:
    if not _is_nonblank_text(value):
        raise MicrosoftTodoInvalidInputError("Microsoft To Do task arguments are invalid.")
    return value


def _is_nonblank_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _importance_from_arguments(value: object) -> str:
    if value in {"low", "normal", "high"}:
        return value
    raise MicrosoftTodoInvalidInputError("Microsoft To Do task importance is invalid.")


def _due_from_arguments(value: object) -> TodoDateTime | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise MicrosoftTodoInvalidInputError("Microsoft To Do task due date is invalid.")
    date_time = value.get("date_time")
    time_zone = value.get("time_zone")
    if not _is_nonblank_text(date_time) or not _is_nonblank_text(time_zone):
        raise MicrosoftTodoInvalidInputError("Microsoft To Do task due date is invalid.")
    return TodoDateTime(date_time=date_time, time_zone=time_zone)


def _matches_due(actual: TodoDateTime | None, expected: Any) -> bool:
    if expected is None:
        return actual is None
    try:
        wanted = _due_from_arguments(expected)
    except MicrosoftTodoInvalidInputError:
        return False
    return actual == wanted
