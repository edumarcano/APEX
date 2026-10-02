# -*- mode: python ; coding: utf-8 -*-

import importlib.util
import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, copy_metadata


ROOT = Path(SPECPATH).resolve().parents[1]
collection_path = ROOT / "packaging" / "windows" / "collection.py"
collection_spec = importlib.util.spec_from_file_location("apex_bundle_collection", collection_path)
if collection_spec is None or collection_spec.loader is None:
    raise RuntimeError("Could not load the shared bundle collection helper.")
collection_module = importlib.util.module_from_spec(collection_spec)
collection_spec.loader.exec_module(collection_module)
bundle_datas = collection_module.bundle_datas
bundle_hidden_imports = collection_module.bundle_hidden_imports
bundle_analysis_excludes = collection_module.bundle_analysis_excludes
include_onnxruntime_submodule = collection_module.include_onnxruntime_submodule
include_runtime_submodule = collection_module.include_runtime_submodule
is_bundle_excluded_data_path = collection_module.is_bundle_excluded_data_path


probe_mode = os.environ.get("APEX_BUNDLE_PROBE_BUILD") == "1"
resource_root = ROOT / "build" / "backend-bundle" / "staging" / "resources"
datas = [(source, destination) for source, destination in bundle_datas(resource_root)]
binaries = []
hiddenimports = bundle_hidden_imports()

_OMIT_DIST_INFO_FILES = {
    "direct_url.json",
    "uv_cache.json",
    "uv_build.json",
    "record",
    "record.jws",
    "record.p7s",
    "installer",
    "requested",
}


def sanitize_analysis_datas(analysis):
    """Remove installer provenance and metadata-only shim records from a build."""
    retained = []
    for item in analysis.datas:
        destination = str(item[0]).replace("\\", "/")
        parts = destination.split("/")
        if is_bundle_excluded_data_path(destination):
            continue
        dist_info = next(
            (part for part in parts if part.lower().endswith(".dist-info")),
            None,
        )
        if dist_info is not None:
            normalized_dist = dist_info[: -len(".dist-info")].lower().replace("_", "-")
            filename = parts[-1].lower()
            if normalized_dist.startswith("pypiwin32-"):
                continue
            if filename in _OMIT_DIST_INFO_FILES:
                continue
        retained.append(item)
    analysis.datas[:] = retained


for package in (
    "fastembed",
    "onnxruntime",
    "numpy",
    "pygame",
    "kokoro_onnx",
    "espeakng_loader",
):
    submodule_filter = (
        include_onnxruntime_submodule if package == "onnxruntime" else include_runtime_submodule
    )
    package_datas, package_binaries, package_hidden = collect_all(
        package,
        filter_submodules=submodule_filter,
        exclude_datas=["**/test/**", "**/tests/**", "**/testing/**"],
    )
    package_datas = [
        item for item in package_datas if not is_bundle_excluded_data_path(item[1])
    ]
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hidden)

datas.extend(copy_metadata("apex", recursive=True))
datas.extend(copy_metadata("fastembed"))
if probe_mode:
    hiddenimports.extend(["scripts.smoke_backend_bundle", "core.host.profile_lock"])

entry = (
    ROOT / "packaging" / "windows" / "smoke" / "probe.py"
    if probe_mode
    else ROOT / "packaging" / "windows" / "backend_entry.py"
)
analysis = Analysis(
    [str(entry)],
    pathex=[str(ROOT), str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "packaging" / "windows" / "rthook_comtypes.py")],
    excludes=bundle_analysis_excludes(),
    noarchive=False,
)
sanitize_analysis_datas(analysis)
pyz = PYZ(analysis.pure)
executable_name = "apex-bundle-probe" if probe_mode else "apex-backend"
console_executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=executable_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

if probe_mode:
    coll = COLLECT(
        console_executable,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        name="apex-bundle-probe",
    )
else:
    cli_analysis = Analysis(
        [str(ROOT / "packaging" / "windows" / "cli_entry.py")],
        pathex=[str(ROOT), str(ROOT / "src")],
        binaries=binaries,
        datas=datas,
        hiddenimports=sorted(set(hiddenimports)),
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=bundle_analysis_excludes(),
        noarchive=False,
    )
    sanitize_analysis_datas(cli_analysis)
    cli_pyz = PYZ(cli_analysis.pure)
    cli_executable = EXE(
        cli_pyz,
        cli_analysis.scripts,
        [],
        exclude_binaries=True,
        name="apex",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
    )
    coll = COLLECT(
        console_executable,
        cli_executable,
        analysis.binaries,
        analysis.datas,
        cli_analysis.binaries,
        cli_analysis.datas,
        strip=False,
        upx=False,
        name="backend-bundle",
    )
