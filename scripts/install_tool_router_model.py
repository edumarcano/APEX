#!/usr/bin/env python3
"""Explicit installer for the APEX tool-routing ONNX encoder."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from huggingface_hub import hf_hub_download

from core.agent.routing.model_manifest import (
    CANDIDATE_MODEL_SPECS,
    PRODUCTION_MODEL_KEY,
    EmbeddingModelSpec,
    ModelArtifact,
    get_model_spec,
)
from core.agent.routing.model_store import (
    artifact_path,
    model_install_dir,
    sha256_file,
    verify_installed_model,
)


def _download_file(
    spec: EmbeddingModelSpec,
    artifact: ModelArtifact,
    *,
    verify_only: bool,
) -> bool:
    target = artifact_path(spec, artifact)
    if verify_only:
        if not target.is_file():
            print(f"Missing {artifact.relative_path}")
            return False
        if artifact.byte_size and target.stat().st_size != artifact.byte_size:
            print(f"Size mismatch for {artifact.relative_path}")
            return False
        digest = sha256_file(target)
        if artifact.sha256 and digest != artifact.sha256:
            print(f"Checksum mismatch for {artifact.relative_path}")
            return False
        return True

    target.parent.mkdir(parents=True, exist_ok=True)
    install_dir = model_install_dir(spec)
    install_dir.mkdir(parents=True, exist_ok=True)
    downloaded = hf_hub_download(
        repo_id=spec.repository,
        filename=artifact.relative_path.replace("\\", "/"),
        revision=spec.revision,
        local_dir=str(install_dir),
        local_dir_use_symlinks=False,
    )
    temp_path = Path(downloaded)
    if artifact.byte_size and temp_path.stat().st_size != artifact.byte_size:
        temp_path.unlink(missing_ok=True)
        print(f"Downloaded size mismatch for {artifact.relative_path}")
        return False
    digest = sha256_file(temp_path)
    if artifact.sha256 and digest != artifact.sha256:
        temp_path.unlink(missing_ok=True)
        print(f"Checksum mismatch for {artifact.relative_path}")
        return False
    if temp_path != target and temp_path.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        temp_path.replace(target)
    return True


def install_model(spec: EmbeddingModelSpec, *, verify_only: bool = False) -> int:
    print(
        f"Model: {spec.key}\n"
        f"Source: {spec.repository}@{spec.revision}\n"
        f"License: {spec.license_id}\n"
        f"Bytes: {spec.total_bytes}\n"
        f"Target: tool-routing/{spec.key}/{spec.revision}/"
    )
    ok = True
    for artifact in spec.files:
        if not _download_file(spec, artifact, verify_only=verify_only):
            ok = False
    if not ok:
        return 1
    verified, reason = verify_installed_model(spec)
    if not verified:
        print(f"Verification failed: {reason}")
        return 1
    print("Verification succeeded.")
    return 0


def remove_model(spec: EmbeddingModelSpec) -> int:
    install_dir = model_install_dir(spec)
    if install_dir.exists():
        for path in sorted(install_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        install_dir.rmdir()
    print(f"Removed model artifacts for {spec.key}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install APEX tool-routing ONNX models.")
    parser.add_argument(
        "--model",
        default=PRODUCTION_MODEL_KEY,
        choices=sorted(CANDIDATE_MODEL_SPECS),
    )
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args(argv)
    spec = get_model_spec(args.model)
    if spec is None:
        print(f"Unknown model: {args.model}")
        return 1
    if args.remove:
        return remove_model(spec)
    return install_model(spec, verify_only=args.verify_only)


if __name__ == "__main__":
    raise SystemExit(main())
