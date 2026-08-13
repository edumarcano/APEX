"""Regression coverage for lifecycle-owned synchronous connector sessions."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi.testclient import TestClient

from clients import market_client, news_client, sports_client, weather_client
from clients.http_sessions import (
    ConnectorHttpSessions,
    get_connector_http_session,
    reset_connector_http_sessions_for_tests,
    set_connector_http_sessions,
)


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
        self.assertEqual(len(sessions), 4)
        self.assertIsNot(registry.for_connector("market"), registry.for_connector("weather"))

        registry.close()
        registry.close()

        self.assertEqual([session.close_calls for session in sessions], [1, 1, 1, 1])

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

    def test_weather_news_and_sports_use_installed_sessions(self) -> None:
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

        news_session = _Session(_Response({"articles": []}))
        with mock.patch.object(news_client, "api_key", "news-key"), mock.patch.object(
            news_client, "get_connector_http_session", return_value=news_session
        ), mock.patch.object(news_client.time, "sleep"):
            result = news_client.collect_news()
        self.assertEqual(result.status, "healthy")
        self.assertEqual(len(news_session.calls), 2)

        with mock.patch.object(news_client, "api_key", "news-key"), mock.patch.object(
            news_client, "get_connector_http_session", return_value=None
        ), mock.patch.object(
            news_client.requests, "get", return_value=news_session.response
        ) as news_get, mock.patch.object(news_client.time, "sleep"):
            news_client.collect_news()
        self.assertEqual(news_get.call_count, 2)

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
        ), mock.patch("core.api.app.configure_logging"), mock.patch(
            "core.api.app.database.initialize_db"
        ), mock.patch("core.api.app.get_settings_store"), mock.patch("core.api.app.speaker.initialize"):
            with TestClient(app):
                pass

        self.assertEqual(
            [call.args[0] for call in action_service.register_handler.call_args_list],
            [
                "create_microsoft_todo_task",
                "update_microsoft_todo_task",
                "complete_microsoft_todo_task",
                "reopen_microsoft_todo_task",
                "delete_microsoft_todo_task",
            ],
        )
        self.assertEqual(
            action_service.mock_calls[:6],
            [
                mock.call.register_handler(
                    name, executor=mock.ANY, verifier=mock.ANY
                )
                for name in (
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
        ), mock.patch("core.api.app.configure_logging"), mock.patch(
            "core.api.app.database.initialize_db"
        ), mock.patch("core.api.app.get_settings_store"), mock.patch("core.api.app.speaker.initialize"):
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
        ), mock.patch("core.api.app.configure_logging"), mock.patch(
            "core.api.app.database.initialize_db"
        ), mock.patch(
            "core.api.app.get_settings_store"
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
        ), mock.patch("core.api.app.configure_logging"), mock.patch(
            "core.api.app.database.initialize_db"
        ), mock.patch(
            "core.api.app.get_settings_store"
        ):
            with self.assertRaises(RuntimeError):
                with TestClient(app):
                    pass

        registry.close.assert_called_once_with()
        self.assertEqual(set_sessions.call_args_list[-1], mock.call(None))


if __name__ == "__main__":
    unittest.main()
