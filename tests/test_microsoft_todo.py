"""Read-only Microsoft To Do foundation regression coverage."""

from __future__ import annotations

import asyncio
import os
import threading
import unittest
from pathlib import Path
from unittest import mock

from clients.microsoft_auth import (
    MICROSOFT_TODO_SCOPES,
    MicrosoftTodoAuthenticationRequiredError,
    MicrosoftTodoAuthenticationService,
    MicrosoftTodoNotConfiguredError,
    get_microsoft_auth_service,
    set_microsoft_auth_service,
)
from clients.microsoft_todo_client import (
    MicrosoftTodoClient,
    MicrosoftTodoInvalidInputError,
    MicrosoftTodoUpstreamError,
)
from core.agent.capabilities import (
    CapabilityError,
    CapabilityErrorCategory,
    get_capability_descriptor,
)
from core.agent.local_commands import list_local_command_statuses
from core.agent.tools import list_microsoft_todo_lists, list_microsoft_todo_tasks
from core.api.routers.microsoft_todo import (
    disconnect_microsoft_todo,
    microsoft_todo_status,
    start_microsoft_todo_authorization,
)


class _Auth:
    def acquire_access_token(self) -> str:
        return "test-token"

    def status_snapshot(self):
        return {"configured": True, "state": "connected", "permission": "Tasks.Read"}


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
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


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

        self.assertEqual(lists["lists"][0]["display_name"], "Tasks")
        self.assertEqual(tasks["task_count"], 1)
        self.assertEqual(tasks["tasks"][0]["title"], "Ship release")
        self.assertEqual(tasks["tasks"][0]["due"]["time_zone"], "Eastern Standard Time")
        self.assertTrue(all(call[0].startswith("https://graph.microsoft.com/v1.0/") for call in session.calls))
        self.assertTrue(all(call[1]["headers"]["Authorization"] == "Bearer test-token" for call in session.calls))

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

    def test_client_has_no_write_operations(self) -> None:
        public = {name for name in dir(MicrosoftTodoClient) if not name.startswith("_")}
        self.assertEqual(public, {"get_status", "list_task_lists", "list_tasks"})


class MicrosoftTodoAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    def test_missing_client_id_does_not_initialize_cache(self) -> None:
        with mock.patch.dict(os.environ, {"MICROSOFT_TODO_CLIENT_ID": ""}), mock.patch(
            "clients.microsoft_auth.build_encrypted_persistence"
        ) as persistence:
            service = MicrosoftTodoAuthenticationService(client_id="")
        self.assertEqual(service.status_snapshot()["state"], "not-configured")
        persistence.assert_not_called()
        with self.assertRaises(MicrosoftTodoNotConfiguredError):
            service.acquire_access_token()

    def test_cache_path_inside_repository_fails_closed(self) -> None:
        repository_cache = Path(__file__).resolve().parent.parent / "token.bin"
        with mock.patch("clients.microsoft_auth.build_encrypted_persistence") as persistence:
            service = MicrosoftTodoAuthenticationService(
                client_id="client", cache_path=repository_cache
            )
        self.assertEqual(service.status_snapshot()["state"], "degraded")
        persistence.assert_not_called()

    def test_scope_is_exactly_tasks_read(self) -> None:
        self.assertEqual(MICROSOFT_TODO_SCOPES, ("Tasks.Read",))

    async def test_device_flow_returns_only_public_fields(self) -> None:
        service = MicrosoftTodoAuthenticationService.__new__(MicrosoftTodoAuthenticationService)
        service.client_id = "client"
        service.tenant_id = "common"
        service.cache_path = mock.Mock()
        service._lock = threading.RLock()
        service._authorization_lock = asyncio.Lock()
        service._flow = None
        service._poll_task = None
        service._state = "disconnected"
        service._cache = None
        app = mock.Mock()
        app.initiate_device_flow.return_value = {
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_in": 900,
            "secret": "must-not-leak",
        }
        app.acquire_token_by_device_flow.return_value = {"access_token": "token"}
        service._application = app

        result = await service.begin_device_authorization()
        await asyncio.sleep(0)
        await service.shutdown()

        self.assertEqual(set(result), {"state", "verification_uri", "user_code", "expires_at"})
        self.assertNotIn("secret", result)
        app.initiate_device_flow.assert_called_once_with(scopes=["Tasks.Read"])

    async def test_concurrent_starts_share_one_device_flow(self) -> None:
        service = MicrosoftTodoAuthenticationService.__new__(MicrosoftTodoAuthenticationService)
        service.client_id = "client"
        service.tenant_id = "common"
        service.cache_path = mock.Mock()
        service._lock = threading.RLock()
        service._authorization_lock = asyncio.Lock()
        service._flow = None
        service._poll_task = None
        service._state = "disconnected"
        service._cache = None
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
        service._application = app

        first, second = await asyncio.gather(
            service.begin_device_authorization(),
            service.begin_device_authorization(),
        )
        release_poll.set()
        await service.shutdown()

        self.assertEqual(first["user_code"], second["user_code"])
        app.initiate_device_flow.assert_called_once_with(scopes=["Tasks.Read"])


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
        service.begin_device_authorization = mock.AsyncMock(return_value={
            "state": "authorizing",
            "verification_uri": "https://microsoft.com/devicelogin",
            "user_code": "ABCD-EFGH",
            "expires_at": "2026-08-01T00:00:00Z",
        })
        service.disconnect = mock.AsyncMock()
        service.status_snapshot.return_value = {
            "configured": True,
            "state": "disconnected",
            "permission": "Tasks.Read",
        }
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
            self.assertTrue(descriptor.expose_to_assistant)
            self.assertFalse(descriptor.expose_to_mcp_server)

    def test_tools_delegate_with_clamped_reads(self) -> None:
        client = mock.Mock()
        client.list_task_lists.return_value = {"list_count": 0, "lists": []}
        client.list_tasks.return_value = {"task_count": 0, "tasks": []}
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

    def test_todo_scope_is_unavailable_without_configuration(self) -> None:
        with mock.patch.dict(os.environ, {"MICROSOFT_TODO_CLIENT_ID": ""}):
            status = next(
                item for item in list_local_command_statuses() if item.key == "todo"
            )
        self.assertFalse(status.available)
        self.assertEqual(status.unavailable_reason, "Microsoft To Do is not configured.")
