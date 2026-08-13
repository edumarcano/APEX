"""Production-path coverage for approval-gated Microsoft To Do task mutations."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from clients.microsoft_auth import MicrosoftTodoAuthenticationRequiredError
from clients.microsoft_todo_client import (
    MicrosoftTodoAmbiguousWriteError,
    MicrosoftTodoInvalidInputError,
    MicrosoftTodoNotFoundError,
    MicrosoftTodoPermissionError,
    MicrosoftTodoThrottledError,
    MicrosoftTodoUpstreamError,
)
from clients.microsoft_todo_models import UNSET, TodoDateTime, TodoTask
from core.actions import ActionService, ActionStore
from core.actions.microsoft_todo import (
    MicrosoftTodoTaskMutationExecutor,
    MicrosoftTodoTaskMutationVerifier,
)
from core.agent.capabilities import CapabilityError, get_capability_descriptor, invoke_capability, validate_capability_arguments
from core.agent.tool_profiles import get_tool_profile


def _task(**changes: object) -> TodoTask:
    fields: dict[str, object] = {
        "id": "task-1", "title": "Study", "status": "notStarted",
        "importance": "normal", "is_completed": False,
        "created_at": "2026-08-13T12:00:00Z",
        "last_modified_at": "2026-08-13T12:00:00Z",
        "due": TodoDateTime("2026-08-14T09:00:00", "UTC"),
        "completed_at": None,
    }
    fields.update(changes)
    return TodoTask(**fields)


class _Client:
    def __init__(self, *, reads: list[object] | None = None, patch: object = None, delete: object = None) -> None:
        self.read_results = list(reads or [_task(), _task()])
        self.patch_result = _task() if patch is None else patch
        self.delete_result = delete
        self.calls: list[tuple[str, object]] = []

    def get_task(self, list_id, task_id):
        self.calls.append(("get", (list_id, task_id)))
        result = self.read_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def patch_task(self, list_id, task_id, request):
        self.calls.append(("patch", (list_id, task_id, request)))
        if isinstance(self.patch_result, Exception):
            raise self.patch_result
        return self.patch_result

    def delete_task(self, list_id, task_id):
        self.calls.append(("delete", (list_id, task_id)))
        if isinstance(self.delete_result, Exception):
            raise self.delete_result


class MicrosoftTodoTaskMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="apex_todo_mutation_")
        self.addCleanup(self.tempdir.cleanup)
        self.service = ActionService(ActionStore(Path(self.tempdir.name) / "actions.db"))

    def _action(self, capability: str, **arguments: object):
        target = {"list_id": "list-1", "task_id": "task-1", "last_modified_at": "2026-08-13T12:00:00Z"}
        target.update(arguments)
        return self.service.propose(
            agent_key="panthera", capability_name=capability, arguments=target,
            target=capability, risk="destructive" if capability.startswith("delete_") else "write",
            summary=f"Approve {capability}",
        )

    def _register(self, client: _Client, capability: str) -> None:
        self.service.register_handler(
            capability,
            executor=MicrosoftTodoTaskMutationExecutor(client, capability),
            verifier=MicrosoftTodoTaskMutationVerifier(client, capability),
        )

    def test_capability_contracts_direct_rejection_and_profiles(self) -> None:
        target = {"list_id": "list-1", "task_id": "task-1", "last_modified_at": "2026-08-13T12:00:00Z"}
        for name, risk in (
            ("update_microsoft_todo_task", "write"),
            ("complete_microsoft_todo_task", "write"),
            ("reopen_microsoft_todo_task", "write"),
            ("delete_microsoft_todo_task", "destructive"),
        ):
            descriptor = get_capability_descriptor(name)
            self.assertEqual(descriptor.risk, risk)
            self.assertFalse(descriptor.expose_to_mcp_server)
            with self.assertRaises(CapabilityError):
                invoke_capability(name, target | ({"title": "New"} if name.startswith("update") else {}))
            for profile in ("personal_ops", "daily_planning"):
                self.assertIn(name, get_tool_profile(profile).tool_names)
        self.assertEqual(
            validate_capability_arguments("update_microsoft_todo_task", target | {"due": None})["due"], None
        )
        for invalid in (target, target | {"due": {}}, target | {"title": " "}, target | {"extra": True}):
            with self.assertRaises(CapabilityError):
                validate_capability_arguments("update_microsoft_todo_task", invalid)

    def test_update_prechecks_then_patches_once_and_verifies_requested_fields(self) -> None:
        client = _Client(reads=[_task(), _task(title="Read", importance="high", due=None)])
        capability = "update_microsoft_todo_task"
        self._register(client, capability)
        action = self._action(capability, title="Read", importance="high", due=None)
        approved = self.service.approve(action.action_id, actor="operator")
        result = self.service.claim_and_execute(action.action_id, actor="executor", expected_version=approved.version)
        self.assertEqual(result.status, "verified")
        self.assertEqual([call[0] for call in client.calls], ["get", "patch", "get"])
        request = client.calls[1][1][2]
        self.assertEqual((request.title, request.importance, request.due), ("Read", "high", None))
        event = next(event for event in self.service.events(action.action_id) if event.to_status == "verifying")
        self.assertEqual(dict(event.evidence), {"list_id": "list-1", "task_id": "task-1"})

    def test_stale_or_mismatched_target_fails_before_any_mutation(self) -> None:
        for current in (_task(last_modified_at="later"), _task(id="other")):
            client = _Client(reads=[current])
            capability = "complete_microsoft_todo_task"
            self._register(client, capability)
            action = self._action(capability)
            approved = self.service.approve(action.action_id, actor="operator")
            result = self.service.claim_and_execute(action.action_id, actor="executor", expected_version=approved.version)
            self.assertEqual(result.status, "execution_failed")
            self.assertEqual(self.service.events(action.action_id)[-1].result_code, "microsoft_todo_task_changed")
            self.assertEqual([call[0] for call in client.calls], ["get"])

    def test_status_actions_patch_only_status_and_verify(self) -> None:
        for capability, expected_status in (
            ("complete_microsoft_todo_task", "completed"),
            ("reopen_microsoft_todo_task", "notStarted"),
        ):
            completed = expected_status == "completed"
            client = _Client(reads=[_task(), _task(status=expected_status, is_completed=completed)])
            self._register(client, capability)
            action = self._action(capability)
            approved = self.service.approve(action.action_id, actor="operator")
            result = self.service.claim_and_execute(action.action_id, actor="executor", expected_version=approved.version)
            self.assertEqual(result.status, "verified")
            request = client.calls[1][1][2]
            self.assertEqual(request.status, expected_status)
            self.assertIs(request.title, UNSET)
            self.assertIs(request.due, UNSET)
            self.assertIs(request.importance, UNSET)

    def test_delete_verifies_only_confirmed_absence_and_retry_does_not_reexecute(self) -> None:
        capability = "delete_microsoft_todo_task"
        client = _Client(reads=[_task(), _task()], delete=MicrosoftTodoAmbiguousWriteError("x"))
        self._register(client, capability)
        action = self._action(capability)
        approved = self.service.approve(action.action_id, actor="operator")
        unknown = self.service.claim_and_execute(action.action_id, actor="executor", expected_version=approved.version)
        self.assertEqual(unknown.status, "outcome_unknown")
        client.read_results = [MicrosoftTodoNotFoundError("gone")]
        verified = self.service.retry_verification(action.action_id, actor="operator", expected_version=unknown.version)
        self.assertEqual(verified.status, "verified")
        self.assertEqual([call[0] for call in client.calls], ["get", "delete", "get"])

    def test_mutation_failure_categories_and_verifier_mismatches(self) -> None:
        capability = "complete_microsoft_todo_task"
        action = self._action(capability)
        for error, code in (
            (MicrosoftTodoInvalidInputError("x"), "microsoft_todo_invalid_input"),
            (MicrosoftTodoAuthenticationRequiredError("x"), "microsoft_todo_authentication_required"),
            (MicrosoftTodoPermissionError("x"), "microsoft_todo_permission_denied"),
            (MicrosoftTodoThrottledError("x"), "microsoft_todo_throttled"),
            (MicrosoftTodoUpstreamError("x"), "microsoft_todo_upstream_unavailable"),
        ):
            outcome = MicrosoftTodoTaskMutationExecutor(_Client(reads=[_task()], patch=error), capability).execute(action)
            self.assertEqual((outcome.succeeded, outcome.code), (False, code))
        mismatch = MicrosoftTodoTaskMutationVerifier(_Client(reads=[_task(status="notStarted")]), capability).verify(action, {})
        self.assertEqual((mismatch.code, mismatch.evidence["fields"]), ("microsoft_todo_task_mismatch", ("status",)))
        unavailable = MicrosoftTodoTaskMutationVerifier(_Client(reads=[MicrosoftTodoPermissionError("x")]), capability).verify(action, {})
        self.assertEqual(unavailable.code, "microsoft_todo_verification_unavailable")


if __name__ == "__main__":
    unittest.main()
