"""HTTP smoke coverage for the extracted API routers."""

from __future__ import annotations

import importlib
import runpy
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from core.agent.types import AgentQueryResponse
from core.api import app
from core.api.models import (
    AgentStatus,
    CloudAgentVerificationResponse,
    LocalLoadResponse,
    LocalUnloadResponse,
)


class ApiPackageCompatibilityTests(unittest.TestCase):
    def test_module_entrypoint_calls_main(self) -> None:
        app_module = importlib.import_module("core.api.app")
        with mock.patch.object(app_module, "main") as main_mock:
            runpy.run_module("core.api", run_name="__main__")

        main_mock.assert_called_once_with()

    def test_public_api_defined_names_remain_importable(self) -> None:
        import core.api as api

        expected_names = {
            "AgentStatus",
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

    def test_canonical_openapi_operation_ids_are_exposed(self) -> None:
        paths = app.openapi()["paths"]

        self.assertEqual(
            paths["/api/v1/trigger"]["post"]["operationId"],
            "trigger_briefing_api_v1_trigger_post",
        )
        self.assertEqual(
            paths["/api/v1/cortex/query"]["post"]["operationId"],
            "cortex_query_api_v1_cortex_query_post",
        )
        self.assertEqual(
            paths["/api/v1/cortex/local-model/unload"]["post"]["operationId"],
            "unload_active_local_model_endpoint_api_v1_cortex_local_model_unload_post",
        )
        self.assertEqual(
            paths["/api/v1/cortex/local-model/load"]["post"]["operationId"],
            "load_local_model_endpoint_api_v1_cortex_local_model_load_post",
        )
        self.assertEqual(
            paths["/api/v1/agents/{agent_key}/verify"]["post"]["operationId"],
            "verify_agent_api_v1_agents__agent_key__verify_post",
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

    def test_cortex_routes_delegate_and_preserve_payloads(self) -> None:
        agent = AgentStatus(
            key="panthera",
            display_name="Apex Panthera",
            description="Balanced general-purpose cloud intelligence.",
            provider="openai",
            version="1.0",
            configured_model="gpt-5.6-luna",
            runtime="cloud",
            tier="balanced",
            stability="stable",
            status="available",
            active=False,
        )
        with mock.patch(
            "core.api.routers.cortex.build_agent_statuses",
            return_value=[agent],
        ):
            response = self.client.get("/api/v1/agents")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["key"], "panthera")

        query_response = AgentQueryResponse(
            answer="Ready.",
            agent_used={"key": "panthera"},
            session_id="session-1",
        )
        with mock.patch(
            "core.api.routers.cortex.query_agent",
            return_value=query_response,
        ) as query_agent:
            response = self.client.post(
                "/api/v1/cortex/query",
                json={
                    "prompt": "Status?",
                    "agent": "panthera",
                    "session_id": "session-1",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Ready.")
        query_agent.assert_called_once()

        with mock.patch(
            "core.api.routers.cortex.unload_active_local_model_endpoint",
            return_value=LocalUnloadResponse(),
        ) as unload:
            second = self.client.post("/api/v1/cortex/local-model/unload")

        self.assertEqual(second.json(), {"status": "success"})
        unload.assert_called_once()

        with mock.patch(
            "core.api.routers.cortex.load_local_model_endpoint",
            return_value=LocalLoadResponse(agent="mus"),
        ) as load:
            response = self.client.post("/api/v1/cortex/local-model/load", json={"agent": "mus"})

        self.assertEqual(response.json(), {"status": "success", "agent": "mus"})
        load.assert_called_once_with("mus")

        verification = CloudAgentVerificationResponse(
            agent="panthera",
            status="verified",
            checked_at="2026-08-02T12:00:00Z",
        )
        with mock.patch(
            "core.api.routers.cortex.verify_cloud_agent_endpoint",
            return_value=verification,
        ) as verify:
            response = self.client.post("/api/v1/agents/panthera/verify")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "verified")
        verify.assert_called_once_with("panthera")

    def test_removed_agent_routes_and_profile_payload_are_rejected(self) -> None:
        self.assertEqual(self.client.get("/api/v1/agent/profiles").status_code, 404)
        self.assertEqual(self.client.post("/api/v1/agent/query").status_code, 404)
        response = self.client.post(
            "/api/v1/cortex/query",
            json={"prompt": "Status?", "profile": "panthera"},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
