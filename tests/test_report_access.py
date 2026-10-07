"""Execution-bound privacy and partition policy for report read tools."""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import mock

from core.agent.capabilities import (
    CapabilityDescriptor,
    CapabilityError,
    CapabilityErrorCategory,
    CapabilityRegistry,
)
from core.agent.report_access import (
    ReportReadExecutionContext,
    bind_report_read_context,
    make_report_read_context,
    report_read_availability,
    require_report_read_context,
)


def _settings(*, cloud: bool = True, local: bool = True):
    return SimpleNamespace(
        ask_apex=SimpleNamespace(
            cloud=SimpleNamespace(personal_context_enabled=cloud),
            local=SimpleNamespace(personal_context_enabled=local),
        )
    )


class ReportReadAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.patches = [
            mock.patch("core.config.DEMO_MODE", False),
            mock.patch("core.config.is_dev_mode", return_value=False),
            mock.patch("core.agent.report_access.get_settings_store"),
            mock.patch("core.activity.service.get_activity_service"),
        ]
        self.mocks = []
        for patcher in self.patches:
            self.mocks.append(patcher.start())
            self.addCleanup(patcher.stop)
        self.mocks[2].return_value.get_snapshot.return_value = _settings()
        self.mocks[3].return_value = object()

    def test_availability_uses_effective_runtime_model_setting(self) -> None:
        self.mocks[2].return_value.get_snapshot.return_value = _settings(
            cloud=False, local=True
        )

        self.assertEqual(
            report_read_availability(
                model_id="gemma-4-E2B-Q4_K_M.gguf", partition="production"
            ),
            (True, None),
        )
        allowed, reason = report_read_availability(
            model_id="z-ai/glm-5.3-flash", partition="production"
        )
        self.assertFalse(allowed)
        self.assertIsNotNone(reason)

    def test_demo_development_sandbox_and_missing_service_are_unavailable(self) -> None:
        with mock.patch("core.config.DEMO_MODE", True):
            self.assertFalse(
                report_read_availability(
                    model_id="z-ai/glm-5.3-flash",
                    partition="production",
                )[0]
            )
        with mock.patch("core.config.is_dev_mode", return_value=True):
            self.assertFalse(
                report_read_availability(
                    model_id="z-ai/glm-5.3-flash",
                    partition="production",
                )[0]
            )
        self.assertFalse(
            report_read_availability(
                model_id="z-ai/glm-5.3-flash", partition="sandbox"
            )[0]
        )
        self.mocks[3].side_effect = RuntimeError("not ready")
        self.assertFalse(
            report_read_availability(
                model_id="z-ai/glm-5.3-flash",
                partition="production",
            )[0]
        )

    def test_missing_and_initially_denied_context_fail_closed(self) -> None:
        with self.assertRaises(CapabilityError) as missing:
            require_report_read_context()
        self.assertEqual(missing.exception.category, CapabilityErrorCategory.UNAVAILABLE)

        self.mocks[2].return_value.get_snapshot.return_value = _settings(cloud=False)
        context = make_report_read_context(
            model_id="z-ai/glm-5.3-flash", partition="production"
        )
        self.assertFalse(context.permitted)
        self.mocks[2].return_value.get_snapshot.return_value = _settings(cloud=True)
        with bind_report_read_context(context), self.assertRaises(CapabilityError):
            require_report_read_context()

    def test_live_privacy_revocation_blocks_an_admitted_context(self) -> None:
        context = make_report_read_context(
            model_id="z-ai/glm-5.3-flash", partition="production"
        )
        self.assertTrue(context.permitted)
        self.mocks[2].return_value.get_snapshot.return_value = _settings(cloud=False)
        with bind_report_read_context(context), self.assertRaises(CapabilityError):
            require_report_read_context()

    def test_bound_context_resets_even_when_execution_raises(self) -> None:
        context = ReportReadExecutionContext("production", "model", True)
        with self.assertRaisesRegex(RuntimeError, "failure"):
            with bind_report_read_context(context):
                raise RuntimeError("failure")
        with self.assertRaises(CapabilityError):
            require_report_read_context()

    def test_registry_sync_executor_receives_isolated_caller_contexts(self) -> None:
        barrier = threading.Barrier(2)
        registry = CapabilityRegistry()
        registry.register(
            CapabilityDescriptor(
                name="test_report_read",
                title="Test report read",
                description="Read test report data.",
                input_schema={"type": "object", "properties": {}},
                origin="native",
                risk="read",
                expose_to_agent=True,
                expose_to_mcp_server=False,
                expose_to_client_display=True,
            ),
            lambda: (barrier.wait(timeout=3), require_report_read_context().model_id)[1],
        )

        def invoke(context: ReportReadExecutionContext) -> str:
            with bind_report_read_context(context):
                return registry.invoke("test_report_read")

        contexts = (
            ReportReadExecutionContext(
                "production", "z-ai/glm-5.3-flash", True
            ),
            ReportReadExecutionContext(
                "production", "gemma-4-E2B-Q4_K_M.gguf", True
            ),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(invoke, contexts))
        self.assertCountEqual(
            results,
            ["z-ai/glm-5.3-flash", "gemma-4-E2B-Q4_K_M.gguf"],
        )

    def test_query_admission_uses_trusted_partition_not_payload_partition(self) -> None:
        from core.agent.types import AgentQueryRequest, ToolSelectionDiagnostics
        from core.api.cortex import query_agent

        settings = mock.Mock()
        settings.ask_apex.enabled = True
        settings.user_designation = ""
        settings.agent_display_name = ""
        conversation = mock.Mock()
        conversation.partition.return_value = "production"
        with (
            mock.patch("core.api.cortex.DEMO_MODE", True),
            mock.patch("core.api.cortex.is_dev_mode", return_value=True),
            mock.patch("core.api.cortex.get_settings_store") as store,
            mock.patch("core.api.cortex.resolve_selected_tools") as select_tools,
            mock.patch("core.api.cortex.make_report_read_context") as make_context,
            mock.patch(
                "core.conversations.get_conversation_service",
                return_value=conversation,
            ),
        ):
            store.return_value.get_snapshot.return_value = settings
            select_tools.return_value = mock.Mock(
                failures=[], descriptors=[], diagnostics=ToolSelectionDiagnostics()
            )
            query_agent(
                AgentQueryRequest(
                    prompt="hello",
                    model_id="openai/gpt-6-luna",
                    history_partition="sandbox",
                )
            )

        conversation.partition.assert_called_once_with()
        make_context.assert_called_once_with(
            model_id="openai/gpt-6-luna", partition="production"
        )

    def test_query_without_conversation_service_keeps_existing_execution_path(self) -> None:
        from core.agent.types import AgentQueryRequest, ToolSelectionDiagnostics
        from core.api.cortex import query_agent

        settings = mock.Mock()
        settings.ask_apex.enabled = True
        settings.user_designation = ""
        settings.agent_display_name = ""
        with (
            mock.patch("core.api.cortex.DEMO_MODE", True),
            mock.patch("core.api.cortex.is_dev_mode", return_value=True),
            mock.patch("core.api.cortex.get_settings_store") as store,
            mock.patch("core.api.cortex.resolve_selected_tools") as select_tools,
            mock.patch("core.api.cortex.make_report_read_context") as make_context,
            mock.patch(
                "core.conversations.get_conversation_service",
                side_effect=RuntimeError("not initialized"),
            ),
        ):
            store.return_value.get_snapshot.return_value = settings
            select_tools.return_value = mock.Mock(
                failures=[], descriptors=[], diagnostics=ToolSelectionDiagnostics()
            )
            response = query_agent(
                AgentQueryRequest(prompt="hello", model_id="openai/gpt-6-luna")
            )

        self.assertTrue(response.answer)
        make_context.assert_called_once_with(
            model_id="openai/gpt-6-luna", partition="unavailable"
        )


if __name__ == "__main__":
    unittest.main()
