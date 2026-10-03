"""Build the Windows x64 one-folder backend bundle from the locked project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN_PATH = ROOT / "packaging" / "windows" / "toolchain.json"
BUILD_ROOT = ROOT / "build" / "backend-bundle"
RESOURCE_STAGE = BUILD_ROOT / "staging" / "resources"
NOTICE_STAGE = BUILD_ROOT / "staging" / "notices"
BUILD_ENV = BUILD_ROOT / "env"
PRODUCTION_DIST = ROOT / "dist" / "backend-bundle"
SPEC = ROOT / "packaging" / "windows" / "backend-bundle.spec"


class BundleBuildError(RuntimeError):
    """A missing or invalid bundle build input."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_toolchain() -> dict[str, Any]:
    try:
        value = json.loads(TOOLCHAIN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleBuildError(f"Cannot read bundle toolchain: {TOOLCHAIN_PATH.name}") from exc
    expected = {
        "architecture": "AMD64",
        "python_version": "3.14.7",
        "uv_version": "0.12.3",
        "pyinstaller_version": "6.22.3",
        "hooks_contrib_version": "2026.8",
        "extras": ["tts-google", "tts-kokoro", "tracing"],
    }
    if value != expected:
        raise BundleBuildError("toolchain.json does not match the approved bundle toolchain.")
    if platform.machine().upper() not in {"AMD64", "X86_64"} or sys.maxsize <= 2**32:
        raise BundleBuildError("The backend bundle must be built on Windows x64 (AMD64).")
    if os.name != "nt":
        raise BundleBuildError("The backend bundle requires a Windows build host.")
    return value


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    timeout: float = 60,
) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise BundleBuildError(f"Required build command is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise BundleBuildError(
            f"Build command failed ({Path(command[0]).name}): {detail[-2000:]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BundleBuildError(f"Build command timed out: {Path(command[0]).name}.") from exc
    return result.stdout.strip()


def _assert_uv_version(toolchain: dict[str, Any]) -> None:
    actual = _run(["uv", "--version"]).split()
    if len(actual) < 2 or actual[1] != toolchain["uv_version"]:
        raise BundleBuildError(
            f"uv {toolchain['uv_version']} is required; found {' '.join(actual) or 'unknown'}."
        )


def _commit_provenance() -> tuple[str, int]:
    commit = _run(["git", "rev-parse", "HEAD"])
    timestamp = _run(["git", "show", "-s", "--format=%ct", "HEAD"])
    try:
        epoch = int(timestamp)
    except ValueError as exc:
        raise BundleBuildError("Could not read the source commit timestamp.") from exc
    return commit, epoch


def _tracked_paths(*prefixes: str) -> set[Path]:
    output = _run(["git", "ls-files", "-z", "--", *prefixes])
    return {ROOT / raw for raw in output.split("\0") if raw}


def _require_clean_tree() -> None:
    status = _run(["git", "status", "--porcelain", "--untracked-files=all"])
    if status:
        raise BundleBuildError(
            "Reproducible distribution builds require a clean committed worktree."
        )


def _input_digest() -> str:
    """Hash bundle-affecting inputs by stable repository-relative names."""
    paths = [
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        TOOLCHAIN_PATH,
        SPEC,
        ROOT / "scripts" / "build_backend_bundle.py",
        ROOT / "packaging" / "windows" / "collection.py",
        ROOT / "packaging" / "windows" / "backend_entry.py",
        ROOT / "packaging" / "windows" / "cli_entry.py",
        ROOT / "packaging" / "windows" / "rthook_comtypes.py",
        ROOT / "packaging" / "windows" / "rthook_espeak.py",
        ROOT / "config.json",
        ROOT / "README.md",
        ROOT / "core" / "mock" / "assistant.json",
        ROOT / "core" / "mock" / "telemetry.json",
    ]
    notices = ROOT / "packaging" / "windows" / "notices.py"
    if notices.is_file():
        paths.append(notices)
    tracked_code_and_docs = _tracked_paths("core", "clients", "src", "docs")
    paths.extend(path for path in tracked_code_and_docs if path.suffix == ".py")
    docs_root = ROOT / "docs"
    paths.extend(
        path for path in tracked_code_and_docs
        if path.suffix == ".md" and path.is_relative_to(docs_root)
    )
    paths.extend(_tracked_paths("packaging/windows/source-material"))
    probe = ROOT / "packaging" / "windows" / "smoke" / "probe.py"
    if probe in _tracked_paths("packaging/windows/smoke"):
        paths.append(probe)
    smoke_suite = ROOT / "scripts" / "smoke_backend_bundle.py"
    if smoke_suite in _tracked_paths("scripts/smoke_backend_bundle.py"):
        paths.append(smoke_suite)
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.relative_to(ROOT).as_posix()):
        if not path.is_file():
            raise BundleBuildError(f"Missing bundle input: {path.relative_to(ROOT).as_posix()}")
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content_hash = bytes.fromhex(_sha256(path))
        digest.update(content_hash)
    return digest.hexdigest()


def make_build_info(toolchain: dict[str, Any], commit: str, lock_digest: str) -> dict[str, Any]:
    input_digest = _input_digest()
    build_id = f"{commit[:12]}-{input_digest[:16]}"
    try:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        application_version = str(project["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise BundleBuildError("Could not read the APEX application version.") from exc
    return {
        "app_version": application_version,
        "architecture": toolchain["architecture"],
        "build_id": build_id,
        "commit": commit,
        "extras": sorted(toolchain["extras"]),
        "input_sha256": input_digest,
        "lock_sha256": lock_digest,
        "python_version": toolchain["python_version"],
        "pyinstaller_hooks_contrib_version": toolchain["hooks_contrib_version"],
        "pyinstaller_version": toolchain["pyinstaller_version"],
        "uv_version": toolchain["uv_version"],
    }


def _safe_remove(target: Path, allowed_parent: Path) -> None:
    parent = allowed_parent.resolve()
    resolved = target.resolve()
    if resolved == parent or not resolved.is_relative_to(parent):
        raise BundleBuildError(f"Refusing to remove an unexpected build path: {target.name}")
    if target.is_symlink():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def _copy_resources() -> None:
    _safe_remove(RESOURCE_STAGE, BUILD_ROOT)
    RESOURCE_STAGE.mkdir(parents=True, exist_ok=True)
    required = [
        ROOT / "config.json",
        ROOT / "README.md",
        ROOT / "core" / "mock" / "assistant.json",
        ROOT / "core" / "mock" / "telemetry.json",
    ]
    docs_root = ROOT / "docs"
    if not docs_root.is_dir():
        raise BundleBuildError("Missing docs/ retrieval resources.")
    tracked_markdown = [
        path for path in _tracked_paths("docs")
        if path.suffix == ".md" and path.is_file()
    ]
    markdown = sorted(
        tracked_markdown,
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    if not markdown:
        raise BundleBuildError("No Markdown retrieval resources exist under docs/.")
    tracked_resources = _tracked_paths("config.json", "README.md", "core/mock")
    for source in [*required, *markdown]:
        resolved = source.resolve()
        is_tracked_resource = source in tracked_resources or source in tracked_markdown
        if not resolved.is_relative_to(ROOT.resolve()) or not source.is_file() or not is_tracked_resource:
            raise BundleBuildError(f"Invalid or missing resource: {source.name}")
        destination = RESOURCE_STAGE / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _prepare_environment(toolchain: dict[str, Any]) -> Path:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(BUILD_ENV)
    env["UV_CACHE_DIR"] = str(BUILD_ROOT / "uv-cache")
    _run(
        [
            "uv", "sync", "--project", str(ROOT), "--locked", "--python",
            toolchain["python_version"], "--group", "bundle", "--all-extras",
            "--no-default-groups",
        ],
        env=env,
        timeout=1800,
    )
    python = BUILD_ENV / "Scripts" / "python.exe"
    if not python.is_file():
        raise BundleBuildError("uv did not create the isolated backend bundle environment.")
    pyinstaller = _run([str(python), "-m", "PyInstaller", "--version"])
    if pyinstaller != toolchain["pyinstaller_version"]:
        raise BundleBuildError(f"Expected PyInstaller {toolchain['pyinstaller_version']}; found {pyinstaller}.")
    hooks = _run([str(python), "-c", "import importlib.metadata; print(importlib.metadata.version('pyinstaller-hooks-contrib'))"])
    if hooks != toolchain["hooks_contrib_version"]:
        raise BundleBuildError(f"Expected hooks-contrib {toolchain['hooks_contrib_version']}; found {hooks}.")
    runtime = json.loads(
        _run([
            str(python), "-c",
            "import json,platform,struct,sys; print(json.dumps({'version': platform.python_version(), 'machine': platform.machine().upper(), 'bits': struct.calcsize('P') * 8}))",
        ])
    )
    if (
        runtime.get("version") != toolchain["python_version"]
        or runtime.get("machine") not in {"AMD64", "X86_64"}
        or runtime.get("bits") != 64
    ):
        raise BundleBuildError("The locked build environment is not Python 3.14.7 AMD64.")
    return python


def _stage_notices(environment_root: Path, python: Path) -> list[dict[str, str]]:
    module_path = ROOT / "packaging" / "windows" / "notices.py"
    if not module_path.is_file():
        raise BundleBuildError("Distribution notice inventory is not available.")
    _safe_remove(NOTICE_STAGE, BUILD_ROOT)
    code = (
        "import importlib.util,json,sys; "
        "module_path,environment_root,output_dir=sys.argv[1:4]; "
        "spec=importlib.util.spec_from_file_location('apex_bundle_notices',module_path); "
        "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
        "print(json.dumps(module.stage_notices(environment_root,output_dir),sort_keys=True))"
    )
    raw_inventory = _run(
        [str(python), "-c", code, str(module_path), str(environment_root), str(NOTICE_STAGE)],
        timeout=120,
    )
    try:
        inventory = json.loads(raw_inventory)
    except json.JSONDecodeError as exc:
        raise BundleBuildError("The distribution notice inventory returned invalid JSON.") from exc
    if not isinstance(inventory, list) or any(
        not isinstance(item, dict)
        or not all(isinstance(item.get(key), str) for key in ("path", "package", "version", "kind"))
        for item in inventory
    ):
        raise BundleBuildError("The distribution notice inventory returned invalid records.")
    return sorted(inventory, key=lambda item: (item["path"], item["package"], item["version"]))


def _build_environment(epoch: int, *, probe: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env["SOURCE_DATE_EPOCH"] = str(epoch)
    env["TZ"] = "UTC"
    if probe:
        env["APEX_BUNDLE_PROBE_BUILD"] = "1"
    else:
        env.pop("APEX_BUNDLE_PROBE_BUILD", None)
    return env


def _invoke_pyinstaller(
    python: Path,
    *,
    distpath: Path,
    workpath: Path,
    env: dict[str, str],
    probe: bool = False,
) -> Path:
    distpath.mkdir(parents=True, exist_ok=True)
    workpath.mkdir(parents=True, exist_ok=True)
    _run(
        [
            str(python), "-m", "PyInstaller", "--noconfirm", "--clean",
            "--log-level", "WARN", "--distpath", str(distpath), "--workpath",
            str(workpath), str(SPEC),
        ],
        env=env,
        timeout=3600,
    )
    name = "apex-bundle-probe" if probe else "backend-bundle"
    output = distpath / name
    if not output.is_dir():
        raise BundleBuildError(f"PyInstaller did not create {output.name}.")
    return output


def _copy_notices(stage: Path, destination: Path) -> None:
    for relative in (Path("LICENSE"), Path("THIRD_PARTY_NOTICES.md"), Path("licenses")):
        source = stage / relative
        if not source.exists():
            if relative.name == "licenses":
                raise BundleBuildError("Notice inventory did not create licenses/.")
            raise BundleBuildError(f"Notice inventory is missing {relative.as_posix()}.")
        candidates = [source, *source.rglob("*")] if source.is_dir() else [source]
        if any(path.is_symlink() for path in candidates):
            raise BundleBuildError(f"Notice inventory contains a symlink: {relative.as_posix()}.")
        target = destination / relative
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copyfile(source, target)


def write_manifest(
    bundle_root: Path,
    build_id: str,
    notice_inventory: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in bundle_root.rglob("*"):
        if path.is_symlink():
            raise BundleBuildError(f"Bundle contains a symlink: {path.relative_to(bundle_root).as_posix()}")
        if path.is_file() and path.name != "bundle-manifest.json":
            files.append({
                "path": path.relative_to(bundle_root).as_posix(),
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            })
    files.sort(key=lambda item: item["path"])
    manifest = {"build_id": build_id, "files": files, "schema_version": 1}
    if notice_inventory is not None:
        manifest["notice_inventory"] = notice_inventory
    target = bundle_root / "bundle-manifest.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def build(*, with_smoke_probe: bool = False, reproducibility_check: bool = False) -> Path:
    toolchain = _load_toolchain()
    _assert_uv_version(toolchain)
    _require_clean_tree()
    commit, epoch = _commit_provenance()
    lock_digest = _sha256(ROOT / "uv.lock")
    build_info = make_build_info(toolchain, commit, lock_digest)
    _copy_resources()
    build_info_path = RESOURCE_STAGE / "build-info.json"
    build_info_path.write_text(json.dumps(build_info, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    python = _prepare_environment(toolchain)
    notice_inventory = _stage_notices(BUILD_ENV, python)

    build_env = _build_environment(epoch)
    _safe_remove(PRODUCTION_DIST, ROOT / "dist")
    production = _invoke_pyinstaller(
        python,
        distpath=ROOT / "dist",
        workpath=BUILD_ROOT / "work" / "production",
        env=build_env,
    )
    _copy_notices(NOTICE_STAGE, production)
    first_manifest = write_manifest(production, build_info["build_id"], notice_inventory)

    if with_smoke_probe:
        probe_entry = ROOT / "packaging" / "windows" / "smoke" / "probe.py"
        if not probe_entry.is_file():
            raise BundleBuildError("--with-smoke-probe requires the packet B probe entrypoint.")
        probe_root = BUILD_ROOT / "smoke-probe"
        _safe_remove(probe_root, BUILD_ROOT)
        probe_dist = BUILD_ROOT / "apex-bundle-probe"
        _safe_remove(probe_dist, BUILD_ROOT)
        probe_work = BUILD_ROOT / "work" / "smoke-probe"
        probe_output = _invoke_pyinstaller(
            python,
            distpath=BUILD_ROOT,
            workpath=probe_work,
            env=_build_environment(epoch, probe=True),
            probe=True,
        )
        probe_root.mkdir(parents=True, exist_ok=True)
        for path in list(probe_output.iterdir()):
            shutil.move(os.fspath(path), os.fspath(probe_root / path.name))
        _safe_remove(probe_output, BUILD_ROOT)
        probe_output = probe_root
        write_manifest(probe_output, build_info["build_id"])

    if reproducibility_check:
        check_root = BUILD_ROOT / "repro-check"
        check_work = BUILD_ROOT / "work" / "repro-check"
        second = _invoke_pyinstaller(
            python,
            distpath=check_root,
            workpath=check_work,
            env=build_env,
        )
        _copy_notices(NOTICE_STAGE, second)
        second_manifest = write_manifest(second, build_info["build_id"], notice_inventory)
        if first_manifest != second_manifest:
            raise BundleBuildError("Controlled PyInstaller builds produced different file hashes.")
    return production


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-smoke-probe", action="store_true")
    parser.add_argument("--reproducibility-check", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        output = build(
            with_smoke_probe=arguments.with_smoke_probe,
            reproducibility_check=arguments.reproducibility_check,
        )
    except (BundleBuildError, OSError, RuntimeError, ValueError) as exc:
        print(f"Backend bundle build failed: {exc}", file=sys.stderr)
        return 2
    print(f"Backend bundle written to {output.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
