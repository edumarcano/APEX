"""Build-only frozen smoke probe; never included in the production distribution."""

from __future__ import annotations

import argparse
import asyncio
import faulthandler
import json
import logging
import multiprocessing
import sys
import threading
import time
from contextlib import redirect_stdout
from pathlib import Path
from urllib.parse import urlsplit

multiprocessing.freeze_support()
if getattr(sys, "frozen", False):
    # Match the production bootstrap: avoid importing NumPy after a worker
    # thread begins reading the frozen process's piped stdin.
    import numpy  # noqa: F401

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from scripts.smoke_backend_bundle import main as _run_smoke_suite


def _worker_dispatch(argv: list[str]) -> int | None:
    if not argv or argv[0] != "worker":
        return None
    from core.backend_host import main as backend_main
    return backend_main(argv)


def _imports() -> dict[str, object]:
    import clients.google_auth  # noqa: F401
    import clients.microsoft_auth  # noqa: F401
    import fastembed  # noqa: F401
    import onnxruntime  # noqa: F401
    import opentelemetry.trace  # noqa: F401
    import opentelemetry.exporter.otlp.proto.http.trace_exporter  # noqa: F401
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import texttospeech  # noqa: F401
    from googleapiclient.discovery import build
    service = build("drive", "v3", credentials=AnonymousCredentials(), cache_discovery=False)
    return {"google_auth": "loaded", "microsoft_auth": "loaded", "google_discovery": service._rootDesc.get("name", "drive"), "google_tts": "loaded", "tracing": "loaded", "fastembed": "loaded", "onnxruntime": "loaded"}


def _retrieval() -> dict[str, object]:
    from core.retrieval.docs import build_documentation_items, documentation_paths, search_documentation
    from core.retrieval.service import RetrievalService
    from core.retrieval.store import RetrievalStore
    from core.runtime_paths import get_runtime_paths
    paths, items = documentation_paths(), build_documentation_items()
    if not paths or not items:
        raise RuntimeError("frozen documentation resources were not discovered")
    db_path = get_runtime_paths().data_root / "smoke-retrieval-fts.db"
    service = RetrievalService(RetrievalStore(db_path), enabled=True)
    service.initialize()
    result = search_documentation("APEX local first workspace", service)
    if result.get("retrieval_mode") != "fts_only" or not result.get("results"):
        raise RuntimeError("production documentation search did not return FTS results")
    return {"documentation_files": len(paths), "documentation_items": len(items), "retrieval_mode": result["retrieval_mode"], "results": len(result["results"])}


def _audio_worker() -> dict[str, object]:
    import threading
    from core.speaker import synthesize_audio
    chunks, engine = synthesize_audio("APEX frozen speech worker smoke.", tts_override="pyttsx3", voice_gender="female", cancellation_event=threading.Event())
    if engine != "pyttsx3" or not chunks or chunks[0].get("content_type") != "audio/wav":
        raise RuntimeError("frozen worker did not produce audio")
    audio = chunks[0]["audio"]
    if not isinstance(audio, bytes) or not audio.startswith(b"RIFF") or b"WAVE" not in audio[:16]:
        raise RuntimeError("frozen worker output was not a valid WAV file")
    return {"worker_engine": engine, "wav_bytes": len(audio)}


def _no_model_assets() -> dict[str, object]:
    import fastembed  # noqa: F401
    from core.retrieval.embedding import EmbeddingError, FastEmbedAdapter
    from core.runtime_paths import get_runtime_paths
    try:
        FastEmbedAdapter(get_runtime_paths().fastembed_cache_dir).prepare(allow_download=False)
    except EmbeddingError as exc:
        return {"package": "loaded", "model_status": exc.args[0] if exc.args else "unavailable"}
    return {"package": "loaded", "model_status": "available"}


def _semantic_assets() -> dict[str, object]:
    from core.retrieval.docs import search_documentation
    from core.retrieval.embedding import FastEmbedAdapter
    from core.retrieval.service import RetrievalService
    from core.retrieval.store import RetrievalStore
    from core.runtime_paths import get_runtime_paths
    paths = get_runtime_paths()
    adapter = FastEmbedAdapter(paths.fastembed_cache_dir)
    service = RetrievalService(RetrievalStore(paths.data_root / "smoke-retrieval-semantic.db"), adapter=adapter, enabled=True)
    service.initialize()
    # Index the documentation through the production sync/search path before
    # preparing embeddings; an empty store correctly reports fts_only.
    initial = search_documentation("APEX local first workspace", service)
    if initial.get("retrieval_mode") != "fts_only" or not initial.get("results"):
        raise RuntimeError("production documentation sync did not return initial FTS results")
    status = service.prepare(allow_download=False)
    if status.mode != "semantic":
        raise RuntimeError(f"FastEmbed model assets did not enable semantic retrieval: {status.error_category or status.mode}")
    result = search_documentation("APEX local first workspace", service)
    if result.get("retrieval_mode") != "semantic" or not result.get("results"):
        raise RuntimeError("FastEmbed-backed production documentation search returned no results")
    semantic_results = len(result["results"])

    return {"retrieval_mode": "semantic", "semantic_results": semantic_results}


def _kokoro_assets() -> dict[str, object]:
    import core.speaker as speaker
    model_path, voices_path = speaker._kokoro_paths()
    assets = {
        "model_path": str(model_path),
        "model_exists": model_path.is_file(),
        "model_bytes": model_path.stat().st_size if model_path.is_file() else 0,
        "voices_path": str(voices_path),
        "voices_exists": voices_path.is_file(),
        "voices_bytes": voices_path.stat().st_size if voices_path.is_file() else 0,
    }
    logger = logging.getLogger("core.speaker")
    previous_level = logger.level
    previous_propagate = logger.propagate
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        chunks, engine = speaker.synthesize_audio("APEX frozen speech smoke.", tts_override="kokoro", voice_gender="female", cancellation_event=threading.Event())
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        handler.close()
    if engine != "kokoro" or not chunks or chunks[0].get("content_type") != "audio/wav":
        ram_percent, cpu_percent = speaker._kokoro_pressure_snapshot()
        raise RuntimeError(
            "Kokoro did not produce real WAV output; "
            f"returned_engine={engine}; readiness={speaker.readiness_snapshot()}; "
            f"pressure_snapshot={{'ram_percent': {ram_percent}, 'cpu_percent': {cpu_percent}}}"
        )
    audio = chunks[0]["audio"]
    if not isinstance(audio, bytes) or not audio.startswith(b"RIFF") or b"WAVE" not in audio[:16]:
        raise RuntimeError("Kokoro result was not a valid WAV file")
    return {"kokoro_assets": assets, "kokoro_engine": engine, "wav_bytes": len(audio)}


def _lifecycle() -> dict[str, object]:
    faulthandler.dump_traceback_later(15, repeat=True, file=sys.stderr)
    try:
        return _run_lifecycle()
    finally:
        faulthandler.cancel_dump_traceback_later()


def _run_lifecycle() -> dict[str, object]:
    from core.api.app import _app_lifespan, app

    phase = {"name": "before_startup"}

    def task_snapshot() -> list[dict[str, object]]:
        current = asyncio.current_task()
        snapshot = []
        for task in asyncio.all_tasks():
            if task is current:
                continue
            coroutine = task.get_coro()
            stack = task.get_stack(limit=6)
            snapshot.append({
                "name": task.get_name(),
                "done": task.done(),
                "coroutine": getattr(coroutine, "__qualname__", type(coroutine).__name__),
                "stack": [
                    {"function": frame.f_code.co_name, "file": frame.f_code.co_filename, "line": frame.f_lineno}
                    for frame in stack
                ],
            })
        return sorted(snapshot, key=lambda item: str(item["name"]))

    async def monitor_tasks() -> None:
        while True:
            await asyncio.sleep(5)
            print(
                "APEX_LIFECYCLE_DIAG " + json.dumps({"phase": phase["name"], "tasks": task_snapshot()}, ensure_ascii=True, separators=(",", ":")),
                file=sys.stderr,
                flush=True,
            )

    async def run() -> dict[str, object]:
        monitor = asyncio.create_task(monitor_tasks(), name="bundle-lifecycle-task-monitor")
        lifecycle = _app_lifespan(app)
        try:
            await lifecycle.__aenter__()
            phase["name"] = "lifespan_running"
            startup_tasks = task_snapshot()
            await asyncio.sleep(5)
            phase["name"] = "lifespan_shutdown"
            await lifecycle.__aexit__(None, None, None)
            return {"status": "started_and_stopped", "tasks_after_startup": startup_tasks, "tasks_after_shutdown": task_snapshot()}
        finally:
            phase["name"] = "monitor_cleanup"
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass

    return asyncio.run(run())


def _managed_host_diagnostic() -> int:
    """Run the real managed host while collecting private startup diagnostics.

    This entry point intentionally speaks the production v1 control protocol
    on stdin/stdout. Diagnostic output is limited to stderr.
    """
    faulthandler.dump_traceback_later(15, repeat=True, file=sys.stderr)
    host = None
    original_serve = None
    original_http_json = None
    try:
        import core.backend_host as host

        original_serve = host._serve
        original_http_json = host._http_json

        def diagnostic_http_json(url: str, *, timeout: float = 0.5):
            started = time.monotonic()
            value = original_http_json(url, timeout=timeout)
            path = urlsplit(url).path
            if value is None:
                outcome = "no_json"
            elif path.endswith("/health/ready"):
                outcome = str(value.get("status", "json"))
            else:
                outcome = "identity_json" if {"app_id", "build_id", "pid"}.issubset(value) else "json"
            print(
                "APEX_MANAGED_HOST_DIAG " + json.dumps({
                    "kind": "http_self_probe",
                    "path": path,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    "timeout_seconds": timeout,
                    "outcome": outcome,
                }, ensure_ascii=True, separators=(",", ":")),
                file=sys.stderr,
                flush=True,
            )
            return value

        async def diagnostic_serve(*args, **kwargs):
            phase = {"name": "production_serve_running"}
            serve_started = time.monotonic()

            def task_snapshot() -> list[dict[str, object]]:
                current = asyncio.current_task()
                snapshot = []
                for task in asyncio.all_tasks():
                    if task is current or task.get_name() == "bundle-managed-host-task-observer":
                        continue
                    coroutine = task.get_coro()
                    snapshot.append({
                        "name": task.get_name(),
                        "done": task.done(),
                        "coroutine": getattr(coroutine, "__qualname__", type(coroutine).__name__),
                        "stack": [
                            {"function": frame.f_code.co_name, "file": frame.f_code.co_filename, "line": frame.f_lineno}
                            for frame in task.get_stack(limit=6)
                        ],
                    })
                return sorted(snapshot, key=lambda item: str(item["name"]))

            async def observe_tasks() -> None:
                while True:
                    await asyncio.sleep(5)
                    print(
                        "APEX_MANAGED_HOST_TASKS " + json.dumps({
                            "phase": phase["name"],
                            "elapsed_seconds": round(time.monotonic() - serve_started, 1),
                            "tasks": task_snapshot(),
                        }, ensure_ascii=True, separators=(",", ":")),
                        file=sys.stderr,
                        flush=True,
                    )

            print("APEX_MANAGED_HOST_DIAG {\"kind\":\"serve_enter\"}", file=sys.stderr, flush=True)
            observer = asyncio.create_task(observe_tasks(), name="bundle-managed-host-task-observer")
            try:
                result = await original_serve(*args, **kwargs)
                phase["name"] = "production_serve_returned"
                print(
                    "APEX_MANAGED_HOST_DIAG " + json.dumps({
                        "kind": "serve_return", "elapsed_seconds": round(time.monotonic() - serve_started, 1),
                        "exit_code": result,
                    }, separators=(",", ":")),
                    file=sys.stderr,
                    flush=True,
                )
                return result
            except BaseException as exc:
                phase["name"] = "production_serve_raised"
                print(
                    "APEX_MANAGED_HOST_DIAG " + json.dumps({
                        "kind": "serve_exception", "elapsed_seconds": round(time.monotonic() - serve_started, 1),
                        "error_type": type(exc).__name__,
                    }, separators=(",", ":")),
                    file=sys.stderr,
                    flush=True,
                )
                raise
            finally:
                observer.cancel()
                try:
                    await observer
                except asyncio.CancelledError:
                    pass

        host._serve = diagnostic_serve
        host._http_json = diagnostic_http_json
        # This invokes the exact production managed-host entry point. The host
        # owns protocol stdout redirection and will preserve its control frames.
        return host.main(["serve", "--managed"])
    finally:
        if host is not None:
            if original_serve is not None:
                host._serve = original_serve
            if original_http_json is not None:
                host._http_json = original_http_json
        faulthandler.cancel_dump_traceback_later()


def _write_json_line(payload: dict[str, object], stream: object = None) -> None:
    print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), file=stream if stream is not None else sys.stdout)


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] == "--run-suite":
        suite_args = values[1:]
        if "--probe" not in suite_args:
            if not getattr(sys, "frozen", False):
                print("Source controller mode requires an explicit frozen --probe executable.", file=sys.stderr)
                return 2
            suite_args.extend(("--probe", sys.executable))
        return _run_smoke_suite(suite_args)
    with redirect_stdout(sys.stderr):
        worker = _worker_dispatch(values)
    if worker is not None:
        return worker
    parser = argparse.ArgumentParser(description="Constrained frozen APEX packaging checks.")
    parser.add_argument("scenario", choices=("imports", "retrieval", "audio-worker", "no-model-assets", "semantic-assets", "kokoro-assets", "lifecycle", "managed-host-diagnostic"))
    args = parser.parse_args(values)
    if args.scenario == "managed-host-diagnostic":
        return _managed_host_diagnostic()
    try:
        with redirect_stdout(sys.stderr):
            evidence = {"imports": _imports, "retrieval": _retrieval, "audio-worker": _audio_worker, "no-model-assets": _no_model_assets, "semantic-assets": _semantic_assets, "kokoro-assets": _kokoro_assets, "lifecycle": _lifecycle}[args.scenario]()
        _write_json_line({"schema_version": 1, "scenario": args.scenario, "status": "passed", "evidence": evidence})
        return 0
    except Exception as exc:
        _write_json_line({"schema_version": 1, "scenario": args.scenario, "status": "failed", "error_type": type(exc).__name__, "error": str(exc)[:4096]})
        return 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
