"""Build an isolated, locally-provenanced 2.0.0 installer for upgrade smoke tests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "31fdd21757a1822ac0223956c20595ff5a13d307"
FIXTURE_VERSION = "2.0.0"
INSTALLER_RELATIVE_PATHS = (
    "frontend/scripts/build-desktop.mjs",
    "frontend/scripts/prepare-desktop.mjs",
    "frontend/src-tauri/nsis",
    "frontend/src-tauri/tauri.conf.json",
    "frontend/package.json",
    "rust-toolchain.toml",
)
REQUIRED_NSIS_FILES = {
    "frontend/src-tauri/nsis/installer.nsi",
    "frontend/src-tauri/nsis/installer.nsi.upstream",
    "frontend/src-tauri/nsis/PROVENANCE.md",
}
MANIFEST_NAME = "distribution-manifest.json"


class FixtureBuildError(RuntimeError):
    """A missing or unsafe input prevented fixture construction."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: float = 3600,
    stream: bool = False,
) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=not stream,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise FixtureBuildError(f"Required command is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or f"exit code {exc.returncode}").strip()
        raise FixtureBuildError(
            f"Command failed ({Path(command[0]).name}): {detail[-3000:]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FixtureBuildError(f"Command timed out: {Path(command[0]).name}.") from exc
    return (result.stdout or "").strip()


def _tracked_overlay_files(source_root: Path) -> list[str]:
    raw = _run(
        ["git", "ls-files", "-z", "--", *INSTALLER_RELATIVE_PATHS],
        cwd=source_root,
    )
    tracked = sorted(item for item in raw.split("\0") if item)
    if not REQUIRED_NSIS_FILES.issubset(tracked):
        missing = sorted(REQUIRED_NSIS_FILES.difference(tracked))
        raise FixtureBuildError("Installer provenance inputs are missing: " + ", ".join(missing))
    for relative in INSTALLER_RELATIVE_PATHS:
        if relative not in tracked and not any(item.startswith(relative.rstrip("/") + "/") for item in tracked):
            raise FixtureBuildError(f"Installer overlay path is not tracked: {relative}")
    for relative in tracked:
        source = source_root / Path(relative)
        if source.is_symlink() or not source.is_file():
            raise FixtureBuildError(f"Installer overlay is not a regular file: {relative}")
    return tracked


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureBuildError(f"Could not read JSON input: {path.name}") from exc
    if not isinstance(value, dict):
        raise FixtureBuildError(f"Expected an object in {path.name}.")
    return value


def _assert_baseline_versions(checkout: Path) -> None:
    try:
        project = tomllib.loads((checkout / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        cargo = tomllib.loads((checkout / "frontend/src-tauri/Cargo.toml").read_text(encoding="utf-8"))["package"]
        lock = tomllib.loads((checkout / "frontend/src-tauri/Cargo.lock").read_text(encoding="utf-8"))
        tauri = _read_json(checkout / "frontend/src-tauri/tauri.conf.json")
        uv_lock = tomllib.loads((checkout / "uv.lock").read_text(encoding="utf-8"))
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise FixtureBuildError("The selected baseline does not contain the locked 2.0.0 project metadata.") from exc

    cargo_lock_versions = {
        package.get("version")
        for package in lock.get("package", [])
        if package.get("name") == "apex-desktop"
    }
    uv_lock_versions = {
        package.get("version")
        for package in uv_lock.get("package", [])
        if package.get("name") == "apex"
    }
    if (
        str(project.get("version")) != FIXTURE_VERSION
        or str(cargo.get("version")) != FIXTURE_VERSION
        or cargo_lock_versions != {FIXTURE_VERSION}
        or uv_lock_versions != {FIXTURE_VERSION}
        or tauri.get("version") != FIXTURE_VERSION
    ):
        raise FixtureBuildError(
            "The fixture baseline must retain the committed 2.0.0 Python, Rust, and Tauri versions."
        )


def _apply_overlay(source_root: Path, checkout: Path, tracked: list[str]) -> list[str]:
    """Copy only installer wiring and merge installer settings into baseline configs."""
    for relative in tracked:
        if relative in {"frontend/src-tauri/tauri.conf.json", "frontend/package.json"}:
            continue
        source = source_root / Path(relative)
        target = checkout / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    baseline_tauri_path = checkout / "frontend/src-tauri/tauri.conf.json"
    installer_tauri = _read_json(source_root / "frontend/src-tauri/tauri.conf.json")
    baseline_tauri = _read_json(baseline_tauri_path)
    windows_bundle = installer_tauri.get("bundle", {}).get("windows")
    if not isinstance(windows_bundle, dict) or not windows_bundle:
        raise FixtureBuildError(
            "The current Tauri configuration is missing bundle.windows installer settings."
        )
    baseline_tauri.setdefault("bundle", {})["windows"] = windows_bundle
    # Preserve every baseline setting, including its 2.0.0 version and security policy.
    _write_json(baseline_tauri_path, baseline_tauri)

    baseline_package_path = checkout / "frontend/package.json"
    installer_package = _read_json(source_root / "frontend/package.json")
    baseline_package = _read_json(baseline_package_path)
    package_script = installer_package.get("scripts", {}).get("desktop:package")
    if not isinstance(package_script, str) or not package_script.strip():
        raise FixtureBuildError("The current package manifest is missing desktop:package wiring.")
    baseline_package.setdefault("scripts", {})["desktop:package"] = package_script
    _write_json(baseline_package_path, baseline_package)

    _assert_baseline_versions(checkout)
    return sorted(tracked)


def _overlay_digest(checkout: Path, tracked: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(set(tracked)):
        path_bytes = relative.replace("\\", "/").encode("utf-8")
        file_bytes = (checkout / Path(relative)).read_bytes()
        digest.update(len(path_bytes).to_bytes(4, "big"))
        digest.update(path_bytes)
        digest.update(len(file_bytes).to_bytes(8, "big"))
        digest.update(file_bytes)
    return digest.hexdigest()


def _validate_external_output(output: Path, repository: Path) -> Path:
    if output.is_symlink():
        raise FixtureBuildError("Fixture output must not be a symbolic link.")
    resolved = output.resolve()
    repo = repository.resolve()
    if resolved == repo or resolved.is_relative_to(repo) or repo.is_relative_to(resolved):
        raise FixtureBuildError("Fixture outputs must stay outside the production checkout.")
    if resolved.exists() and (resolved.is_symlink() or not resolved.is_dir()):
        raise FixtureBuildError("Fixture output must be a real directory.")
    if resolved.exists() and any(resolved.iterdir()):
        raise FixtureBuildError("Fixture output directory must be empty.")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _fixture_sidecar(
    *,
    base_commit: str,
    fixture_commit: str,
    overlay_sha256: str,
    backend_build_id: str,
    installer_name: str,
    installer_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "synthetic_upgrade_fixture",
        "base_commit": base_commit,
        "fixture_commit": fixture_commit,
        "overlay_sha256": overlay_sha256,
        "app_version": FIXTURE_VERSION,
        "backend_build_id": backend_build_id,
        "installer_name": installer_name,
        "installer_sha256": installer_sha256,
    }


def _validate_manifest(
    manifest_path: Path,
    installer_root: Path,
    fixture_commit: str,
    backend_build_id: str,
) -> tuple[Path, dict[str, Any]]:
    manifest = _read_json(manifest_path)
    installer_name = manifest.get("installer")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("product") != "APEX"
        or manifest.get("version") != FIXTURE_VERSION
        or manifest.get("target") != "x86_64-pc-windows-msvc"
        or manifest.get("source_commit") != fixture_commit
        or manifest.get("backend_build_id") != backend_build_id
        or not isinstance(installer_name, str)
        or Path(installer_name).name != installer_name
        or not installer_name.lower().endswith("-setup.exe")
    ):
        raise FixtureBuildError("The 2.0.0 installer manifest does not match its committed fixture build.")
    installer = installer_root / installer_name
    if installer.is_symlink() or not installer.is_file():
        raise FixtureBuildError("The installer named by the 2.0.0 distribution manifest is missing.")
    if manifest.get("installer_sha256") != _sha256(installer):
        raise FixtureBuildError("The 2.0.0 installer checksum does not match its manifest.")
    return installer, manifest


def build_fixture(*, base_ref: str, output: Path) -> dict[str, Any]:
    if base_ref != BASELINE_COMMIT:
        raise FixtureBuildError(f"The synthetic upgrade fixture must use baseline {BASELINE_COMMIT}.")
    output = _validate_external_output(output, ROOT)
    if _run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT):
        raise FixtureBuildError("Fixture source must be a clean committed checkout.")
    _run(["git", "cat-file", "-e", f"{base_ref}^{{commit}}"], cwd=ROOT)
    tracked = _tracked_overlay_files(ROOT)

    with tempfile.TemporaryDirectory(prefix="apex-distribution-fixture-", dir=output.parent) as temporary:
        worktree = Path(temporary) / "source"
        try:
            _run(["git", "worktree", "add", "--detach", str(worktree), base_ref], cwd=ROOT)
            _assert_baseline_versions(worktree)
            overlay_paths = _apply_overlay(ROOT, worktree, tracked)
            overlay_sha256 = _overlay_digest(worktree, overlay_paths)
            _run(["git", "add", "--", *overlay_paths], cwd=worktree)
            _run(
                [
                    "git", "-c", "user.name=APEX Distribution CI",
                    "-c", "user.email=apex-distribution-ci@localhost",
                    "commit", "--message", "ci: prepare synthetic 2.0.0 installer fixture",
                ],
                cwd=worktree,
            )
            fixture_commit = _run(["git", "rev-parse", "HEAD"], cwd=worktree)
            if len(fixture_commit) != 40 or _run(
                ["git", "status", "--porcelain", "--untracked-files=all"], cwd=worktree
            ):
                raise FixtureBuildError("The committed 2.0.0 fixture worktree is not clean.")

            _run(
                [
                    "uv", "run", "--locked", "--all-extras", "--python", "3.14.7",
                    "python", "scripts/build_backend_bundle.py",
                ],
                cwd=worktree,
                timeout=3600,
                stream=True,
            )
            build_info = _read_json(worktree / "dist/backend-bundle/_internal/build-info.json")
            backend_build_id = build_info.get("build_id")
            if not isinstance(backend_build_id, str) or not backend_build_id:
                raise FixtureBuildError("The baseline backend bundle has no build identifier.")

            _run(["npm", "ci"], cwd=worktree / "frontend", timeout=1800, stream=True)
            _run(["npm", "run", "desktop:package"], cwd=worktree / "frontend", timeout=3600, stream=True)
            installer_root = worktree / "build/desktop-shell/installers"
            installer, manifest = _validate_manifest(
                installer_root / MANIFEST_NAME,
                installer_root,
                fixture_commit,
                backend_build_id,
            )

            staged_output = Path(temporary) / "result"
            staged_output.mkdir()
            output_installer = staged_output / installer.name
            shutil.copyfile(installer, output_installer)
            sidecar = _fixture_sidecar(
                base_commit=base_ref,
                fixture_commit=fixture_commit,
                overlay_sha256=overlay_sha256,
                backend_build_id=backend_build_id,
                installer_name=installer.name,
                installer_sha256=_sha256(output_installer),
            )
            if sidecar["installer_sha256"] != manifest["installer_sha256"]:
                raise FixtureBuildError("Copied fixture installer checksum differs from its build manifest.")
            _write_json(Path(f"{output_installer}.fixture.json"), sidecar)
            if any(output.iterdir()):
                raise FixtureBuildError("Fixture output changed while the upgrade installer was being built.")
            output.rmdir()
            staged_output.rename(output)
            result = {"schema_version": 1, "status": "passed", **sidecar}
            return result
        finally:
            if worktree.is_dir() and (worktree / ".git").is_file():
                _run(["git", "worktree", "remove", "--force", str(worktree)], cwd=ROOT, timeout=120)


def _emit_report(path: Path | None, report: dict[str, Any]) -> None:
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(encoded, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True, help="The approved 2.0.0 baseline commit.")
    parser.add_argument("--output", type=Path, required=True, help="An empty directory outside the repository checkout.")
    parser.add_argument("--report", type=Path, help="Optional JSON report path outside the installer output.")
    args = parser.parse_args(argv)
    try:
        result = build_fixture(base_ref=args.base_ref, output=args.output)
    except (FixtureBuildError, OSError, RuntimeError, ValueError) as exc:
        report = {"schema_version": 1, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        _emit_report(args.report, report)
        print("Synthetic distribution fixture build failed.", file=sys.stderr)
        return 2
    _emit_report(args.report, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
