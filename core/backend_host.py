"""Lifecycle-owning source and frozen entry point for the APEX API host."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import importlib
import logging
import os
import signal
import socket
import sys
import threading
import time
import uuid
from dataclasses import replace
from typing import Any, Callable

from core.host.identity import HostContext, SHUTDOWN_TIMEOUT_SECONDS, create_host_context
from core.host.processes import redirect_stdout_to_stderr, terminate_owned_processes
from core.host.protocol import ControlChannel, ControlEnvelope

HOST = "127.0.0.1"
PORT = 8000
API_RUNTIME_URL = "http://127.0.0.1:8000/api/v1/runtime"
API_READY_URL = "http://127.0.0.1:8000/api/v1/health/ready"
START_HANDSHAKE_SECONDS = 10.0
HTTP_GRACE_SECONDS = 5.0
DEPENDENCY_CLEANUP_SECONDS = 20.0
FORCED_CHILD_CLEANUP_SECONDS = 5.0
_LOGGER = logging.getLogger(__name__)


def bind_api_socket() -> socket.socket:
    """Reserve the loopback API port exclusively before profile writes."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.set_inheritable(False)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HOST, PORT))
        listener.listen(socket.SOMAXCONN)
        return listener
    except BaseException:
        listener.close()
        raise


class _HardStopWatchdog:
    """Enforce an absolute shutdown deadline even when lifespan is stuck."""

    def __init__(
        self,
        *,
        budget_seconds: float,
        terminate: Callable[[float], None] = terminate_owned_processes,
        exit_process: Callable[[int], None] = os._exit,
        protocol_error: Callable[[], None] | None = None,
        forced_cleanup_seconds: float = FORCED_CHILD_CLEANUP_SECONDS,
    ) -> None:
        self._condition = threading.Condition()
        self._budget = max(0.05, float(budget_seconds))
        self._shutdown_at: float | None = None
        self._cancelled = False
        self._terminate = terminate
        self._exit_process = exit_process
        self._protocol_error = protocol_error
        self._forced_cleanup_seconds = max(0.0, forced_cleanup_seconds)
        self._thread = threading.Thread(
            target=self._run, name="apex-host-hard-stop", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def update_budget(self, budget_seconds: float) -> None:
        with self._condition:
            self._budget = max(0.05, float(budget_seconds))
            self._condition.notify_all()

    def arm(self) -> None:
        with self._condition:
            if self._shutdown_at is None:
                self._shutdown_at = time.monotonic()
            self._condition.notify_all()

    def cancel(self) -> None:
        with self._condition:
            self._cancelled = True
            self._condition.notify_all()

    def _run(self) -> None:
        with self._condition:
            while self._shutdown_at is None and not self._cancelled:
                self._condition.wait()
            if self._cancelled:
                return
        cleanup_started = False
        with self._condition:
            while not self._cancelled:
                assert self._shutdown_at is not None
                deadline = self._shutdown_at + self._budget
                cleanup_at = max(
                    self._shutdown_at,
                    deadline - min(self._forced_cleanup_seconds, self._budget),
                )
                now = time.monotonic()
                target = deadline if cleanup_started else cleanup_at
                remaining = target - now
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                if cleanup_started:
                    break
                cleanup_started = True
                cleanup_budget = max(0.0, deadline - now)
                cleanup = threading.Thread(
                    target=self._terminate,
                    args=(cleanup_budget,),
                    name="apex-host-owned-child-cleanup",
                    daemon=True,
                )
                cleanup.start()
                # Recompute the deadline after every budget update or cancel.
            if self._cancelled:
                return
        if self._protocol_error is not None:
            def report() -> None:
                try:
                    self._protocol_error()
                except Exception:
                    pass

            threading.Thread(
                target=report,
                name="apex-host-timeout-report",
                daemon=True,
            ).start()
        self._exit_process(1)


def _make_envelope(message_type: str, payload: dict[str, object], request_id: str | None = None) -> ControlEnvelope:
    return ControlEnvelope(
        version=1,
        type=message_type,
        request_id=request_id or str(uuid.uuid4()),
        payload=payload,
    )


def _send(
    channel: ControlChannel | None,
    message_type: str,
    payload: dict[str, object],
    request_id: str | None = None,
) -> bool:
    if channel is None:
        return False
    try:
        channel.send(_make_envelope(message_type, payload, request_id))
        return True
    except Exception:
        return False


def _wait_start(channel: ControlChannel) -> tuple[str, str]:
    deadline = time.monotonic() + START_HANDSHAKE_SECONDS
    while True:
        if channel._failed:
            raise RuntimeError("start handshake failed")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("start handshake failed")
        try:
            envelope = channel.receive(timeout=min(0.25, remaining))
        except Exception:
            continue
        if envelope.type != "start":
            raise RuntimeError("start handshake failed")
        launch_id = envelope.payload.get("launch_id")
        if not isinstance(launch_id, str):
            raise RuntimeError("start handshake failed")
        return str(uuid.UUID(launch_id)), envelope.request_id


def _http_json(url: str, *, timeout: float = 0.5) -> dict[str, object] | None:
    import json
    import urllib.error
    import urllib.request

    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as response:
            if response.status != 200:
                return None
            body = response.read(64 * 1024 + 1)
            if len(body) > 64 * 1024:
                return None
            value = json.loads(body)
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _host_uvicorn_server_type(server_base, app):
    """Make the owned server's signal and bounded-HTTP-drain hooks testable."""

    class HostUvicornServer(server_base):
        @contextmanager
        def capture_signals(self):
            # Uvicorn's serve() uses this hook; the host handlers also arm its
            # independent watchdog and therefore must remain installed.
            yield

        async def _wait_tasks_to_complete(self) -> None:
            try:
                await super()._wait_tasks_to_complete()
            except asyncio.CancelledError:
                app.state.http_shutdown_timed_out = True
                raise

    return HostUvicornServer


async def _serve(
    *,
    start_request_id: str | None,
    correlation: dict[str, str | None],
    channel: ControlChannel | None,
    listener: socket.socket,
    context: HostContext,
    shutdown_requested: threading.Event,
    watchdog: _HardStopWatchdog,
) -> int:
    if shutdown_requested.is_set():
        context.release()
        failure = correlation.get("failure")
        if failure is not None:
            _send(channel, "error", {"code": failure}, start_request_id)
        else:
            _send(channel, "stopped", {}, start_request_id)
        listener.close()
        return 1 if failure is not None else 0
    # Import the API only after the port is reserved and the profile is leased.
    api_module = importlib.import_module("core.api.app")
    app = api_module.app
    drain_seconds = float(api_module.CORTEX_RUNS_SHUTDOWN_DRAIN_SECONDS)
    hard_budget = drain_seconds + HTTP_GRACE_SECONDS + DEPENDENCY_CLEANUP_SECONDS + FORCED_CHILD_CLEANUP_SECONDS
    watchdog.update_budget(hard_budget)
    context.identity = replace(
        context.identity,
        shutdown_timeout_seconds=int(hard_budget),
    )
    app.state.host_context = context
    app.state.lifecycle_entered = False
    app.state.lifecycle_established = False
    app.state.lifecycle_cleanup_complete = False

    if channel is not None:
        identity = context.identity.as_dict()

        def completion_sink(event: dict[str, str]) -> None:
            payload: dict[str, object] = {
                "instance_id": str(identity["instance_id"]),
                "run_id": event["run_id"],
                "status": event["status"],
            }
            _send(channel, "completion", payload, event["run_id"])

        app.state.completion_sink = completion_sink
        _send(channel, "starting", identity, start_request_id)
    else:
        app.state.completion_sink = None

    if shutdown_requested.is_set():
        context.release()
        app.state.host_context = None
        failure = correlation.get("failure")
        if failure is not None:
            _send(channel, "error", {"code": failure}, start_request_id)
            listener.close()
            return 1
        _send(channel, "stopped", {}, start_request_id)
        listener.close()
        return 0

    import uvicorn

    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        workers=1,
        timeout_graceful_shutdown=HTTP_GRACE_SECONDS,
        log_config=None,
    )
    server = _host_uvicorn_server_type(uvicorn.Server, app)(config)

    failure_code: str | None = None
    failure_lock = threading.Lock()

    def mark_failure(code: str) -> None:
        nonlocal failure_code
        with failure_lock:
            failure_code = failure_code or code

    def request_shutdown(_reason: str = "shutdown") -> None:
        shutdown_requested.set()
        watchdog.arm()
        server.should_exit = True

    if channel is not None:
        def channel_failed(reason: str) -> None:
            del reason
            correlation["failure"] = "protocol_error"
            mark_failure("protocol_error")
            request_shutdown("control_channel_failed")

        channel._on_failure = channel_failed

        def watch_commands() -> None:
            while not shutdown_requested.is_set():
                try:
                    incoming = channel.receive(timeout=0.25)
                except Exception:
                    if channel._failed:
                        mark_failure("protocol_error")
                        request_shutdown("control_channel_failed")
                        return
                    continue
                if incoming.type == "shutdown" and incoming.payload == {}:
                    correlation["shutdown"] = incoming.request_id
                    request_shutdown("requested")
                    return
                mark_failure("protocol_error")
                request_shutdown("invalid_command")
                return

        threading.Thread(target=watch_commands, name="apex-host-control", daemon=True).start()

    old_handlers: dict[int, Any] = {}
    for sig in (
        getattr(signal, "SIGINT", None),
        getattr(signal, "SIGTERM", None),
        getattr(signal, "SIGBREAK", None),
    ):
        if sig is None:
            continue
        try:
            old_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda _signum, _frame: request_shutdown("signal"))
        except (ValueError, OSError):
            pass

    async def drive_shutdown() -> None:
        while not shutdown_requested.is_set():
            await asyncio.sleep(0.05)
        _send(
            channel,
            "stopping",
            {},
            correlation.get("shutdown") or start_request_id,
        )
        server.should_exit = True

    shutdown_task = asyncio.create_task(drive_shutdown(), name="apex-host-shutdown-controller")
    exit_code = 0
    try:
        server_task = asyncio.create_task(server.serve(sockets=[listener]), name="apex-uvicorn-server")
        ready_sent = False
        identity = context.identity.as_dict()
        while not server_task.done():
            if shutdown_requested.is_set():
                server.should_exit = True
            if (
                channel is not None
                and not ready_sent
                and server.started
                and not shutdown_requested.is_set()
            ):
                runtime, readiness = await asyncio.gather(
                    asyncio.to_thread(_http_json, API_RUNTIME_URL),
                    asyncio.to_thread(_http_json, API_READY_URL),
                )
                if runtime is not None and runtime != identity:
                    request_shutdown("runtime_identity_mismatch")
                    exit_code = 1
                elif runtime == identity and readiness == {
                    "status": "ready",
                    "config": "ok",
                    "database": "ok",
                }:
                    ready_sent = _send(channel, "ready", identity, start_request_id)
                    if not ready_sent:
                        request_shutdown("control_channel_failed")
            await asyncio.sleep(0.05)
        await server_task
        lifespan = getattr(server, "lifespan", None)
        startup_failed = bool(getattr(lifespan, "startup_failed", False))
        shutdown_failed = bool(getattr(lifespan, "shutdown_failed", False))
        entered = bool(getattr(app.state, "lifecycle_entered", False))
        cleanup_complete = bool(getattr(app.state, "lifecycle_cleanup_complete", False))
        safe_cleanup = not entered or cleanup_complete
        with failure_lock:
            control_failure = failure_code
        reply_request_id = correlation.get("shutdown") if channel is not None else None
        if reply_request_id is None:
            reply_request_id = start_request_id
        failed = (
            startup_failed
            or shutdown_failed
            or control_failure is not None
            or (channel is not None and not ready_sent and exit_code == 0)
        )
        if not safe_cleanup:
            exit_code = 1
            _send(
                channel,
                "error",
                {"code": control_failure or "shutdown_failed"},
                reply_request_id,
            )
            if channel is not None:
                channel.flush(0.25)
            request_shutdown("unsafe_cleanup")
            await asyncio.Future()
        context.release()
        app.state.host_context = None
        if failed:
            exit_code = 1
            code = control_failure or (
                "shutdown_failed" if entered and shutdown_failed else "startup_failed"
            )
            _send(channel, "error", {"code": code}, reply_request_id)
        elif shutdown_requested.is_set():
            _send(channel, "stopped", {}, reply_request_id)
        else:
            # Uvicorn returning without an orderly request means unexpected exit.
            exit_code = 1
            _send(channel, "error", {"code": "startup_failed"}, start_request_id)
    except BaseException:
        exit_code = 1
        # asyncio.run() can wait for its default executor while unwinding. Keep
        # the independent watchdog armed whenever the profile lease is held.
        if context.profile_lock.acquired:
            request_shutdown("server_failure")
        _send(channel, "error", {"code": "startup_failed"}, start_request_id)
        raise
    finally:
        shutdown_task.cancel()
        for sig, handler in old_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
        listener.close()
    return exit_code


def serve(
    *,
    hosting_mode: str = "standalone",
    launch_id: str | None = None,
    shutdown_timeout_seconds: int = SHUTDOWN_TIMEOUT_SECONDS,
) -> int:
    """Reserve the API endpoint and selected profile, then serve one worker."""
    channel: ControlChannel | None = None
    protocol_writer = None
    shutdown_requested = threading.Event()
    correlation: dict[str, str | None] = {
        "start": None,
        "shutdown": None,
        "failure": None,
    }

    def report_shutdown_timeout() -> None:
        request_id = correlation.get("shutdown") or correlation.get("start")
        if _send(channel, "error", {"code": "shutdown_timeout"}, request_id) and channel is not None:
            channel.flush(0.15)

    watchdog = _HardStopWatchdog(
        budget_seconds=shutdown_timeout_seconds,
        protocol_error=report_shutdown_timeout,
    )
    watchdog.start()

    def parent_lost(_reason: str) -> None:
        correlation["failure"] = "protocol_error"
        shutdown_requested.set()
        watchdog.arm()

    start_request_id: str | None = None
    if hosting_mode == "managed":
        try:
            sys.stdout.flush()
        except Exception:
            pass
        protocol_writer = redirect_stdout_to_stderr()
        reader_fd = os.dup(0)
        os.set_inheritable(reader_fd, False)
        control_reader = os.fdopen(reader_fd, "rb", buffering=0)
        channel = ControlChannel(
            control_reader,
            protocol_writer,
            on_failure=parent_lost,
        )
        try:
            handshake_launch_id, start_request_id = _wait_start(channel)
            if launch_id is not None and str(uuid.UUID(launch_id)) != handshake_launch_id:
                raise RuntimeError("start handshake failed")
            launch_id = handshake_launch_id
            correlation["start"] = start_request_id
        except Exception:
            _send(channel, "error", {"code": "protocol_error"})
            channel.flush(0.25)
            channel.close()
            protocol_writer.close()
            return 2
    if shutdown_requested.is_set():
        if channel is not None:
            channel.close()
        if protocol_writer is not None:
            protocol_writer.close()
        return 1

    context: HostContext | None = None
    try:
        runtime_paths = importlib.import_module("core.runtime_paths")
        runtime_paths.initialize_environment()
        paths = runtime_paths.get_runtime_paths()
        try:
            listener = bind_api_socket()
        except OSError as exc:
            code = "port_in_use" if exc.errno in {48, 98, 10048, 10013} else "startup_failed"
            if channel is None:
                print(
                    "APEX could not reserve 127.0.0.1:8000; close the existing service and retry."
                    if code == "port_in_use"
                    else "APEX could not start its API listener.",
                    file=sys.stderr,
                    flush=True,
                )
            _send(channel, "error", {"code": code}, start_request_id)
            if channel is not None:
                channel.flush(0.25)
            return 1
        try:
            context = create_host_context(
                paths,
                hosting_mode=hosting_mode,  # type: ignore[arg-type]
                launch_id=launch_id,
                shutdown_timeout_seconds=shutdown_timeout_seconds,
            )
        except Exception as exc:
            listener.close()
            from core.host.profile_lock import ProfileAlreadyRunningError

            code = "profile_in_use" if isinstance(exc, ProfileAlreadyRunningError) else "startup_failed"
            if channel is None:
                print(
                    "The selected APEX data profile is already in use. Close the other APEX instance and retry."
                    if code == "profile_in_use"
                    else "APEX could not initialize its selected data profile.",
                    file=sys.stderr,
                    flush=True,
                )
            _send(channel, "error", {"code": code}, start_request_id)
            if channel is not None:
                channel.flush(0.25)
            return 1
        result = asyncio.run(
            _serve(
                start_request_id=start_request_id,
                correlation=correlation,
                channel=channel,
                listener=listener,
                context=context,
                shutdown_requested=shutdown_requested,
                watchdog=watchdog,
            )
        )
        return result
    except BaseException:
        if context is not None:
            # Process exit is the safe release boundary if application teardown failed.
            _LOGGER.exception("APEX host failed before safe cleanup")
            watchdog.arm()
        _send(channel, "error", {"code": "startup_failed"}, start_request_id)
        return 1
    finally:
        if channel is not None:
            channel.flush(0.5)
            channel.close()
        if protocol_writer is not None:
            protocol_writer.close()
        # Keep the watchdog armed through bounded protocol cleanup. Never close
        # the raw input stream here: its daemon reader may still be blocked in
        # FileIO.readline(), and Windows waits for that read lock on close.
        if context is None or not context.profile_lock.acquired:
            watchdog.cancel()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apex-backend")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser("serve", help="serve the APEX API")
    mode = serve_parser.add_mutually_exclusive_group()
    mode.add_argument("--standalone", action="store_true")
    mode.add_argument("--managed", action="store_true")
    serve_parser.add_argument("--launch-id")
    subparsers.add_parser("worker", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch the explicitly supported worker or API host command."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    worker_dispatch = importlib.import_module("core.host.worker_dispatch")
    worker_result = worker_dispatch.dispatch_worker(arguments)
    if worker_result is not None:
        return worker_result
    parsed = _parser().parse_args(arguments)
    if parsed.command != "serve":
        return 2
    hosting_mode = "managed" if parsed.managed else "standalone"
    if parsed.launch_id is not None and hosting_mode != "managed":
        _parser().error("--launch-id is only valid with --managed")
    return serve(hosting_mode=hosting_mode, launch_id=parsed.launch_id)


if __name__ == "__main__":
    raise SystemExit(main())
