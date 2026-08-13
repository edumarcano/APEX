"""Action control API and Cortex proposal interception coverage."""

from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.actions import (
    ActionService,
    ActionStore,
    ExecutionOutcome,
    VerificationOutcome,
    set_action_service,
)
from core.agent.capabilities import (
    CapabilityDescriptor,
    clear_capability_registry_for_tests,
    register_capability,
    validate_capability_arguments,
)
from core.agent.catalog import build_concrete_agent
from core.agent.loop import run_agent_loop
from core.agent.providers.contract import ProviderTurnResult
from core.agent.tool_selection import resolve_selected_tools
from core.agent.types import AgentMessage, AgentQueryRequest, ToolCall
from core.api.app import app


class _Executor:
    def __init__(self) -> None:
        self.calls = 0
        self.arguments: dict[str, object] | None = None
        self.lock = threading.Lock()

    def execute(self, action):
        with self.lock:
            self.calls += 1
            self.arguments = dict(action.proposal.arguments)
        return ExecutionOutcome(True, "test_written", {"written": True})


class _Verifier:
    def __init__(self, verified: bool = True) -> None:
        self.calls = 0
        self.verified = verified

    def verify(self, _action):
        self.calls += 1
        return VerificationOutcome(self.verified, "test_verified", {"found": self.verified})


class _ProposalProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate_turn(self, _messages, _tools, _profile, system_instruction_override=None):
        del system_instruction_override
        self.calls += 1
        if self.calls == 1:
            return ProviderTurnResult(message=AgentMessage(
                role="agent",
                tool_calls=[ToolCall(id="call-1", name="test_write", arguments={"count": "4"})],
            ))
        return ProviderTurnResult(message=AgentMessage(role="agent", content="Proposed."))


class ActionControlApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.service = ActionService(ActionStore(Path(self.tempdir.name) / "actions.db"))
        self.executor = _Executor()
        self.verifier = _Verifier()
        self.service.register_handler("test_write", executor=self.executor, verifier=self.verifier)
        set_action_service(self.service)
        clear_capability_registry_for_tests()
        self.handler_calls = 0
        register_capability(
            CapabilityDescriptor(
                name="test_write", title="Test Write", description="Write test data.",
                input_schema={
                    "type": "object", "properties": {"count": {"type": "integer"}},
                    "required": ["count"], "additionalProperties": False,
                },
                origin="native", risk="write", expose_to_agent=True,
                expose_to_mcp_server=False, expose_to_client_display=True,
            ),
            self._handler,
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        set_action_service(None)
        clear_capability_registry_for_tests()
        self.tempdir.cleanup()

    def _handler(self, **_arguments):
        self.handler_calls += 1
        return {"unexpected": True}

    def _propose(self):
        return self.service.propose(
            agent_key="panthera", capability_name="test_write", arguments={"count": 4},
            target="Test Write", risk="write", summary="Approve Test Write",
        )

    def test_validation_normalizes_without_invoking_handler(self) -> None:
        self.assertEqual(validate_capability_arguments("test_write", {"count": "4"}), {"count": 4})
        self.assertEqual(self.handler_calls, 0)
        with self.assertRaises(Exception):
            validate_capability_arguments("test_write", {"count": "bad"})
        self.assertEqual(self.handler_calls, 0)

    def test_supported_native_write_is_selectable_and_loop_creates_proposal(self) -> None:
        selection = resolve_selected_tools("panthera", ["test_write"])
        self.assertEqual([tool.name for tool in selection.descriptors], ["test_write"])
        provider = _ProposalProvider()
        response = run_agent_loop(
            AgentQueryRequest(prompt="Write", agent="panthera", selected_tool_names=["test_write"]),
            provider, build_concrete_agent("panthera", native_effort=None),
            selected_tools=list(selection.descriptors), tool_selection=selection.diagnostics,
            agent_key="panthera",
        )
        self.assertEqual(response.tool_outputs[0]["status"], "ok")
        output = response.tool_outputs[0]["output"]
        self.assertEqual(output["status"], "proposed")
        self.assertEqual(self.handler_calls, 0)
        action = self.service.get(output["action_id"])
        self.assertEqual(dict(action.proposal.arguments), {"count": 4})

    def test_unsupported_native_and_mcp_actions_are_not_selectable(self) -> None:
        for name, origin in (("unsupported_write", "native"), ("remote_write", "mcp")):
            register_capability(
                CapabilityDescriptor(
                    name=name, title=name, description="Write.",
                    input_schema={"type": "object", "properties": {}},
                    origin=origin, risk="write", expose_to_agent=True,
                    expose_to_mcp_server=False, expose_to_client_display=False,
                ),
                lambda: None,
            )
        native = resolve_selected_tools("panthera", ["unsupported_write"])
        self.assertEqual(native.diagnostics.rejected_tools[0].code, "unavailable")
        remote = resolve_selected_tools("panthera", ["remote_write"])
        self.assertEqual(remote.diagnostics.rejected_tools[0].code, "risk-rejected")

    def test_api_list_detail_approve_and_audit(self) -> None:
        action = self._propose()
        listed = self.client.get("/api/v1/actions")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["action_id"], action.action_id)
        detail = self.client.get(f"/api/v1/actions/{action.action_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["events"][0]["to_status"], "proposed")
        approved = self.client.post(
            f"/api/v1/actions/{action.action_id}/approve", json={"expected_version": 0}
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "verified")
        self.assertEqual(self.executor.calls, 1)
        self.assertEqual(self.verifier.calls, 1)

    def test_reject_does_not_execute_and_verify_retry_does_not_reexecute(self) -> None:
        rejected = self._propose()
        response = self.client.post(
            f"/api/v1/actions/{rejected.action_id}/reject", json={"expected_version": 0}
        )
        self.assertEqual(response.json()["status"], "rejected")
        self.assertEqual(self.executor.calls, 0)

        self.verifier.verified = False
        retryable = self._propose()
        failed = self.client.post(
            f"/api/v1/actions/{retryable.action_id}/approve", json={"expected_version": 0}
        )
        self.assertEqual(failed.json()["status"], "verification_failed")
        self.verifier.verified = True
        retried = self.client.post(
            f"/api/v1/actions/{retryable.action_id}/verify", json={"expected_version": 4}
        )
        self.assertEqual(retried.json()["status"], "verified")
        self.assertEqual(self.executor.calls, 1)

    def test_stale_and_concurrent_approvals_execute_once(self) -> None:
        action = self._propose()
        barrier = threading.Barrier(2)

        def approve():
            barrier.wait()
            return self.client.post(
                f"/api/v1/actions/{action.action_id}/approve", json={"expected_version": 0}
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda _value: approve(), range(2)))
        self.assertEqual(sorted(codes), [200, 409])
        self.assertEqual(self.executor.calls, 1)

    def test_api_approval_resumes_an_already_approved_action(self) -> None:
        action = self._propose()
        approved = self.service.approve(action.action_id, actor="operator", expected_version=0)
        response = self.client.post(
            f"/api/v1/actions/{action.action_id}/approve",
            json={"expected_version": approved.version},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "verified")
        self.assertEqual(self.executor.calls, 1)

    def test_missing_version_and_demo_mode_are_rejected(self) -> None:
        action = self._propose()
        self.assertEqual(
            self.client.post(f"/api/v1/actions/{action.action_id}/approve", json={}).status_code,
            422,
        )
        with patch("core.api.routers.actions.DEMO_MODE", True):
            self.assertEqual(self.client.get("/api/v1/actions").json(), [])
            self.assertEqual(self.client.get(f"/api/v1/actions/{action.action_id}").status_code, 403)


if __name__ == "__main__":
    unittest.main()
