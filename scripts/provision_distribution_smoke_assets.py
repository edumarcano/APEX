"""Provision pinned, test-only inference assets outside the APEX package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST_PATH = REPOSITORY_ROOT / "packaging" / "windows" / "smoke" / "assets.json"
MAX_DOWNLOAD_SECONDS = 900
RETRIES = 2
FASTEMBED_DOWNLOAD_TIMEOUT = 900


def _source_manifest() -> dict[str, Any]:
    try:
        value = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvisionError("the pinned smoke asset provenance manifest is missing or invalid") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("assets"), dict):
        raise ProvisionError("the pinned smoke asset provenance manifest has an unsupported shape")
    return value


class ProvisionError(RuntimeError):
    pass


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path, expected_size: int, expected_sha256: str) -> None:
    opener = urllib.request.build_opener()
    last_error: Exception | None = None
    for attempt in range(RETRIES + 1):
        temporary = destination.with_name(destination.name + ".partial")
        temporary.unlink(missing_ok=True)
        started = time.monotonic()
        total = 0
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "APEX-distribution-smoke-assets/1"})
            with opener.open(request, timeout=30) as response, temporary.open("wb") as output:
                declared = response.headers.get("Content-Length")
                if declared and int(declared) != expected_size:
                    raise ProvisionError("upstream content length differs from the pinned asset manifest")
                digest = hashlib.sha256()
                while True:
                    if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                        raise TimeoutError("asset download exceeded its 15 minute bound")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > expected_size:
                        raise ProvisionError("upstream asset exceeded its pinned byte length")
                    output.write(chunk)
                    digest.update(chunk)
            if total != expected_size or digest.hexdigest() != expected_sha256:
                raise ProvisionError("downloaded asset failed pinned size or SHA-256 verification")
            temporary.replace(destination)
            return
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            temporary.unlink(missing_ok=True)
            if attempt == RETRIES:
                break
            time.sleep((attempt + 1) * 2)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    raise ProvisionError(f"could not fetch pinned asset from {url}: {type(last_error).__name__ if last_error else 'unknown error'}")


def _verify_asset(path: Path, size: int, digest: str) -> None:
    if not path.is_file() or path.stat().st_size != size or _hash(path) != digest:
        raise ProvisionError(f"pinned asset verification failed: {path.name}")


def _repository_roots() -> tuple[Path, ...]:
    roots = {REPOSITORY_ROOT.resolve()}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], cwd=REPOSITORY_ROOT,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=5, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            git_dir = Path(result.stdout.strip())
            if not git_dir.is_absolute():
                git_dir = REPOSITORY_ROOT / git_dir
            roots.add(git_dir.resolve().parent)
    except (OSError, subprocess.SubprocessError):
        pass
    return tuple(roots)


def _inside_repository(destination: Path) -> bool:
    resolved = destination.resolve()
    return any(resolved == root or resolved.is_relative_to(root) for root in _repository_roots())


def _fetch_fastembed_snapshot(cache: Path, source: dict[str, Any]) -> None:
    code = (
        "import sys; from huggingface_hub import snapshot_download; "
        "snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2], cache_dir=sys.argv[3], "
        "allow_patterns=sys.argv[4].split('|'), max_workers=2)"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", code, source["repository"], source["revision"],
             str(cache), "|".join(sorted(source["files"]))],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=FASTEMBED_DOWNLOAD_TIMEOUT, check=False,
            env=os.environ.copy(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise ProvisionError("pinned FastEmbed download exceeded its 15 minute bound") from exc
    except OSError as exc:
        raise ProvisionError("pinned FastEmbed downloader could not start") from exc
    if result.returncode != 0:
        raise ProvisionError("pinned FastEmbed download failed before its hash-verification step")


def _write_fastembed_default_ref(cache: Path, repository: str, revision: str) -> Path:
    """Make FastEmbed's offline default `main` resolve to the verified pin."""
    repo_cache = f"models--{repository.replace('/', '--')}"
    snapshot = cache / repo_cache / "snapshots" / revision
    if not snapshot.is_dir():
        raise ProvisionError("verified FastEmbed snapshot directory is missing")
    refs = cache / repo_cache / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    target = refs / "main"
    temporary = refs / "main.apex-smoke-tmp"
    temporary.write_text(revision + "\n", encoding="ascii")
    temporary.replace(target)
    return target


def _fastembed(cache: Path, source: dict[str, Any]) -> dict[str, Any]:
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_ETAG_TIMEOUT"] = "30"
    os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "30"
    _fetch_fastembed_snapshot(cache, source)
    repo_cache = f"models--{source['repository'].replace('/', '--')}"
    snapshot = cache / repo_cache / "snapshots" / source["revision"]
    records = []
    for name, item in source["files"].items():
        size, digest = int(item["bytes"]), str(item["sha256"])
        path = snapshot / name
        _verify_asset(path, size, digest)
        records.append({"path": path.relative_to(cache).as_posix(), "bytes": size, "sha256": digest})
    main_ref = _write_fastembed_default_ref(cache, source["repository"], source["revision"])
    if main_ref.read_text(encoding="ascii").strip() != source["revision"]:
        raise ProvisionError("FastEmbed offline default reference does not resolve to the pinned snapshot")
    return {
        **{key: value for key, value in source.items() if key != "files"},
        "default_ref": {"path": main_ref.relative_to(cache).as_posix(), "revision": source["revision"]},
        "files": records,
    }


def _kokoro(directory: Path, source: dict[str, Any]) -> dict[str, Any]:
    records = []
    for name, item in source["files"].items():
        size, digest = int(item["bytes"]), str(item["sha256"])
        url = f"https://github.com/{source['repository']}/releases/download/{source['release']}/{name}"
        path = directory / name
        if not path.exists():
            _download(url, path, size, digest)
        _verify_asset(path, size, digest)
        records.append({"path": name, "url": url, "bytes": size, "sha256": digest})
    return {
        **{key: value for key, value in source.items() if key != "files"},
        "files": records,
    }


def provision(destination: Path) -> dict[str, Any]:
    _windows_or_posix = destination.expanduser().resolve()
    if _inside_repository(_windows_or_posix):
        raise ProvisionError("test weights must be stored outside the repository and production package")
    if _windows_or_posix.exists() and any(_windows_or_posix.iterdir()):
        raise ProvisionError("asset destination must be new or empty")
    _windows_or_posix.mkdir(parents=True, exist_ok=True)
    cache = _windows_or_posix / "fastembed_cache"
    kokoro_dir = _windows_or_posix / "kokoro"
    cache.mkdir(exist_ok=True)
    kokoro_dir.mkdir(exist_ok=True)
    try:
        source_manifest = _source_manifest()
        sources = source_manifest["assets"]
        manifest = {
            "schema_version": 1,
            "purpose": "external test assets for strict APEX Windows distribution smoke only",
            "provenance_manifest": str(SOURCE_MANIFEST_PATH.relative_to(REPOSITORY_ROOT).as_posix()),
            "assets": {
                "fastembed": _fastembed(cache, sources["fastembed"]),
                "kokoro": _kokoro(kokoro_dir, sources["kokoro"]),
            },
        }
        target = _windows_or_posix / "apex-distribution-smoke-assets.json"
        target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"destination": str(_windows_or_posix), "fastembed_cache": str(cache), "kokoro_assets": str(kokoro_dir), "manifest": str(target)}
    except Exception:
        # Keep downloaded files for inspection, but a later invocation requires
        # a new empty destination rather than trusting/reusing partial content.
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True, help="new or empty directory outside the repository")
    args = parser.parse_args(argv)
    try:
        result = provision(args.destination)
    except (OSError, ProvisionError, ValueError) as exc:
        print(f"Distribution smoke asset provisioning failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
