"""Bounded, path-free diagnostics for comparing frozen Windows executables."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import marshal
import re
import sys
import types
from pathlib import Path
from typing import Any


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")
_CODE_FIELDS = (
    "co_argcount",
    "co_posonlyargcount",
    "co_kwonlyargcount",
    "co_nlocals",
    "co_stacksize",
    "co_flags",
    "co_code",
    "co_names",
    "co_varnames",
    "co_freevars",
    "co_cellvars",
    "co_filename",
    "co_name",
    "co_qualname",
    "co_firstlineno",
    "co_linetable",
    "co_exceptiontable",
    "co_consts",
)


@dataclass(frozen=True)
class _NestedCodeMarker:
    ordinal_path: tuple[int, ...]


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _safe_name(name: str) -> str | None:
    """Return a bounded logical name, never an arbitrary archive path."""
    normalized = name.replace("\\", "/")
    if normalized.endswith(".pyc"):
        normalized = normalized[:-4]
    normalized = normalized.replace("/", ".")
    if normalized.startswith(".") or ".." in normalized or not _SAFE_NAME.fullmatch(normalized):
        return None
    return normalized


def _safe_names(names: list[str], limit: int) -> list[str]:
    return [safe for name in names if (safe := _safe_name(name)) is not None][:limit]


def _code_field_values(root: types.CodeType) -> dict[str, Any]:
    """Collect structural fields, separating nested code from parent constants."""
    field_values: dict[str, Any] = {}

    def replace_nested_code(value: Any, path: tuple[int, ...]) -> Any:
        if isinstance(value, types.CodeType):
            # Nested code objects are walked independently below.
            return _NestedCodeMarker(path)
        if isinstance(value, tuple):
            return tuple(
                replace_nested_code(item, path + (index,))
                for index, item in enumerate(value)
            )
        if isinstance(value, frozenset):
            return frozenset(replace_nested_code(item, path) for item in value)
        return value

    def walk(code: types.CodeType, ordinal_path: tuple[int, ...]) -> None:
        prefix = ".".join(map(str, ordinal_path)) or "root"
        for field in _CODE_FIELDS:
            if not hasattr(code, field):
                continue
            value = getattr(code, field)
            if field == "co_consts":
                value = replace_nested_code(value, ordinal_path)
            field_values[f"{prefix}:{field}"] = value
        children = [item for item in code.co_consts if isinstance(item, types.CodeType)]
        for index, child in enumerate(children):
            walk(child, ordinal_path + (index,))

    walk(root, ())
    return field_values


def _analyze_code_pair(first: bytes, second: bytes, limit: int) -> dict[str, Any]:
    try:
        left = marshal.loads(first)
        right = marshal.loads(second)
    except (EOFError, ValueError, TypeError):
        return {"parsed": False, "changed_fields": [], "serialization_only": False}
    if not isinstance(left, types.CodeType) or not isinstance(right, types.CodeType):
        return {"parsed": False, "changed_fields": [], "serialization_only": False}
    left_fields = _code_field_values(left)
    right_fields = _code_field_values(right)
    changed = sorted({
        key.rsplit(":", 1)[-1]
        for key in set(left_fields) | set(right_fields)
        if left_fields.get(key) != right_fields.get(key)
    })
    return {
        "parsed": True,
        "changed_fields": changed[:limit],
        "serialization_only": first != second and not changed,
    }


def _pe_summary(first: Path, second: Path, limit: int) -> dict[str, Any]:
    import pefile  # type: ignore[import-not-found]

    left = pefile.PE(str(first), fast_load=False)
    right = pefile.PE(str(second), fast_load=False)
    fixed = (
        ("TimeDateStamp", lambda pe: pe.FILE_HEADER.TimeDateStamp),
        ("CheckSum", lambda pe: pe.OPTIONAL_HEADER.CheckSum),
        ("AddressOfEntryPoint", lambda pe: pe.OPTIONAL_HEADER.AddressOfEntryPoint),
        ("ImageBase", lambda pe: pe.OPTIONAL_HEADER.ImageBase),
        ("SizeOfImage", lambda pe: pe.OPTIONAL_HEADER.SizeOfImage),
        ("SectionAlignment", lambda pe: pe.OPTIONAL_HEADER.SectionAlignment),
        ("FileAlignment", lambda pe: pe.OPTIONAL_HEADER.FileAlignment),
    )
    changed_fields = [name for name, get in fixed if get(left) != get(right)]

    def sections(pe: Any) -> dict[str, str]:
        result: dict[str, str] = {}
        for section in pe.sections:
            name = section.Name.rstrip(b"\0").decode("ascii", errors="ignore")
            if _SAFE_NAME.fullmatch(name):
                result[name] = _digest(section.get_data())
        return result

    left_sections = sections(left)
    right_sections = sections(right)
    changed_sections = sorted(
        name for name in set(left_sections) | set(right_sections)
        if left_sections.get(name) != right_sections.get(name)
    )
    result = {
        "changed_fields": changed_fields,
        "section_count": [len(left_sections), len(right_sections)],
        "changed_section_count": len(changed_sections),
        "changed_sections": changed_sections[:limit],
    }
    left.close()
    right.close()
    return result


def _archive_summary(first: Path, second: Path, limit: int) -> dict[str, Any]:
    from PyInstaller.archive.readers import CArchiveReader

    left = CArchiveReader(str(first))
    right = CArchiveReader(str(second))
    left_order = list(left.toc)
    right_order = list(right.toc)
    left_set, right_set = set(left_order), set(right_order)
    only_left = sorted(left_set - right_set)
    only_right = sorted(right_set - left_set)
    changed: list[str] = []
    changed_metadata: list[str] = []
    changed_scripts: list[str] = []
    changed_script_fields: set[str] = set()
    serialization_only_scripts = 0
    for name in sorted(left_set & right_set):
        left_entry = left.toc[name]
        right_entry = right.toc[name]
        # PyInstaller CArchive TOC is (offset, compressed size, raw size,
        # compression flag, type code). Offsets are intentionally excluded:
        # a prior size change shifts later entries without changing them.
        if (left_entry[1], left_entry[2], left_entry[3], left_entry[4]) != (
            right_entry[1], right_entry[2], right_entry[3], right_entry[4]
        ):
            changed_metadata.append(name)
    pyz_details: list[dict[str, Any]] = []
    for name in sorted(left_set & right_set):
        if name.lower().endswith(".pyz"):
            lz = left.open_embedded_archive(name)
            rz = right.open_embedded_archive(name)
            lorder, rorder = list(lz.toc), list(rz.toc)
            lnames, rnames = set(lorder), set(rorder)
            lonly, ronly = sorted(lnames - rnames), sorted(rnames - lnames)
            modules_changed: list[str] = []
            storage_changed: list[str] = []
            pyz_changed_fields: set[str] = set()
            serialization_only = 0
            for module in sorted(lnames & rnames):
                if (lz.toc[module][0], lz.toc[module][2]) != (
                    rz.toc[module][0], rz.toc[module][2]
                ):
                    storage_changed.append(module)
                lraw = lz.extract(module, raw=True)
                rraw = rz.extract(module, raw=True)
                if lraw != rraw:
                    modules_changed.append(module)
                    analysis = _analyze_code_pair(lraw, rraw, limit)
                    pyz_changed_fields.update(analysis["changed_fields"])
                    serialization_only += bool(analysis["serialization_only"])
            pyz_details.append({
                "name": _safe_name(name) or "PYZ",
                "order_equal": lorder == rorder,
                "module_count": [len(lorder), len(rorder)],
                "only_left_count": len(lonly),
                "only_right_count": len(ronly),
                "changed_module_count": len(modules_changed),
                "changed_storage_module_count": len(storage_changed),
                "only_left": _safe_names(lonly, limit),
                "only_right": _safe_names(ronly, limit),
                "changed_modules": _safe_names(modules_changed, limit),
                "changed_storage_modules": _safe_names(storage_changed, limit),
                "changed_code_fields": sorted(pyz_changed_fields)[:limit],
                "serialization_only_module_count": serialization_only,
            })
            continue
        ldata = left.extract(name)
        rdata = right.extract(name)
        if ldata != rdata:
            changed.append(name)
            if left.toc[name][4] == "s":
                changed_scripts.append(name)
                analysis = _analyze_code_pair(ldata, rdata, limit)
                changed_script_fields.update(analysis["changed_fields"])
                serialization_only_scripts += bool(analysis["serialization_only"])
    left_payload_count = len(left_set)
    right_payload_count = len(right_set)
    return {
        "order_equal": left_order == right_order,
        "entry_count": [left_payload_count, right_payload_count],
        "only_left_count": len(only_left),
        "only_right_count": len(only_right),
        "changed_payload_count": len(changed),
        "changed_entry_metadata_count": len(changed_metadata),
        "changed_script_count": len(changed_scripts),
        "serialization_only_script_count": serialization_only_scripts,
        "only_left": _safe_names(only_left, limit),
        "only_right": _safe_names(only_right, limit),
        "changed_payloads": _safe_names(changed, limit),
        "changed_entry_metadata": _safe_names(changed_metadata, limit),
        "changed_scripts": _safe_names(changed_scripts, limit),
        "changed_script_code_fields": sorted(changed_script_fields)[:limit],
        "pyz": pyz_details[:limit],
        "base_library_zip": None,
    }


def compare_executables(first: Path | str, second: Path | str, max_items: int = 10) -> dict[str, Any]:
    """Return bounded structural differences without exposing local path/data."""
    limit = max(1, min(int(max_items), 10))
    left_path, right_path = Path(first), Path(second)
    left_hash, left_size = _file_digest(left_path)
    right_hash, right_size = _file_digest(right_path)
    pe = _pe_summary(left_path, right_path, limit)
    archive = _archive_summary(left_path, right_path, limit)
    equal = left_hash == right_hash
    return {
        "schema_version": 1,
        "equal": equal,
        "summary": {
            "sha256": [left_hash, right_hash],
            "size_bytes": [left_size, right_size],
        },
        "pe": pe,
        "carchive": archive,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--max-items", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        report = compare_executables(args.first, args.second, args.max_items)
    except Exception as exc:  # diagnostics must never echo parser errors or paths
        print(json.dumps({"schema_version": 1, "error": type(exc).__name__}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
