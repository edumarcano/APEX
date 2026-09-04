"""Bounded, process-local event replay for Cortex runs."""

from __future__ import annotations

from collections import OrderedDict, deque
from datetime import datetime, timezone
import threading
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.runs.models import SAFE_ERROR_MESSAGES, RunRecord, RunRuntimeMeasurements

RunEventType = Literal[
    "run.snapshot",
    "run.status",
    "model.started",
    "model.completed",
    "response.delta",
    "response.reset",
    "response.completed",
    "tool.started",
    "tool.completed",
    "action.proposed",
    "usage.updated",
    "runtime.updated",
    "run.completed",
]


class RunEvent(BaseModel):
    """One sanitized event delivered by the live Cortex run stream."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=0)
    run_id: UUID
    type: RunEventType
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class RunEventBuffer:
    """Thread-safe replay buffer for one run, with no durable storage."""

    def __init__(self, record: RunRecord, *, limit: int) -> None:
        self.run_id = record.id
        self._record = record
        self._events: deque[RunEvent] = deque(maxlen=limit)
        self._answer = ""
        self._sequence = 0
        self._terminal = False
        self._condition = threading.Condition()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def publish(
        self,
        event_type: RunEventType,
        payload: dict[str, Any] | None = None,
        *,
        record: RunRecord | None = None,
    ) -> RunEvent:
        """Append an event and wake reconnecting or live subscribers."""
        with self._condition:
            if record is not None:
                self._record = record
            self._sequence += 1
            safe_payload = _safe_payload(event_type, payload or {})
            event = RunEvent(
                sequence=self._sequence,
                run_id=self.run_id,
                type=event_type,
                timestamp=self._now(),
                payload=safe_payload,
            )
            if event_type == "response.delta":
                self._answer += str(event.payload.get("text", ""))
            elif event_type == "response.reset":
                self._answer = ""
            elif event_type == "response.completed":
                self._answer = str(event.payload.get("answer", ""))
            self._events.append(event)
            self._condition.notify_all()
            return event

    def snapshot(self) -> RunEvent:
        """Build a non-buffered current snapshot for a new or gapped client."""
        with self._condition:
            return RunEvent(
                sequence=self._sequence,
                run_id=self.run_id,
                type="run.snapshot",
                timestamp=self._now(),
                payload={
                    "run": self._record.model_dump(mode="json"),
                    "answer": self._answer,
                },
            )

    def replay(self, after: int) -> tuple[list[RunEvent], bool, bool]:
        """Return events after a cursor, reporting when that cursor has expired."""
        with self._condition:
            first = self._events[0].sequence if self._events else self._sequence
            gap = after > self._sequence or bool(self._events and after < first - 1)
            events = [] if gap else [event for event in self._events if event.sequence > after]
            return events, gap, self._terminal

    def wait_for(self, after: int, timeout: float) -> tuple[list[RunEvent], bool, bool]:
        """Block off the event loop until data, termination, or heartbeat timeout."""
        with self._condition:
            if not self._terminal and self._sequence <= after:
                self._condition.wait(timeout=timeout)
            return self.replay(after)

    def complete(self, record: RunRecord) -> None:
        """Mark the buffer terminal after its terminal event has been published."""
        with self._condition:
            self._record = record
            self._terminal = True
            self._condition.notify_all()


class RunEventRegistry:
    """Own active streams and a bounded LRU of recent terminal streams."""

    def __init__(self, *, replay_limit: int, terminal_limit: int = 32) -> None:
        self._replay_limit = replay_limit
        self._terminal_limit = terminal_limit
        self._lock = threading.RLock()
        self._active: dict[UUID, RunEventBuffer] = {}
        self._terminal: OrderedDict[UUID, RunEventBuffer] = OrderedDict()

    def start(self, record: RunRecord) -> RunEventBuffer:
        """Create the buffer before worker execution can publish live activity."""
        with self._lock:
            existing = self._active.get(record.id)
            if existing is not None:
                return existing
            buffer = RunEventBuffer(record, limit=self._replay_limit)
            self._active[record.id] = buffer
            buffer.publish("run.snapshot", {"run": record.model_dump(mode="json"), "answer": ""})
            buffer.publish("run.status", {"status": record.status}, record=record)
            return buffer

    def get(self, run_id: UUID) -> RunEventBuffer | None:
        with self._lock:
            buffer = self._active.get(run_id)
            if buffer is not None:
                return buffer
            buffer = self._terminal.get(run_id)
            if buffer is not None:
                self._terminal.move_to_end(run_id)
            return buffer

    def publish(
        self,
        run_id: UUID,
        event_type: RunEventType,
        payload: dict[str, Any] | None = None,
        *,
        record: RunRecord | None = None,
    ) -> RunEvent | None:
        buffer = self.get(run_id)
        if buffer is None:
            return None
        return buffer.publish(event_type, payload, record=record)

    def complete(self, run_id: UUID, record: RunRecord) -> None:
        with self._lock:
            buffer = self._active.pop(run_id, None)
            if buffer is None:
                return
            buffer.complete(record)
            self._terminal[run_id] = buffer
            self._terminal.move_to_end(run_id)
            while len(self._terminal) > self._terminal_limit:
                self._terminal.popitem(last=False)

    def discard(self, run_id: UUID) -> None:
        """Drop a stream when submission failed before work became observable."""
        with self._lock:
            self._active.pop(run_id, None)

    @staticmethod
    def durable_snapshot(record: RunRecord) -> RunEvent:
        """Build the fallback snapshot used after restart or terminal-cache eviction."""
        return RunEvent(
            sequence=0,
            run_id=record.id,
            type="run.snapshot",
            timestamp=datetime.now(timezone.utc),
            payload={"run": record.model_dump(mode="json"), "answer": ""},
        )


def _safe_payload(event_type: RunEventType, payload: dict[str, Any]) -> dict[str, Any]:
    """Allow only the public fields documented for each closed event type."""
    if event_type == "run.snapshot":
        run = payload.get("run")
        return {
            "run": run if isinstance(run, dict) else {},
            "answer": _text(payload.get("answer")),
        }
    if event_type == "run.status":
        return _selected(payload, "status", "stop_reason")
    if event_type == "model.started":
        return _selected(payload, "turn")
    if event_type == "model.completed":
        return _selected(payload, "turn", "provider_ms")
    if event_type == "response.delta":
        return {"text": _text(payload.get("text"))}
    if event_type == "response.reset":
        return {}
    if event_type == "response.completed":
        return {"answer": _text(payload.get("answer"))}
    if event_type == "tool.started":
        return _selected(payload, "name", "origin")
    if event_type == "tool.completed":
        return _selected(payload, "name", "origin", "status", "duration_ms", "billable_units")
    if event_type == "action.proposed":
        return _selected(payload, "action_id", "status", "risk")
    if event_type == "usage.updated":
        return _selected(payload, "total_tokens", "usage_quality", "retries_count")
    if event_type == "runtime.updated":
        measurements = payload.get("runtime_measurements")
        return {
            "runtime_measurements": {
                key: value
                for key, value in measurements.items()
                if key in RunRuntimeMeasurements.model_fields
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value >= 0
            }
            if isinstance(measurements, dict) else {},
        }
    error = payload.get("error")
    error_code = error.get("code") if isinstance(error, dict) else None
    return {
        **_selected(payload, "status", "stop_reason"),
        "error": (
            {"code": error_code, "message": SAFE_ERROR_MESSAGES[error_code]}
            if error_code in SAFE_ERROR_MESSAGES
            else None
        ),
    }


def _selected(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Copy scalar safe fields while discarding unknown and nested payload data."""
    return {
        key: value
        for key in keys
        if (value := payload.get(key)) is None
        or isinstance(value, (str, int, float, bool))
    }


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""
