from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest import mock

from core.agent.providers.litert_protocol import (
    LiteRTInferenceAmbiguousError,
    LiteRTProtocolError,
    decode_frame,
    encode_frame,
    operation_is_retryable,
)
from core.agent.local_runtime import LOCAL_RUNTIME
from core.agent.providers.litert_lifecycle import LiteRTLifecycleBackend
from core.agent.providers.litert_models import LiteRTModelProfile
from core.agent.providers.litert_runtime import LiteRTRuntimeManager, restricted_worker_environment
from scripts.litert_worker import REQUIRED_VERSION, Worker


FAKE_WORKER = textwrap.dedent(
    r'''
    import json, os, sys, time
    PREFIX = "APEX_LITERT/1 "
    mode = os.environ.get("FAKE_LITERT_MODE", "normal")
    count_file = os.environ.get("FAKE_LITERT_COUNT")
    def count(op):
        if count_file:
            with open(count_file, "a", encoding="utf-8") as handle:
                handle.write(op + "\n")
    for line in sys.stdin.buffer:
        if not line:
            break
        if not line.startswith(PREFIX.encode()):
            continue
        request = json.loads(line.decode()[len(PREFIX):])
        op = request["op"]
        count(op)
        if op == "send_message" and mode == "crash_send":
            os._exit(17)
        if op == "send_message" and mode == "slow_send":
            time.sleep(5)
        payload = {
            "state": "idle",
            "loaded_model": None,
            "dependency": {"available": True, "version": "0.15.0"},
        }
        if op == "hello":
            payload.update({"protocol": "APEX_LITERT/1", "pid": os.getpid()})
        elif op == "send_message":
            payload = {"content": [{"type": "text", "text": "ok"}]}
        elif op == "load_engine":
            payload = {
                "state": "ready",
                "loaded_model": request["payload"]["model_path"],
            }
        elif op == "unload_engine" and mode == "error_unload":
            payload = {
                "error": {
                    "code": "engine_error",
                    "message": "simulated unload failure",
                }
            }
        elif op == "shutdown":
            payload = {"shutdown": True, "state": "stopped"}
        response = {"id": request["id"], "op": op, "payload": payload}
        sys.stdout.buffer.write((PREFIX + json.dumps(response, separators=(",", ":")) + "\n").encode())
        sys.stdout.buffer.flush()
        if op == "shutdown":
            break
    ''',
)


class TestLiteRTProtocol(unittest.TestCase):
    def test_round_trip_and_validation(self) -> None:
        encoded = encode_frame("one", "status", {"safe": True})
        frame = decode_frame(encoded)
        self.assertEqual((frame.request_id, frame.operation, frame.payload), ("one", "status", {"safe": True}))
        with self.assertRaises(LiteRTProtocolError):
            decode_frame(b'{"id":"one","op":"status","payload":{}}\n')
        with self.assertRaises(LiteRTProtocolError):
            encode_frame("one", "send_message", {"bad": object()})

    def test_only_read_only_operations_are_retryable(self) -> None:
        self.assertTrue(operation_is_retryable("hello"))
        self.assertTrue(operation_is_retryable("status"))
        for operation in (
            "load_engine",
            "open_conversation",
            "send_message",
            "close_conversation",
            "unload_engine",
            "shutdown",
        ):
            self.assertFalse(operation_is_retryable(operation))

    def test_worker_environment_removes_credentials(self) -> None:
        safe = restricted_worker_environment(
            {
                "PATH": "path",
                "GEMINI_API_KEY": "secret",
                "MSAL_CLIENT_SECRET": "secret",
                "APEX_SAFE_FLAG": "1",
                "APEX_OAUTH_TOKEN": "secret",
            }
        )
        self.assertEqual(safe["PATH"], "path")
        self.assertEqual(safe["APEX_SAFE_FLAG"], "1")
        self.assertNotIn("GEMINI_API_KEY", safe)
        self.assertNotIn("MSAL_CLIENT_SECRET", safe)
        self.assertNotIn("APEX_OAUTH_TOKEN", safe)


class TestLiteRTRuntimeManager(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="apex_litert_runtime_")
        self.root = Path(self.temp.name)
        self.script = self.root / "fake_worker.py"
        self.script.write_text(FAKE_WORKER, encoding="utf-8")
        self.count_file = self.root / "operations.log"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def manager(self, mode: str = "normal") -> LiteRTRuntimeManager:
        return LiteRTRuntimeManager(
            interpreter=sys.executable,
            worker_script=self.script,
            project_root=self.root,
            environment={
                "PATH": os.environ.get("PATH", ""),
                "FAKE_LITERT_MODE": mode,
                "FAKE_LITERT_COUNT": str(self.count_file),
            },
            handshake_timeout=1,
            inference_timeout=0.2,
            shutdown_timeout=0.5,
        )

    def test_worker_is_lazy_and_shutdown_leaves_no_orphan(self) -> None:
        manager = self.manager()
        self.assertIsNone(manager.process)
        hello = manager.hello()
        self.assertEqual(hello["protocol"], "APEX_LITERT/1")
        process = manager.process
        self.assertIsNotNone(process)
        self.assertTrue(manager.shutdown())
        self.assertIsNotNone(process)
        self.assertIsNotNone(process.poll())
        self.assertIsNone(manager.process)

    def test_send_message_crash_is_ambiguous_and_not_replayed(self) -> None:
        manager = self.manager("crash_send")
        manager.hello()
        with self.assertRaises(LiteRTInferenceAmbiguousError):
            manager.send_message("conversation-1", "hello", timeout=0.5)
        self.assertIsNone(manager.process)
        operations = self.count_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(operations.count("send_message"), 1)

    def test_send_message_timeout_is_ambiguous_and_not_replayed(self) -> None:
        manager = self.manager("slow_send")
        manager.hello()
        with self.assertRaises(LiteRTInferenceAmbiguousError):
            manager.send_message("conversation-1", "hello", timeout=0.05)
        self.assertIsNone(manager.process)
        operations = self.count_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(operations.count("send_message"), 1)

    def test_failed_unload_poison_terminates_worker_and_forces_fresh_reload(self) -> None:
        manager = self.manager("error_unload")
        backend = object.__new__(LiteRTLifecycleBackend)
        backend._loaded_model = None
        backend._loaded_artifact = None
        backend.runtime = manager
        manager._state_callback = backend._runtime_state_changed

        with tempfile.TemporaryDirectory(prefix="apex_litert_unload_") as temp:
            artifact = Path(temp) / "model.litertlm"
            artifact.write_bytes(b"model")
            profile = LiteRTModelProfile(
                display_name="Test LiteRT",
                agent_version="1",
                api_model="model-a",
                tier="lightweight",
                stability="preview",
                system_instruction="test",
                artifact_path=str(artifact),
            )
            self.assertTrue(backend.switch_model(profile))
            first_process = manager.process
            self.assertIsNotNone(first_process)
            self.assertFalse(backend.unload_active_model())

            self.assertIsNotNone(first_process)
            self.assertIsNotNone(first_process.poll())
            self.assertIsNone(manager.process)
            self.assertIsNone(manager.engine_model)
            self.assertIsNone(backend._loaded_model)
            self.assertIsNone(backend._loaded_artifact)
            self.assertIsNone(LOCAL_RUNTIME.get_active_model("litert"))
            self.assertIsNone(LOCAL_RUNTIME.get_loading_model("litert"))

            self.assertTrue(backend.switch_model(profile))
            second_process = manager.process
            self.assertIsNotNone(second_process)
            self.assertIsNot(first_process, second_process)
            operations = self.count_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(operations.count("load_engine"), 2)

        manager.shutdown()


class _FakeConversation:
    def __init__(self) -> None:
        self.closed = False
        self.messages: list[object] = []

    def send_message(self, message: object) -> dict[str, object]:
        self.messages.append(message)
        return {"content": [{"type": "text", "text": "ok"}], "tool_calls": []}

    def close(self) -> None:
        self.closed = True


class _FakeEngine:
    instances: list["_FakeEngine"] = []

    def __init__(self, *, model_path: str, backend: object) -> None:
        self.model_path = model_path
        self.backend = backend
        self.closed = False
        self.conversations: list[_FakeConversation] = []
        self.__class__.instances.append(self)

    def create_conversation(self, **_kwargs: object) -> _FakeConversation:
        conversation = _FakeConversation()
        self.conversations.append(conversation)
        return conversation

    def close(self) -> None:
        self.closed = True


class TestLiteRTWorkerWithFakeBinding(unittest.TestCase):
    def test_engine_and_conversation_cleanup_without_native_dependency(self) -> None:
        class FakeTool:
            pass

        fake_interfaces = types.ModuleType("litert_lm.interfaces")
        fake_interfaces.Tool = FakeTool
        fake_interfaces.CPU = lambda: "cpu"
        fake_module = types.ModuleType("litert_lm")
        fake_module.Engine = _FakeEngine
        fake_content = types.SimpleNamespace(
            ToolResponse=lambda name, response: {"name": name, "response": response}
        )
        fake_module.Content = fake_content
        fake_module.Contents = types.SimpleNamespace(of=lambda *items: list(items))
        fake_module.Message = types.SimpleNamespace(tool=lambda contents: {"role": "tool", "content": contents})
        fake_messages = types.ModuleType("litert_lm._messages")
        _FakeEngine.instances.clear()
        with tempfile.TemporaryDirectory(prefix="apex_litert_model_") as temp:
            model = Path(temp) / "fake.litertlm"
            model.write_bytes(b"fake")
            with mock.patch.dict(
                sys.modules,
                {
                    "litert_lm": fake_module,
                    "litert_lm.interfaces": fake_interfaces,
                    "litert_lm._messages": fake_messages,
                },
            ):
                worker = Worker()
                worker.dependency_error = None
                worker.dependency_version = REQUIRED_VERSION
                loaded = worker.load_engine({"model_path": str(model), "backend": "cpu"})
                self.assertEqual(loaded["loaded_model"], str(model))
                opened = worker.open_conversation(
                    {
                        "conversation_id": "request-1",
                        "system_instruction": "test",
                        "tools": [],
                        "automatic_tool_calling": False,
                    }
                )
                self.assertEqual(opened["conversation_id"], "request-1")
                worker.send_message({"conversation_id": "request-1", "message": "hello"})
                worker.close_conversation({"conversation_id": "request-1"})
                worker.unload_engine()
        self.assertTrue(_FakeEngine.instances[0].closed)
        self.assertTrue(_FakeEngine.instances[0].conversations[0].closed)


if __name__ == "__main__":
    unittest.main()
