"""Private, bounded NDJSON control channel for an APEX host process."""

from __future__ import annotations

import json
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import BinaryIO, Callable, Mapping

MAX_FRAME_BYTES = 64 * 1024
CONTROL_QUEUE_SIZE = 64
CONTROL_TYPES = frozenset(
    {
        "start", "starting", "ready", "shutdown", "stopping", "stopped",
        "error", "completion", "desktop_preferences",
    }
)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_READY_FIELDS = frozenset(
    {
        "app_id", "app_version", "build_id", "instance_id", "pid", "hosting_mode",
        "launch_id", "data_root_fingerprint", "shutdown_timeout_seconds",
    }
)
_ERROR_CODES = frozenset(
    {
        "startup_failed", "port_in_use", "profile_in_use", "protocol_error",
        "shutdown_timeout", "shutdown_failed", "child_failed", "internal_error",
    }
)


class ControlProtocolError(ValueError):
    """An incoming or outgoing control frame violates the v1 contract."""


@dataclass(frozen=True, slots=True)
class ControlEnvelope:
    version: int
    type: str
    request_id: str
    payload: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "type": self.type,
            "request_id": self.request_id,
            "payload": self.payload,
        }


def _validate_identity_payload(payload: Mapping[str, object], *, exact: bool) -> None:
    if (exact and set(payload) != _READY_FIELDS) or not _READY_FIELDS.issubset(payload):
        raise ControlProtocolError("Ready payload does not match the host identity contract.")
    if (
        payload.get("app_id") != "apex"
        or not isinstance(payload.get("hosting_mode"), str)
        or payload.get("hosting_mode") not in {"standalone", "managed"}
    ):
        raise ControlProtocolError("Ready payload does not match the host identity contract.")
    for key in ("app_version", "build_id", "instance_id", "data_root_fingerprint"):
        if (
            not isinstance(payload.get(key), str)
            or not payload[key]
            or len(payload[key]) > 256
            or any(ord(char) < 32 for char in payload[key])
        ):
            raise ControlProtocolError("Ready payload does not match the host identity contract.")
    try:
        uuid.UUID(str(payload["instance_id"]))
        if payload["launch_id"] is not None:
            uuid.UUID(str(payload["launch_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ControlProtocolError("Ready payload does not match the host identity contract.") from exc
    if not re.fullmatch(r"[0-9a-f]{64}", str(payload["data_root_fingerprint"])):
        raise ControlProtocolError("Ready payload does not match the host identity contract.")
    if isinstance(payload["pid"], bool) or not isinstance(payload["pid"], int) or payload["pid"] <= 0:
        raise ControlProtocolError("Ready payload does not match the host identity contract.")
    timeout = payload["shutdown_timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
        raise ControlProtocolError("Ready payload does not match the host identity contract.")


def _validate_type_payload(message_type: str, payload: Mapping[str, object]) -> None:
    if message_type == "start":
        if set(payload) != {"launch_id"}:
            raise ControlProtocolError("Start payload does not match the lifecycle contract.")
        try:
            uuid.UUID(str(payload["launch_id"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ControlProtocolError("Start payload does not match the lifecycle contract.") from exc
    elif message_type == "starting":
        _validate_identity_payload(payload, exact=True)
    elif message_type == "ready":
        _validate_identity_payload(payload, exact=True)
    elif message_type == "error":
        code = payload.get("code")
        if set(payload) != {"code"} or not isinstance(code, str) or code not in _ERROR_CODES:
            raise ControlProtocolError("Error payload does not match the safe error contract.")
    elif message_type == "completion":
        if set(payload) != {"instance_id", "run_id", "status"}:
            raise ControlProtocolError("Completion payload does not match the lifecycle contract.")
        try:
            uuid.UUID(str(payload["instance_id"]))
            uuid.UUID(str(payload["run_id"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ControlProtocolError("Completion payload does not match the lifecycle contract.") from exc
        if not isinstance(payload["status"], str) or payload["status"] not in {
            "completed", "failed", "cancelled"
        }:
            raise ControlProtocolError("Completion payload does not match the lifecycle contract.")
    elif message_type == "desktop_preferences":
        if set(payload) != {"instance_id", "launch_on_startup", "completion_notifications"}:
            raise ControlProtocolError(
                "Desktop preferences payload does not match the lifecycle contract."
            )
        try:
            uuid.UUID(str(payload["instance_id"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ControlProtocolError("Desktop preferences payload does not match the lifecycle contract.") from exc
        if (
            type(payload["launch_on_startup"]) is not bool
            or type(payload["completion_notifications"]) is not bool
        ):
            raise ControlProtocolError("Desktop preferences payload does not match the lifecycle contract.")
    elif message_type == "shutdown" and payload:
        raise ControlProtocolError("Shutdown payload must be empty.")


def validate_envelope(
    value: object,
    *,
    expected_request_id: str | None = None,
) -> ControlEnvelope:
    """Validate an already-decoded frame, including response correlation."""
    if not isinstance(value, dict) or set(value) != {"version", "type", "request_id", "payload"}:
        raise ControlProtocolError("Control frame has an invalid shape.")
    version = value["version"]
    if type(version) is not int or version != 1:
        raise ControlProtocolError("Unsupported control protocol version.")
    message_type = value["type"]
    if not isinstance(message_type, str) or message_type not in CONTROL_TYPES:
        raise ControlProtocolError("Unsupported control message type.")
    request_id = value["request_id"]
    if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
        raise ControlProtocolError("Control frame has an invalid request identifier.")
    if expected_request_id is not None and request_id != expected_request_id:
        raise ControlProtocolError("Control frame correlation did not match the request.")
    payload = value["payload"]
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise ControlProtocolError("Control payload must be an object.")
    _validate_type_payload(message_type, payload)
    return ControlEnvelope(version=1, type=message_type, request_id=request_id, payload=payload)


def encode_envelope(envelope: ControlEnvelope | Mapping[str, object]) -> bytes:
    """Serialize one v1 envelope and enforce the byte limit."""
    raw = envelope.as_dict() if isinstance(envelope, ControlEnvelope) else dict(envelope)
    validated = validate_envelope(raw)
    try:
        frame = json.dumps(
            validated.as_dict(), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ControlProtocolError("Control frame could not be serialized.") from exc
    if len(frame) > MAX_FRAME_BYTES:
        raise ControlProtocolError("Control frame exceeds the size limit.")
    return frame


def decode_frame(data: bytes, *, expected_request_id: str | None = None) -> ControlEnvelope:
    """Decode and validate one bounded UTF-8 NDJSON frame."""
    if not isinstance(data, bytes) or len(data) > MAX_FRAME_BYTES:
        raise ControlProtocolError("Control frame exceeds the size limit.")
    line = data[:-1] if data.endswith(b"\n") else data
    if not data.endswith(b"\n") or not line or b"\n" in line or b"\r" in line:
        raise ControlProtocolError("Control frame is not one NDJSON record.")
    try:
        value = json.loads(
            line.decode("utf-8"),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ControlProtocolError("Control frame is not valid UTF-8 JSON.") from exc
    return validate_envelope(value, expected_request_id=expected_request_id)


class ControlChannel:
    """Bounded control channel with daemon reader and serialized writer threads.

    ``send`` never waits for a pipe consumer. The callback is itself invoked on
    a daemon thread, so reporting a broken pipe cannot block application work.
    """

    def __init__(
        self,
        reader: BinaryIO,
        writer: BinaryIO,
        *,
        on_failure: Callable[[str], None] | None = None,
        queue_size: int = CONTROL_QUEUE_SIZE,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be positive.")
        self._reader = reader
        self._writer = writer
        self._outgoing: queue.Queue[bytes | None] = queue.Queue(maxsize=queue_size)
        self._incoming: queue.Queue[ControlEnvelope] = queue.Queue(maxsize=queue_size)
        self._on_failure = on_failure
        self._failure_lock = threading.Lock()
        self._failed = False
        self._pending_lock = threading.Condition()
        self._pending_writes = 0
        self._closed = threading.Event()
        self._writer_thread = threading.Thread(target=self._write_loop, name="apex-control-writer", daemon=True)
        self._reader_thread = threading.Thread(target=self._read_loop, name="apex-control-reader", daemon=True)
        self._writer_thread.start()
        self._reader_thread.start()

    def _report_failure(self, reason: str) -> None:
        with self._failure_lock:
            if self._failed:
                return
            self._failed = True
        callback = self._on_failure
        if callback is not None:
            def report() -> None:
                try:
                    callback(reason)
                except Exception:
                    pass

            threading.Thread(target=report, name="apex-control-failure", daemon=True).start()

    def send(self, envelope: ControlEnvelope | Mapping[str, object]) -> None:
        if self._closed.is_set():
            raise RuntimeError("Control channel is closed.")
        frame = encode_envelope(envelope)
        with self._pending_lock:
            self._pending_writes += 1
            try:
                self._outgoing.put_nowait(frame)
            except queue.Full as exc:
                self._pending_writes -= 1
                self._pending_lock.notify_all()
                self._report_failure("outgoing_queue_full")
                raise RuntimeError("Control channel output queue is full.") from exc

    def receive(self, timeout: float | None = None) -> ControlEnvelope:
        return self._incoming.get(timeout=timeout)

    def _write_loop(self) -> None:
        while not self._closed.is_set():
            try:
                frame = self._outgoing.get(timeout=0.1)
            except queue.Empty:
                continue
            if frame is None:
                return
            try:
                view = memoryview(frame)
                while view:
                    written = self._writer.write(view)
                    if written is None:
                        break
                    if written <= 0:
                        raise BrokenPipeError
                    view = view[written:]
                self._writer.flush()
            except (BrokenPipeError, OSError, ValueError):
                self._report_failure("writer_failed")
                self._closed.set()
                return
            finally:
                with self._pending_lock:
                    self._pending_writes -= 1
                    self._pending_lock.notify_all()

    def _read_loop(self) -> None:
        while not self._closed.is_set():
            try:
                line = self._reader.readline(MAX_FRAME_BYTES + 1)
                if not line:
                    if not self._closed.is_set():
                        self._report_failure("reader_closed")
                    return
                envelope = decode_frame(line)
                self._incoming.put_nowait(envelope)
            except queue.Full:
                self._report_failure("incoming_queue_full")
                return
            except (ControlProtocolError, OSError, ValueError):
                self._report_failure("reader_failed")
                return

    def flush(self, timeout: float = 1.0) -> bool:
        """Wait up to ``timeout`` for queued output to reach the pipe."""
        end = time.monotonic() + max(0.0, timeout)
        with self._pending_lock:
            while self._pending_writes:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self._pending_lock.wait(remaining)
            return True

    def close(self, *, join_timeout: float = 0.2) -> None:
        if not self.flush(join_timeout):
            self._report_failure("writer_drain_timeout")
        self._closed.set()
        try:
            self._outgoing.put_nowait(None)
        except queue.Full:
            pass
        self._writer_thread.join(timeout=max(0.0, join_timeout))
        self._reader_thread.join(timeout=max(0.0, join_timeout))


__all__ = [
    "CONTROL_QUEUE_SIZE",
    "CONTROL_TYPES",
    "MAX_FRAME_BYTES",
    "ControlChannel",
    "ControlEnvelope",
    "ControlProtocolError",
    "decode_frame",
    "encode_envelope",
    "validate_envelope",
]
