"""Unit and integration tests for APEX OpenTelemetry tracing and GenAI semantic conventions."""

from __future__ import annotations

import logging
import unittest
from unittest import mock
from uuid import uuid4

try:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    HAS_OTEL_SDK = True
except (ImportError, ModuleNotFoundError):
    TracerProvider = None  # type: ignore[assignment, misc]
    SimpleSpanProcessor = None  # type: ignore[assignment, misc]
    InMemorySpanExporter = None  # type: ignore[assignment, misc]
    HAS_OTEL_SDK = False

from opentelemetry.trace import StatusCode

from core.runs.models import RunCompletionEvidence, RunLimitSnapshot, RunRecord
from core.tracing import (
    TracingService,
    get_tracing_service,
    set_tracing_service,
    trace_provider_turn,
    trace_run,
    trace_tool_execution,
)


class TracingServiceLifecycleTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_tracing_service(None)

    def test_disabled_when_endpoint_unset(self) -> None:
        service = TracingService(endpoint=None)
        service.initialize()
        self.assertFalse(service.is_enabled)

    def test_graceful_warning_when_imports_fail(self) -> None:
        service = TracingService(endpoint="http://127.0.0.1:4318/v1/traces")
        with mock.patch.dict("sys.modules", {"opentelemetry.sdk.trace": None}):
            with self.assertLogs("core.tracing.service", level=logging.WARNING) as logs:
                service.initialize()
                self.assertFalse(service.is_enabled)
                self.assertTrue(any("not installed" in record or "Failed to import" in record for record in logs.output))

    def test_parses_otlp_headers(self) -> None:
        from core.tracing.service import parse_otlp_headers

        headers = parse_otlp_headers("api-key=secret123, X-Custom = value456 , trailing=789")
        self.assertEqual(
            headers,
            {"api-key": "secret123", "X-Custom": "value456", "trailing": "789"},
        )
        self.assertEqual(parse_otlp_headers(None), {})
        self.assertEqual(parse_otlp_headers(""), {})


@unittest.skipUnless(HAS_OTEL_SDK, "OpenTelemetry SDK not installed")
class GenAISpansTests(unittest.TestCase):
    def setUp(self) -> None:
        self.memory_exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.memory_exporter))
        self.service = TracingService(tracer_provider=self.provider)
        self.service.initialize()
        set_tracing_service(self.service)

    def tearDown(self) -> None:
        self.service.shutdown()
        set_tracing_service(None)

    def test_root_invoke_agent_span_and_privacy_boundaries(self) -> None:
        run_id = uuid4()
        conv_id = uuid4()
        user_msg_id = uuid4()
        agent_msg_id = uuid4()

        limit_snapshot = RunLimitSnapshot(
            max_elapsed_seconds=300,
            max_total_tokens=64000,
            max_retries=3,
            max_model_turns=5,
            max_tool_calls=8,
        )

        with trace_run(
            run_id=run_id,
            conversation_id=conv_id,
            user_message_id=user_msg_id,
            agent_message_id=agent_msg_id,
            requested_model="deepseek/deepseek-v4-flash-0731",
            provider="openrouter",
            runtime="cloud",
            limit_snapshot=limit_snapshot,
        ) as span_ctx:
            self.assertIsNotNone(span_ctx.trace_id)
            self.assertEqual(len(span_ctx.trace_id), 32)

            span_ctx.record_progress(
                resolved_model="deepseek/deepseek-v4-flash-0731",
                turns_count=2,
                tool_calls_count=1,
                retries_count=0,
                total_tokens=1420,
                usage_quality="reported",
                status="completed",
                stop_reason="end_turn",
            )

        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        root_span = spans[0]
        self.assertEqual(root_span.name, "invoke_agent")
        attrs = root_span.attributes or {}

        # Conformance to GenAI semantic conventions & metadata
        self.assertEqual(attrs.get("gen_ai.system"), "apex")
        self.assertEqual(attrs.get("gen_ai.request.model"), "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(attrs.get("gen_ai.response.model"), "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(attrs.get("apex.run_id"), str(run_id))
        self.assertEqual(attrs.get("apex.conversation_id"), str(conv_id))
        self.assertEqual(attrs.get("apex.user_message_id"), str(user_msg_id))
        self.assertEqual(attrs.get("apex.agent_message_id"), str(agent_msg_id))
        self.assertEqual(attrs.get("apex.provider"), "openrouter")
        self.assertEqual(attrs.get("apex.runtime"), "cloud")
        self.assertEqual(attrs.get("apex.turns_count"), 2)
        self.assertEqual(attrs.get("apex.tool_calls_count"), 1)
        self.assertEqual(attrs.get("apex.total_tokens"), 1420)
        self.assertEqual(attrs.get("apex.usage_quality"), "reported")
        self.assertEqual(attrs.get("apex.status"), "completed")
        self.assertEqual(attrs.get("apex.stop_reason"), "end_turn")
        self.assertEqual(attrs.get("apex.limit.max_elapsed_seconds"), 300)
        self.assertEqual(attrs.get("apex.limit.max_total_tokens"), 64000)
        self.assertEqual(root_span.status.status_code, StatusCode.OK)

        # STRICT PRIVACY GUARANTEE: ensure no prompts, answers, or sensitive content
        for attr_key, attr_val in attrs.items():
            val_str = str(attr_val).lower()
            self.assertNotIn("prompt", attr_key.lower())
            self.assertNotIn("answer", attr_key.lower())
            self.assertNotIn("content", attr_key.lower())

    def test_child_provider_and_tool_spans_in_parent_context(self) -> None:
        run_id = uuid4()
        conv_id = uuid4()
        user_msg_id = uuid4()
        agent_msg_id = uuid4()

        with trace_run(
            run_id=run_id,
            conversation_id=conv_id,
            user_message_id=user_msg_id,
            agent_message_id=agent_msg_id,
            requested_model="deepseek/deepseek-v4-flash-0731",
            provider="openrouter",
            runtime="cloud",
        ) as root_ctx:
            root_trace_id = root_ctx.trace_id

            # Turn 1: provider call
            with trace_provider_turn(
                model="deepseek/deepseek-v4-flash-0731",
                provider="openrouter",
                turn=1,
            ) as turn_ctx:
                mock_result = mock.Mock(
                    resolved_model="deepseek/deepseek-v4-flash-0731",
                    usage=mock.Mock(input_tokens=100, output_tokens=50),
                    provider_ms=150.5,
                    runtime_measurements=mock.Mock(
                        ttft_ms=45.0,
                        tokens_per_second=35.2,
                        eval_duration_ms=105.5,
                    ),
                )
                turn_ctx.record_result(mock_result)

            # Tool call
            with trace_tool_execution(tool_name="weather_forecast", origin="apex") as tool_ctx:
                tool_ctx.record_completion(duration_ms=42.1, status="ok")

            root_ctx.record_progress(status="completed", stop_reason="end_turn")

        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 3)

        turn_span = next(s for s in spans if s.name.startswith("chat "))
        tool_span = next(s for s in spans if s.name.startswith("execute_tool "))
        root_span = next(s for s in spans if s.name == "invoke_agent")

        # Context propagation check
        self.assertEqual(format(root_span.context.trace_id, "032x"), root_trace_id)
        self.assertEqual(format(turn_span.context.trace_id, "032x"), root_trace_id)
        self.assertEqual(format(tool_span.context.trace_id, "032x"), root_trace_id)
        self.assertEqual(turn_span.parent.span_id, root_span.context.span_id)
        self.assertEqual(tool_span.parent.span_id, root_span.context.span_id)

        # Provider turn attributes
        turn_attrs = turn_span.attributes or {}
        self.assertEqual(turn_attrs.get("gen_ai.system"), "openrouter")
        self.assertEqual(turn_attrs.get("gen_ai.request.model"), "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(turn_attrs.get("gen_ai.response.model"), "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(turn_attrs.get("apex.turn"), 1)
        self.assertEqual(turn_attrs.get("gen_ai.usage.input_tokens"), 100)
        self.assertEqual(turn_attrs.get("gen_ai.usage.output_tokens"), 50)
        self.assertEqual(turn_attrs.get("apex.provider_ms"), 150.5)
        self.assertEqual(turn_attrs.get("apex.ttft_ms"), 45.0)

        # Tool execution attributes & ZERO argument/result privacy check
        tool_attrs = tool_span.attributes or {}
        self.assertEqual(tool_attrs.get("gen_ai.tool.name"), "weather_forecast")
        self.assertEqual(tool_attrs.get("apex.tool.origin"), "apex")
        self.assertEqual(tool_attrs.get("apex.tool.status"), "ok")
        self.assertEqual(tool_attrs.get("apex.tool.duration_ms"), 42.1)
        self.assertNotIn("arguments", tool_attrs)
        self.assertNotIn("output", tool_attrs)

    def test_action_proposal_records_id_and_risk_without_target_or_content(self) -> None:
        with trace_tool_execution(tool_name="create_todo_task", origin="apex") as tool_ctx:
            tool_ctx.record_completion(
                duration_ms=15.0,
                status="ok",
                action_id="action-uuid-1234",
                action_risk="write",
            )

        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        tool_span = spans[0]
        attrs = tool_span.attributes or {}
        self.assertEqual(attrs.get("apex.action.id"), "action-uuid-1234")
        self.assertEqual(attrs.get("apex.action.risk"), "write")
        self.assertNotIn("target", attrs)
        self.assertNotIn("arguments", attrs)
        self.assertNotIn("title", attrs)

    def test_failed_tool_records_sanitized_category(self) -> None:
        with trace_tool_execution(tool_name="unauthorized_tool", origin="apex") as tool_ctx:
            tool_ctx.record_completion(
                duration_ms=8.0,
                status="error",
                error_category="unavailable",
            )

        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        tool_span = spans[0]
        self.assertEqual(tool_span.status.status_code, StatusCode.ERROR)
        self.assertEqual(tool_span.attributes.get("apex.tool.error_category"), "unavailable")

    def test_record_terminal_consolidates_run_record_metrics(self) -> None:
        run_id = uuid4()
        conv_id = uuid4()
        user_msg_id = uuid4()
        agent_msg_id = uuid4()

        with trace_run(
            run_id=run_id,
            conversation_id=conv_id,
            user_message_id=user_msg_id,
            agent_message_id=agent_msg_id,
            requested_model="deepseek/deepseek-v4-flash-0731",
            provider="openrouter",
            runtime="cloud",
        ) as root_ctx:
            mock_record = mock.Mock(
                resolved_model="deepseek/deepseek-v4-flash-0731",
                provider="openrouter",
                runtime="cloud",
                turns_count=3,
                tool_calls_count=2,
                retries_count=1,
                total_tokens=2048,
                usage_quality="reported",
                status="completed",
                stop_reason="end_turn",
                error=None,
            )
            root_ctx.record_terminal(mock_record)

        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        attrs = spans[0].attributes or {}
        self.assertEqual(attrs.get("gen_ai.response.model"), "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(attrs.get("apex.turns_count"), 3)
        self.assertEqual(attrs.get("apex.tool_calls_count"), 2)
        self.assertEqual(attrs.get("apex.retries_count"), 1)
        self.assertEqual(attrs.get("apex.total_tokens"), 2048)
        self.assertEqual(attrs.get("apex.status"), "completed")
        self.assertEqual(attrs.get("apex.stop_reason"), "end_turn")
        self.assertEqual(spans[0].status.status_code, StatusCode.OK)


if __name__ == "__main__":
    unittest.main()
