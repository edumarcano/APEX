"""Compare build-only SAPI export diagnostics across normal and smoke environments."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.smoke_backend_bundle import _sanitized_environment


_SCENARIO = "sapi-export-diagnostic"
_GENDERS = ("male", "female")
_MODES = ("source", "frozen")
_ENVIRONMENTS = ("normal", "strict-sanitized")
_INVOCATION_TIMEOUT_SECONDS = 60
_MAX_OUTPUT_BYTES = 16 * 1024
_CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,79}$")


class DiagnosticError(RuntimeError):
    """Raised when diagnostic collection itself cannot be safely interpreted."""


def _integer(value: object, *, minimum: int, maximum: int, nullable: bool = False) -> int | None:
    if nullable and value is None:
        return None
    if type(value) is not int or value < minimum or value > maximum:
        raise DiagnosticError("SAPI diagnostic output was invalid.")
    return value


def _class_name(value: object, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not _CLASS_NAME.fullmatch(value):
        raise DiagnosticError("SAPI diagnostic output was invalid.")
    return value


def _project_diagnostic(
    output: bytes,
    *,
    mode: str,
    environment: str,
    gender: str,
) -> dict[str, object]:
    if len(output) > _MAX_OUTPUT_BYTES:
        raise DiagnosticError("SAPI diagnostic output exceeded its limit.")
    try:
        decoded = output.decode("utf-8")
        raw = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DiagnosticError("SAPI diagnostic output was invalid.") from None
    if not isinstance(raw, dict):
        raise DiagnosticError("SAPI diagnostic output was invalid.")
    if (
        type(raw.get("schema_version")) is not int
        or raw.get("schema_version") != 1
        or raw.get("scenario") != _SCENARIO
        or raw.get("status") != "diagnostic"
        or raw.get("voice_gender") != gender
    ):
        raise DiagnosticError("SAPI diagnostic output was unavailable or unexpected.")

    worker_exit_code = _integer(raw.get("worker_exit_code"), minimum=-(2**31), maximum=2**31 - 1, nullable=True)
    wav_present = raw.get("wav_present")
    if type(wav_present) is not bool:
        raise DiagnosticError("SAPI diagnostic output was invalid.")
    wav_bytes = _integer(raw.get("wav_bytes"), minimum=0, maximum=2**63 - 1)
    wav_frames = _integer(raw.get("wav_frames"), minimum=0, maximum=2**63 - 1, nullable=True)
    wav_rate = _integer(raw.get("wav_rate"), minimum=0, maximum=2**63 - 1, nullable=True)
    wav_channels = _integer(raw.get("wav_channels"), minimum=0, maximum=2**63 - 1, nullable=True)
    wav_sample_width = _integer(raw.get("wav_sample_width_bytes"), minimum=0, maximum=2**63 - 1, nullable=True)
    duration = raw.get("wav_duration_seconds")
    if duration is not None:
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or not 0 <= duration <= 86400
        ):
            raise DiagnosticError("SAPI diagnostic output was invalid.")
        duration = float(duration)
    parse_error = _class_name(raw.get("wav_parse_error_type"), nullable=True)
    event_count = _integer(raw.get("error_event_count"), minimum=0, maximum=1_000_000)
    errors = raw.get("errors")
    if not isinstance(errors, list) or len(errors) > 3:
        raise DiagnosticError("SAPI diagnostic output was invalid.")
    safe_errors: list[dict[str, object]] = []
    for error in errors:
        if not isinstance(error, dict) or set(error) != {
            "exception_type", "hresult", "sapi_save_to_file_line_offset"
        }:
            raise DiagnosticError("SAPI diagnostic output was invalid.")
        exception_type = _class_name(error.get("exception_type"))
        hresult = _integer(error.get("hresult"), minimum=-(2**31), maximum=2**32 - 1, nullable=True)
        line_offset = _integer(
            error.get("sapi_save_to_file_line_offset"), minimum=0, maximum=256, nullable=True
        )
        safe_errors.append({
            "exception_type": exception_type,
            "hresult": hresult,
            "sapi_save_to_file_line_offset": line_offset,
        })

    return {
        "mode": mode,
        "environment": environment,
        "schema_version": 1,
        "scenario": _SCENARIO,
        "status": "diagnostic",
        "voice_gender": gender,
        "worker_exit_code": worker_exit_code,
        "wav_present": wav_present,
        "wav_bytes": wav_bytes,
        "wav_frames": wav_frames,
        "wav_rate": wav_rate,
        "wav_channels": wav_channels,
        "wav_sample_width_bytes": wav_sample_width,
        "wav_duration_seconds": duration,
        "wav_parse_error_type": parse_error,
        "error_event_count": event_count,
        "errors": safe_errors,
    }


def _invoke(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    mode: str,
    context: str,
    gender: str,
) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            timeout=_INVOCATION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise DiagnosticError("SAPI diagnostic invocation timed out.") from None
    except OSError:
        raise DiagnosticError("SAPI diagnostic invocation could not start.") from None
    if completed.returncode != 0:
        raise DiagnosticError("SAPI diagnostic helper returned a failure status.")
    return _project_diagnostic(completed.stdout, mode=mode, environment=context, gender=gender)


def run_diagnostics(
    frozen_probe: Path | None,
    *,
    project_root: Path,
    scratch_root: Path,
    source_only: bool = False,
    on_result: Callable[[dict[str, object]], None] | None = None,
) -> list[dict[str, object]]:
    source_probe = project_root / "packaging" / "windows" / "smoke" / "probe.py"
    if not source_probe.is_file() or (not source_only and (frozen_probe is None or not frozen_probe.is_file())):
        raise DiagnosticError("SAPI diagnostic executable was unavailable.")

    working_directory = scratch_root / "unrelated-working-directory"
    working_directory.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    strict_environment_root = scratch_root / "strict-environment"
    modes = ("source",) if source_only else _MODES
    for context in _ENVIRONMENTS:
        for mode in modes:
            for gender in _GENDERS:
                profile = scratch_root / f"{context}-{mode}-{gender}-profile"
                if context == "strict-sanitized":
                    environment = _sanitized_environment(strict_environment_root, profile)
                else:
                    environment = os.environ.copy()
                    profile.mkdir(parents=True, exist_ok=True)
                    environment["APEX_DATA_DIR"] = str(profile.resolve())
                if mode == "source":
                    command = [sys.executable, str(source_probe.resolve())]
                else:
                    if frozen_probe is None:
                        raise DiagnosticError("SAPI diagnostic executable was unavailable.")
                    command = [str(frozen_probe.resolve())]
                command.extend((_SCENARIO, "--voice-gender", gender))
                result = _invoke(
                    command,
                    environment=environment,
                    cwd=working_directory,
                    mode=mode,
                    context=context,
                    gender=gender,
                )
                results.append(result)
                if on_result is not None:
                    on_result(result)
    return results


def _source_only_diagnostics_healthy(results: list[dict[str, object]]) -> bool:
    return len(results) == len(_ENVIRONMENTS) * len(_GENDERS) and all(
        result.get("wav_present") is True
        and type(result.get("wav_frames")) is int
        and result["wav_frames"] > 0
        and result.get("worker_exit_code") == 0
        for result in results
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Collect bounded source/frozen SAPI diagnostics in normal and strict environments."
    )
    parser.add_argument("--frozen-probe", type=Path)
    parser.add_argument("--source-only", action="store_true")
    args = parser.parse_args(argv)
    if args.source_only != (args.frozen_probe is None):
        parser.error("provide --source-only or --frozen-probe")
    project_root = Path(__file__).resolve().parents[1]
    frozen_probe = args.frozen_probe
    if frozen_probe is not None and not frozen_probe.is_absolute():
        frozen_probe = project_root / frozen_probe
    try:
        with tempfile.TemporaryDirectory(prefix="apex-smoke-測試-") as temporary:
            results = run_diagnostics(
                frozen_probe,
                project_root=project_root,
                scratch_root=Path(temporary),
                source_only=args.source_only,
                on_result=lambda result: print(
                    "APEX_SAPI_EXPORT_DIAGNOSTIC "
                    + json.dumps(result, ensure_ascii=True, separators=(",", ":")),
                    flush=True,
                ),
            )
        if args.source_only and not _source_only_diagnostics_healthy(results):
            print(
                "APEX_SAPI_EXPORT_DIAGNOSTIC status=failed reason=source-audio-unhealthy",
                file=sys.stderr,
            )
            return 1
    except DiagnosticError as exc:
        print(f"APEX_SAPI_EXPORT_DIAGNOSTIC status=unavailable reason={exc}", file=sys.stderr)
        return 1
    except Exception:
        print("APEX_SAPI_EXPORT_DIAGNOSTIC status=unavailable reason=runner-failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
