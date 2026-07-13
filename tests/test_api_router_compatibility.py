"""Compatibility and HTTP smoke coverage for the extracted API routers."""

from __future__ import annotations

import importlib
import runpy
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from core.agent.types import AgentQueryResponse
from core.api import app
from core.api.models import AgentProfileStatus, LocalUnloadResponse


class ApiPackageCompatibilityTests(unittest.TestCase):
    def test_module_entrypoint_calls_main(self) -> None:
        app_module = importlib.import_module("core.api.app")
        with mock.patch.object(app_module, "main") as main_mock:
            runpy.run_module("core.api", run_name="__main__")

        main_mock.assert_called_once_with()

    def test_previous_api_defined_names_remain_importable(self) -> None:
        import core.api as api

        expected_names = {
            "AgentProfileStatus",
            "BriefingResponse",
            "CreateReminderRequest",
            "MarketResponse",
            "PipelineState",
            "_build_demo_briefing",
            "_load_mock_telemetry",
            "_resolve_tts_diagnostics",
            "create_reminder",
            "get_market_snapshot",
            "query_agent",
            "trigger_briefing",
        }

        self.assertEqual(
            {name for name in expected_names if not hasattr(api, name)},
            set(),
        )

    def test_previous_openapi_operation_ids_are_preserved(self) -> None:
        paths = app.openapi()["paths"]

        self.assertEqual(
            paths["/api/v1/trigger"]["post"]["operationId"],
            "trigger_briefing_api_v1_trigger_post",
        )
        self.assertEqual(
            paths["/api/v1/agent/query"]["post"]["operationId"],
            "query_agent_api_v1_agent_query_post",
        )
        self.assertEqual(
            paths["/api/v1/agent/local/unload"]["post"]["operationId"],
            "unload_active_local_model_endpoint_api_v1_agent_local_unload_post",
        )
        self.assertEqual(
            paths["/api/v1/local-model/unload"]["post"]["operationId"],
            "unload_active_local_model_endpoint_api_v1_local_model_unload_post",
        )


class ExtractedRouterHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, raise_server_exceptions=True)

    def test_reminder_routes_delegate_and_preserve_payloads(self) -> None:
        with mock.patch(
            "core.api.routers.reminders.DEMO_MODE", False
        ), mock.patch(
            "core.api.routers.reminders.database.fetch_unread_reminders",
            return_value=[(7, "Review branch")],
        ):
            response = self.client.get("/api/v1/reminders")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"id": 7, "note": "Review branch"}])

        with mock.patch(
            "core.api.routers.reminders.DEMO_MODE", False
        ), mock.patch(
            "core.api.routers.reminders.database.save_reminder", return_value=8
        ) as save_reminder:
            response = self.client.post(
                "/api/v1/reminders",
                json={"text": "**Call** advisor"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"id": 8})
        save_reminder.assert_called_once_with("Call advisor")

        with mock.patch(
            "core.api.routers.reminders.DEMO_MODE", False
        ), mock.patch(
            "core.api.routers.reminders.database.mark_reminders_read"
        ) as mark_read:
            response = self.client.post(
                "/api/v1/reminders/read",
                json={"ids": [7, 8]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "success"})
        mark_read.assert_called_once_with([7, 8])

    def test_market_route_delegates_and_validates_payload(self) -> None:
        market_payload = {
            "status": "live",
            "cooldown_active": False,
            "cooldown_remaining_seconds": 0,
            "tickers": [
                {
                    "symbol": "SPY",
                    "price": 520.0,
                    "change": 1.5,
                    "change_percent": 0.29,
                    "status": "live",
                    "last_updated": "2026-07-13T12:00:00+00:00",
                    "sparkline": [520.0, 518.5],
                }
            ],
        }
        with mock.patch(
            "core.api.routers.market.market_client.fetch_market_data",
            return_value=market_payload,
        ) as fetch_market:
            response = self.client.get("/api/v1/market")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), market_payload)
        fetch_market.assert_called_once_with()

    def test_assistant_routes_delegate_and_preserve_payloads(self) -> None:
        profile = AgentProfileStatus(
            key="comet",
            display_name="Comet",
            provider="gemini",
            tier="fast",
            stability="stable",
            status="available",
            active=False,
        )
        with mock.patch(
            "core.api.routers.assistant.build_agent_profile_statuses",
            return_value=[profile],
        ):
            response = self.client.get("/api/v1/agent/profiles")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["key"], "comet")

        query_response = AgentQueryResponse(
            answer="Ready.",
            profile_used={"key": "comet"},
            session_id="session-1",
        )
        with mock.patch(
            "core.api.routers.assistant.query_agent",
            return_value=query_response,
        ) as query_agent:
            response = self.client.post(
                "/api/v1/agent/query",
                json={
                    "prompt": "Status?",
                    "profile": "comet",
                    "session_id": "session-1",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Ready.")
        query_agent.assert_called_once()

        with mock.patch(
            "core.api.routers.assistant.unload_active_local_model_endpoint",
            return_value=LocalUnloadResponse(),
        ) as unload:
            first = self.client.post("/api/v1/agent/local/unload")
            second = self.client.post("/api/v1/local-model/unload")

        self.assertEqual(first.json(), {"status": "success"})
        self.assertEqual(second.json(), {"status": "success"})
        self.assertEqual(unload.call_count, 2)


if __name__ == "__main__":
    unittest.main()
