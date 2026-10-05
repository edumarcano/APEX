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
    "core.data_import.cli",
    "core.data_import.engine",
    "core.data_import.guard",
    "core.persistence_validation",
    "core.runtime_paths",
    "core.actions.models",
    "core.actions.runtime",
    "core.actions.service",
    "core.actions.store",
    "core.activity.models",
    "core.activity.service",
    "core.activity.store",
    "core.briefings.service",
    "core.briefings.store",
    "core.conversations.service",
    "core.conversations.store",
    "core.knowledge.service",
    "core.knowledge.store",
    "core.retrieval.models",
    "core.retrieval.service",
    "core.retrieval.store",
    "core.runs.coordinator",
    "core.runs.models",
    "core.runs.service",
    "core.runs.store",
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

_ANALYSIS_EXCLUDES = (
    "numpy.f2py",
    "numpy._pyinstaller",
    "pygame.__pyinstaller",
    "setuptools",
)


def bundle_analysis_excludes() -> list[str]:
    """Return exact package roots that are build tools, not runtime features."""
    return list(_ANALYSIS_EXCLUDES)


def is_onnxruntime_example_data_path(value: str | Path) -> bool:
    """Identify only ONNX Runtime's packaged example dataset subtree."""
    parts = str(value).replace("\\", "/").casefold().split("/")
    return any(
        parts[index : index + 2] == ["onnxruntime", "datasets"]
        for index in range(len(parts) - 1)
    )


def is_bundle_excluded_data_path(value: str | Path) -> bool:
    """Identify known collected-package data not used by APEX at runtime."""
    parts = str(value).replace("\\", "/").casefold().split("/")
    excluded_subtrees = (
        ["numpy", "_pyinstaller"],
        ["numpy", "f2py"],
        ["pygame", "__pyinstaller"],
        ["onnxruntime", "datasets"],
    )
    return any(
        parts[index : index + 2] == subtree
        for subtree in excluded_subtrees
        for index in range(len(parts) - 1)
    )


def include_runtime_submodule(name: str) -> bool:
    """Keep runtime modules while excluding package hooks and NumPy's compiler."""
    normalized = name.casefold()
    parts = normalized.split(".")
    if any(
        part in {"test", "tests", "testing", "_pyinstaller", "__pyinstaller"}
        for part in parts
    ):
        return False
    if (
        normalized == "numpy._pytesttester"
        or normalized == "numpy.f2py"
        or normalized.startswith("numpy.f2py.")
    ):
        return False
    return True


def include_onnxruntime_submodule(name: str) -> bool:
    """Keep runtime modules while excluding ONNX Runtime example datasets."""
    normalized = name.casefold()
    return (
        include_runtime_submodule(name)
        and normalized != "onnxruntime.datasets"
        and not normalized.startswith("onnxruntime.datasets.")
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
