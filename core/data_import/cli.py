"""Closed-stdin protocol for native first-run setup operations."""

from __future__ import annotations

import json
import sys

from core.data_import.engine import ImportEngine, ImportOperationError
from core.host.protocol import MAX_FRAME_BYTES


def _read_request() -> dict[str, object]:
    line = sys.stdin.buffer.readline(MAX_FRAME_BYTES + 1)
    if not line or len(line) > MAX_FRAME_BYTES or not line.endswith(b"\n"):
        raise ImportOperationError("request_invalid")
    if sys.stdin.buffer.read(1):
        raise ImportOperationError("request_invalid")
    try:
        value = json.loads(line)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ImportOperationError("request_invalid") from exc
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise ImportOperationError("request_invalid")
    request_id = value.get("request_id")
    if (
        not isinstance(request_id, str) or not 1 <= len(request_id) <= 128
        or any(not 33 <= ord(c) <= 126 for c in request_id)
    ):
        raise ImportOperationError("request_invalid")
    operation = value.get("operation")
    if operation not in {"status", "preview", "import", "fresh_start", "recover"}:
        raise ImportOperationError("request_invalid")
    allowed = {"version", "request_id", "operation"}
    if operation in {"preview", "import"}:
        allowed.add("source_dir")
    if operation == "import":
        allowed.add("preview_id")
    if set(value) != allowed:
        raise ImportOperationError("request_invalid")
    if operation in {"preview", "import"} and not isinstance(value.get("source_dir"), str):
        raise ImportOperationError("request_invalid")
    if operation == "import" and not isinstance(value.get("preview_id"), str):
        raise ImportOperationError("request_invalid")
    return value


def main() -> int:
    request_id = "invalid"

    def send(kind: str, payload: dict[str, object]) -> None:
        frame = {"version": 1, "request_id": request_id, "type": kind, "payload": payload}
        encoded = json.dumps(frame, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        if len(encoded) + 1 > MAX_FRAME_BYTES:
            frame = {"version": 1, "request_id": request_id, "type": "error", "payload": {"code": "response_too_large"}}
            encoded = json.dumps(frame, separators=(",", ":")).encode("utf-8")
        if len(encoded) + 1 > MAX_FRAME_BYTES:
            raise ImportOperationError("response_too_large")
        sys.stdout.buffer.write(encoded + b"\n")
        sys.stdout.buffer.flush()

    try:
        request = _read_request()
        request_id = str(request["request_id"])
        operation = str(request["operation"])

        def progress(stage: str, completed: int, total: int) -> None:
            if stage not in {
                "inventory", "database_preview_transport", "database_preview_backup",
                "copying", "database_transport", "database_backup", "recovery_verify",
            }:
                return
            send("progress", {"stage": stage, "completed_bytes": completed, "total_bytes": total})

        engine = ImportEngine(progress=progress)
        if operation == "status":
            result = engine.status()
        elif operation == "preview":
            result = engine.preview(request["source_dir"])  # type: ignore[arg-type]
        elif operation == "import":
            result = engine.import_data(request["source_dir"], request["preview_id"])  # type: ignore[arg-type]
        elif operation == "fresh_start":
            result = engine.fresh_start()
        else:
            result = engine.recover()
        send("result", result)
        return 0
    except ImportOperationError as exc:
        print(f"APEX setup operation failed ({exc.code}).", file=sys.stderr, flush=True)
        send("error", {"code": exc.code})
        return 1
    except Exception:
        print("APEX setup operation failed (internal_error).", file=sys.stderr, flush=True)
        send("error", {"code": "internal_error"})
        return 1


__all__ = ["main"]
