"""Regression coverage for lifecycle-owned synchronous connector sessions."""

from __future__ import annotations

import asyncio
import threading
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from clients import market_client, sports_client, weather_client
from clients.http_sessions import (
    ConnectorHttpSessions,
    get_connector_http_session,
    reset_connector_http_sessions_for_tests,
    set_connector_http_sessions,
)
from core.runtime_paths import RuntimePaths


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, response: _Response | list[_Response]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.close_calls = 0

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, kwargs))
        if isinstance(self.response, list):
            return self.response.pop(0)
        return self.response

    def close(self) -> None:
        self.close_calls += 1


class ConnectorHttpSessionsTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_connector_http_sessions_for_tests()

    def test_creates_one_session_per_provider_and_closes_each_once(self) -> None:
        sessions: list[_Session] = []

        def factory() -> _Session:
            session = _Session(_Response({}))
            sessions.append(session)
            return session

        registry = ConnectorHttpSessions(session_factory=factory)
        self.assertEqual(len(sessions), 3)
        self.assertIsNot(registry.for_connector("market"), registry.for_connector("weather"))

        registry.close()
        registry.close()

        self.assertEqual([session.close_calls for session in sessions], [1, 1, 1])

    def test_installed_registry_is_available_and_can_be_cleared(self) -> None:
        registry = ConnectorHttpSessions(
            session_factory=lambda: _Session(_Response({}))
        )
        set_connector_http_sessions(registry)

        self.assertIsNotNone(get_connector_http_session("market"))

        reset_connector_http_sessions_for_tests()
        self.assertIsNone(get_connector_http_session("market"))
        registry.close()

    def test_market_uses_installed_session_and_falls_back_without_one(self) -> None:
        response = _Response({"Time Series (Daily)": {}})
        session = _Session(response)
        with mock.patch.object(
            market_client, "get_connector_http_session", return_value=session
        ), mock.patch.object(market_client.requests, "get") as top_level_get:
            market_client._alpha_vantage_get({"symbol": "SPY"})

        self.assertEqual(len(session.calls), 1)
        top_level_get.assert_not_called()

        with mock.patch.object(
            market_client, "get_connector_http_session", return_value=None
        ), mock.patch.object(
            market_client.requests, "get", return_value=response
        ) as top_level_get:
            market_client._alpha_vantage_get({"symbol": "SPY"})
        top_level_get.assert_called_once()

    def test_weather_and_sports_use_installed_sessions(self) -> None:
        weather_session = _Session(
            [
                _Response({"results": [{"latitude": 42.36, "longitude": -71.06}]}),
                _Response({"current": {"temperature_2m": 70, "weather_code": 0}}),
            ]
        )
        with mock.patch.dict(
            "os.environ",
            {"TARGET_LOCATION": "Boston"},
            clear=False,
        ), mock.patch.object(
            weather_client, "get_connector_http_session", return_value=weather_session
        ):
            result = weather_client.collect_weather()
        self.assertEqual(result.status, "healthy")
        self.assertEqual(len(weather_session.calls), 2)

        fallback_responses = [
            _Response({"results": [{"latitude": 42.36, "longitude": -71.06}]}),
            _Response({"current": {"temperature_2m": 70, "weather_code": 0}}),
        ]
        with mock.patch.dict(
            "os.environ",
            {"TARGET_LOCATION": "Boston"},
            clear=False,
        ), mock.patch.object(
            weather_client, "get_connector_http_session", return_value=None
        ), mock.patch.object(
            weather_client.requests, "get", side_effect=fallback_responses
        ) as weather_get:
            weather_client.collect_weather()
        self.assertEqual(weather_get.call_count, 2)

        sports_session = _Session(
            _Response(
                {
                    "MRData": {
                        "RaceTable": {
                            "season": "2026",
                            "Races": [],
                        }
                    }
                }
            )
        )
        with mock.patch.object(
            sports_client, "get_connector_http_session", return_value=sports_session
        ):
            sports_client.fetch_f1_season_calendar()
        self.assertEqual(len(sports_session.calls), 1)

        with mock.patch.object(
            sports_client, "get_connector_http_session", return_value=None
        ), mock.patch.object(
            sports_client.requests, "get", return_value=sports_session.response
        ) as sports_get:
            sports_client.fetch_f1_season_calendar()
        sports_get.assert_called_once()


class AppHttpSessionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        from core import database

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        runtime_paths = mock.patch(
            "core.runtime_paths.get_runtime_paths",
            return_value=RuntimePaths(resource_root=root, data_root=root),
        )
        runtime_paths.start()
        self.addCleanup(runtime_paths.stop)
        self._reset_host_context()
        db_override = mock.patch(
            "core.api.app.database.DB_NAME",
            str(Path(self.temp_dir.name) / "http-lifecycle.db"),
        )
        db_override.start()
        self.addCleanup(db_override.stop)
        database.initialize_db()

        # These tests cover resource ownership; persistence compatibility has
        # production lifecycle coverage in test_persistence_lifecycle.py.
        validator = mock.patch("core.api.app._validate_persistence_before_startup")
        validator.start()
        self.addCleanup(validator.stop)

    def _reset_host_context(self) -> None:
        from core.api.app import app

        context = getattr(app.state, "host_context", None)
        if context is not None and context.profile_lock.acquired:
            context.release()
        app.state.host_context = None
        app.state.lifecycle_entered = False
        app.state.lifecycle_established = False
        app.state.lifecycle_cleanup_complete = False
        app.state.http_shutdown_timed_out = False

    def tearDown(self) -> None:
        # Failed-drain coverage intentionally retains the lease until this
        # isolated fixture is discarded.
        self._reset_host_context()

    def _assert_lifespan_preserves_dependencies_on_drain_failure(
        self,
        *,
        coordinator: mock.Mock,
        expected_error: str,
        task_drain: mock.AsyncMock | None = None,
        speech_service: mock.Mock | None = None,
        http_timeout: bool = False,
    ) -> None:
        from core.api.app import app
        from core.mcp.models import McpRuntimeConfig

        conversation_store = mock.Mock()
        run_store = mock.Mock()
        briefing_session_store = mock.Mock()
        retrieval_store = mock.Mock()
        knowledge_store = mock.Mock()
        activity_store = mock.Mock()
        speech_service = speech_service or mock.Mock()
        registry = mock.Mock()
        tracing = mock.Mock()
        manager = mock.Mock()
        manager.start = mock.AsyncMock()
        manager.shutdown = mock.AsyncMock()
        speech_service.close.return_value = True
        demo_db = mock.Mock()

        with ExitStack() as stack:
            stack.enter_context(mock.patch("core.api.app.DEMO_MODE", True))
            stack.enter_context(mock.patch("core.api.app.sqlite3.connect", return_value=demo_db))
            stack.enter_context(mock.patch("core.api.app.configure_logging"))
            stack.enter_context(
                mock.patch("core.api.app.get_tracing_service", return_value=tracing)
            )
            stack.enter_context(mock.patch("core.api.app.database.initialize_db"))
            stack.enter_context(
                mock.patch("core.api.app.ConversationStore", return_value=conversation_store)
            )
            stack.enter_context(
                mock.patch("core.api.app.ConversationService", return_value=mock.Mock())
            )
            stack.enter_context(mock.patch("core.api.app.RunStore", return_value=run_store))
            stack.enter_context(mock.patch("core.api.app.RunService", return_value=mock.Mock()))
            stack.enter_context(
                mock.patch(
                    "core.api.app.BriefingSessionStore",
                    return_value=briefing_session_store,
                )
            )
            stack.enter_context(
                mock.patch(
                    "core.api.app.BriefingSpeechService",
                    return_value=speech_service,
                )
            )
            stack.enter_context(
                mock.patch("core.api.app.CortexRunCoordinator", return_value=coordinator)
            )
            stack.enter_context(
                mock.patch("core.api.app.RetrievalStore", return_value=retrieval_store)
            )
            stack.enter_context(
                mock.patch("core.api.app.RetrievalService", return_value=mock.Mock())
            )
            stack.enter_context(
                mock.patch("core.api.app.KnowledgeStore", return_value=knowledge_store)
            )
            stack.enter_context(
                mock.patch("core.api.app.KnowledgeService", return_value=mock.Mock())
            )
            stack.enter_context(mock.patch("core.api.app.ActivityStore", return_value=activity_store))
            stack.enter_context(mock.patch("core.api.app.ActivityService", return_value=mock.Mock()))
            stack.enter_context(mock.patch("core.api.app.get_settings_store"))
            stack.enter_context(mock.patch("core.api.app.speaker.initialize"))
            speaker_shutdown = stack.enter_context(
                mock.patch("core.api.app.speaker.shutdown")
            )
            stack.enter_context(
                mock.patch("core.api.app.get_llama_cpp_server_supervisor", return_value=mock.Mock())
            )
            stack.enter_context(mock.patch("core.api.app.any_local_runtime_enabled", return_value=False))
            stack.enter_context(
                mock.patch(
                    "core.api.app.load_mcp_config",
                    return_value=McpRuntimeConfig(enabled=False, servers={}),
                )
            )
            stack.enter_context(mock.patch("core.api.app.MCPClientManager", return_value=manager))
            stack.enter_context(
                mock.patch("core.api.app.ConnectorHttpSessions", return_value=registry)
            )
            if task_drain is not None:
                stack.enter_context(
                    mock.patch("core.api.app._drain_application_tasks", task_drain)
                )
            for setter in (
                "set_action_service",
                "set_activity_service",
                "set_briefing_session_queries",
                "set_connector_http_sessions",
                "set_conversation_service",
                "set_knowledge_service",
                "set_mcp_manager",
                "set_reminder_service",
                "set_retrieval_service",
                "set_run_coordinator",
                "set_run_service",
            ):
                stack.enter_context(mock.patch(f"core.api.app.{setter}"))
            with self.assertRaisesRegex(RuntimeError, expected_error):
                with TestClient(app):
                    if http_timeout:
                        # Uvicorn sets this marker when its HTTP grace expires;
                        # canceled ASGI tasks may already have disappeared.
                        app.state.http_shutdown_timed_out = True

        conversation_store.close.assert_not_called()
        run_store.close.assert_not_called()
        briefing_session_store.close.assert_not_called()
        if http_timeout:
            speech_service.close.assert_called_once()
            speaker_shutdown.assert_not_called()
        else:
            speech_service.close.assert_not_called()
        retrieval_store.close.assert_not_called()
        knowledge_store.close.assert_not_called()
        activity_store.close.assert_not_called()
        registry.close.assert_not_called()
        manager.shutdown.assert_not_awaited()
        tracing.shutdown.assert_not_called()

    def test_lifespan_keeps_dependencies_open_when_startup_task_drain_times_out(self) -> None:
        coordinator = mock.Mock()
        coordinator.close.return_value = True
        task_drain = mock.AsyncMock(return_value=False)

        self._assert_lifespan_preserves_dependencies_on_drain_failure(
            coordinator=coordinator,
            expected_error="Application task shutdown drain timed out",
            task_drain=task_drain,
        )

        task_drain.assert_awaited_once()
        drained_tasks = task_drain.await_args.args[0]
        self.assertEqual(len(drained_tasks), 2)
        self.assertIn("activity-report-folder-poller", {task.get_name() for task in drained_tasks})
        self.assertIn("optional-resource-idle-maintenance", {task.get_name() for task in drained_tasks})

    def test_http_grace_timeout_preserves_dependencies_after_request_task_cancellation(self) -> None:
        call_order: list[str] = []
        coordinator = mock.Mock()

        def drain_runs(**_kwargs) -> bool:
            call_order.append("runs")
            return True

        coordinator.close.side_effect = drain_runs
        speech_service = mock.Mock()
        speech_service.close.return_value = True
        speech_service.request_shutdown.side_effect = lambda: call_order.append(
            "speech_cancel"
        )

        async def drain_application_tasks(*_args, **_kwargs) -> bool:
            call_order.append("application_tasks")
            return True

        task_drain = mock.AsyncMock(side_effect=drain_application_tasks)
        self._assert_lifespan_preserves_dependencies_on_drain_failure(
            coordinator=coordinator,
            expected_error="HTTP request shutdown drain timed out",
            http_timeout=True,
            task_drain=task_drain,
            speech_service=speech_service,
        )
        coordinator.close.assert_called_once()
        task_drain.assert_awaited_once()
        speech_service.request_shutdown.assert_called_once()
        speech_service.close.assert_called_once()
        self.assertEqual(
            call_order,
            ["speech_cancel", "runs", "application_tasks"],
        )

    def test_request_tracker_keeps_a_blocked_handler_active_until_it_finishes(self) -> None:
        from core.api.app import _HttpRequestTracker, _HttpRequestTrackingMiddleware

        tracker = _HttpRequestTracker()
        entered = threading.Event()
        release = threading.Event()

        async def blocked_app(_scope, _receive, _send) -> None:
            entered.set()
            await asyncio.to_thread(release.wait)

        middleware = _HttpRequestTrackingMiddleware(blocked_app, tracker)
        failures: list[BaseException] = []

        def invoke() -> None:
            try:
                asyncio.run(middleware({"type": "http"}, None, None))
            except BaseException as exc:
                failures.append(exc)

        request = threading.Thread(target=invoke, daemon=True)
        request.start()
        self.assertTrue(entered.wait(2))
        self.assertEqual(tracker.active, 1)
        release.set()
        request.join(2)
        self.assertFalse(request.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(tracker.active, 0)

    def test_lifespan_keeps_dependencies_open_when_run_drain_errors(self) -> None:
        call_order: list[str] = []

        def fail_run_drain(*_args, **_kwargs):
            call_order.append("run_drain")
            raise RuntimeError("drain failed")

        speech_service = mock.Mock()
        speech_service.request_shutdown.side_effect = lambda: call_order.append(
            "speech_cancel"
        )
        coordinator = mock.Mock()
        coordinator.close.side_effect = fail_run_drain
        self._assert_lifespan_preserves_dependencies_on_drain_failure(
            coordinator=coordinator,
            expected_error="Cortex run shutdown drain failed",
            speech_service=speech_service,
        )

        coordinator.close.assert_called_once()
        self.assertEqual(call_order, ["speech_cancel", "run_drain"])
        speech_service.request_shutdown.assert_called_once()

    def test_lifespan_registers_action_handlers_before_recovery_and_publication(self) -> None:
        from core.api.app import app
        from core.mcp.models import McpRuntimeConfig

        auth = mock.Mock()
        auth.initialize = mock.AsyncMock()
        auth.shutdown = mock.AsyncMock()
        todo_client = mock.Mock()
        manager = mock.Mock()
        manager.start = mock.AsyncMock()
        manager.shutdown = mock.AsyncMock()
        action_service = mock.Mock()
        activity_store = mock.Mock()

        with mock.patch("core.api.app.DEMO_MODE", False), mock.patch(
            "core.api.app.MicrosoftTodoAuthenticationService", return_value=auth
        ), mock.patch("core.api.app.MicrosoftTodoClient", return_value=todo_client), mock.patch(
            "core.api.app.ActionService", return_value=action_service
        ), mock.patch("core.api.app.set_action_service") as set_action_service, mock.patch(
            "core.api.app.get_llama_cpp_server_supervisor", return_value=mock.Mock()
        ), mock.patch("core.api.app.any_local_runtime_enabled", return_value=False), mock.patch(
            "core.api.app.load_mcp_config", return_value=McpRuntimeConfig(enabled=False, servers={})
        ), mock.patch("core.api.app.MCPClientManager", return_value=manager), mock.patch(
            "core.api.app.ConnectorHttpSessions", return_value=mock.Mock()
        ), mock.patch("core.api.app.ReminderService"
        ), mock.patch("core.api.app.configure_logging"), mock.patch(
            "core.api.app.database.initialize_db"
        ), mock.patch("core.api.app.get_settings_store"), mock.patch("core.api.app.speaker.initialize"), mock.patch(
            "core.api.app.ActivityStore", return_value=activity_store
        ), mock.patch("core.api.app.ActivityService"), mock.patch("core.api.app.set_activity_service"):
            with TestClient(app):
                pass

        self.assertEqual(
            [call.args[0] for call in action_service.register_handler.call_args_list],
            [
                "remember_personal_context",
                "reconcile_personal_context",
                "create_microsoft_todo_task",
                "update_microsoft_todo_task",
                "complete_microsoft_todo_task",
                "reopen_microsoft_todo_task",
                "delete_microsoft_todo_task",
            ],
        )
        self.assertEqual(
            action_service.mock_calls[:8],
            [
                mock.call.register_handler(
                    name, executor=mock.ANY, verifier=mock.ANY
                )
                for name in (
                    "remember_personal_context",
                    "reconcile_personal_context",
                    "create_microsoft_todo_task",
                    "update_microsoft_todo_task",
                    "complete_microsoft_todo_task",
                    "reopen_microsoft_todo_task",
                    "delete_microsoft_todo_task",
                )
            ]
            + [mock.call.recover_interrupted()],
        )
        self.assertEqual(
            set_action_service.call_args_list,
            [mock.call(action_service), mock.call(None)],
        )

    def test_lifespan_does_not_construct_or_publish_actions_in_demo_mode(self) -> None:
        from core.api.app import app
        from core.mcp.models import McpRuntimeConfig

        auth = mock.Mock()
        auth.initialize = mock.AsyncMock()
        auth.shutdown = mock.AsyncMock()
        todo_client = mock.Mock()
        manager = mock.Mock()
        manager.start = mock.AsyncMock()
        manager.shutdown = mock.AsyncMock()
        activity_store = mock.Mock()

        with mock.patch("core.api.app.DEMO_MODE", True), mock.patch(
            "core.api.app.MicrosoftTodoAuthenticationService", return_value=auth
        ), mock.patch("core.api.app.MicrosoftTodoClient", return_value=todo_client), mock.patch(
            "core.api.app.ActionService", side_effect=AssertionError("action ledger accessed")
        ), mock.patch("core.api.app.set_action_service") as set_action_service, mock.patch(
            "core.api.app.get_llama_cpp_server_supervisor", return_value=mock.Mock()
        ), mock.patch("core.api.app.any_local_runtime_enabled", return_value=False), mock.patch(
            "core.api.app.load_mcp_config", return_value=McpRuntimeConfig(enabled=False, servers={})
        ), mock.patch("core.api.app.MCPClientManager", return_value=manager), mock.patch(
            "core.api.app.ConnectorHttpSessions", return_value=mock.Mock()
        ), mock.patch("core.api.app.ReminderService", side_effect=AssertionError("reminder service accessed")
        ), mock.patch("core.api.app.configure_logging"), mock.patch(
            "core.api.app.database.initialize_db"
        ), mock.patch("core.api.app.get_settings_store"), mock.patch("core.api.app.speaker.initialize"), mock.patch(
            "core.api.app.ActivityStore", return_value=activity_store
        ), mock.patch("core.api.app.ActivityService"), mock.patch("core.api.app.set_activity_service"):
            with TestClient(app):
                pass

        self.assertEqual(set_action_service.call_args_list, [mock.call(None)])

    def test_lifespan_creates_installs_closes_and_clears_registry(self) -> None:
        from core.api.app import app
        from core.mcp.models import McpRuntimeConfig

        registry = mock.Mock()
        supervisor = mock.Mock()
        auth = mock.Mock()
        auth.initialize = mock.AsyncMock()
        auth.shutdown = mock.AsyncMock()
        todo_client = mock.Mock()
        manager = mock.Mock()
        manager.start = mock.AsyncMock()
        manager.shutdown = mock.AsyncMock()

        with mock.patch("core.api.app.ConnectorHttpSessions", return_value=registry) as factory, mock.patch(
            "core.api.app.set_connector_http_sessions"
        ) as set_sessions, mock.patch(
            "core.api.app.MicrosoftTodoAuthenticationService", return_value=auth
        ), mock.patch(
            "core.api.app.MicrosoftTodoClient", return_value=todo_client
        ), mock.patch(
            "core.api.app.get_llama_cpp_server_supervisor", return_value=supervisor
        ), mock.patch(
            "core.api.app.any_local_runtime_enabled", return_value=False
        ), mock.patch(
            "core.api.app.load_mcp_config",
            return_value=McpRuntimeConfig(enabled=False, servers={}),
        ), mock.patch(
            "core.api.app.MCPClientManager", return_value=manager
        ), mock.patch("core.api.app.ReminderService"
        ), mock.patch("core.api.app.configure_logging"), mock.patch(
            "core.api.app.database.initialize_db"
        ), mock.patch(
            "core.api.app.get_settings_store"
        ), mock.patch("core.api.app.ActivityStore"), mock.patch("core.api.app.ActivityService"), mock.patch(
            "core.api.app.set_activity_service"
        ):
            with TestClient(app):
                factory.assert_called_once_with()
                set_sessions.assert_called_once_with(registry)
                auth.initialize.assert_awaited_once_with()

        registry.close.assert_called_once_with()
        self.assertEqual(
            set_sessions.call_args_list,
            [mock.call(registry), mock.call(None)],
        )
        supervisor.ensure_ready.assert_not_called()

    def test_lifespan_closes_sessions_when_mcp_shutdown_fails(self) -> None:
        from core.api.app import app
        from core.mcp.models import McpRuntimeConfig

        registry = mock.Mock()
        supervisor = mock.Mock()
        auth = mock.Mock()
        auth.initialize = mock.AsyncMock()
        auth.shutdown = mock.AsyncMock()
        todo_client = mock.Mock()
        manager = mock.Mock()
        manager.start = mock.AsyncMock()
        manager.shutdown = mock.AsyncMock(side_effect=RuntimeError("shutdown failed"))

        with mock.patch("core.api.app.ConnectorHttpSessions", return_value=registry), mock.patch(
            "core.api.app.set_connector_http_sessions"
        ) as set_sessions, mock.patch(
            "core.api.app.MicrosoftTodoAuthenticationService", return_value=auth
        ), mock.patch(
            "core.api.app.MicrosoftTodoClient", return_value=todo_client
        ), mock.patch(
            "core.api.app.get_llama_cpp_server_supervisor", return_value=supervisor
        ), mock.patch(
            "core.api.app.any_local_runtime_enabled", return_value=False
        ), mock.patch(
            "core.api.app.load_mcp_config",
            return_value=McpRuntimeConfig(enabled=False, servers={}),
        ), mock.patch(
            "core.api.app.MCPClientManager", return_value=manager
        ), mock.patch("core.api.app.ReminderService"
        ), mock.patch("core.api.app.configure_logging"), mock.patch(
            "core.api.app.database.initialize_db"
        ), mock.patch(
            "core.api.app.get_settings_store"
        ), mock.patch("core.api.app.ActivityStore"), mock.patch("core.api.app.ActivityService"), mock.patch(
            "core.api.app.set_activity_service"
        ):
            with self.assertRaises(RuntimeError):
                with TestClient(app):
                    pass

        registry.close.assert_called_once_with()
        self.assertEqual(set_sessions.call_args_list[-1], mock.call(None))

    def test_partial_lifespan_startup_closes_acquired_run_resources(self) -> None:
        from core.api.app import app
        from core.mcp.models import McpRuntimeConfig

        manager = mock.Mock()
        manager.start = mock.AsyncMock(side_effect=RuntimeError("MCP startup failed"))
        manager.shutdown = mock.AsyncMock()
        coordinator = mock.Mock()
        coordinator.close.return_value = True
        conversation_store = mock.Mock()
        run_store = mock.Mock()
        retrieval_store = mock.Mock()
        retrieval_service = mock.Mock()
        call_order: list[str] = []
        retrieval_service.close.side_effect = lambda **_kwargs: (
            call_order.append("retrieval_close") or True
        )
        conversation_store.close.side_effect = lambda: call_order.append("conversation_store_close")
        knowledge_store = mock.Mock()
        activity_store = mock.Mock()
        tracing = mock.Mock()
        supervisor = mock.Mock()

        with ExitStack() as stack:
            stack.enter_context(mock.patch("core.api.app.DEMO_MODE", True))
            stack.enter_context(mock.patch("core.api.app.configure_logging"))
            stack.enter_context(
                mock.patch("core.api.app.get_tracing_service", return_value=tracing)
            )
            stack.enter_context(mock.patch("core.api.app.database.initialize_db"))
            stack.enter_context(
                mock.patch("core.api.app.ConversationStore", return_value=conversation_store)
            )
            stack.enter_context(
                mock.patch("core.api.app.ConversationService", return_value=mock.Mock())
            )
            stack.enter_context(mock.patch("core.api.app.RunStore", return_value=run_store))
            stack.enter_context(mock.patch("core.api.app.RunService", return_value=mock.Mock()))
            stack.enter_context(
                mock.patch("core.api.app.CortexRunCoordinator", return_value=coordinator)
            )
            stack.enter_context(
                mock.patch("core.api.app.RetrievalStore", return_value=retrieval_store)
            )
            stack.enter_context(
                mock.patch("core.api.app.RetrievalService", return_value=retrieval_service)
            )
            stack.enter_context(
                mock.patch("core.api.app.KnowledgeStore", return_value=knowledge_store)
            )
            stack.enter_context(
                mock.patch("core.api.app.KnowledgeService", return_value=mock.Mock())
            )
            stack.enter_context(mock.patch("core.api.app.ActivityStore", return_value=activity_store))
            stack.enter_context(mock.patch("core.api.app.ActivityService", return_value=mock.Mock()))
            stack.enter_context(mock.patch("core.api.app.set_activity_service"))
            stack.enter_context(mock.patch("core.api.app.get_settings_store"))
            stack.enter_context(mock.patch("core.api.app.speaker.initialize"))
            stack.enter_context(
                mock.patch(
                    "core.api.app.speaker.shutdown",
                    side_effect=lambda: call_order.append("speaker_shutdown"),
                )
            )
            stack.enter_context(
                mock.patch(
                    "core.api.app.speaker.close_kokoro",
                    side_effect=lambda _timeout: call_order.append("kokoro_close") or True,
                )
            )
            stack.enter_context(
                mock.patch("core.api.app.get_llama_cpp_server_supervisor", return_value=supervisor)
            )
            stack.enter_context(mock.patch("core.api.app.any_local_runtime_enabled", return_value=False))
            stack.enter_context(
                mock.patch(
                    "core.api.app.load_mcp_config",
                    return_value=McpRuntimeConfig(enabled=False, servers={}),
                )
            )
            stack.enter_context(mock.patch("core.api.app.MCPClientManager", return_value=manager))
            with self.assertRaisesRegex(RuntimeError, "MCP startup failed"):
                with TestClient(app):
                    pass

        coordinator.close.assert_called_once_with(timeout_seconds=mock.ANY)
        manager.shutdown.assert_awaited_once_with()
        conversation_store.close.assert_called_once_with()
        run_store.close.assert_called_once_with()
        retrieval_store.close.assert_called_once_with()
        knowledge_store.close.assert_called_once_with()
        activity_store.close.assert_called_once_with()
        tracing.shutdown.assert_called_once_with()
        retrieval_service.close.assert_called_once_with(timeout_seconds=mock.ANY)
        self.assertLess(call_order.index("retrieval_close"), call_order.index("kokoro_close"))
        self.assertLess(call_order.index("kokoro_close"), call_order.index("speaker_shutdown"))
        self.assertLess(call_order.index("speaker_shutdown"), call_order.index("conversation_store_close"))


class ApplicationTaskDrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_an_overdue_startup_task_without_cancelling_it(self) -> None:
        from core.api.app import _drain_application_tasks

        release = asyncio.Event()
        task = asyncio.create_task(release.wait(), name="retrieval-warmup")
        try:
            self.assertFalse(
                await _drain_application_tasks([task], timeout_seconds=0)
            )
            self.assertFalse(task.done())
        finally:
            release.set()
            await task


class OptionalResourceIdleMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_sweep_runs_after_idle_interval_and_offloads_both_releases(self) -> None:
        from core.api.app import (
            OPTIONAL_RESOURCE_IDLE_SWEEP_SECONDS,
            _run_optional_resource_idle_maintenance,
        )

        stop_event = asyncio.Event()
        retrieval = mock.Mock()
        release_threads: list[int] = []
        loop_thread = threading.get_ident()

        def release_retrieval() -> bool:
            release_threads.append(threading.get_ident())
            return True

        def release_speaker() -> bool:
            release_threads.append(threading.get_ident())
            return True

        retrieval.release_if_idle.side_effect = release_retrieval
        wait_calls = 0

        async def advance_fake_clock(awaitable, *, timeout: float) -> bool:
            nonlocal wait_calls
            wait_calls += 1
            self.assertEqual(timeout, OPTIONAL_RESOURCE_IDLE_SWEEP_SECONDS)
            awaitable.close()
            if wait_calls == 1:
                raise asyncio.TimeoutError
            stop_event.set()
            return True

        task = asyncio.create_task(
            _run_optional_resource_idle_maintenance(retrieval, stop_event)
        )
        try:
            with mock.patch("core.api.app.asyncio.wait_for", side_effect=advance_fake_clock), mock.patch(
                "core.api.app.speaker.release_kokoro_if_idle", side_effect=release_speaker
            ):
                await task
        finally:
            if not task.done():
                stop_event.set()
                await task

        self.assertEqual(wait_calls, 2)
        retrieval.release_if_idle.assert_called_once_with()
        self.assertEqual(len(release_threads), 2)
        self.assertTrue(all(thread_id != loop_thread for thread_id in release_threads))


if __name__ == "__main__":
    unittest.main()
