"""Stdio worker for the optional LiteRT-LM Python binding.

This process is intentionally small and policy-free.  It owns native engine
and conversation handles only; APEX remains responsible for validation,
permissions, dispatch, and all turn limits.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Mapping

# When launched by an interpreter with ``scripts`` as ``sys.path[0]``, make
# the repository package importable without relying on the caller's
# ``PYTHONPATH``.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.agent.providers.litert_protocol import (
    MAX_FRAME_BYTES,
    ProtocolFrame,
    LiteRTProtocolError,
    PROTOCOL_NAME,
    PROTOCOL_VERSION,
    decode_frame,
    encode_frame,
)


REQUIRED_PACKAGE = "litert-lm-api"
REQUIRED_VERSION = "0.15.0"


class _SchemaTool:
    """LiteRT tool adapter that exposes a schema but never executes host code."""

    def __init__(self, schema: Mapping[str, Any]) -> None:
        from litert_lm.interfaces import Tool

        self._base = Tool
        self._schema = dict(schema)

    def get_tool_description(self) -> dict[str, Any]:
        return dict(self._schema)

    def execute(self, _param: Mapping[str, Any]) -> Any:
        raise RuntimeError("Automatic LiteRT tool execution is disabled.")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "to_json"):
        try:
            return _json_safe(value.to_json())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return _json_safe(vars(value))
        except Exception:
            pass
    return str(value)


def _safe_error(code: str, message: str) -> dict[str, Any]:
    # Native exception details stay in the worker's local stderr only.
    print(f"LiteRT worker {code}: {type(message).__name__}", file=sys.stderr, flush=True)
    return {"error": {"code": code, "message": message}}


class Worker:
    def __init__(self) -> None:
        self.engine: Any = None
        self.engine_model: str | None = None
        self.conversations: dict[str, Any] = {}
        self.dependency_error: str | None = None
        self.dependency_version: str | None = None
        try:
            self.dependency_version = importlib.metadata.version(REQUIRED_PACKAGE)
        except Exception as exc:
            self.dependency_error = "LiteRT Python dependency is not installed."
            print(f"LiteRT dependency probe failed: {type(exc).__name__}", file=sys.stderr, flush=True)

    def _dependency(self) -> tuple[Any, Any, Any]:
        if self.dependency_error is not None:
            raise RuntimeError(self.dependency_error)
        if self.dependency_version != REQUIRED_VERSION:
            raise RuntimeError("LiteRT Python dependency version is unsupported.")
        module = importlib.import_module("litert_lm")
        interfaces = importlib.import_module("litert_lm.interfaces")
        return module, interfaces, importlib.import_module("litert_lm._messages")

    def handle(self, frame: ProtocolFrame) -> tuple[dict[str, Any], bool]:
        try:
            if frame.operation == "hello":
                return self.hello(), False
            if frame.operation == "status":
                return self.status(), False
            if frame.operation == "load_engine":
                return self.load_engine(frame.payload), False
            if frame.operation == "open_conversation":
                return self.open_conversation(frame.payload), False
            if frame.operation == "send_message":
                return self.send_message(frame.payload), False
            if frame.operation == "close_conversation":
                return self.close_conversation(frame.payload), False
            if frame.operation == "unload_engine":
                return self.unload_engine(), False
            if frame.operation == "shutdown":
                return self.shutdown(), True
            return _safe_error("invalid_request", "Unsupported LiteRT worker operation."), False
        except FileNotFoundError:
            return _safe_error("model_missing", "The configured LiteRT model artifact is missing."), False
        except ImportError:
            return _safe_error("dependency_unavailable", "LiteRT Python worker dependency is unavailable."), False
        except ValueError:
            return _safe_error("invalid_request", "The LiteRT worker request is invalid."), False
        except Exception as exc:
            print(f"LiteRT worker operation failed: {type(exc).__name__}", file=sys.stderr, flush=True)
            return _safe_error("worker_error", "LiteRT worker operation failed."), False

    def hello(self) -> dict[str, Any]:
        version_mismatch = (
            self.dependency_version is not None and self.dependency_version != REQUIRED_VERSION
        )
        return {
            "protocol": f"{PROTOCOL_NAME}/{PROTOCOL_VERSION}",
            "python_version": sys.version.split()[0],
            "pid": os.getpid(),
            "dependency": {
                "package": REQUIRED_PACKAGE,
                "version": self.dependency_version,
                "available": self.dependency_error is None and not version_mismatch,
                "version_mismatch": version_mismatch,
            },
            "state": "ready" if self.dependency_error is None and not version_mismatch else "unavailable",
            "loaded_model": self.engine_model,
        }

    def status(self) -> dict[str, Any]:
        return {
            "state": "ready" if self.engine is not None else ("unavailable" if self.dependency_error else "idle"),
            "loaded_model": self.engine_model,
            "conversation_count": len(self.conversations),
            "dependency_available": self.dependency_error is None,
            "dependency_version": self.dependency_version,
        }

    def load_engine(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        model_path = payload.get("model_path")
        if not isinstance(model_path, str) or not model_path.strip():
            return _safe_error("invalid_request", "A LiteRT model artifact is required.")
        if not Path(model_path).is_file():
            return _safe_error("model_missing", "The configured LiteRT model artifact is missing.")
        module, interfaces, _ = self._dependency()
        self.unload_engine()
        backend = str(payload.get("backend") or "cpu").lower()
        if backend != "cpu":
            return _safe_error("invalid_request", "Only the CPU LiteRT backend is supported.")
        self.engine = module.Engine(model_path=model_path, backend=interfaces.CPU())
        self.engine_model = model_path
        return self.status()

    def _message(self, raw: Any) -> Any:
        if isinstance(raw, str):
            return raw
        if not isinstance(raw, Mapping):
            raise ValueError("LiteRT message must be text or an object.")
        role = raw.get("role")
        if role == "user":
            content = raw.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = [
                    str(item.get("text", ""))
                    for item in content
                    if isinstance(item, Mapping) and item.get("type") == "text"
                ]
                return "".join(texts)
        if role == "tool":
            from litert_lm import Content, Contents, Message

            content = raw.get("content")
            if not isinstance(content, list) or not content:
                raise ValueError("LiteRT tool message requires content.")
            responses = []
            for item in content:
                if not isinstance(item, Mapping) or item.get("type") != "tool_response":
                    raise ValueError("LiteRT tool message contains an invalid response.")
                name = item.get("name")
                if not isinstance(name, str) or not name:
                    raise ValueError("LiteRT tool response requires a name.")
                responses.append(Content.ToolResponse(name=name, response=item.get("response")))
            return Message.tool(Contents.of(*responses))
        raise ValueError("Unsupported LiteRT message role.")

    def open_conversation(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self.engine is None:
            return _safe_error("engine_error", "LiteRT engine is not loaded.")
        conversation_id = payload.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            return _safe_error("invalid_request", "A conversation id is required.")
        if payload.get("automatic_tool_calling") is not False:
            return _safe_error("invalid_request", "Automatic LiteRT tool calling must be disabled.")
        _, interfaces, _ = self._dependency()
        raw_tools = payload.get("tools", [])
        if not isinstance(raw_tools, list):
            return _safe_error("invalid_request", "LiteRT tools must be a list.")
        tools = [self._schema_tool(item, interfaces) for item in raw_tools]
        kwargs: dict[str, Any] = {
            "tools": tools,
            "automatic_tool_calling": False,
        }
        system_instruction = payload.get("system_instruction")
        if system_instruction is not None:
            if not isinstance(system_instruction, str):
                return _safe_error("invalid_request", "LiteRT system instruction must be text.")
            kwargs["system_message"] = system_instruction
        initial_messages = payload.get("initial_messages", [])
        if initial_messages:
            if not isinstance(initial_messages, list):
                return _safe_error("invalid_request", "LiteRT initial messages must be a list.")
            kwargs["messages"] = [self._message(message) for message in initial_messages]
        max_output_tokens = payload.get("max_output_tokens")
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = int(max_output_tokens)
        self.conversations[conversation_id] = self.engine.create_conversation(**kwargs)
        return {"conversation_id": conversation_id, "automatic_tool_calling": False}

    @staticmethod
    def _schema_tool(schema: Any, interfaces: Any) -> Any:
        if not isinstance(schema, Mapping):
            raise ValueError("LiteRT tool schema must be an object.")
        tool_cls = type("SchemaOnlyTool", (interfaces.Tool,), {})
        normalized = dict(schema)

        def get_tool_description(self: Any) -> dict[str, Any]:
            return dict(normalized)

        def execute(self: Any, _param: Mapping[str, Any]) -> Any:
            raise RuntimeError("Automatic LiteRT tool execution is disabled.")

        tool_cls.get_tool_description = get_tool_description  # type: ignore[attr-defined]
        tool_cls.execute = execute  # type: ignore[attr-defined]
        return tool_cls()

    def send_message(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        conversation_id = payload.get("conversation_id")
        if not isinstance(conversation_id, str) or conversation_id not in self.conversations:
            return _safe_error("conversation_error", "LiteRT conversation is unavailable.")
        response = self.conversations[conversation_id].send_message(self._message(payload.get("message")))
        return _json_safe(response) if isinstance(response, Mapping) else {"content": _json_safe(response)}

    def close_conversation(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        conversation_id = payload.get("conversation_id")
        if isinstance(conversation_id, str):
            conversation = self.conversations.pop(conversation_id, None)
            if conversation is not None:
                conversation.close()
        return {"closed": True, "conversation_id": conversation_id}

    def unload_engine(self) -> dict[str, Any]:
        for conversation in tuple(self.conversations.values()):
            try:
                conversation.close()
            except Exception:
                pass
        self.conversations.clear()
        if self.engine is not None:
            try:
                self.engine.close()
            finally:
                self.engine = None
                self.engine_model = None
        return self.status()

    def shutdown(self) -> dict[str, Any]:
        self.unload_engine()
        return {"shutdown": True, "state": "stopped"}


def main() -> int:
    worker = Worker()
    for raw_line in sys.stdin.buffer:
        if len(raw_line) > MAX_FRAME_BYTES:
            continue
        try:
            frame = decode_frame(raw_line)
            payload, should_exit = worker.handle(frame)
        except LiteRTProtocolError:
            continue
        except Exception:
            traceback.print_exc(file=sys.stderr)
            continue
        try:
            sys.stdout.buffer.write(encode_frame(frame.request_id, frame.operation, payload))
            sys.stdout.buffer.flush()
        except (BrokenPipeError, OSError):
            break
        if should_exit:
            break
    try:
        worker.unload_engine()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
