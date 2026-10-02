"""Shared, explicit PyInstaller collection inputs for APEX executables."""

from __future__ import annotations

from pathlib import Path


_RESOURCE_FILES = (
    Path("config.json"),
    Path("build-info.json"),
    Path("README.md"),
    Path("core/mock/assistant.json"),
    Path("core/mock/telemetry.json"),
)

_HIDDEN_IMPORTS = (
    "apex.cli",
    "core.api.app",
    "core.runtime_paths",
    "core.host.worker_dispatch",
    "core.speaker_export",
    "fastembed",
    "google.api_core",
    "google.auth.transport.requests",
    "google.protobuf",
    "google.oauth2.credentials",
    "google_auth_oauthlib.flow",
    "googleapiclient.discovery_cache",
    "googleapiclient.discovery",
    "grpc",
    "numpy",
    "onnxruntime",
    "opentelemetry",
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "opentelemetry.sdk",
    "pygame",
    "pyttsx3",
    "pyttsx3.drivers.sapi5",
    "pythoncom",
    "tzdata",
    "win32com.client",
    "comtypes",
    "comtypes.client",
    "certifi",
    "fastmcp",
    "google.cloud.texttospeech",
    "kokoro_onnx",
    "phonemizer",
    "espeakng_loader",
)


def bundle_datas(resource_root: Path) -> list[tuple[str, str]]:
    """Return only the approved resource files, rooted at their runtime paths."""
    root = resource_root.resolve()
    candidates = list(_RESOURCE_FILES)
    docs = root / "docs"
    if docs.is_dir():
        candidates.extend(
            path.relative_to(root)
            for path in docs.rglob("*.md")
            if path.is_file()
        )
    result: list[tuple[str, str]] = []
    for relative in sorted(set(candidates), key=lambda item: item.as_posix()):
        source = root / relative
        if not source.is_file():
            raise FileNotFoundError(f"Missing required bundle resource: {relative.as_posix()}")
        resolved = source.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"Bundle resource escapes its root: {relative.as_posix()}")
        result.append((str(resolved), relative.parent.as_posix() if relative.parent != Path(".") else "."))
    if not any(destination == "docs" or destination.startswith("docs/") for _source, destination in result):
        raise FileNotFoundError("No retrieval documentation was found under docs/.")
    return result


def bundle_hidden_imports() -> list[str]:
    """Return explicit imports used by deferred runtime and optional features."""
    return list(_HIDDEN_IMPORTS)
