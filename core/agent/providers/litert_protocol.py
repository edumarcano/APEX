"""Wire contracts for the optional LiteRT worker.

The APEX process deliberately speaks a small, versioned JSON-lines protocol to
the Python 3.11 LiteRT worker.  This module contains only framing and
validation helpers; it never imports the optional LiteRT package.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


PROTOCOL_NAME = "APEX_LITERT"
PROTOCOL_VERSION = 1
PROTOCOL_PREFIX = f"{PROTOCOL_NAME}/{PROTOCOL_VERSION} "
MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_DIAGNOSTIC_TAIL = 8_192

READ_ONLY_OPERATIONS = frozenset({"hello", "status"})
KNOWN_OPERATIONS = frozenset(
    {
        "hello",
        "load_engine",
        "open_conversation",
        "send_message",
        "close_conversation",
        "status",
        "unload_engine",
        "shutdown",
    }
)


class LiteRTProtocolError(ValueError):
    """Raised when a frame violates the local worker protocol."""


class LiteRTTransportError(RuntimeError):
    """Raised when a request cannot obtain a correlated worker response."""


class LiteRTTimeoutError(LiteRTTransportError):
    """Raised when a bounded worker operation exceeds its deadline."""


class LiteRTWorkerCrashedError(LiteRTTransportError):
    """Raised when the worker exits before a response is received."""


class LiteRTInferenceAmbiguousError(LiteRTTransportError):
    """Raised for an uncertain ``send_message`` submission.

    The operation may have reached the native engine even though its response
    was not observed.  Callers must poison their request-scoped conversation
    and must not retry it.
    """


class LiteRTWorkerError(RuntimeError):
    """Raised for a structured, non-transport worker failure."""

    def __init__(self, code: str, message: str = "LiteRT worker operation failed.") -> None:
        self.code = code or "worker_error"
        self.safe_message = message or "LiteRT worker operation failed."
        super().__init__(self.safe_message)


@dataclass(frozen=True, slots=True)
class ProtocolFrame:
    """Validated request/response frame."""

    request_id: str
    operation: str
    payload: dict[str, Any]


def _ensure_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LiteRTProtocolError(f"{label} must be an object.")
    return dict(value)


def encode_frame(
    request_id: str,
    operation: str,
    payload: Mapping[str, Any] | None = None,
) -> bytes:
    """Encode one bounded protocol frame, including its required prefix."""
    request_id = str(request_id).strip()
    operation = str(operation).strip()
    if not request_id:
        raise LiteRTProtocolError("Frame id must be non-empty.")
    if not operation or operation not in KNOWN_OPERATIONS:
        raise LiteRTProtocolError(f"Unsupported LiteRT operation: {operation!r}.")
    body = {
        "id": request_id,
        "op": operation,
        "payload": _ensure_object(payload or {}, label="Frame payload"),
    }
    try:
        encoded = (PROTOCOL_PREFIX + json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise LiteRTProtocolError("Frame payload is not JSON serializable.") from exc
    if len(encoded) > MAX_FRAME_BYTES:
        raise LiteRTProtocolError("LiteRT protocol frame exceeds the size limit.")
    return encoded


def decode_frame(line: bytes | bytearray | str) -> ProtocolFrame:
    """Validate and decode one prefixed JSON-lines frame."""
    if isinstance(line, str):
        raw = line.encode("utf-8")
    else:
        raw = bytes(line)
    if len(raw) > MAX_FRAME_BYTES:
        raise LiteRTProtocolError("LiteRT protocol frame exceeds the size limit.")
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise LiteRTProtocolError("LiteRT protocol frame is not UTF-8.") from exc
    if not text.startswith(PROTOCOL_PREFIX):
        raise LiteRTProtocolError("LiteRT protocol prefix is missing.")
    try:
        body = json.loads(text[len(PROTOCOL_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise LiteRTProtocolError("LiteRT protocol frame is not valid JSON.") from exc
    obj = _ensure_object(body, label="Frame")
    request_id = obj.get("id")
    operation = obj.get("op")
    if not isinstance(request_id, str) or not request_id.strip():
        raise LiteRTProtocolError("Frame id must be a non-empty string.")
    if not isinstance(operation, str) or operation not in KNOWN_OPERATIONS:
        raise LiteRTProtocolError(f"Unsupported LiteRT operation: {operation!r}.")
    payload = _ensure_object(obj.get("payload", {}), label="Frame payload")
    return ProtocolFrame(request_id=request_id, operation=operation, payload=payload)


def frame_request(request_id: str, operation: str, payload: Mapping[str, Any] | None = None) -> bytes:
    """Compatibility alias for :func:`encode_frame`."""
    return encode_frame(request_id, operation, payload)


def parse_frame(line: bytes | bytearray | str) -> ProtocolFrame:
    """Compatibility alias for :func:`decode_frame`."""
    return decode_frame(line)


def operation_is_retryable(operation: str) -> bool:
    """Return whether an operation is safe to replay after transport failure."""
    return operation in READ_ONLY_OPERATIONS


def is_idempotent_operation(operation: str) -> bool:
    """Compatibility alias documenting the deliberately tiny retry set."""
    return operation_is_retryable(operation)


_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"password|authorization|cookie|oauth)[^\s=:#]*[\s=:]+[^\s,;]+"
)
_PATH_PATTERN = re.compile(r"(?i)(?:[A-Z]:\\|/)(?:[^\s\\/]+[\\/])+[^\s]+")


def sanitize_diagnostic(value: object, *, limit: int = MAX_DIAGNOSTIC_TAIL) -> str:
    """Keep local diagnostics bounded and free of obvious secrets/paths."""
    text = str(value or "").replace("\x00", " ")
    text = _SECRET_PATTERN.sub("[redacted]", text)
    text = _PATH_PATTERN.sub("[path]", text)
    text = " ".join(text.split())
    return text[:limit]


def safe_worker_error(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Extract only sanitized, user-safe fields from a worker error object."""
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return "worker_error", "LiteRT worker operation failed."
    code = str(error.get("code") or "worker_error")
    message = str(error.get("message") or "LiteRT worker operation failed.")
    allowed_codes = {
        "dependency_unavailable",
        "dependency_version_mismatch",
        "model_missing",
        "engine_error",
        "conversation_error",
        "protocol_error",
        "worker_error",
        "invalid_request",
    }
    if code not in allowed_codes:
        code = "worker_error"
    return code, sanitize_diagnostic(message, limit=240)
