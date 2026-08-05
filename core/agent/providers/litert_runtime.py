"""Managed subprocess runtime for the optional LiteRT-LM Python binding.

The APEX Python 3.14 process never imports LiteRT.  A lazily-created worker
running the known-compatible interpreter owns the native engine and handles
only protocol-level operations.  Inference submissions are intentionally
non-retryable because a missing response cannot distinguish a failed send from
a completed native model turn.
"""

from __future__ import annotations

import itertools
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from core.agent.providers.litert_protocol import (
    MAX_DIAGNOSTIC_TAIL,
    ProtocolFrame,
    LiteRTInferenceAmbiguousError,
    LiteRTProtocolError,
    LiteRTTimeoutError,
    LiteRTTransportError,
    LiteRTWorkerCrashedError,
    LiteRTWorkerError,
    decode_frame,
    encode_frame,
    operation_is_retryable,
    safe_worker_error,
    sanitize_diagnostic,
)


_LOGGER = logging.getLogger(__name__)
_DEFAULT_HANDSHAKE_TIMEOUT = 10.0
_DEFAULT_LOAD_TIMEOUT = 300.0
_DEFAULT_INFERENCE_TIMEOUT = 120.0
_DEFAULT_SHUTDOWN_TIMEOUT = 5.0
_MAX_STDERR_TAIL_LINES = 128
_SENSITIVE_ENV_NAMES = (
    "API_KEY",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "CLIENT_SECRET",
    "PASSWORD",
    "AUTH_TOKEN",
    "OAUTH",
    "CREDENTIAL",
    "COOKIE",
)


class _PendingResponse:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.frame: ProtocolFrame | None = None
        self.error: BaseException | None = None


def restricted_worker_environment(
    base: Mapping[str, str] | None = None,
    *,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a worker environment without APEX credentials or OAuth state."""
    source = dict(base or os.environ)
    safe: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if any(token in upper for token in _SENSITIVE_ENV_NAMES):
            continue
        if upper.startswith("APEX_") and any(
            token in upper for token in ("KEY", "TOKEN", "SECRET", "OAUTH", "CREDENTIAL")
        ):
            continue
        safe[key] = str(value)
    for key, value in (extra or {}).items():
        safe[str(key)] = str(value)
    return safe


class LiteRTRuntimeManager:
    """Own one lazy worker process and at most one loaded LiteRT engine."""

    def __init__(
        self,
        *,
        interpreter: str | os.PathLike[str] | None = None,
        worker_script: str | os.PathLike[str] | None = None,
        project_root: str | os.PathLike[str] | None = None,
        popen_factory: Callable[..., subprocess.Popen[bytes]] | None = None,
        environment: Mapping[str, str] | None = None,
        handshake_timeout: float = _DEFAULT_HANDSHAKE_TIMEOUT,
        load_timeout: float = _DEFAULT_LOAD_TIMEOUT,
        inference_timeout: float = _DEFAULT_INFERENCE_TIMEOUT,
        shutdown_timeout: float = _DEFAULT_SHUTDOWN_TIMEOUT,
        max_frame_bytes: int | None = None,
    ) -> None:
        root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[3]
        self.interpreter = str(interpreter or (root / ".venv-litert" / "Scripts" / "python.exe"))
        self.worker_script = str(worker_script or (root / "scripts" / "litert_worker.py"))
        self.project_root = root
        self._popen_factory = popen_factory or subprocess.Popen
        self._environment = restricted_worker_environment(environment)
        self.handshake_timeout = max(0.1, float(handshake_timeout))
        self.load_timeout = max(0.1, float(load_timeout))
        self.inference_timeout = max(0.1, float(inference_timeout))
        self.shutdown_timeout = max(0.1, float(shutdown_timeout))
        self.max_frame_bytes = max_frame_bytes
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._pending: dict[str, _PendingResponse] = {}
        self._counter = itertools.count(1)
        self._stderr_tail: deque[str] = deque(maxlen=_MAX_STDERR_TAIL_LINES)
        self._protocol_ready = False
        self._engine_model: str | None = None
        self._last_status: dict[str, Any] = {"state": "unavailable", "loaded_model": None}

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        """Expose the child for diagnostics/tests without exposing conversation state."""
        with self._lock:
            return self._process

    @property
    def engine_model(self) -> str | None:
        with self._lock:
            return self._engine_model

    @property
    def is_running(self) -> bool:
        process = self.process
        return process is not None and process.poll() is None

    def diagnostic_tail(self) -> str:
        with self._lock:
            return "\n".join(self._stderr_tail)[-MAX_DIAGNOSTIC_TAIL:]

    def _command(self) -> list[str]:
        return [self.interpreter, self.worker_script]

    def _spawn(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            if self._process is not None:
                self._finalize_process_locked()
            try:
                kwargs: dict[str, Any] = {
                    "stdin": subprocess.PIPE,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "env": dict(self._environment),
                    "cwd": str(self.project_root),
                    "bufsize": 0,
                }
                if os.name == "nt":
                    kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                process = self._popen_factory(self._command(), **kwargs)
            except (OSError, TypeError) as exc:
                raise LiteRTTransportError("LiteRT worker could not be started.") from exc
            self._process = process
            self._protocol_ready = False
            self._engine_model = None
            self._last_status = {"state": "loading", "loaded_model": None}
            self._stdout_thread = threading.Thread(
                target=self._read_stdout,
                args=(process,),
                name="apex-litert-stdout",
                daemon=True,
            )
            self._stderr_thread = threading.Thread(
                target=self._read_stderr,
                args=(process,),
                name="apex-litert-stderr",
                daemon=True,
            )
            self._stdout_thread.start()
            self._stderr_thread.start()

    def _read_stdout(self, process: subprocess.Popen[bytes]) -> None:
        stream = process.stdout
        if stream is None:
            self._fail_pending(LiteRTWorkerCrashedError("LiteRT worker stdout is unavailable."))
            return
        try:
            for line in iter(stream.readline, b""):
                try:
                    frame = decode_frame(line)
                except LiteRTProtocolError:
                    # Protocol noise is never returned to a client.  Keep only
                    # a bounded local diagnostic entry.
                    with self._lock:
                        self._stderr_tail.append("protocol output ignored")
                    continue
                with self._lock:
                    pending = self._pending.pop(frame.request_id, None)
                if pending is not None:
                    pending.frame = frame
                    pending.event.set()
        finally:
            self._fail_pending(LiteRTWorkerCrashedError("LiteRT worker exited before responding."))

    def _read_stderr(self, process: subprocess.Popen[bytes]) -> None:
        stream = process.stderr
        if stream is None:
            return
        try:
            for line in iter(stream.readline, b""):
                try:
                    decoded = line.decode("utf-8", errors="replace")
                except Exception:
                    decoded = "worker diagnostic unavailable"
                with self._lock:
                    self._stderr_tail.append(sanitize_diagnostic(decoded))
        finally:
            pass

    def _fail_pending(self, error: BaseException) -> None:
        with self._lock:
            pending = tuple(self._pending.values())
            self._pending.clear()
        for response in pending:
            response.error = error
            response.event.set()

    def _finalize_process_locked(self) -> None:
        process = self._process
        if process is None:
            return
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
        self._process = None
        self._protocol_ready = False
        self._engine_model = None
        self._last_status = {"state": "unavailable", "loaded_model": None}

    def _terminate_process(self) -> None:
        with self._lock:
            process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=self.shutdown_timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.shutdown_timeout)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            with self._lock:
                self._finalize_process_locked()

    def _poison_transport(self) -> None:
        self._fail_pending(LiteRTWorkerCrashedError("LiteRT worker transport is unavailable."))
        self._terminate_process()

    def _ensure_handshake(self) -> None:
        with self._lock:
            ready = self._protocol_ready and self._process is not None and self._process.poll() is None
        if ready:
            return
        self._spawn()
        response = self._request_once("hello", {}, timeout=self.handshake_timeout)
        dependency = response.get("dependency")
        if not isinstance(dependency, Mapping) or not dependency.get("available"):
            code = "dependency_unavailable"
            message = "LiteRT Python worker dependency is unavailable."
            if isinstance(dependency, Mapping) and dependency.get("version_mismatch"):
                code = "dependency_version_mismatch"
                message = "LiteRT Python worker dependency version is unsupported."
            raise LiteRTWorkerError(code, message)
        with self._lock:
            self._protocol_ready = True
            self._last_status = response

    def _request_once(self, operation: str, payload: Mapping[str, Any], *, timeout: float) -> dict[str, Any]:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                raise LiteRTWorkerCrashedError("LiteRT worker is not running.")
            request_id = f"apex-{next(self._counter)}-{uuid.uuid4().hex[:8]}"
            pending = _PendingResponse()
            self._pending[request_id] = pending
            frame = encode_frame(request_id, operation, payload)
            try:
                process.stdin.write(frame)
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._pending.pop(request_id, None)
                raise LiteRTWorkerCrashedError("LiteRT worker stopped while sending a request.") from exc
        if not pending.event.wait(timeout=max(0.01, timeout)):
            with self._lock:
                self._pending.pop(request_id, None)
            raise LiteRTTimeoutError(f"LiteRT worker {operation} operation timed out.")
        if pending.error is not None:
            raise pending.error
        if pending.frame is None:
            raise LiteRTTransportError("LiteRT worker returned no response.")
        if pending.frame.operation != operation:
            raise LiteRTProtocolError("LiteRT worker response operation did not match request.")
        result = pending.frame.payload
        if "error" in result:
            code, message = safe_worker_error(result)
            raise LiteRTWorkerError(code, message)
        return result

    def _request(
        self,
        operation: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float,
        handshake: bool = True,
    ) -> dict[str, Any]:
        if handshake and operation not in {"hello", "status"}:
            self._ensure_handshake()
        attempts = 2 if operation_is_retryable(operation) else 1
        last_error: BaseException | None = None
        for attempt in range(attempts):
            if operation == "hello" and attempt == 0:
                self._spawn()
            elif operation == "status" and attempt == 0 and not self.is_running:
                self._spawn()
            try:
                result = self._request_once(operation, payload or {}, timeout=timeout)
                if operation == "status":
                    with self._lock:
                        self._last_status = dict(result)
                return result
            except (LiteRTTimeoutError, LiteRTWorkerCrashedError, BrokenPipeError) as exc:
                last_error = exc
                if not operation_is_retryable(operation) or attempt + 1 >= attempts:
                    if operation == "send_message":
                        self._poison_transport()
                        raise LiteRTInferenceAmbiguousError(
                            "LiteRT inference outcome is ambiguous; the request was not retried."
                        ) from exc
                    self._poison_transport()
                    raise
                self._poison_transport()
                self._spawn()
        assert last_error is not None
        raise last_error

    def hello(self) -> dict[str, Any]:
        """Perform a bounded dependency/protocol handshake."""
        return self._request("hello", {}, timeout=self.handshake_timeout, handshake=False)

    def status(self) -> dict[str, Any]:
        """Read worker status; this operation may be retried once."""
        return self._request("status", {}, timeout=self.handshake_timeout)

    def load_engine(self, model_path: str | os.PathLike[str], *, backend: str = "cpu") -> dict[str, Any]:
        """Load one engine explicitly; no ambiguous result is replayed."""
        path = str(model_path)
        result = self._request(
            "load_engine",
            {"model_path": path, "backend": backend},
            timeout=self.load_timeout,
        )
        with self._lock:
            self._engine_model = path
            self._last_status = dict(result)
        return result

    def open_conversation(
        self,
        *,
        conversation_id: str,
        system_instruction: str | None = None,
        tools: Sequence[Mapping[str, Any]] = (),
        initial_messages: Sequence[Mapping[str, Any]] = (),
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Open a native conversation using schema-only tools."""
        payload: dict[str, Any] = {
            "conversation_id": str(conversation_id),
            "system_instruction": system_instruction,
            "tools": [dict(tool) for tool in tools],
            "initial_messages": [dict(message) for message in initial_messages],
            "automatic_tool_calling": False,
        }
        if max_output_tokens is not None:
            payload["max_output_tokens"] = int(max_output_tokens)
        return self._request("open_conversation", payload, timeout=self.load_timeout)

    def send_message(
        self,
        conversation_id: str,
        message: Mapping[str, Any] | str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Submit exactly one message; never automatically retry it."""
        payload = {"conversation_id": str(conversation_id), "message": message}
        return self._request(
            "send_message",
            payload,
            timeout=self.inference_timeout if timeout is None else max(0.01, float(timeout)),
        )

    def close_conversation(self, conversation_id: str) -> dict[str, Any]:
        """Close a native conversation once, without replaying ambiguity."""
        return self._request(
            "close_conversation",
            {"conversation_id": str(conversation_id)},
            timeout=self.shutdown_timeout,
        )

    def unload_engine(self) -> dict[str, Any]:
        """Explicitly unload conversations and the current engine."""
        result = self._request("unload_engine", {}, timeout=self.shutdown_timeout)
        with self._lock:
            self._engine_model = None
            self._last_status = dict(result)
        return result

    def shutdown(self) -> bool:
        """Request clean worker shutdown and terminate if it does not comply."""
        with self._lock:
            running = self._process is not None and self._process.poll() is None
        if not running:
            self._terminate_process()
            return True
        success = True
        try:
            self._request("shutdown", {}, timeout=self.shutdown_timeout)
        except (LiteRTTransportError, LiteRTProtocolError, LiteRTWorkerError):
            success = False
        finally:
            self._terminate_process()
        return success

    def close(self) -> bool:
        """Compatibility alias for :meth:`shutdown`."""
        return self.shutdown()
