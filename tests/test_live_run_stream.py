"""Focused coverage for process-local Cortex run event streaming."""

from __future__ import annotations

from datetime import datetime, timezone
import asyncio
import threading
import unittest
from uuid import uuid4

from fastapi import Request
from core.agent.loop import run_agent_loop
from core.agent.providers.contract import ProviderStreamEvent, ProviderTurnResult
from core.agent.types import AgentMessage, AgentQueryRequest, ToolCall
from core.api.routers.cortex import (
    _format_sse,
    _parse_last_event_id,
    stream_cortex_run_events,
)
from core.runs.coordinator import set_run_coordinator
from core.runs.events import RunEventBuffer, RunEventRegistry
from core.runs.models import RunLimitSnapshot, RunRecord
from core.runs.service import set_run_service
from tests.support.agent_fixtures import build_local_profile


def _record(*, status: str = "running") -> RunRecord:
    now = datetime.now(timezone.utc)
    return RunRecord(
        id=uuid4(),
        conversation_id=uuid4(),
        partition="production",
        user_message_id=uuid4(),
        agent_message_id=uuid4(),
        requested_model="test-model",
        status=status,
        created_at=now,
        updated_at=now,
        limit_snapshot=RunLimitSnapshot(
            max_elapsed_seconds=60,
            max_total_tokens=1000,
            max_retries=1,
            max_model_turns=2,
            max_tool_calls=2,
        ),
    )


class LiveRunStreamTests(unittest.TestCase):
    def test_replay_is_ordered_and_snapshot_keeps_visible_answer(self) -> None:
        record = _record()
        buffer = RunEventBuffer(record, limit=8)
        buffer.publish("run.status", {"status": "running"})
        buffer.publish("response.delta", {"text": "hel"})
        buffer.publish("response.delta", {"text": "lo"})
        buffer.publish("response.completed", {"answer": "hello"})

        events, gap, terminal = buffer.replay(1)
        self.assertFalse(gap)
        self.assertFalse(terminal)
        self.assertEqual([event.sequence for event in events], [2, 3, 4])
        self.assertEqual(buffer.snapshot().payload["answer"], "hello")

    def test_rollover_requests_a_snapshot_instead_of_partial_replay(self) -> None:
        buffer = RunEventBuffer(_record(), limit=2)
        buffer.publish("response.delta", {"text": "a"})
        buffer.publish("response.delta", {"text": "b"})
        buffer.publish("response.delta", {"text": "c"})

        events, gap, _terminal = buffer.replay(0)
        self.assertTrue(gap)
        self.assertEqual(events, [])
        self.assertEqual(buffer.snapshot().payload["answer"], "abc")

    def test_future_cursor_requests_a_snapshot_instead_of_waiting_forever(self) -> None:
        buffer = RunEventBuffer(_record(), limit=2)
        buffer.publish("response.delta", {"text": "a"})

        events, gap, _terminal = buffer.replay(100)
        self.assertTrue(gap)
        self.assertEqual(events, [])

    def test_wait_for_delivers_new_events_without_reacquiring_its_lock(self) -> None:
        buffer = RunEventBuffer(_record(), limit=2)
        result = []
        completed = threading.Event()

        def wait_for_event() -> None:
            result.append(buffer.wait_for(0, timeout=1))
            completed.set()

        waiter = threading.Thread(target=wait_for_event, daemon=True)
        waiter.start()
        buffer.publish("response.delta", {"text": "live"})

        self.assertTrue(completed.wait(timeout=1))
        events, gap, terminal = result[0]
        self.assertFalse(gap)
        self.assertFalse(terminal)
        self.assertEqual([event.type for event in events], ["response.delta"])

    def test_terminal_buffers_use_bounded_lru_retention(self) -> None:
        registry = RunEventRegistry(replay_limit=4, terminal_limit=1)
        first = _record(status="completed")
        second = _record(status="completed")
        registry.start(first)
        registry.publish(first.id, "run.completed", {"status": "completed"}, record=first)
        registry.complete(first.id, first)
        registry.start(second)
        registry.publish(second.id, "run.completed", {"status": "completed"}, record=second)
        registry.complete(second.id, second)

        self.assertIsNone(registry.get(first.id))
        retained = registry.get(second.id)
        self.assertIsNotNone(retained)
        self.assertTrue(retained.replay(0)[2])

    def test_terminal_buffer_rejects_late_publication(self) -> None:
        registry = RunEventRegistry(replay_limit=4)
        record = _record(status="completed")
        registry.start(record)
        registry.publish(record.id, "run.completed", {"status": "completed"}, record=record)
        registry.complete(record.id, record)

        self.assertIsNone(registry.publish(record.id, "run.status", {"status": "completed"}))
        retained = registry.get(record.id)
        self.assertIsNotNone(retained)
        events, _gap, terminal = retained.replay(0)
        self.assertTrue(terminal)
        self.assertEqual(events[-1].type, "run.completed")

    def test_event_payload_and_sse_framing_do_not_expand_private_data(self) -> None:
        record = _record()
        event = RunEventBuffer(record, limit=4).publish(
            "tool.completed",
            {
                "name": "search",
                "origin": "apex",
                "status": "ok",
                "duration_ms": 2.5,
                "arguments": {"token": "secret"},
                "result": "private result",
            },
        )
        encoded = _format_sse(event)
        self.assertIn("event: tool.completed", encoded)
        self.assertIn('"name":"search"', encoded)
        self.assertNotIn("arguments", encoded)
        self.assertNotIn("result", encoded)

    def test_last_event_id_requires_non_negative_integer(self) -> None:
        self.assertEqual(_parse_last_event_id(None), 0)
        self.assertEqual(_parse_last_event_id("12"), 12)
        for value in ("-1", "oops"):
            with self.assertRaises(Exception):
                _parse_last_event_id(value)

    def test_loop_forwards_stream_text_and_final_activity(self) -> None:
        class Provider:
            def generate_turn(self, _history, _tools, _profile, *, stream_observer=None, **_kwargs):
                stream_observer(ProviderStreamEvent(kind="text", text="done"))
                stream_observer(ProviderStreamEvent(kind="completed"))
                return ProviderTurnResult(message=AgentMessage(role="agent", content="done"))

        provider_events = []
        activity = []
        response = run_agent_loop(
            AgentQueryRequest(prompt="Test", agent="apex"),
            Provider(),
            build_local_profile(model="qwen3:1.7b"),
            selected_tools=[],
            stream_observer=provider_events.append,
            activity_observer=lambda event_type, payload: activity.append((event_type, payload)),
        )

        self.assertEqual(response.answer, "done")
        self.assertEqual([event.kind for event in provider_events], ["text", "completed"])
        self.assertEqual([item[0] for item in activity], ["model.started", "model.completed", "response.completed"])

    def test_loop_resets_provisional_text_before_following_a_tool_call(self) -> None:
        class Provider:
            calls = 0

            def generate_turn(self, _history, _tools, _profile, *, stream_observer=None, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    stream_observer(ProviderStreamEvent(kind="text", text="discard me"))
                    return ProviderTurnResult(
                        message=AgentMessage(
                            role="agent",
                            content="discard me",
                            tool_calls=[ToolCall(id="call-1", name="unavailable", arguments={})],
                        )
                    )
                stream_observer(ProviderStreamEvent(kind="text", text="final"))
                return ProviderTurnResult(message=AgentMessage(role="agent", content="final"))

        activity = []
        response = run_agent_loop(
            AgentQueryRequest(prompt="Test", agent="apex"),
            Provider(),
            build_local_profile(model="qwen3:1.7b"),
            selected_tools=[],
            activity_observer=lambda event_type, payload: activity.append((event_type, payload)),
        )

        self.assertEqual(response.answer, "final")
        self.assertIn(("response.reset", {}), activity)
        self.assertEqual(activity[-1], ("response.completed", {"answer": "final"}))

    def test_sse_route_replays_terminal_buffer_with_standard_headers(self) -> None:
        record = _record(status="completed")
        registry = RunEventRegistry(replay_limit=4)
        registry.start(record)
        registry.publish(record.id, "run.completed", {"status": "completed"}, record=record)
        registry.complete(record.id, record)

        class Service:
            def get_run(self, run_id):
                self.assertEqual(run_id, record.id)
                return record

        service = Service()
        service.assertEqual = self.assertEqual
        set_run_service(service)
        set_run_coordinator(type("Coordinator", (), {"events": registry})())
        self.addCleanup(set_run_service, None)
        self.addCleanup(set_run_coordinator, None)
        request = Request({"type": "http", "headers": []})

        async def collect() -> tuple[object, list[str]]:
            response = await stream_cortex_run_events(record.id, request)
            chunks = [chunk async for chunk in response.body_iterator]
            return response, chunks

        response, chunks = asyncio.run(collect())
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        self.assertIn("event: run.completed", "".join(chunks))


if __name__ == "__main__":
    unittest.main()
