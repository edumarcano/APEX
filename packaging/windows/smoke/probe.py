"""Build-only frozen smoke probe; never included in the production distribution."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
import threading
import traceback
from contextlib import redirect_stdout
from pathlib import Path

multiprocessing.freeze_support()

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


def _optional_assets() -> dict[str, object]:
    from core.retrieval.docs import search_documentation
    from core.retrieval.embedding import FastEmbedAdapter
    from core.retrieval.service import RetrievalService
    from core.retrieval.store import RetrievalStore
    from core.runtime_paths import get_runtime_paths
    import core.speaker as speaker
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
    model_path, voices_path = speaker._kokoro_paths()
    assets = {
        "model_path": str(model_path),
        "model_exists": model_path.is_file(),
        "model_bytes": model_path.stat().st_size if model_path.is_file() else 0,
        "voices_path": str(voices_path),
        "voices_exists": voices_path.is_file(),
        "voices_bytes": voices_path.stat().st_size if voices_path.is_file() else 0,
    }
    try:
        speaker._get_kokoro_client()
    except Exception as exc:
        diagnostic = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-2048:]
        raise RuntimeError(
            f"Kokoro client initialization failed; paths={assets}; "
            f"{type(exc).__name__}: {exc}; traceback={diagnostic}"
        ) from exc
    chunks, engine = speaker.synthesize_audio("APEX frozen speech smoke.", tts_override="kokoro", voice_gender="female", cancellation_event=threading.Event())
    if engine != "kokoro" or not chunks or chunks[0].get("content_type") != "audio/wav":
        raise RuntimeError("Kokoro did not produce real WAV output")
    audio = chunks[0]["audio"]
    if not isinstance(audio, bytes) or not audio.startswith(b"RIFF") or b"WAVE" not in audio[:16]:
        raise RuntimeError("Kokoro result was not a valid WAV file")
    return {"retrieval_mode": "semantic", "semantic_results": semantic_results, "kokoro_assets": assets, "kokoro_engine": engine, "wav_bytes": len(audio)}


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
    parser.add_argument("scenario", choices=("imports", "retrieval", "audio-worker", "no-model-assets", "optional-assets"))
    args = parser.parse_args(values)
    try:
        with redirect_stdout(sys.stderr):
            evidence = {"imports": _imports, "retrieval": _retrieval, "audio-worker": _audio_worker, "no-model-assets": _no_model_assets, "optional-assets": _optional_assets}[args.scenario]()
        print(json.dumps({"schema_version": 1, "scenario": args.scenario, "status": "passed", "evidence": evidence}, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"schema_version": 1, "scenario": args.scenario, "status": "failed", "error_type": type(exc).__name__, "error": str(exc)[:512]}, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
