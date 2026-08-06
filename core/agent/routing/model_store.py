"""Per-user model storage for the tool-routing encoder."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from core.agent.routing.model_manifest import EmbeddingModelSpec, ModelArtifact


def resolve_model_dir() -> Path:
    override = os.getenv("APEX_TOOL_ROUTER_MODEL_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        return Path(base) / "APEX" / "models" / "tool-routing"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "APEX"
            / "models"
            / "tool-routing"
        )
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg) / "apex" / "models" / "tool-routing"
    return Path.home() / ".local" / "share" / "apex" / "models" / "tool-routing"


def model_install_dir(spec: EmbeddingModelSpec) -> Path:
    return resolve_model_dir() / spec.key / spec.revision


def artifact_path(spec: EmbeddingModelSpec, artifact: ModelArtifact) -> Path:
    return model_install_dir(spec) / artifact.relative_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_installed_model(spec: EmbeddingModelSpec) -> tuple[bool, str | None]:
    install_dir = model_install_dir(spec)
    if not install_dir.is_dir():
        return False, "not_installed"
    for artifact in spec.files:
        target = artifact_path(spec, artifact)
        if not target.is_file():
            return False, "verification_failed"
        if artifact.byte_size and target.stat().st_size != artifact.byte_size:
            return False, "verification_failed"
        if artifact.sha256 and sha256_file(target) != artifact.sha256:
            return False, "verification_failed"
    return True, None


def is_model_installed(spec: EmbeddingModelSpec) -> bool:
    verified, _ = verify_installed_model(spec)
    return verified
