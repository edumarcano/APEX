"""Coverage for run ID context propagation into logs and metadata."""

from __future__ import annotations

import logging
import threading
import unittest
from unittest import mock

from core.agent import tools as agent_tools
from core.agent.loop import run_agent_loop
from core.agent.providers.gemini_models import GEMINI_MODEL_PROFILES
from core.agent.types import AgentMessage, AgentQueryRequest, ToolCall
from core.api.models import RuntimeMetadata
from core.api.state import PipelineState
from core.runtime_logging import bind_run_id_context, get_run_id, run_id_scope


class RunIdPropagationTests(unittest.TestCase):
    def test_run_id_scope_binds_context(self) -> None:
        self.assertIsNone(get_run_id())
        with run_id_scope("abc-123"):
            self.assertEqual(get_run_id(), "abc-123")
        self.assertIsNone(get_run_id())

    def test_pipeline_state_exposes_run_id(self) -> None:
        state = PipelineState()
        self.assertIsNone(state.get_state())
        state.begin_run("run-xyz")
        state.update(1, "GATE")
        snapshot = state.get_state()
        assert snapshot is not None
        self.assertEqual(snapshot["run_id"], "run-xyz")
        self.assertEqual(snapshot["step"], 1)
        state.reset()
        self.assertIsNone(state.get_state())

    def test_runtime_metadata_persists_run_id(self) -> None:
        metadata = RuntimeMetadata(
            run_id="run-persist",
            dev_mode_active=False,
            demo_mode_active=False,
            synthesis_strategy="cloud",
            tts_strategy="google",
            active_tts_engine="google",
            system_load_throttled=False,
        )
        dumped = metadata.model_dump()
        self.assertEqual(dumped["run_id"], "run-persist")
        restored = RuntimeMetadata.model_validate(dumped)
        self.assertEqual(restored.run_id, "run-persist")

    def test_logger_includes_run_id_filter(self) -> None:
        from core.runtime_logging import RunIdFilter, configure_logging

        configure_logging()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        with run_id_scope("log-run"):
            self.assertTrue(RunIdFilter().filter(record))
            self.assertEqual(getattr(record, "run_id"), "log-run")

    def test_bound_run_id_context_reaches_worker_thread(self) -> None:
        observed: list[str | None] = []

        with run_id_scope("thread-run"):
            worker = threading.Thread(
                target=bind_run_id_context(lambda: observed.append(get_run_id()))
            )
            worker.start()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(observed, ["thread-run"])


class StableAgentErrorTests(unittest.TestCase):
    def test_provider_error_payloads_are_replaced_with_stable_messages(self) -> None:
        cases = (
            (
                "fetch_weather_forecast",
                agent_tools.get_weather_forecast,
                "Weather forecast unavailable.",
            ),
            (
                "fetch_f1_driver_standings",
                agent_tools.get_f1_driver_standings,
                "F1 standings unavailable.",
            ),
            (
                "fetch_f1_season_calendar",
                agent_tools.get_f1_season_calendar,
                "F1 calendar unavailable.",
            ),
        )

        for dependency, tool, stable_message in cases:
            with self.subTest(tool=tool.__name__), mock.patch.object(
                agent_tools,
                dependency,
                return_value={"error": "private-provider-detail"},
            ):
                result = tool()
                self.assertEqual(result, {"error": stable_message})
                self.assertNotIn("private-provider-detail", str(result))

    def test_calendar_tool_does_not_return_provider_exception_text(self) -> None:
        with mock.patch(
            "clients.google_auth.get_service", return_value=object()
        ), mock.patch(
            "clients.calendar_client.get_upcoming_calendar_events",
            side_effect=RuntimeError("private-provider-detail"),
        ):
            result = agent_tools.get_upcoming_calendar_events()

        self.assertEqual(result, {"error": "Calendar data unavailable."})
        self.assertNotIn("private-provider-detail", str(result))

    def test_dispatcher_exception_is_stable_for_model_and_public_output(self) -> None:
        class Provider:
            def __init__(self) -> None:
                self.calls = 0
                self.tool_result: object | None = None

            def generate_turn(
                self,
                messages: list[AgentMessage],
                _tools: list[object],
                _profile: object,
                system_instruction_override: str | None = None,
            ) -> AgentMessage:
                del system_instruction_override
                self.calls += 1
                if self.calls == 1:
                    return AgentMessage(
                        role="model",
                        tool_calls=[
                            ToolCall(
                                id="call-1",
                                name="get_weather_forecast",
                                arguments={"days": 1},
                            )
                        ],
                    )
                self.tool_result = messages[-1].tool_results[0].output
                return AgentMessage(role="model", content="Done.")

        provider = Provider()

        def failing_dispatcher(_name: str, _arguments: dict[str, object]) -> object:
            raise RuntimeError("private-dispatcher-detail")

        response = run_agent_loop(
            AgentQueryRequest(prompt="Check weather", profile="comet"),
            provider,
            GEMINI_MODEL_PROFILES["comet"],
            tools_dispatcher=failing_dispatcher,
        )

        expected_error = {
            "error": "Tool execution failed.",
            "error_category": "upstream-failure",
        }
        self.assertEqual(provider.tool_result, expected_error)
        self.assertEqual(response.tool_outputs[0]["output"], expected_error)
        self.assertNotIn("private-dispatcher-detail", str(response.model_dump()))


if __name__ == "__main__":
    unittest.main()
