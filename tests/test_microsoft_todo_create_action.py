"""Production-path coverage for approval-gated Microsoft To Do creation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from clients.microsoft_auth import (
    MicrosoftTodoAuthenticationRequiredError,
    MicrosoftTodoNotConfiguredError,
)
from clients.microsoft_todo_client import (
    MicrosoftTodoAmbiguousWriteError,
    MicrosoftTodoInvalidInputError,
    MicrosoftTodoNotFoundError,
    MicrosoftTodoPermissionError,
    MicrosoftTodoThrottledError,
    MicrosoftTodoUpstreamError,
)
from clients.microsoft_todo_models import TodoDateTime, TodoTask
from core.actions import ActionService, ActionStore
from core.actions.microsoft_todo import (
    CreateMicrosoftTodoTaskExecutor,
    CreateMicrosoftTodoTaskVerifier,
)
from core.agent.capabilities import (
    CapabilityError,
    get_capability_descriptor,
    invoke_capability,
    validate_capability_arguments,
)
from core.agent.tool_profiles import get_tool_profile


def _task(**changes: object) -> TodoTask:
    fields: dict[str, object] = {
        "id": "task-1",
        "title": "Study",
        "status": "notStarted",
        "importance": "normal",
        "is_completed": False,
        "created_at": "2026-08-13T12:00:00Z",
        "last_modified_at": "2026-08-13T12:00:00Z",
        "due": None,
        "completed_at": None,
    }
    fields.update(changes)
    return TodoTask(**fields)


class _Client:
    def __init__(self, *, create: object = None, read: object = None) -> None:
        self.create_result = _task() if create is None else create
        self.read_result = _task() if read is None else read
        self.creates: list[tuple[str, object]] = []
        self.reads: list[tuple[str, str]] = []

    def create_task(self, list_id, request):
        self.creates.append((list_id, request))
        if isinstance(self.create_result, Exception):
            raise self.create_result
        return self.create_result

    def get_task(self, list_id, task_id):
        self.reads.append((list_id, task_id))
        if isinstance(self.read_result, Exception):
            raise self.read_result
        return self.read_result


class MicrosoftTodoCreateActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="apex_todo_action_")
        self.addCleanup(self.tempdir.cleanup)
        self.service = ActionService(ActionStore(Path(self.tempdir.name) / "actions.db"))

    def _action(self, **arguments: object):
        payload = {"list_id": "list-1", "title": "Study", "importance": "normal"}
        payload.update(arguments)
        return self.service.propose(
            agent_key="panthera",
            capability_name="create_microsoft_todo_task",
            arguments=payload,
            target="Create Microsoft To Do Task",
            risk="write",
            summary="Approve Create Microsoft To Do Task",
        )

    def _register(self, client: _Client) -> None:
        self.service.register_handler(
            "create_microsoft_todo_task",
            executor=CreateMicrosoftTodoTaskExecutor(client),
            verifier=CreateMicrosoftTodoTaskVerifier(client),
        )

    def test_capability_schema_defaults_and_profiles(self) -> None:
        descriptor = get_capability_descriptor("create_microsoft_todo_task")
        self.assertIsNotNone(descriptor)
        self.assertEqual(descriptor.risk, "write")
        self.assertFalse(descriptor.expose_to_mcp_server)
        self.assertEqual(
            validate_capability_arguments(
                "create_microsoft_todo_task", {"list_id": "AQMkADAwATMwMAIt", "title": "Study"}
            )["importance"],
            "normal",
        )
        with self.assertRaises(Exception):
            validate_capability_arguments(
                "create_microsoft_todo_task",
                {"list_id": "AQMkADAwATMwMAIt", "title": "Study", "due": {"date_time": "2026-08-14"}},
            )
        with self.assertRaises(Exception):
            validate_capability_arguments(
                "create_microsoft_todo_task", {"list_id": "Tasks", "title": "Study"}
            )
        with self.assertRaises(CapabilityError):
            invoke_capability(
                "create_microsoft_todo_task", {"list_id": "AQMkADAwATMwMAIt", "title": "Study"}
            )
        for profile_name in ("personal_ops", "daily_planning"):
            self.assertIn("create_microsoft_todo_task", get_tool_profile(profile_name).tool_names)

    def test_approval_creates_once_persists_identifiers_and_verifies_exact_fields(self) -> None:
        client = _Client(read=_task(due=TodoDateTime("2026-08-14T09:00:00", "UTC")))
        self._register(client)
        action = self._action(due={"date_time": "2026-08-14T09:00:00", "time_zone": "UTC"})

        approved = self.service.approve(action.action_id, actor="operator")
        result = self.service.claim_and_execute(action.action_id, actor="executor", expected_version=approved.version)

        self.assertEqual(result.status, "verified")
        self.assertEqual(len(client.creates), 1)
        self.assertEqual(client.creates[0][1].due, TodoDateTime("2026-08-14T09:00:00", "UTC"))
        self.assertEqual(client.reads, [("list-1", "task-1")])
        verifying_event = [event for event in self.service.events(action.action_id) if event.to_status == "verifying"][0]
        self.assertEqual(dict(verifying_event.evidence), {"list_id": "list-1", "task_id": "task-1"})

    def test_verification_retry_reuses_persisted_evidence_without_creating_again(self) -> None:
        client = _Client(read=_task(title="Different"))
        self._register(client)
        action = self._action()
        approved = self.service.approve(action.action_id, actor="operator")
        failed = self.service.claim_and_execute(action.action_id, actor="executor", expected_version=approved.version)
        self.assertEqual(failed.status, "verification_failed")

        client.read_result = _task()
        recovered = self.service.retry_verification(
            action.action_id, actor="operator", expected_version=failed.version
        )
        self.assertEqual(recovered.status, "verified")
        self.assertEqual(len(client.creates), 1)
        self.assertEqual(client.reads, [("list-1", "task-1"), ("list-1", "task-1")])

    def test_executor_classifies_known_and_ambiguous_failures(self) -> None:
        expected = [
            (MicrosoftTodoAmbiguousWriteError("x"), None, "microsoft_todo_create_outcome_unknown"),
            (MicrosoftTodoInvalidInputError("x"), False, "microsoft_todo_invalid_input"),
            (MicrosoftTodoAuthenticationRequiredError("x"), False, "microsoft_todo_authentication_required"),
            (MicrosoftTodoNotConfiguredError("x"), False, "microsoft_todo_not_configured"),
            (MicrosoftTodoPermissionError("x"), False, "microsoft_todo_permission_denied"),
            (MicrosoftTodoNotFoundError("x"), False, "microsoft_todo_list_not_found"),
            (MicrosoftTodoThrottledError("x"), False, "microsoft_todo_throttled"),
            (MicrosoftTodoUpstreamError("x"), False, "microsoft_todo_upstream_unavailable"),
            (TimeoutError(), False, "microsoft_todo_upstream_unavailable"),
        ]
        action = self._action()
        for error, succeeded, code in expected:
            outcome = CreateMicrosoftTodoTaskExecutor(_Client(create=error)).execute(action)
            self.assertEqual((outcome.succeeded, outcome.code, dict(outcome.evidence)), (succeeded, code, {}))

    def test_verifier_reports_missing_evidence_mismatches_and_read_failures(self) -> None:
        action = self._action()
        verifier = CreateMicrosoftTodoTaskVerifier(_Client())
        self.assertEqual(verifier.verify(action, {}).code, "microsoft_todo_execution_evidence_missing")
        self.assertEqual(
            verifier.verify(action, {"list_id": "other", "task_id": "task-1"}).evidence["fields"],
            ("list_id",),
        )
        mismatch = CreateMicrosoftTodoTaskVerifier(_Client(read=_task(title="Other", is_completed=True))).verify(
            action, {"list_id": "list-1", "task_id": "task-1"}
        )
        self.assertEqual(mismatch.code, "microsoft_todo_task_mismatch")
        self.assertEqual(set(mismatch.evidence["fields"]), {"title", "status"})
        for error, code in (
            (MicrosoftTodoNotFoundError("x"), "microsoft_todo_task_not_found"),
            (MicrosoftTodoPermissionError("x"), "microsoft_todo_verification_unavailable"),
            (MicrosoftTodoInvalidInputError("x"), "microsoft_todo_verification_unavailable"),
            (TimeoutError(), "microsoft_todo_verification_unavailable"),
        ):
            outcome = CreateMicrosoftTodoTaskVerifier(_Client(read=error)).verify(
                action, {"list_id": "list-1", "task_id": "task-1"}
            )
            self.assertEqual(outcome.code, code)


if __name__ == "__main__":
    unittest.main()
