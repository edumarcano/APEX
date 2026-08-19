"""Read-only Microsoft To Do foundation regression coverage."""

from __future__ import annotations

import asyncio
import os
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

import requests

from clients.microsoft_auth import (
    MICROSOFT_TODO_SCOPES,
    MicrosoftTodoAuthenticationRequiredError,
    MicrosoftTodoAuthenticationService,
    MicrosoftTodoNotConfiguredError,
    get_microsoft_auth_service,
    set_microsoft_auth_service,
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
from clients.microsoft_todo_models import (
    MicrosoftTodoAuthConfig,
    MicrosoftTodoAuthStatus,
    MicrosoftTodoDeviceAuthorization,
    TodoDateTime,
    TodoTaskCreateRequest,
    TodoTaskPatchRequest,
    TodoTaskListsResult,
    TodoTasksResult,
)

from core.agent.capabilities import (
    CapabilityError,
    CapabilityErrorCategory,
    get_capability_descriptor,
)
from core.agent.tool_catalog import build_tool_catalog
from core.agent.tools import list_microsoft_todo_lists, list_microsoft_todo_tasks
from core.api.routers.microsoft_todo import (
    disconnect_microsoft_todo,
    microsoft_todo_status,
    start_microsoft_todo_authorization,
)


class _Auth:
    def acquire_access_token(self) -> str:
        return "test-token"

    def status_snapshot(self) -> MicrosoftTodoAuthStatus:
        return MicrosoftTodoAuthStatus(configured=True, state="connected")


    def mark_authentication_required(self) -> None:
        self.authentication_required = True

class _Response:
    def __init__(self, payload, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        return self._request("get", url, **kwargs)

    def post(self, url, **kwargs):
        return self._request("post", url, **kwargs)

    def patch(self, url, **kwargs):
        return self._request("patch", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._request("delete", url, **kwargs)

    def _request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class MicrosoftTodoClientTests(unittest.TestCase):
    def test_lists_and_tasks_are_bounded_and_normalized(self) -> None:
        session = _Session([
            _Response({"value": [{"id": "list-1", "displayName": "Tasks", "isOwner": True}]}),
            _Response({"value": [
                {
                    "id": "task-1",
                    "title": "  Ship\x00 release  ",
                    "status": "notStarted",
                    "importance": "high",
                    "dueDateTime": {
                        "dateTime": "2026-08-01T13:00:00",
                        "timeZone": "Eastern Standard Time",
                    },
                },
                {"id": "task-2", "title": "Done", "status": "completed"},
                {"id": "", "title": "Malformed"},
            ]}),
        ])
        client = MicrosoftTodoClient(_Auth(), session=session)

        lists = client.list_task_lists()
        tasks = client.list_tasks("list-1")

        self.assertEqual(lists.lists[0].display_name, "Tasks")
        self.assertEqual(tasks.task_count, 1)
        self.assertEqual(tasks.tasks[0].title, "Ship release")
        self.assertEqual(tasks.tasks[0].due.time_zone, "Eastern Standard Time")
        self.assertTrue(all(call[1].startswith("https://graph.microsoft.com/v1.0/") for call in session.calls))
        self.assertTrue(all(call[2]["headers"]["Authorization"] == "Bearer test-token" for call in session.calls))
        self.assertTrue(all("$select" not in call[1] for call in session.calls))
        self.assertIn("?$top=50", session.calls[0][1])
        self.assertIn("/tasks?$top=50", session.calls[1][1])

    def test_untrusted_pagination_host_is_rejected(self) -> None:
        client = MicrosoftTodoClient(
            _Auth(),
            session=_Session([_Response({
                "value": [],
                "@odata.nextLink": "https://example.com/steal",
            })]),
        )
        with self.assertRaises(MicrosoftTodoUpstreamError):
            client.list_task_lists()

    def test_invalid_identifier_is_rejected_before_request(self) -> None:
        session = _Session([])
        client = MicrosoftTodoClient(_Auth(), session=session)
        with self.assertRaises(MicrosoftTodoInvalidInputError):
            client.list_tasks("bad\x00id")
        self.assertEqual(session.calls, [])

    def test_unauthorized_graph_response_updates_authentication_state(self) -> None:
        auth = _Auth()
        client = MicrosoftTodoClient(
            auth,
            session=_Session([_Response({"value": []}, status_code=401)]),
        )

        with self.assertRaises(MicrosoftTodoAuthenticationRequiredError):
            client.list_task_lists()
        self.assertTrue(auth.authentication_required)

    def test_exact_read_uses_documented_request(self) -> None:
        task = {
            "id": "task-1", "title": "Ship release", "status": "notStarted",
            "importance": "normal", "lastModifiedDateTime": "2026-08-12T00:00:00Z",
        }
        session = _Session([_Response(task)])
        client = MicrosoftTodoClient(_Auth(), session=session)

        self.assertEqual(client.get_task("list-1", "task-1").id, "task-1")
        self.assertEqual(session.calls[0][0], "get")
        self.assertTrue(session.calls[0][1].endswith("/lists/list-1/tasks/task-1"))

    def test_default_list_alias_uses_its_canonical_identifier_for_write_and_read(self) -> None:
        list_id = "AQMkADAwATMwMAItMDFkYS00MmMyLTAwAi0wMAoALgAAAA=="
        task = {"id": "task-1", "title": "Ship release", "status": "notStarted"}
        session = _Session([
            _Response({"value": [{
                "id": list_id,
                "displayName": "Tasks",
                "wellknownListName": "defaultList",
            }]}),
            _Response(task, status_code=201),
            _Response({"value": [{
                "id": list_id,
                "displayName": "Tasks",
                "wellknownListName": "defaultList",
            }]}),
            _Response(task),
        ])
        client = MicrosoftTodoClient(_Auth(), session=session)

        self.assertEqual(
            client.create_task("Tasks", TodoTaskCreateRequest(title="Ship release")).id,
            "task-1",
        )
        self.assertEqual(client.get_task("Tasks", "task-1").id, "task-1")
        encoded_list_id = quote(list_id, safe="")
        self.assertTrue(session.calls[1][1].endswith(f"/lists/{encoded_list_id}/tasks"))
        self.assertTrue(session.calls[3][1].endswith(f"/lists/{encoded_list_id}/tasks/task-1"))

    def test_create_uses_documented_request(self) -> None:
        task = {"id": "task-1", "title": "Ship release", "status": "notStarted"}
        session = _Session([_Response(task, status_code=201)])
        client = MicrosoftTodoClient(_Auth(), session=session)

        self.assertEqual(client.create_task("list-1", TodoTaskCreateRequest(
            title="Ship release",
            due=TodoDateTime("2026-08-13T09:00:00", "Eastern Standard Time"),
            importance="high",
        )).title, "Ship release")
        self.assertEqual(session.calls[0][0], "post")
        self.assertEqual(session.calls[0][2]["json"], {
            "title": "Ship release",
            "dueDateTime": {
                "dateTime": "2026-08-13T09:00:00",
                "timeZone": "Eastern Standard Time",
            },
            "importance": "high",
        })

    def test_patch_uses_documented_request_and_can_clear_due_date(self) -> None:
        task = {"id": "task-1", "title": "Ship release", "status": "completed"}
        session = _Session([_Response(task)])
        client = MicrosoftTodoClient(_Auth(), session=session)

        self.assertTrue(client.patch_task(
            "list-1", "task-1", TodoTaskPatchRequest(due=None, status="completed")
        ).is_completed)
        self.assertEqual(session.calls[0][0], "patch")
        self.assertEqual(session.calls[0][2]["json"], {
            "dueDateTime": None, "status": "completed",
        })

    def test_delete_accepts_only_no_content(self) -> None:
        session = _Session([_Response({}, status_code=204)])
        client = MicrosoftTodoClient(_Auth(), session=session)

        self.assertIsNone(client.delete_task("list-1", "task-1"))
        self.assertEqual(session.calls[0][0], "delete")

    def test_write_rejects_invalid_input_before_request(self) -> None:
        session = _Session([])
        client = MicrosoftTodoClient(_Auth(), session=session)
        with self.assertRaises(MicrosoftTodoInvalidInputError):
            client.create_task("list-1", TodoTaskCreateRequest(title="\x00invalid"))
        with self.assertRaises(MicrosoftTodoInvalidInputError):
            client.patch_task("list-1", "task-1", TodoTaskPatchRequest())
        with self.assertRaises(MicrosoftTodoInvalidInputError):
            client.get_task("list-1", "bad\x00task")
        with self.assertRaises(MicrosoftTodoInvalidInputError):
            client.get_task(" list-1 ", "task-1")
        with self.assertRaises(MicrosoftTodoInvalidInputError):
            client.create_task("list-1", TodoTaskCreateRequest(title="bad\u0085title"))
        self.assertEqual(session.calls, [])

    def test_exact_read_and_writes_classify_graph_responses(self) -> None:
        client = MicrosoftTodoClient(_Auth(), session=_Session([_Response({}, status_code=404)]))
        with self.assertRaises(MicrosoftTodoNotFoundError):
            client.get_task("list-1", "task-1")

        client = MicrosoftTodoClient(_Auth(), session=_Session([_Response({}, status_code=400)]))
        with self.assertRaises(MicrosoftTodoInvalidInputError):
            client.create_task("list-1", TodoTaskCreateRequest(title="Study"))

        client = MicrosoftTodoClient(_Auth(), session=_Session([_Response({}, status_code=403)]))
        with self.assertRaises(MicrosoftTodoPermissionError):
            client.create_task("list-1", TodoTaskCreateRequest(title="Study"))

        client = MicrosoftTodoClient(_Auth(), session=_Session([_Response({}, status_code=429)]))
        with self.assertRaises(MicrosoftTodoThrottledError):
            client.patch_task("list-1", "task-1", TodoTaskPatchRequest(status="completed"))

        client = MicrosoftTodoClient(_Auth(), session=_Session([_Response({}, status_code=503)]))
        with self.assertRaises(MicrosoftTodoAmbiguousWriteError):
            client.delete_task("list-1", "task-1")

        client = MicrosoftTodoClient(_Auth(), session=_Session([_Response({}, status_code=200)]))
        with self.assertRaises(MicrosoftTodoAmbiguousWriteError):
            client.delete_task("list-1", "task-1")

        auth = _Auth()
        client = MicrosoftTodoClient(auth, session=_Session([_Response({}, status_code=401)]))
        with self.assertRaises(MicrosoftTodoAuthenticationRequiredError):
            client.get_task("list-1", "task-1")
        self.assertTrue(auth.authentication_required)

    def test_ambiguous_writes_never_retry_or_expose_response_data(self) -> None:
        timeout_session = _Session([requests.Timeout("access_token=secret")])
        client = MicrosoftTodoClient(
            _Auth(), session=timeout_session
        )
        with self.assertRaises(MicrosoftTodoAmbiguousWriteError) as raised:
            client.create_task("list-1", TodoTaskCreateRequest(title="Study"))
        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(len(timeout_session.calls), 1)

        client = MicrosoftTodoClient(_Auth(), session=_Session([_Response({"id": "task-1"}, 201)]))
        with self.assertRaises(MicrosoftTodoAmbiguousWriteError):
            client.create_task("list-1", TodoTaskCreateRequest(title="Study"))

        client = MicrosoftTodoClient(_Auth(), session=_Session([_Response({"id": "task-1"})]))
        with self.assertRaises(MicrosoftTodoUpstreamError):
            client.get_task("list-1", "task-1")


class MicrosoftTodoAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    def test_missing_client_id_does_not_initialize_cache(self) -> None:
        with mock.patch.dict(os.environ, {"MICROSOFT_TODO_CLIENT_ID": ""}), mock.patch(
            "clients.microsoft_auth.build_encrypted_persistence"
        ) as persistence:
            service = MicrosoftTodoAuthenticationService(client_id="")
        self.assertEqual(service.status_snapshot().state, "not-configured")
        persistence.assert_not_called()
        with self.assertRaises(MicrosoftTodoNotConfiguredError):
            service.acquire_access_token()

    def test_cache_path_inside_repository_fails_closed(self) -> None:
        repository_cache = Path(__file__).resolve().parent.parent / "token.bin"
        with mock.patch("clients.microsoft_auth.build_encrypted_persistence") as persistence:
            service = MicrosoftTodoAuthenticationService(
                client_id="client", cache_path=repository_cache
            )
        self.assertEqual(service.status_snapshot().state, "degraded")
        persistence.assert_not_called()

    def test_scope_is_exactly_tasks_read_write(self) -> None:
        self.assertEqual(MICROSOFT_TODO_SCOPES, ("Tasks.ReadWrite",))

    @staticmethod
    def _service_for(
        app: mock.Mock, *, accounts: list[dict[str, str]] | None = None
    ) -> MicrosoftTodoAuthenticationService:
        app.get_accounts.return_value = [] if accounts is None else accounts
        return MicrosoftTodoAuthenticationService(
            config=MicrosoftTodoAuthConfig(
                client_id="client",
                tenant_id="common",
                cache_path=Path("C:/apex-tests/microsoft-todo.cache"),
            ),
            application_factory=lambda _config: (app, mock.Mock()),
        )

    async def test_existing_read_only_cache_requires_reconnection(self) -> None:
        app = mock.Mock()
        app.acquire_token_silent.return_value = None

        service = self._service_for(app, accounts=[{"home_account_id": "account"}])
        app.acquire_token_silent.assert_not_called()
        await service.initialize()

        snapshot = service.status_snapshot()
        self.assertEqual(snapshot.state, "authentication-required")
        self.assertEqual(snapshot.auth_error_code, "permission")
        self.assertIn("Tasks.ReadWrite", snapshot.auth_error_message or "")
        app.acquire_token_silent.assert_called_once_with(
            ["Tasks.ReadWrite"], account={"home_account_id": "account"}
        )

    async def test_cached_write_grant_is_validated_once_at_startup(self) -> None:
        app = mock.Mock()
        app.acquire_token_silent.return_value = {"access_token": "token"}

        service = self._service_for(app, accounts=[{"home_account_id": "account"}])
        app.acquire_token_silent.assert_not_called()
        await service.initialize()

        self.assertEqual(service.status_snapshot().state, "connected")
        self.assertEqual(service.status_snapshot().state, "connected")
        app.acquire_token_silent.assert_called_once_with(
            ["Tasks.ReadWrite"], account={"home_account_id": "account"}
        )

    async def test_cached_grant_validation_runs_outside_the_event_loop(self) -> None:
        app = mock.Mock()
        app.acquire_token_silent.return_value = {"access_token": "token"}
        service = self._service_for(app, accounts=[{"home_account_id": "account"}])

        with mock.patch(
            "clients.microsoft_auth.asyncio.to_thread", new=mock.AsyncMock(
                side_effect=lambda operation: operation()
            )
        ) as to_thread:
            await service.initialize()

        to_thread.assert_awaited_once_with(service._refresh_cached_authorization)

    async def test_silent_grant_failure_is_sanitized(self) -> None:
        app = mock.Mock()
        app.acquire_token_silent.return_value = {
            "error": "invalid_grant",
            "error_description": "refresh_token=must-not-leak",
        }
        service = self._service_for(app, accounts=[{"home_account_id": "account"}])

        await service.initialize()

        snapshot = service.status_snapshot()
        self.assertEqual(snapshot.state, "authentication-required")
        self.assertEqual(snapshot.auth_error_code, "permission")
        self.assertNotIn("refresh_token", snapshot.auth_error_message or "")


    async def test_device_flow_returns_only_public_fields(self) -> None:
        app = mock.Mock()
        app.initiate_device_flow.return_value = {
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_in": 900,
            "secret": "must-not-leak",
        }
        app.acquire_token_by_device_flow.return_value = {"access_token": "token"}
        service = self._service_for(app)

        result = await service.begin_device_authorization()
        if service._poll_task:
            await service._poll_task
        await service.shutdown()

        self.assertEqual(set(result.to_dict()), {"state", "verification_uri", "user_code", "expires_at"})
        self.assertNotIn("secret", result.to_dict())
        app.initiate_device_flow.assert_called_once_with(scopes=["Tasks.ReadWrite"])

    async def test_concurrent_starts_share_one_device_flow(self) -> None:
        release_poll = threading.Event()
        app = mock.Mock()
        app.initiate_device_flow.return_value = {
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_in": 900,
        }
        app.acquire_token_by_device_flow.side_effect = lambda flow: (
            release_poll.wait(1) or {"access_token": "token"}
        )
        service = self._service_for(app)

        first, second = await asyncio.gather(
            service.begin_device_authorization(),
            service.begin_device_authorization(),
        )
        release_poll.set()
        await service.shutdown()

        self.assertEqual(first.user_code, second.user_code)
        app.initiate_device_flow.assert_called_once_with(scopes=["Tasks.ReadWrite"])

    async def test_device_flow_failure_exposes_only_safe_diagnostic(self) -> None:
        app = mock.Mock()
        app.initiate_device_flow.return_value = {
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_in": 900,
        }
        app.acquire_token_by_device_flow.return_value = {
            "error": "invalid_request",
            "error_description": "client_secret=must-not-leak",
        }
        service = self._service_for(app)

        await service.begin_device_authorization()
        if service._poll_task:
            await service._poll_task
        snapshot = service.status_snapshot()
        await service.shutdown()

        self.assertEqual(snapshot.state, "authentication-required")
        self.assertEqual(snapshot.auth_error_code, "request")
        self.assertIn("app registration", snapshot.auth_error_message or "")
        self.assertNotIn("client_secret", snapshot.auth_error_message or "")


class MicrosoftTodoApiTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        set_microsoft_auth_service(None)

    def test_status_without_service_is_sanitized(self) -> None:
        set_microsoft_auth_service(None)
        response = microsoft_todo_status()
        self.assertFalse(response.configured)
        self.assertEqual(response.state, "not-configured")

    async def test_start_and_disconnect_delegate_to_service(self) -> None:
        service = mock.Mock()
        service.begin_device_authorization = mock.AsyncMock(return_value=MicrosoftTodoDeviceAuthorization(
            verification_uri="https://microsoft.com/devicelogin",
            user_code="ABCD-EFGH",
            expires_at="2026-08-01T00:00:00Z",
        ))
        service.disconnect = mock.AsyncMock()
        service.status_snapshot.return_value = MicrosoftTodoAuthStatus(
            configured=True, state="disconnected"
        )
        set_microsoft_auth_service(service)

        started = await start_microsoft_todo_authorization()
        disconnected = await disconnect_microsoft_todo()

        self.assertEqual(started.user_code, "ABCD-EFGH")
        self.assertEqual(disconnected.state, "disconnected")
        self.assertIs(get_microsoft_auth_service(), service)

    async def test_start_masks_raw_exception(self) -> None:
        service = mock.Mock()
        service.begin_device_authorization = mock.AsyncMock(
            side_effect=RuntimeError("access_token=secret")
        )
        set_microsoft_auth_service(service)
        with self.assertRaises(Exception) as raised:
            await start_microsoft_todo_authorization()
        self.assertNotIn("secret", str(raised.exception))


class MicrosoftTodoCapabilityTests(unittest.TestCase):
    def test_capabilities_are_read_only_and_not_server_exported(self) -> None:
        for name in ("list_microsoft_todo_lists", "list_microsoft_todo_tasks"):
            descriptor = get_capability_descriptor(name)
            self.assertIsNotNone(descriptor)
            self.assertEqual(descriptor.risk, "read")
            self.assertTrue(descriptor.expose_to_agent)
            self.assertFalse(descriptor.expose_to_mcp_server)

    def test_tools_delegate_with_clamped_reads(self) -> None:
        client = mock.Mock()
        client.list_task_lists.return_value = TodoTaskListsResult(lists=())
        client.list_tasks.return_value = TodoTasksResult(list_id="list-1", include_completed=False, tasks=())
        with mock.patch(
            "clients.microsoft_todo_client.get_microsoft_todo_client",
            return_value=client,
        ):
            self.assertEqual(list_microsoft_todo_lists()["list_count"], 0)
            list_microsoft_todo_tasks("list-1", max_results=999)
        client.list_tasks.assert_called_once_with(
            "list-1", include_completed=False, max_results=50
        )

    def test_authentication_error_is_normalized(self) -> None:
        client = mock.Mock()
        client.list_task_lists.side_effect = MicrosoftTodoAuthenticationRequiredError(
            "Connect Microsoft To Do in Settings."
        )
        with mock.patch(
            "clients.microsoft_todo_client.get_microsoft_todo_client",
            return_value=client,
        ), self.assertRaises(CapabilityError) as raised:
            list_microsoft_todo_lists()
        self.assertEqual(raised.exception.category, CapabilityErrorCategory.AUTHENTICATION)

    def test_todo_catalog_is_unavailable_without_configuration(self) -> None:
        with mock.patch.dict(os.environ, {"MICROSOFT_TODO_CLIENT_ID": ""}):
            tool = next(
                item
                for item in build_tool_catalog("panthera").tools
                if item.name == "list_microsoft_todo_lists"
            )
        self.assertFalse(tool.available)
        self.assertEqual(tool.unavailable_reason, "Microsoft To Do is not configured.")
