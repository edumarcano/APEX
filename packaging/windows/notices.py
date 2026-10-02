"""Stage notices for the Windows backend bundle from installed distributions."""

from __future__ import annotations

import importlib.metadata
import hashlib
import json
import re
import shutil
import sys
import sysconfig
import tarfile
import tomllib
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

_LICENSE_NAME = re.compile(r"(license|licence|copying|notices?|copyright|(?:lgpl|gpl)(?:[-_. ]|$))", re.IGNORECASE)
_LICENSE_DIR_PART = re.compile(r"(?:^|/)(?:licenses|license|licences|licence)(?:/|$)", re.IGNORECASE)


def _site_packages(environment_root: Path) -> Path:
    candidates = (
        environment_root / "Lib" / "site-packages",
        environment_root / "lib" / "site-packages",
        *sorted(environment_root.glob("lib/python*/site-packages")),
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    if environment_root.name.lower() == "site-packages" and environment_root.is_dir():
        return environment_root
    raise FileNotFoundError(f"No site-packages directory found under {environment_root}")


def _is_license_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return bool(
        _LICENSE_NAME.search(normalized.rsplit("/", 1)[-1])
        or _LICENSE_DIR_PART.search(normalized)
    )


def _safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "package"


def _read_file(distribution: importlib.metadata.Distribution, entry: Any) -> bytes:
    return Path(distribution.locate_file(entry)).read_bytes()


def _stage_python_license(environment_root: Path, output_dir: Path) -> dict[str, str]:
    candidates = [
        environment_root / "LICENSE.txt",
        environment_root / "LICENSE",
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE",
        Path(sysconfig.get_config_var("prefix") or sys.base_prefix) / "LICENSE.txt",
    ]
    source = next((candidate for candidate in candidates if candidate.is_file()), None)
    if source is None:
        raise RuntimeError("Python interpreter license text is missing from the bundled runtime")
    destination = output_dir / "licenses" / f"Python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}" / "LICENSE.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return {
        "path": destination.relative_to(output_dir).as_posix(),
        "package": "Python interpreter",
        "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "kind": "interpreter-license",
    }


def _copy_license_files(
    distribution: importlib.metadata.Distribution,
    output_dir: Path,
    package: str,
    version: str,
) -> list[dict[str, str]]:
    files = sorted(
        (entry for entry in (distribution.files or ()) if _is_license_file(str(entry))),
        key=lambda entry: str(entry).casefold(),
    )
    if not files:
        raise RuntimeError(
            f"{package} {version} has no installed LICENSE, COPYING, or NOTICE material; "
            "refusing to generate a license from metadata."
        )

    package_dir = output_dir / "licenses" / f"{_safe_component(package)}-{_safe_component(version)}"
    records: list[dict[str, str]] = []
    for index, entry in enumerate(files, start=1):
        output_name = f"{index:02d}-{_safe_component(Path(str(entry)).name)}"
        destination = package_dir / output_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_read_file(distribution, entry))
        records.append(
            {
                "path": destination.relative_to(output_dir).as_posix(),
                "package": package,
                "version": version,
                "kind": "license-or-notice",
            }
        )
    return records


def _stage_locked_sdist_licenses(
    repository_root: Path,
    output_dir: Path,
    distribution: importlib.metadata.Distribution,
    *,
    prefix_sdist: bool = False,
) -> list[dict[str, str]]:
    """Extract upstream license files from the exact sdist pinned in uv.lock."""
    name = distribution.metadata.get("Name") or ""
    normalized_name = _normalized_name(name)
    lock = tomllib.loads((repository_root / "uv.lock").read_text(encoding="utf-8"))
    package = next(
        (
            item for item in lock.get("package", [])
            if _normalized_name(item.get("name", "")) == normalized_name
            and item.get("version") == distribution.version
        ),
        None,
    )
    sdist = package.get("sdist") if package else None
    if not isinstance(sdist, dict):
        raise RuntimeError(
            f"{name} {distribution.version} has no installed license text and no locked source distribution"
        )
    archive_name = Path(urlparse(sdist.get("url", "")).path).name
    archive = repository_root / "packaging" / "windows" / "source-material" / archive_name
    if not archive.is_file() or _sha256(archive) != sdist.get("hash", "").removeprefix("sha256:"):
        raise RuntimeError(
            f"{name} {distribution.version} needs its uv.lock-pinned source archive at "
            f"packaging/windows/source-material/{archive_name}"
        )
    records: list[dict[str, str]] = []
    with tarfile.open(archive, "r:gz") as source_tar:
        members = [
            member for member in source_tar.getmembers()
            if member.isfile() and _is_license_file(member.name)
        ]
        if not members:
            raise RuntimeError(f"The locked {name} source archive contains no license or notice files")
        for index, member in enumerate(sorted(members, key=lambda entry: entry.name.casefold()), start=1):
            source = source_tar.extractfile(member)
            if source is None:
                raise RuntimeError(f"The locked {name} source archive has an unreadable license entry")
            basename = _safe_component(Path(member.name).name)
            filename = f"{'sdist-' if prefix_sdist else ''}{index:02d}-{basename}"
            target = (
                output_dir
                / "licenses"
                / f"{_safe_component(name)}-{_safe_component(distribution.version)}"
                / filename
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            source_bytes = source.read()
            if target.exists():
                raise RuntimeError(f"Duplicate staged license path for {name}: {member.name}")
            target.write_bytes(source_bytes)
            records.append(
                {
                    "path": target.relative_to(output_dir).as_posix(),
                    "package": name,
                    "version": distribution.version,
                    "kind": "license-or-notice-from-locked-sdist",
                }
            )
    return records


def _stage_flatbuffers_license(
    repository_root: Path,
    output_dir: Path,
    distribution: importlib.metadata.Distribution,
) -> list[dict[str, str]]:
    """Use the exact FlatBuffers tag license for its wheel-only locked release."""
    manifest_path = repository_root / "packaging" / "windows" / "source-material" / "flatbuffers-source.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        distribution.version != "25.12.19"
        or manifest.get("version") != distribution.version
        or manifest.get("upstream_revision") != "7e163021e59cca4f8e1e35a7c828b5c6b7915953"
        or manifest.get("wheel_sha256") != "7634f50c427838bb021c2d66a3d1168e9d199b0607e6329399f04846d42e20b4"
    ):
        raise RuntimeError("The FlatBuffers license mapping does not match the locked wheel")
    lock = tomllib.loads((repository_root / "uv.lock").read_text(encoding="utf-8"))
    package = next(
        item for item in lock["package"]
        if _normalized_name(item.get("name", "")) == "flatbuffers"
        and item.get("version") == distribution.version
    )
    expected_wheel_hashes = {
        wheel.get("hash", "").removeprefix("sha256:") for wheel in package.get("wheels", [])
    }
    if manifest["wheel_sha256"] not in expected_wheel_hashes:
        raise RuntimeError("The FlatBuffers wheel hash is not present in uv.lock")
    license_path = repository_root / "packaging" / "windows" / "source-material" / manifest["license_file"]
    if _sha256(license_path) != manifest.get("license_sha256"):
        raise RuntimeError("The FlatBuffers upstream license text hash does not match its source manifest")
    destination = output_dir / "licenses" / "flatbuffers-25.12.19" / "LICENSE.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_path, destination)
    return [
        {
            "path": destination.relative_to(output_dir).as_posix(),
            "package": "flatbuffers",
            "version": distribution.version,
            "kind": "verified-upstream-license",
        }
    ]


def _stage_fastmcp_slim_license(
    repository_root: Path,
    output_dir: Path,
    distribution: importlib.metadata.Distribution,
) -> list[dict[str, str]]:
    manifest_path = repository_root / "packaging" / "windows" / "source-material" / "fastmcp-slim-source.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        distribution.version != "3.4.4"
        or manifest.get("version") != distribution.version
        or manifest.get("upstream_revision") != "9138d40e8813c2a7c6c7a015f3dffe0a120730e0"
        or manifest.get("wheel_sha256") != "9d3a6327b9ee835188eb7323fc3b5d4cd061631b48da8ece56794bb538972505"
    ):
        raise RuntimeError("The FastMCP Slim license mapping does not match the locked 3.4.4 wheel")
    lock = tomllib.loads((repository_root / "uv.lock").read_text(encoding="utf-8"))
    package = next(
        item for item in lock["package"]
        if _normalized_name(item.get("name", "")) == "fastmcp-slim"
        and item.get("version") == distribution.version
    )
    locked_hashes = {
        wheel.get("hash", "").removeprefix("sha256:") for wheel in package.get("wheels", [])
    }
    if manifest["wheel_sha256"] not in locked_hashes:
        raise RuntimeError("The FastMCP Slim wheel hash is not present in uv.lock")
    license_path = repository_root / "packaging" / "windows" / "source-material" / manifest["license_file"]
    if _sha256(license_path) != manifest.get("license_sha256"):
        raise RuntimeError("The FastMCP Slim upstream license text hash does not match its source manifest")
    destination = output_dir / "licenses" / "fastmcp-slim-3.4.4" / "LICENSE.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_path, destination)
    return [
        {
            "path": destination.relative_to(output_dir).as_posix(),
            "package": "fastmcp-slim",
            "version": distribution.version,
            "kind": "verified-upstream-license",
        }
    ]


def _stage_pygame_native_licenses(
    repository_root: Path,
    output_dir: Path,
    distribution: importlib.metadata.Distribution,
) -> list[dict[str, str]]:
    if distribution.version != "2.5.7":
        raise RuntimeError("The pygame-ce native license map only covers locked version 2.5.7")
    lock = tomllib.loads((repository_root / "uv.lock").read_text(encoding="utf-8"))
    package = next(
        item for item in lock["package"]
        if _normalized_name(item.get("name", "")) == "pygame-ce"
        and item.get("version") == distribution.version
    )
    wheel_hashes = {
        wheel.get("hash", "").removeprefix("sha256:") for wheel in package.get("wheels", [])
    }
    expected_wheel_hash = "595f4257c15fed11cd816ae0bfabad3d99f8f04a000d7d164a22c0f9afd6cb65"
    if expected_wheel_hash not in wheel_hashes:
        raise RuntimeError("The pygame-ce Windows x64 wheel hash is not present in uv.lock")
    records = []
    source_root = repository_root / "packaging" / "windows" / "source-material"
    for manifest_name in ("libxmp-source.json", "wavpack-source.json"):
        manifest = json.loads((source_root / manifest_name).read_text(encoding="utf-8"))
        dll_relative = manifest["dll"]
        dll_path = Path(distribution.locate_file(dll_relative))
        if not dll_path.is_file() or manifest["version_marker"].encode("ascii") not in dll_path.read_bytes():
            raise RuntimeError(
                f"The installed pygame-ce wheel does not match the recorded {manifest['component']} DLL version"
            )
        license_source = source_root / manifest["license_file"]
        if _sha256(license_source) != manifest["license_sha256"]:
            raise RuntimeError(f"The {manifest['component']} license file hash does not match its source mapping")
        license_destination = (
            output_dir / "licenses" / f"{_safe_component(manifest['component'])}-{manifest['version']}" / "COPYING.txt"
        )
        license_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(license_source, license_destination)
        record = {
            "path": license_destination.relative_to(output_dir).as_posix(),
            "package": manifest["component"],
            "version": manifest["version"],
            "kind": "verified-native-license",
        }
        records.append(record)
        provenance_destination = license_destination.parent / "source-mapping.json"
        shutil.copyfile(source_root / manifest_name, provenance_destination)
        records.append(
            {
                "path": provenance_destination.relative_to(output_dir).as_posix(),
                "package": f"{manifest['component']} source mapping",
                "version": manifest["version"],
                "kind": "source-provenance",
            }
        )
    return records


def _stage_loguru_license(
    repository_root: Path,
    output_dir: Path,
    distribution: importlib.metadata.Distribution,
) -> list[dict[str, str]]:
    manifest_path = repository_root / "packaging" / "windows" / "source-material" / "loguru-source.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        distribution.version != "0.7.3"
        or manifest.get("version") != distribution.version
        or manifest.get("upstream_revision") != "ae3bfd1b85b6b4a3db535f69b975687c79498be4"
        or manifest.get("wheel_sha256") != "31a33c10c8e1e10422bfd431aeb5d351c7cf7fa671e3c4df004162264b28220c"
    ):
        raise RuntimeError("The Loguru license mapping does not match the locked 0.7.3 wheel")
    lock = tomllib.loads((repository_root / "uv.lock").read_text(encoding="utf-8"))
    package = next(
        item for item in lock["package"]
        if _normalized_name(item.get("name", "")) == "loguru"
        and item.get("version") == distribution.version
    )
    locked_hashes = {
        wheel.get("hash", "").removeprefix("sha256:") for wheel in package.get("wheels", [])
    }
    if manifest["wheel_sha256"] not in locked_hashes:
        raise RuntimeError("The Loguru wheel hash is not present in uv.lock")
    license_path = repository_root / "packaging" / "windows" / "source-material" / manifest["license_file"]
    if _sha256(license_path) != manifest.get("license_sha256"):
        raise RuntimeError("The Loguru upstream license text hash does not match its source manifest")
    destination = output_dir / "licenses" / "loguru-0.7.3" / "LICENSE.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_path, destination)
    return [
        {
            "path": destination.relative_to(output_dir).as_posix(),
            "package": "loguru",
            "version": distribution.version,
            "kind": "verified-upstream-license",
        }
    ]


def _has_non_metadata_payload(distribution: importlib.metadata.Distribution) -> bool:
    files = distribution.files
    if files is None or not files:
        name = distribution.metadata.get("Name") or "unknown distribution"
        raise RuntimeError(
            f"{name} {distribution.version} has no installed RECORD inventory; "
            "refusing to infer that the runtime distribution contains no code."
        )
    return any(
        not any(part.lower().endswith((".dist-info", ".egg-info")) for part in Path(str(entry)).parts)
        for entry in files
    )


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _locked_runtime_names(lock_path: Path) -> set[str]:
    try:
        from packaging.markers import Marker, default_environment
    except ImportError as exc:  # packaging is a PyInstaller build dependency.
        raise RuntimeError("The locked build environment is missing the packaging marker parser") from exc

    with lock_path.open("rb") as stream:
        lock = tomllib.load(stream)
    packages = {
        _normalized_name(item["name"]): item
        for item in lock.get("package", [])
        if item.get("name")
    }
    root = packages.get("apex")
    if root is None:
        raise RuntimeError("uv.lock has no apex package entry")
    environment = default_environment()
    requested_extras: dict[str, set[str]] = {"apex": set(root.get("optional-dependencies", {}))}
    pending: list[tuple[str, dict[str, Any]]] = []
    for dependency in root.get("dependencies", []):
        pending.append(("apex", dependency))
    for dependencies in root.get("optional-dependencies", {}).values():
        pending.extend(("apex", dependency) for dependency in dependencies)

    included = {"apex"}
    expanded: set[tuple[str, str]] = set()
    while pending:
        parent_name, dependency = pending.pop()
        marker_text = dependency.get("marker")
        extras = {"", *requested_extras.get(parent_name, set())}
        if marker_text and not any(
            Marker(marker_text).evaluate({**environment, "extra": extra}) for extra in extras
        ):
            continue
        name = _normalized_name(dependency["name"])
        package = packages.get(name)
        if package is None:
            raise RuntimeError(f"uv.lock references missing package metadata for {name}")
        new_extras = set(dependency.get("extra", dependency.get("extras", [])))
        prior_extras = requested_extras.setdefault(name, set())
        newly_requested = new_extras - prior_extras
        prior_extras.update(new_extras)
        included.add(name)

        key = (name, "base")
        if key not in expanded:
            expanded.add(key)
            pending.extend((name, edge) for edge in package.get("dependencies", []))
        for extra in sorted(newly_requested):
            key = (name, extra)
            if key not in expanded:
                expanded.add(key)
                pending.extend((name, edge) for edge in package.get("optional-dependencies", {}).get(extra, []))
    return included


def _runtime_distributions(
    site_packages: Path, locked_runtime_names: set[str]
) -> list[importlib.metadata.Distribution]:
    distributions = list(importlib.metadata.distributions(path=[str(site_packages)]))
    by_name = {
        _normalized_name(dist.metadata.get("Name") or ""): dist
        for dist in distributions
        if dist.metadata.get("Name")
    }
    missing = sorted(locked_runtime_names - by_name.keys())
    if missing:
        raise RuntimeError(
            "The locked runtime environment is missing required Windows distributions: "
            + ", ".join(missing)
        )
    selected = [by_name[name] for name in locked_runtime_names if name not in {"apex", "pyinstaller"}]
    selected.sort(key=lambda dist: ((dist.metadata.get("Name") or "").casefold(), dist.version))
    return selected


def _write_staged_notices(output_dir: Path, records: list[dict[str, str]], source_text: str) -> None:
    # The notice file sits beside _internal in the one-folder distribution.
    source_text = source_text.replace(
        "(docs/backend-bundle.md)", "(_internal/docs/backend-bundle.md)"
    )
    lines = [
        source_text.rstrip(),
        "",
        "## Installed backend inventory",
        "",
        "The following entries were collected from the locked runtime environment used for this build. Original license and notice files are preserved under `licenses/`. Build tools are excluded except for the PyInstaller bootloader license and exception notice.",
        "",
        "| Component | Version | Included material |",
        "| --- | --- | --- |",
    ]
    for record in records:
        lines.append(
            f"| {record['package']} | {record['version']} | [`{record['path']}`]({record['path']}) |"
        )
    lines.extend(["", "Model weights and operator-provided files are not part of this bundle.", ""])
    (output_dir / "THIRD_PARTY_NOTICES.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_corresponding_sources(
    repository_root: Path,
    output_dir: Path,
    included_names: set[str],
    distributions_by_name: dict[str, importlib.metadata.Distribution] | None = None,
) -> list[dict[str, str]]:
    """Stage exact GPL source archives or stop when provenance is incomplete."""
    source_root = repository_root / "packaging" / "windows" / "source-material"
    records: list[dict[str, str]] = []

    if "phonemizer-fork" in included_names:
        archive = source_root / "phonemizer-fork-3.3.2.tar.gz"
        if not archive.is_file():
            raise RuntimeError(
                "The shipped phonemizer-fork 3.3.2 package requires its locked source archive at "
                "packaging/windows/source-material/phonemizer-fork-3.3.2.tar.gz"
            )
        lock = tomllib.loads((repository_root / "uv.lock").read_text(encoding="utf-8"))
        package = next(item for item in lock["package"] if item.get("name") == "phonemizer-fork")
        expected_hash = package["sdist"]["hash"].removeprefix("sha256:")
        if _sha256(archive) != expected_hash:
            raise RuntimeError("The phonemizer-fork source archive does not match uv.lock")
        relative = Path("licenses") / "source-material" / archive.name
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, destination)
        records.append(
            {
                "path": relative.as_posix(),
                "package": "phonemizer-fork source",
                "version": "3.3.2",
                "kind": "corresponding-source",
            }
        )

    if "espeakng-loader" in included_names:
        manifest_path = source_root / "espeak-ng-source.json"
        if not manifest_path.is_file():
            raise RuntimeError(
                "The espeakng-loader 0.2.4 wheel contains eSpeak NG native files, but the exact "
                "upstream eSpeak NG source revision is not recorded. Add a verified "
                "packaging/windows/source-material/espeak-ng-source.json mapping and archive."
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        revision = manifest.get("upstream_revision")
        loader_revision = manifest.get("loader_revision")
        archive_name = manifest.get("archive")
        expected_hash = manifest.get("sha256")
        if (
            revision != "4870adfa25b1a32b4361592f1be8a40337c58d6c"
            or loader_revision != "146599e29be31bf17d99f0bcb7dbb2f92aef3d95"
        ):
            raise RuntimeError("The eSpeak NG source mapping does not match the 0.2.4 wheel build workflow")
        if not all(isinstance(value, str) and value.strip() for value in (archive_name, expected_hash)):
            raise RuntimeError("The eSpeak NG source manifest must record archive and sha256")
        archive = (source_root / archive_name).resolve()
        if source_root.resolve() not in archive.parents or not archive.is_file():
            raise RuntimeError("The eSpeak NG source archive path is missing or outside source-material")
        if _sha256(archive) != expected_hash:
            raise RuntimeError("The eSpeak NG source archive hash does not match its manifest")
        relative = Path("licenses") / "source-material" / archive.name
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, destination)
        records.append(
            {
                "path": relative.as_posix(),
                "package": "eSpeak NG source",
                "version": revision,
                "kind": "corresponding-source",
            }
        )
    if "pygame-ce" in included_names:
        pygame_distribution = (distributions_by_name or {}).get("pygame-ce")
        if pygame_distribution is None:
            raise RuntimeError("The locked pygame-ce runtime distribution is missing")
        source_archive = source_root / "pygame_ce-2.5.7.tar.gz"
        lock = tomllib.loads((repository_root / "uv.lock").read_text(encoding="utf-8"))
        package = next(
            item for item in lock["package"]
            if _normalized_name(item.get("name", "")) == "pygame-ce"
            and item.get("version") == pygame_distribution.version
        )
        expected = package.get("sdist", {}).get("hash", "").removeprefix("sha256:")
        if pygame_distribution.version != "2.5.7" or not source_archive.is_file() or _sha256(source_archive) != expected:
            raise RuntimeError("pygame-ce native license source does not match the locked 2.5.7 sdist")
        destination = output_dir / "licenses" / "source-material" / source_archive.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_archive, destination)
        records.append(
            {
                "path": destination.relative_to(output_dir).as_posix(),
                "package": "pygame-ce corresponding source",
                "version": pygame_distribution.version,
                "kind": "corresponding-source",
            }
        )

    if "espeakng-loader" in included_names:
        # The wheel omitted its license file. The exact 0.2.4 wrapper sources
        # are byte-identical modulo checkout line endings to upstream commit
        # 0ddc87a, a child of its build commit that adds the MIT grant. Verify
        # that narrow correspondence before applying that grant to the wheel.
        loader_manifest_path = source_root / "espeakng-loader-source.json"
        if not loader_manifest_path.is_file() or distributions_by_name is None:
            raise RuntimeError(
                "The espeakng-loader 0.2.4 wheel has no installed license file; its verified "
                "MIT source mapping and installed wrapper must be available to stage the license."
            )
        loader_manifest = json.loads(loader_manifest_path.read_text(encoding="utf-8"))
        if (
            loader_manifest.get("upstream_revision")
            != "0ddc87adf77e5850d7eeb542ac8a87d421b64daa"
            or loader_manifest.get("build_revision") != loader_revision
            or loader_manifest.get("version") != "0.2.4"
        ):
            raise RuntimeError("The espeakng-loader source mapping does not match the locked 0.2.4 wheel")
        loader_archive_name = loader_manifest.get("archive")
        loader_archive_hash = loader_manifest.get("sha256")
        loader_archive = (source_root / str(loader_archive_name)).resolve()
        if (
            source_root.resolve() not in loader_archive.parents
            or not loader_archive.is_file()
            or _sha256(loader_archive) != loader_archive_hash
        ):
            raise RuntimeError("The espeakng-loader source archive is missing or has an unexpected hash")
        distribution = distributions_by_name.get("espeakng-loader")
        if distribution is None or distribution.version != "0.2.4":
            raise RuntimeError("The installed espeakng-loader distribution is not version 0.2.4")
        installed_wrapper = next(
            (
                Path(distribution.locate_file(entry)).read_bytes()
                for entry in (distribution.files or ())
                if str(entry).replace("\\", "/") == "espeakng_loader/__init__.py"
            ),
            None,
        )
        if installed_wrapper is None:
            raise RuntimeError("The espeakng-loader wheel is missing espeakng_loader/__init__.py")
        with tarfile.open(loader_archive, "r:gz") as source_tar:
            source_files = [
                member for member in source_tar.getmembers()
                if member.isfile()
                and member.name.endswith(("/espeakng_loader/__init__.py", "/LICENSE", "/pyproject.toml"))
            ]
            wrapper_member = next(
                (member for member in source_files if member.name.endswith("/espeakng_loader/__init__.py")),
                None,
            )
            license_member = next(
                (member for member in source_files if member.name.endswith("/LICENSE")), None
            )
            project_member = next(
                (member for member in source_files if member.name.endswith("/pyproject.toml")), None
            )
            if wrapper_member is None or license_member is None or project_member is None:
                raise RuntimeError("The espeakng-loader source archive lacks wrapper, metadata, or MIT LICENSE")
            source_wrapper = source_tar.extractfile(wrapper_member)
            source_license = source_tar.extractfile(license_member)
            source_project = source_tar.extractfile(project_member)
            if source_wrapper is None or source_license is None or source_project is None:
                raise RuntimeError("The espeakng-loader source archive is incomplete")
            project_metadata = tomllib.loads(source_project.read().decode("utf-8"))
            if project_metadata.get("project", {}).get("version") != "0.2.4":
                raise RuntimeError("The espeakng-loader source archive metadata is not version 0.2.4")
            if installed_wrapper.replace(b"\r\n", b"\n") != source_wrapper.read().replace(b"\r\n", b"\n"):
                raise RuntimeError(
                    "The installed espeakng-loader wrapper differs from the source covered by the MIT grant"
                )
            license_bytes = source_license.read()
        loader_version = "0.2.4"
        license_path = Path("licenses") / "espeakng-loader-0.2.4" / "LICENSE.txt"
        license_destination = output_dir / license_path
        license_destination.parent.mkdir(parents=True, exist_ok=True)
        license_destination.write_bytes(license_bytes)
        records.append(
            {
                "path": license_path.as_posix(),
                "package": "espeakng-loader",
                "version": loader_version,
                "kind": "verified-upstream-license",
            }
        )
        source_destination = output_dir / "licenses" / "source-material" / loader_archive.name
        source_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(loader_archive, source_destination)
        records.append(
            {
                "path": source_destination.relative_to(output_dir).as_posix(),
                "package": "espeakng-loader wrapper source",
                "version": loader_version,
                "kind": "source-provenance",
            }
        )
        loader_manifest_destination = source_destination.parent / loader_manifest_path.name
        shutil.copyfile(loader_manifest_path, loader_manifest_destination)
        records.append(
            {
                "path": loader_manifest_destination.relative_to(output_dir).as_posix(),
                "package": "espeakng-loader source mapping",
                "version": loader_version,
                "kind": "source-provenance",
            }
        )
        manifest_destination = destination.parent / "espeak-ng-source.json"
        shutil.copyfile(manifest_path, manifest_destination)
        records.append(
            {
                "path": manifest_destination.relative_to(output_dir).as_posix(),
                "package": "eSpeak NG source mapping",
                "version": revision,
                "kind": "source-provenance",
            }
        )
    readme = source_root / "README.md"
    if not readme.is_file():
        raise RuntimeError("The corresponding-source materials are missing their provenance README")
    destination = output_dir / "licenses" / "source-material" / "README.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(readme, destination)
    records.append(
        {
            "path": destination.relative_to(output_dir).as_posix(),
            "package": "Corresponding source provenance",
            "version": "",
            "kind": "source-provenance",
        }
    )
    return records


def stage_notices(environment_root: Path, output_dir: Path) -> list[dict[str, str]]:
    """Copy APEX and runtime license materials into a bundle staging directory.

    ``environment_root`` is the locked runtime virtual environment installed
    with every project extra. Returned records have stable relative paths and
    contain no build-machine paths.
    """
    environment_root = Path(environment_root)
    output_dir = Path(output_dir)
    site_packages = _site_packages(environment_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    repository_root = Path(__file__).resolve().parents[2]
    locked_runtime_names = _locked_runtime_names(repository_root / "uv.lock")
    apex_license = repository_root / "LICENSE"
    if not apex_license.is_file():
        raise FileNotFoundError("APEX LICENSE is missing")
    shutil.copyfile(apex_license, output_dir / "LICENSE")
    records = [{"path": "LICENSE", "package": "APEX", "version": "", "kind": "license"}]
    records.append(_stage_python_license(environment_root, output_dir))

    runtime_distributions = _runtime_distributions(site_packages, locked_runtime_names)
    for distribution in runtime_distributions:
        name = distribution.metadata.get("Name")
        if not name:
            raise RuntimeError("An installed runtime distribution has no Name metadata")
        has_payload = _has_non_metadata_payload(distribution)
        normalized_name = _normalized_name(name)
        if normalized_name == "pypiwin32":
            if distribution.version != "223" or has_payload:
                raise RuntimeError(
                    f"pypiwin32 {distribution.version} is not the verified metadata-only compatibility shim"
                )
            # pypiwin32 223 ships only dist-info metadata and contributes no
            # executable module to the frozen runtime.
            continue
        if normalized_name == "espeakng-loader":
            # Its wheel omits LICENSE; _stage_corresponding_sources verifies
            # and supplies the exact upstream MIT grant for the wrapper.
            continue
        try:
            records.extend(_copy_license_files(distribution, output_dir, name, distribution.version))
        except RuntimeError:
            if _normalized_name(name) == "flatbuffers":
                records.extend(_stage_flatbuffers_license(repository_root, output_dir, distribution))
            elif _normalized_name(name) == "fastmcp-slim":
                records.extend(_stage_fastmcp_slim_license(repository_root, output_dir, distribution))
            elif _normalized_name(name) == "loguru":
                records.extend(_stage_loguru_license(repository_root, output_dir, distribution))
            else:
                records.extend(_stage_locked_sdist_licenses(repository_root, output_dir, distribution))
        if _normalized_name(name) == "pygame-ce":
            # The wheel carries pygame's LGPL text, while its source sdist also
            # carries notices for bundled SDL and codec DLL dependencies.
            records.extend(
                _stage_locked_sdist_licenses(
                    repository_root, output_dir, distribution, prefix_sdist=True
                )
            )
    distributions_by_name = {
        _normalized_name(dist.metadata.get("Name") or ""): dist for dist in runtime_distributions
    }
    records.extend(
        _stage_corresponding_sources(
            repository_root, output_dir, locked_runtime_names, distributions_by_name
        )
    )
    if "pygame-ce" in distributions_by_name:
        records.extend(
            _stage_pygame_native_licenses(
                repository_root, output_dir, distributions_by_name["pygame-ce"]
            )
        )

    # PyInstaller is build-only. Its bootloader exception still covers the
    # bootloader copied into the frozen application and must travel with it.
    pyinstaller = next(
        (
            dist
            for dist in importlib.metadata.distributions(path=[str(site_packages)])
            if (dist.metadata.get("Name") or "").casefold() == "pyinstaller"
        ),
        None,
    )
    if pyinstaller is None:
        raise RuntimeError("PyInstaller is missing from the locked build environment")
    bootloader_files = [
        entry
        for entry in (pyinstaller.files or ())
        if "license" in str(entry).casefold() and "bootloader" not in str(entry).casefold()
    ]
    entry = next(
        (
            candidate
            for candidate in sorted(bootloader_files, key=lambda item: str(item).casefold())
            if b"bootloader exception" in _read_file(pyinstaller, candidate).lower()
        ),
        None,
    )
    if entry is None:
        raise RuntimeError("PyInstaller installed license material does not contain the bootloader exception")
    destination = (
        output_dir
        / "licenses"
        / f"PyInstaller-{_safe_component(pyinstaller.version)}"
        / "BOOTLOADER-LICENSE.txt"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_read_file(pyinstaller, entry))
    records.append(
        {
            "path": destination.relative_to(output_dir).as_posix(),
            "package": "PyInstaller bootloader",
            "version": pyinstaller.version,
            "kind": "bootloader-license-and-exception",
        }
    )

    records.sort(key=lambda item: (item["path"].casefold(), item["package"].casefold(), item["version"]))
    _write_staged_notices(
        output_dir,
        records,
        (repository_root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8"),
    )
    return records
