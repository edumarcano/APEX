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
from core.reminders.service import ReminderServiceError


class ApiPackageCompatibilityTests(unittest.TestCase):
    def test_module_entrypoint_calls_main(self) -> None:
        app_module = importlib.import_module("core.api.app")
        with mock.patch.object(app_module, "main") as main_mock:
            runpy.run_module("core.api", run_name="__main__")

        main_mock.assert_called_once_with()

    def test_public_api_defined_names_remain_importable(self) -> None:
        import core.api as api

        self.assertEqual(
            {name for name in api.__all__ if not hasattr(api, name)},
            set(),
        )


class ExtractedRouterHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, raise_server_exceptions=True)

    def test_reminder_routes_delegate_and_preserve_payloads(self) -> None:
        service = mock.Mock()
        service.list.return_value.to_dict.return_value = {
            "items": [
                {
                    "id": "local:7",
                    "note": "Review branch",
                    "source": "local",
                    "sync_state": "pending",
                }
            ],
            "source_state": "unavailable",
            "cache_timestamp": None,
            "pending_sync_count": 1,
        }
        service.create.return_value = {
            "id": "local:8",
            "outcome": "pending",
            "action_id": None,
        }
        service.complete.return_value = {
            "id": "local:7",
            "outcome": "dismissed",
            "action_id": None,
        }
        with mock.patch(
            "core.api.routers.reminders.DEMO_MODE", False
        ), mock.patch(
            "core.api.routers.reminders.get_reminder_service", return_value=service,
        ):
            response = self.client.get("/api/v1/reminders")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["id"], "local:7")

        with mock.patch(
            "core.api.routers.reminders.DEMO_MODE", False
        ), mock.patch(
            "core.api.routers.reminders.get_reminder_service", return_value=service,
        ):
            response = self.client.post(
                "/api/v1/reminders",
                json={"text": "**Call** advisor"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["id"], "local:8")
        service.create.assert_called_once_with("Call advisor")

        with mock.patch(
            "core.api.routers.reminders.DEMO_MODE", False
        ), mock.patch(
            "core.api.routers.reminders.get_reminder_service", return_value=service,
        ):
            response = self.client.post(
                "/api/v1/reminders/complete",
                json={"id": "local:7"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["outcome"], "dismissed")
        service.complete.assert_called_once_with("local:7")

    def test_reminder_task_management_routes_validate_and_delegate(self) -> None:
        service = mock.Mock()
        task = {
            "id": "todo:task-7", "title": "Review branch", "due": None,
            "importance": "normal", "is_completed": False,
            "completed_at": None, "last_modified_at": "stamp-7",
        }
        service.task_detail.return_value = task
        service.completed.return_value = {"items": [task], "source_state": "live"}
        service.update_task.return_value = {
            "id": "todo:task-7", "outcome": "synced", "action_id": "action-7"
        }
        service.delete_task.return_value = {
            "id": "todo:task-7", "outcome": "unknown", "action_id": "action-8"
        }
        service.reopen_task.return_value = {
            "id": "todo:task-7", "outcome": "synced", "action_id": "action-9"
        }
        patch = mock.patch(
            "core.api.routers.reminders.get_reminder_service", return_value=service,
        )
        demo = mock.patch("core.api.routers.reminders.DEMO_MODE", False)
        with patch, demo:
            response = self.client.get("/api/v1/reminders/task", params={"id": "todo:task-7"})
            completed = self.client.get("/api/v1/reminders/completed")
            update = self.client.post("/api/v1/reminders/update", json={
                "id": "todo:task-7", "last_modified_at": "stamp-7", "due": None,
            })
            deleted = self.client.post("/api/v1/reminders/delete", json={
                "id": "todo:task-7", "last_modified_at": "stamp-7",
            })
            reopened = self.client.post("/api/v1/reminders/reopen", json={
                "id": "todo:task-7", "last_modified_at": "stamp-7",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(completed.json()["source_state"], "live")
        self.assertEqual(update.status_code, 200)
        self.assertEqual(deleted.status_code, 202)
        self.assertEqual(reopened.status_code, 200)
        service.update_task.assert_called_once_with("todo:task-7", "stamp-7", {"due": None})
        with self.assertRaises(Exception):
            self.client.post("/api/v1/reminders/update", json={
                "id": "todo:task-7", "last_modified_at": "stamp-7",
            }).raise_for_status()

    def test_reminder_task_mutation_errors_preserve_status_and_action_id(self) -> None:
        service = mock.Mock()
        payload = {
            "id": "todo:task-7", "last_modified_at": "stamp-7", "title": "Review branch",
        }
        cases = (
            ("reminder_not_found", 404),
            ("reminder_target_changed", 409),
            ("microsoft_todo_unavailable", 503),
            ("microsoft_todo_mutation_failed", 502),
        )
        with mock.patch(
            "core.api.routers.reminders.DEMO_MODE", False
        ), mock.patch(
            "core.api.routers.reminders.get_reminder_service", return_value=service,
        ):
            for code, expected_status in cases:
                service.update_task.side_effect = ReminderServiceError(
                    code, action_id=f"action-{code}"
                )
                response = self.client.post("/api/v1/reminders/update", json=payload)
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json()["detail"], {
                    "code": code, "action_id": f"action-{code}"
                })

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

        with (
            mock.patch(
                "core.api.routers.cortex.resolve_agent_selection",
                return_value=("local", "apodemus", None),
            ) as resolve_selection,
            mock.patch(
                "core.api.routers.cortex.query_agent",
                return_value=query_response,
            ) as omitted_query_agent,
        ):
            response = self.client.post(
                "/api/v1/cortex/query",
                json={"prompt": "Use my saved Agent."},
            )

        self.assertEqual(response.status_code, 200)
        resolve_selection.assert_called_once()
        omitted_query_agent.assert_called_once()
        self.assertEqual(omitted_query_agent.call_args.args[0].agent, "apodemus")

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
